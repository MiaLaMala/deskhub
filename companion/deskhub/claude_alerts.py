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


class ClaudeAlerts:
    def __init__(self, root: pathlib.Path | None = None):
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
            if d.get("state") not in ("permission", "input") or now - d["updated"] > FRESH_S:
                continue
            if self.dismissed.get(sid) == d["updated"]:
                continue
            if best is None or d["updated"] > best[1]["updated"]:
                best = (sid, d)
        if best is None:
            return None
        sid, d = best
        if d["state"] == "permission":
            title, detail = "Claude needs your permission", d.get("message")
        else:
            title, detail = "Claude is waiting for you", d.get("message") or "Finished. Waiting for your reply"
        return {"type": "alert", "id": sid, "kind": d["state"], "agent": "claude",
                "title": ascii_fold(title, 60), "detail": ascii_fold(detail, 120),
                "project": ascii_fold(d.get("project"), 40)}

    def poll(self) -> dict | None:
        """The message to send if the alert changed since the last call, else None."""
        self._load()
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
