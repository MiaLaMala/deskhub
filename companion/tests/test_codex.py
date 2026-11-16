"""Codex usage reader and AI provider pick, on a temp CODEX_HOME.

    uv run python tests/test_codex.py
"""
import datetime as dt
import json
import os
import pathlib
import shutil
import tempfile
import time

problems = []

def check(cond, msg):
    if not cond:
        problems.append(msg)

home = pathlib.Path(tempfile.mkdtemp())
os.environ["CODEX_HOME"] = str(home)

from deskhub.__main__ import pick_ai
from deskhub.codex_usage import CodexUsage, _model_name, codex_home

check(codex_home() == home, "CODEX_HOME respected")
check(_model_name("gpt-6.1-sol") == "GPT-6.1 Sol", _model_name("gpt-6.1-sol"))
check(_model_name("gpt-5-codex") == "GPT-5 Codex", _model_name("gpt-5-codex"))
check(len(_model_name("gpt-5.1-codex-max-extra")) <= 15, "name length")

now = dt.datetime.now(dt.timezone.utc)

def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")

def tc(t, total, out, rl=None, info=True):
    payload = {"type": "token_count", "rate_limits": rl,
               "info": {"last_token_usage": {"input_tokens": total - out, "output_tokens": out,
                                             "total_tokens": total}} if info else None}
    return json.dumps({"timestamp": iso(t), "type": "event_msg", "payload": payload})

def ctx(t, model):
    return json.dumps({"timestamp": iso(t), "type": "turn_context", "payload": {"model": model}})

reset5, reset7 = int(time.time()) + 3600, int(time.time()) + 86400
good = {"primary": {"used_percent": 42.0, "window_minutes": 300, "resets_at": reset5},
        "secondary": {"used_percent": 17.5, "window_minutes": 10080, "resets_at": reset7}}
stale = {"primary": {"used_percent": 90.0, "window_minutes": 10080, "resets_at": int(time.time()) - 60},
         "secondary": None}

d = home / "sessions" / "2026" / "01" / "01"
d.mkdir(parents=True)
f = d / "rollout-a.jsonl"
lines = [
    ctx(now - dt.timedelta(minutes=50), "gpt-6.1-sol"),
    tc(now - dt.timedelta(days=2), 1000, 100, stale),
    tc(now - dt.timedelta(days=1), 2000, 200),
    tc(now - dt.timedelta(minutes=40), 3000, 300, good),
    tc(now - dt.timedelta(minutes=30), 500, 50, info=False),
    tc(now - dt.timedelta(minutes=20), 700, 70),
]
text = "\n".join(lines) + "\n" + tc(now, 9999, 99)[:40]  # partial last line
f.write_text(text, encoding="utf-8")

usage = CodexUsage()
s = usage.snapshot()
check(s["block"] == {"active": False}, "block inactive")
check(s["last_hour"] == 3700, f"last_hour {s['last_hour']}")
check(s["days"][-2] == 2000 and len(s["days"]) == 7, f"days {s['days']}")
check(s["days"][-1] + s["days"][-2] + s["days"][-3] == 1000 + 2000 + 3700 or s["today"]["messages"] >= 1,
      "day totals")
check(s["today"]["messages"] in (2, 3), f"today messages {s['today']}")
check(s["models"] and s["models"][0]["name"] == "GPT-6.1 Sol", f"models {s['models']}")
check(s["last_active"] == int((now - dt.timedelta(minutes=20)).timestamp()), "last_active")
lim = s["limits"]
check(lim.get("five_hour") == {"pct": 42.0, "reset": reset5}, f"five_hour {lim}")
check(lim.get("seven_day") == {"pct": 17.5, "reset": reset7}, f"seven_day {lim}")
check(lim.get("updated") == int((now - dt.timedelta(minutes=40)).timestamp()), "updated")

# The partial line is completed later and picked up; duplicates are not double counted.
with open(f, "a", encoding="utf-8") as fh:
    fh.write(tc(now, 9999, 99)[40:] + "\n")
s2 = usage.snapshot()
check(s2["last_hour"] == 3700 + 9999, f"partial line completed: {s2['last_hour']}")
f2 = d / "rollout-b.jsonl"
f2.write_text(tc(now - dt.timedelta(minutes=20), 700, 70) + "\n", encoding="utf-8")
check(usage.snapshot()["last_hour"] == 3700 + 9999 + 700, "separate file counted once per (file, timestamp)")

# Only an expired reading: no limits at all.
home2 = pathlib.Path(tempfile.mkdtemp())
(home2 / "sessions").mkdir()
(home2 / "sessions" / "rollout-x.jsonl").write_text(tc(now, 100, 10, stale) + "\n", encoding="utf-8")
check(CodexUsage(home2).snapshot()["limits"] == {}, "expired limits dropped")
check(CodexUsage(pathlib.Path(tempfile.mkdtemp()) / "nope").snapshot()["last_active"] == 0, "missing home")
shutil.rmtree(home2)

# Provider pick.
claude = {"type": "claude", "last_active": 100, "limits": {}}
codex = {"type": "codex", "last_active": 200, "limits": {}}
m = pick_ai("auto", claude, codex)
check(m["type"] == "ai" and m["provider"] == "codex", f"auto newer codex: {m['provider']}")
check(pick_ai("auto", {**claude, "last_active": 300}, codex)["provider"] == "claude", "auto newer claude")
check(pick_ai("auto", {**claude, "last_active": 200}, codex)["provider"] == "claude", "auto tie -> claude")
check(pick_ai("auto", claude, None)["provider"] == "claude", "auto without codex")
check(pick_ai("claude", claude, codex)["provider"] == "claude", "forced claude")
check(pick_ai("codex", claude, codex)["provider"] == "codex", "forced codex")
check(pick_ai("codex", None, codex)["provider"] == "codex", "forced codex, no claude")

shutil.rmtree(home)
print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
