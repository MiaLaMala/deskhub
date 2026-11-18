"""Exercises the Claude Code waiting alerts against temp dirs: the hook bridge,
the hooks installer and the companion's alert watcher. Never touches the real
~/.claude or ~/.deskhub.

    uv run --no-sync python tests/test_alerts.py
"""
import copy
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from deskhub.claude_alerts import ClaudeAlerts

problems = []

def check(cond, msg):
    if not cond:
        problems.append(msg)

home = pathlib.Path(tempfile.mkdtemp())
env = {**os.environ, "USERPROFILE": str(home), "HOME": str(home)}
sess = home / ".deskhub" / "claude_sessions"

# ---- hook bridge -----------------------------------------------------------

def hook(event, **fields):
    data = {"session_id": "s1", "cwd": "C:\\Code\\my-proj", "hook_event_name": event,
            "transcript_path": "x.jsonl", "prompt": "SECRET PROMPT", "tool_input": {"command": "SECRET"}, **fields}
    r = subprocess.run([sys.executable, str(ROOT / "deskhub" / "hook_bridge.py"), event],
                       input=json.dumps(data).encode(), capture_output=True, env=env, timeout=30)
    check(r.returncode == 0 and r.stdout == b"", f"{event}: exit {r.returncode}, stdout {r.stdout!r}")

def state(sid="s1"):
    p = sess / f"{sid}.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

hook("Notification", notification_type="permission_prompt", message="Claude needs your permission to use Bash")
s = state()
check(s and s["state"] == "permission" and s["project"] == "my-proj", f"permission state: {s}")
check(s["message"] == "Claude needs your permission to use Bash" and s["cwd"] == "C:\\Code\\my-proj", "permission fields")
check(abs(s["updated"] - time.time()) < 60, "updated is now")
check(isinstance(s["pids"], list) and len(s["pids"]) <= 12, f"pids: {s['pids']}")
if sys.platform == "win32":
    check(len(s["pids"]) >= 1 and all(isinstance(p, int) for p in s["pids"]), "pid chain recorded")
check("SECRET" not in (sess / "s1.json").read_text(), "no prompt or tool input stored")
hook("PostToolUse")
check(state()["state"] == "working" and state()["message"] == "", "PostToolUse -> working")
hook("Notification", notification_type="idle_prompt", message="Claude is waiting for your input")
check(state()["state"] == "input", "idle_prompt -> input")
hook("Stop")
check(state()["state"] == "idle", "Stop -> idle")
hook("PermissionRequest", tool_name="Bash")
check(state()["state"] == "permission" and state()["message"] == "Claude wants to use Bash", "PermissionRequest -> permission")
hook("PostToolUse")
hook("PreToolUse", tool_name="AskUserQuestion")
check(state()["state"] == "input" and state()["message"] == "Claude has a question for you", "AskUserQuestion -> input")
hook("PostToolUse")
hook("PreToolUse", tool_name="Bash")
check(state()["state"] == "working", "other PreToolUse ignored")
hook("Notification", notification_type="elicitation_dialog", message="Pick one")
check(state()["state"] == "input", "elicitation_dialog -> input")
hook("Notification", notification_type="agent_needs_input", message="x")
check(state()["state"] == "input", "agent_needs_input -> input")
hook("UserPromptSubmit")
check(state()["state"] == "working", "UserPromptSubmit -> working")
hook("Notification", notification_type="auth_success", message="ok")
check(state()["state"] == "working", "other notifications ignored")
hook("SessionEnd")
check(state() is None, "SessionEnd deletes the file")
r = subprocess.run([sys.executable, str(ROOT / "deskhub" / "hook_bridge.py"), "Stop"],
                   input=b"not json", capture_output=True, env=env, timeout=30)
check(r.returncode == 0 and r.stdout == b"", "garbage stdin is harmless")

# ---- installer -------------------------------------------------------------

other = {"matcher": "", "hooks": [{"type": "command", "command": "node omc/hook.mjs notification"}]}
settings = {
    "model": "opus",
    "statusLine": {"type": "command", "command": "echo hi"},
    "hooks": {
        "Notification": [copy.deepcopy(other)],
        "Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "node omc/hook.mjs stop"}]}],
        "PreToolUse": [{"matcher": "Bash", "hooks": [{"type": "command", "command": "lint"}]}],
    },
}
settings_path = home / ".claude" / "settings.json"
settings_path.parent.mkdir(parents=True)
settings_path.write_text(json.dumps(settings, indent=2), encoding="utf-8")

def install(*args):
    r = subprocess.run([sys.executable, str(ROOT / "install_claude.py"), *args],
                       capture_output=True, env=env, timeout=60, text=True)
    check(r.returncode == 0, f"installer {args}: {r.stderr}")
    return json.loads(settings_path.read_text(encoding="utf-8"))

def ours(cfg):
    return {ev: [e for e in v if "hook_bridge.py" in json.dumps(e)] for ev, v in cfg["hooks"].items()}

got = install("hooks")
check((home / ".deskhub" / "hook_bridge.py").is_file(), "bridge copied")
check((home / ".deskhub" / "settings.json.bak").is_file(), "settings backed up")
for ev in ["Notification", "PermissionRequest", "PreToolUse", "UserPromptSubmit", "PostToolUse", "Stop", "SessionEnd"]:
    mine = ours(got).get(ev, [])
    want = "AskUserQuestion|ExitPlanMode" if ev == "PreToolUse" else ""
    check(len(mine) == 1 and mine[0]["matcher"] == want and mine[0]["hooks"][0]["type"] == "command"
          and mine[0]["hooks"][0]["command"].endswith(f'hook_bridge.py" {ev}'), f"{ev} hook added: {mine}")
check(got["hooks"]["Notification"][0] == other and got["hooks"]["Notification"][1:] == ours(got)["Notification"],
      "existing hook first, ours appended")
check(got["hooks"]["PreToolUse"][0] == settings["hooks"]["PreToolUse"][0] and got["statusLine"] == settings["statusLine"],
      "other settings untouched")

again = install("hooks")
check(again == got, "re-running does not duplicate")
check(all(len(v) == 1 for v in ours(again).values() if v), "one entry per event")

removed = install("hooks", "--remove")
check(removed == settings, f"--remove restores the original: {removed}")

# `all` installs the status line too and removes both.
full = install()
check("hook_bridge.py" in json.dumps(full["hooks"]) and "statusline_bridge.py" in full["statusLine"]["command"], "all installs both")
back = install("--remove")
check(back == settings, f"all --remove restores the original: {back}")

# ---- alert watcher ---------------------------------------------------------

watch_dir = home / "watch"
watch_dir.mkdir()

def put(sid, state, age=0, message="", project="proj", pids=()):
    (watch_dir / f"{sid}.json").write_text(json.dumps({
        "state": state, "cwd": f"C:\\x\\{project}", "project": project, "message": message,
        "updated": int(time.time() - age), "pids": list(pids)}), encoding="utf-8")

a = ClaudeAlerts(watch_dir)
a.foreground_pid = lambda: 0
check(a.poll() is None and a.msg is None, "nothing waiting -> nothing sent at start")

put("a", "permission", age=20, message="Claude needs your permission to use Bash", project="alpha")
m = a.poll()
check(m == {"type": "alert", "id": "a", "kind": "permission", "agent": "claude",
            "title": "Claude needs your permission to use Bash", "detail": "",
            "project": "alpha"}, f"permission alert: {m}")
check(a.poll() is None, "unchanged alert is not resent")

put("b", "input", age=5, project="beta")
m = a.poll()
check(m and m["id"] == "b" and m["kind"] == "input" and m["title"] == "Claude is waiting for you"
      and m["detail"] == "Finished. Waiting for your reply", f"newest waiting session wins: {m}")

put("c", "working", age=0)
check(a.poll() is None, "working sessions do not alert")

a.dismiss("b")
m = a.poll()
check(m and m["id"] == "a", f"dismissed session suppressed, older one shows: {m}")
a.dismiss("a")
check(a.poll() == {"type": "alert", "clear": True}, "clear when everything is dismissed")
check(a.poll() is None, "clear sent once")
put("b", "input", age=0, message="Pick an option")
m = a.poll()
check(m and m["id"] == "b" and m["detail"] == "Pick an option", f"state change lifts the suppression: {m}")

put("b", "working")
check(a.poll() == {"type": "alert", "clear": True}, "clear when the session starts working")

put("i", "idle", age=5, project="idle-proj")
check(a.poll() is None, "just-finished session does not alert yet")
put("i", "idle", age=40, project="idle-proj")
m = a.poll()
check(m and m["id"] == "i" and m["kind"] == "input" and m["detail"] == "Finished. Waiting for your reply",
      f"idle 30+ s alerts as waiting: {m}")
put("i", "working")
check(a.poll() == {"type": "alert", "clear": True}, "clear when the idle session resumes")

# A waiting session whose window is in front counts as seen, and stays seen.
fg = {"pid": 4242}
a.foreground_pid = lambda: fg["pid"]
put("v", "idle", age=40, project="viewed", pids=[1, 4242, 9])
check(a.poll() is None, "session in the front window is treated as seen")
fg["pid"] = 0
check(a.poll() is None, "...and stays seen after switching away")
put("v", "permission", age=0, project="viewed", pids=[1, 4242, 9])
m = a.poll()
check(m and m["id"] == "v", f"new state after switching away alerts again: {m}")
fg["pid"] = 4242
check(a.poll() is None and a.msg and a.msg["id"] == "v", "permission stays while its window is in front")
put("v", "idle", age=40, project="viewed", pids=[1, 4242, 9])
check(a.poll() == {"type": "alert", "clear": True}, "a finished session clears once its window is in front")
fg["pid"] = 0
put("v", "working")
a.poll()

put("old", "permission", age=31 * 60)
check(a.poll() is None, "30+ minute old waiting session ignored")
check((watch_dir / "old.json").is_file(), "...but kept")
put("ancient", "permission", age=3 * 3600)
a.poll()
check(not (watch_dir / "ancient.json").exists(), "2+ hour old file deleted")

put("long", "input", message="Caf\u00e9 " + "x" * 300, project="p" * 80)
m = a.poll()
check(m and len(m["detail"]) <= 120 and m["detail"].startswith("Cafe ") and len(m["project"]) == 40, f"text folded and trimmed: {m}")
check(a.msg == m, "current alert kept for resend after reconnect")

put("f", "input", pids=[2**30, 2**30 + 1])
a.poll()
res = a.focus("f")
check(isinstance(res, str), "focus with missing pids returns")
check(isinstance(a.focus("nope"), str), "focus of unknown session returns")
if sys.platform == "win32":
    check(res == "no window found for the session", f"focus result: {res}")

shutil.rmtree(home, ignore_errors=True)
print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
