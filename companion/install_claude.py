"""Connect (or disconnect) Claude Code to the desk hub.

    python install_claude.py [statusline|hooks|all]            # install (default: all)
    python install_claude.py [statusline|hooks|all] --remove   # undo it

statusline: copies statusline_bridge.py to ~/.deskhub/ and points `statusLine` in
  ~/.claude/settings.json at it. The bridge wraps whatever status line you had and
  reports your plan usage limits. Remove puts the previous `statusLine` back.
hooks: copies hook_bridge.py to ~/.deskhub/ and adds hooks to settings.json that
  report when a session is waiting for you, so the board can alert you. Your other
  hooks are left alone; remove deletes only the ones added here.

Both back up settings.json to ~/.deskhub/settings.json.bak first.
"""
import json
import pathlib
import shutil
import sys

HOME = pathlib.Path.home()
SETTINGS = HOME / ".claude" / "settings.json"
DEST = HOME / ".deskhub"
BRIDGE = DEST / "statusline_bridge.py"
STATE = DEST / "statusline_previous.json"
SRC = pathlib.Path(__file__).resolve().parent / "deskhub" / "statusline_bridge.py"
HOOK_BRIDGE = DEST / "hook_bridge.py"
HOOK_SRC = pathlib.Path(__file__).resolve().parent / "deskhub" / "hook_bridge.py"
HOOK_EVENTS = ["Notification", "PermissionRequest", "PreToolUse", "UserPromptSubmit", "PostToolUse", "Stop",
               "SessionEnd"]
# PreToolUse only for the tools that wait for you, so other tool calls skip the hook.
HOOK_MATCHERS = {"PreToolUse": "AskUserQuestion|ExitPlanMode"}


def load() -> dict:
    return json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.is_file() else {}


def write(settings: dict):
    SETTINGS.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")


def backup():
    if SETTINGS.is_file():
        shutil.copy2(SETTINGS, DEST / "settings.json.bak")


def install_statusline():
    DEST.mkdir(exist_ok=True)
    shutil.copy2(SRC, BRIDGE)
    settings = load()
    current = settings.get("statusLine")
    if current and "statusline_bridge.py" in json.dumps(current):
        print("Status line already installed; bridge script updated.")
        return
    backup()
    STATE.write_text(json.dumps({"statusLine": current}), encoding="utf-8")

    py = pathlib.Path(sys.executable).as_posix()
    cmd = f'"{py}" "{BRIDGE.as_posix()}"'
    if current and current.get("type") == "command" and current.get("command"):
        wrapped = current["command"].replace('"', '\\"')
        cmd += f' --wrap "{wrapped}"'
    new = {"type": "command", "command": cmd}
    if current and "padding" in current:
        new["padding"] = current["padding"]
    settings["statusLine"] = new
    write(settings)
    print("Installed. New Claude Code sessions will report usage limits to the hub.")


def remove_statusline(strict: bool = True):
    if not STATE.is_file():
        if strict:
            sys.exit("Nothing to remove (no saved previous status line).")
        return
    previous = json.loads(STATE.read_text(encoding="utf-8")).get("statusLine")
    settings = load()
    if previous is None:
        settings.pop("statusLine", None)
    else:
        settings["statusLine"] = previous
    write(settings)
    STATE.unlink()
    print("Restored your previous status line.")


def _ours(entry) -> bool:
    return isinstance(entry, dict) and "hook_bridge.py" in json.dumps(entry.get("hooks"))


def _strip_hooks(settings: dict) -> bool:
    """Remove our hook entries in place. Returns whether anything was removed."""
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return False
    changed = False
    for event in list(hooks):
        entries = hooks[event]
        if not isinstance(entries, list):
            continue
        kept = [e for e in entries if not _ours(e)]
        if len(kept) != len(entries):
            changed = True
            if kept:
                hooks[event] = kept
            else:
                del hooks[event]
    if changed and not hooks:
        del settings["hooks"]
    return changed


def install_hooks():
    DEST.mkdir(exist_ok=True)
    shutil.copy2(HOOK_SRC, HOOK_BRIDGE)
    settings = load()
    backup()
    _strip_hooks(settings)  # re-running replaces our entries instead of duplicating them
    py = pathlib.Path(sys.executable).as_posix()
    hooks = settings.setdefault("hooks", {})
    for event in HOOK_EVENTS:
        cmd = f'"{py}" "{HOOK_BRIDGE.as_posix()}" {event}'
        hooks.setdefault(event, []).append({"matcher": HOOK_MATCHERS.get(event, ""),
                                            "hooks": [{"type": "command", "command": cmd}]})
    write(settings)
    print("Installed. New Claude Code sessions will tell the hub when they are waiting for you.")


def remove_hooks():
    settings = load()
    if _strip_hooks(settings):
        write(settings)
        print("Removed the desk hub hooks.")
    else:
        print("No desk hub hooks found.")


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    remove = "--remove" in args
    what = [a for a in args if a != "--remove"] or ["all"]
    if what[0] not in ("statusline", "hooks", "all") or len(what) > 1:
        sys.exit(__doc__)
    what = what[0]
    if what in ("statusline", "all"):
        remove_statusline(strict=what == "statusline") if remove else install_statusline()
    if what in ("hooks", "all"):
        remove_hooks() if remove else install_hooks()


if __name__ == "__main__":
    main()
