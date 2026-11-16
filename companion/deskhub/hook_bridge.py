"""Claude Code hook bridge for the desk hub. Standard library only.

Claude Code runs this as a hook command with the hook's JSON on stdin:

    python hook_bridge.py <Event>

It records whether the session is working or waiting for you in
~/.deskhub/claude_sessions/<session_id>.json, for the companion to show on the
board. Only the state, the project folder name and the notification text are
stored, never prompts or tool input. It prints nothing and always exits 0, so it
can't get in Claude Code's way.
"""
import json
import os
import pathlib
import sys
import tempfile
import time

MAX_LEVELS = 12
WAITING = {
    "permission_prompt": "permission",
    "idle_prompt": "input",
    "elicitation_dialog": "input",
    "agent_needs_input": "input",
}
ASKS = {
    "AskUserQuestion": "Claude has a question for you",
    "ExitPlanMode": "Claude has a plan ready for your review",
}


def sessions_dir() -> pathlib.Path:
    return pathlib.Path.home() / ".deskhub" / "claude_sessions"


def ancestors(limit: int = MAX_LEVELS) -> list[int]:
    """Parent process ids, nearest first (Windows only; empty elsewhere)."""
    if sys.platform != "win32":
        return []
    import ctypes
    from ctypes import wintypes

    class ENTRY(ctypes.Structure):
        _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                    ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_size_t),
                    ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                    ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", ctypes.c_long),
                    ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_wchar * 260)]

    k32 = ctypes.windll.kernel32
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)  # TH32CS_SNAPPROCESS
    if snap in (None, wintypes.HANDLE(-1).value):
        return []
    parent = {}
    try:
        e = ENTRY()
        e.dwSize = ctypes.sizeof(ENTRY)
        ok = k32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(e))
        while ok:
            parent[e.th32ProcessID] = e.th32ParentProcessID
            ok = k32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(e))
    finally:
        k32.CloseHandle(wintypes.HANDLE(snap))
    out, pid = [], os.getpid()
    while len(out) < limit:
        pid = parent.get(pid, 0)
        if not pid or pid in out:  # pids get reused, so guard against loops
            break
        out.append(pid)
    return out


def record(event: str, data: dict):
    sid = str(data.get("session_id") or "")
    if not sid or any(c in sid for c in "/\\:"):
        return
    path = sessions_dir() / f"{sid}.json"
    if event == "SessionEnd":
        path.unlink(missing_ok=True)
        return
    state, message = "working", ""
    tool = str(data.get("tool_name") or "")
    if event == "Notification":
        state = WAITING.get(data.get("notification_type"), "")
        if not state:
            return
        message = " ".join(str(data.get("message") or "").split())[:200]
    elif event == "PermissionRequest":
        # A permission dialog is showing (terminal and desktop app alike).
        state, message = "permission", f"Claude wants to use {tool}" if tool else ""
    elif event == "PreToolUse":
        # Tools that stop and wait for you without a permission dialog.
        if tool not in ASKS:
            return
        state, message = "input", ASKS[tool]
    elif event == "Stop":
        # Finished its turn. The companion alerts once it has been idle a little
        # while (the desktop app never sends Claude Code's idle_prompt notification).
        state = "idle"
    elif event not in ("UserPromptSubmit", "PostToolUse"):
        return
    cwd = str(data.get("cwd") or "")
    rec = {
        "state": state,
        "cwd": cwd,
        "project": os.path.basename(cwd.rstrip("/\\")),
        "message": message,
        "updated": int(time.time()),
        "pids": ancestors(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(rec, f)
    os.replace(tmp, path)


def main():
    try:
        event = sys.argv[1] if len(sys.argv) > 1 else ""
        record(event, json.loads(sys.stdin.buffer.read()))
    except Exception:
        pass  # never break Claude Code over this


if __name__ == "__main__":
    main()
