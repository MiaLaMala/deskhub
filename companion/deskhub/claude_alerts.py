"""Tells the board when a Claude Code session is waiting for you.

hook_bridge.py (run by Claude Code hooks) keeps one small state file per session
in ~/.deskhub/claude_sessions/. This picks the session to alert about, and brings
its window to the front when you tap "Show on PC".
"""
import json
import logging
import pathlib
import sys
import time

from .text import ascii_fold

log = logging.getLogger(__name__)

FRESH_S = 30 * 60
STALE_S = 2 * 3600
IDLE_AFTER_S = 30  # a finished session alerts once it has waited this long


class ClaudeAlerts:
    def __init__(self, root: pathlib.Path | None = None, idle_after: float = IDLE_AFTER_S):
        self.idle_after = idle_after
        self.foreground_pid = foreground_pid  # replaceable in tests
        self.root = root or pathlib.Path.home() / ".deskhub" / "claude_sessions"
        self.dismissed: dict[str, int] = {}  # session id -> `updated` of the dismissed alert
        self.sessions: dict[str, dict] = {}
        self.msg: dict | None = None  # what the board currently shows

    def _load(self):
        now = time.time()
        self.sessions = {}
        if not self.root.is_dir():
            return
        for p in self.root.glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                age = now - float(d["updated"])
            except (OSError, ValueError, KeyError, TypeError):
                continue
            if age > STALE_S:
                p.unlink(missing_ok=True)
            elif isinstance(d, dict):
                self.sessions[p.stem] = d

    def _pick(self) -> dict | None:
        now = time.time()
        best = None
        for sid, d in self.sessions.items():
            state, age = d.get("state"), now - d["updated"]
            if state not in ("permission", "input", "idle") or age > FRESH_S:
                continue
            if state == "idle" and age < self.idle_after:
                continue  # just finished: you are probably still looking at it
            if self.dismissed.get(sid) == d["updated"]:
                continue
            if best is None or d["updated"] > best[1]["updated"]:
                best = (sid, d)
        if best is None:
            return None
        sid, d = best
        kind = "permission" if d["state"] == "permission" else "input"
        # Claude Code's own message ("Claude needs your permission to use Bash") is
        # the most specific line, so it's the title on its own. A message that
        # isn't a sentence about Claude (an answer choice, say) goes under a
        # generic title instead.
        message = (d.get("message") or "").strip()
        generic = "Claude needs your permission" if kind == "permission" else "Claude is waiting for you"
        if message.startswith("Claude "):
            title, detail = message, ""
        elif message:
            title, detail = generic, message
        else:
            title, detail = generic, "" if kind == "permission" else "Finished. Waiting for your reply"
        return {"type": "alert", "id": sid, "kind": kind, "agent": "claude",
                "title": ascii_fold(title, 60), "detail": ascii_fold(detail, 120),
                "project": ascii_fold(d.get("project"), 40)}

    def _mark_seen(self):
        """Opening a session in the desktop app (or its terminal) fires no hook, so
        treat a finished session as seen while the window that runs it is in front.
        It alerts again only once its state changes."""
        try:
            fg = self.foreground_pid()
        except Exception:
            return
        if not fg:
            return
        for sid, d in self.sessions.items():
            # Only finished sessions: questions and permissions clear when answered.
            if d.get("state") == "idle" and fg in (d.get("pids") or []):
                self.dismissed[sid] = d["updated"]

    def poll(self) -> dict | None:
        """The message to send if the alert changed since the last call, else None."""
        self._load()
        self._mark_seen()
        new = self._pick()
        if new == self.msg:
            return None
        self.msg = new
        return new or {"type": "alert", "clear": True}

    def dismiss(self, sid: str):
        d = self.sessions.get(sid)
        if d:
            self.dismissed[sid] = d["updated"]

    def focus(self, sid: str) -> str:
        if sid not in self.sessions:
            self._load()
        d = self.sessions.get(sid)
        if not d:
            result = "session not found"
        else:
            try:
                result = focus_pids(d.get("pids") or [])
            except Exception as e:
                result = f"failed ({e})"
        log.info("alert focus %s: %s", sid, result)
        return result


def foreground_pid() -> int:
    """Process id that owns the window in front, or 0."""
    if sys.platform != "win32":
        return 0
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.windll.user32
    u32.GetForegroundWindow.restype = wintypes.HWND
    hwnd = u32.GetForegroundWindow()
    if not hwnd:
        return 0
    pid = wintypes.DWORD()
    u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def focus_pids(pids: list[int]) -> str:
    """Bring the window of the first process in `pids` that owns one to the front."""
    if sys.platform != "win32":
        return "not supported on this OS"
    import ctypes
    from ctypes import wintypes

    u32 = ctypes.windll.user32
    wanted = [int(p) for p in pids]
    found: dict[int, int] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if u32.IsWindowVisible(hwnd):
            pid = wintypes.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value in wanted and not u32.GetWindow(hwnd, 4):  # skip owned windows
                found.setdefault(pid.value, hwnd)
        return True

    u32.EnumWindows(visit, 0)
    for pid in wanted:
        hwnd = found.get(pid)
        if not hwnd:
            continue
        if u32.IsIconic(hwnd):
            u32.ShowWindow(hwnd, 9)  # SW_RESTORE
        # Windows refuses focus changes from background apps unless the user just
        # pressed a key, so tap Alt first.
        u32.keybd_event(0x12, 0, 0, 0)
        u32.keybd_event(0x12, 0, 2, 0)
        if u32.SetForegroundWindow(hwnd):
            return f"focused window of pid {pid}"

        class FLASHW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("hwnd", wintypes.HWND), ("dwFlags", wintypes.DWORD),
                        ("uCount", wintypes.UINT), ("dwTimeout", wintypes.DWORD)]

        u32.FlashWindowEx(ctypes.byref(FLASHW(ctypes.sizeof(FLASHW), hwnd, 3 | 12, 3, 0)))
        return f"could not focus window of pid {pid}, flashed it instead"
    return "no window found for the session"
