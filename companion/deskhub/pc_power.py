"""Watch the PC's display power, so the board can sleep along with it.

Windows tells a window when the console display turns off, dims or turns back on
(GUID_CONSOLE_DISPLAY_STATE), and when the PC is about to suspend. A hidden window
on its own thread receives those and reports "asleep" True/False.
"""
import ctypes
import ctypes.wintypes as wt
import logging
import sys
import threading
from typing import Callable

log = logging.getLogger(__name__)

WM_POWERBROADCAST = 0x0218
PBT_APMSUSPEND = 0x0004
PBT_POWERSETTINGCHANGE = 0x8013
DEVICE_NOTIFY_WINDOW_HANDLE = 0

# Display states in the notification: 0 off, 1 on, 2 dimmed (counts as on).
DISPLAY_OFF = 0


class GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD), ("Data4", ctypes.c_ubyte * 8)]


def _guid(d1, d2, d3, d4: bytes) -> GUID:
    return GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*d4))


GUID_CONSOLE_DISPLAY_STATE = _guid(0x6FE69556, 0x704A, 0x47A0, bytes.fromhex("8F24C28D936FDA47"))


class POWERBROADCAST_SETTING(ctypes.Structure):
    _fields_ = [("PowerSetting", GUID), ("DataLength", wt.DWORD), ("Data", ctypes.c_ubyte * 4)]


LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM)


class WNDCLASSW(ctypes.Structure):
    _fields_ = [("style", wt.UINT), ("lpfnWndProc", WNDPROC), ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int), ("hInstance", wt.HINSTANCE), ("hIcon", wt.HICON),
                ("hCursor", wt.HANDLE), ("hbrBackground", wt.HBRUSH), ("lpszMenuName", wt.LPCWSTR),
                ("lpszClassName", wt.LPCWSTR)]


def display_state(lparam: int) -> int | None:
    """The display state in a PBT_POWERSETTINGCHANGE notification, or None for another setting."""
    s = POWERBROADCAST_SETTING.from_address(lparam)
    if bytes(s.PowerSetting) != bytes(GUID_CONSOLE_DISPLAY_STATE):
        return None
    return s.Data[0]


class PowerWatch:
    """Calls on_change(asleep) from its own thread when the PC's display sleeps or wakes.

    on_change(True) is also called just before the PC suspends, and should return
    quickly (it may block briefly so a message gets out before the network goes down).
    """

    def __init__(self, on_change: Callable[[bool], None]):
        self.on_change = on_change
        self.asleep: bool | None = None
        self._proc = WNDPROC(self._wndproc)  # kept referenced for the window's lifetime

    def start(self) -> bool:
        if sys.platform != "win32":
            return False
        threading.Thread(target=self._run, name="pc-power", daemon=True).start()
        return True

    def _set(self, asleep: bool):
        if asleep != self.asleep:
            self.asleep = asleep
            log.info("PC display %s", "asleep" if asleep else "awake")
            try:
                self.on_change(asleep)
            except Exception as e:
                log.warning("display power callback failed: %s", e)

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_POWERBROADCAST:
            if wparam == PBT_POWERSETTINGCHANGE and lparam:
                state = display_state(lparam)
                if state is not None:
                    self._set(state == DISPLAY_OFF)
            elif wparam == PBT_APMSUSPEND:
                self._set(True)
            return 1
        return _user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _run(self):
        try:
            hinst = _kernel32.GetModuleHandleW(None)
            wc = WNDCLASSW(lpfnWndProc=self._proc, hInstance=hinst, lpszClassName="DeskHubPowerWatch")
            _user32.RegisterClassW(ctypes.byref(wc))
            # A normal (never shown) top-level window: message-only windows miss suspend broadcasts.
            hwnd = _user32.CreateWindowExW(0, "DeskHubPowerWatch", "Desk Hub", 0, 0, 0, 0, 0,
                                           None, None, hinst, None)
            if not hwnd:
                raise ctypes.WinError(ctypes.get_last_error())
            # Windows sends the current state right away, then each change.
            if not _user32.RegisterPowerSettingNotification(
                    hwnd, ctypes.byref(GUID_CONSOLE_DISPLAY_STATE), DEVICE_NOTIFY_WINDOW_HANDLE):
                raise ctypes.WinError(ctypes.get_last_error())
            msg = wt.MSG()
            while _user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                _user32.TranslateMessage(ctypes.byref(msg))
                _user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            log.warning("can't watch the PC's display power: %s", e)


if sys.platform == "win32":
    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _kernel32.GetModuleHandleW.restype = wt.HMODULE
    _kernel32.GetModuleHandleW.argtypes = [wt.LPCWSTR]
    _user32.DefWindowProcW.restype = LRESULT
    _user32.DefWindowProcW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    _user32.RegisterClassW.restype = wt.ATOM
    _user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    _user32.CreateWindowExW.restype = wt.HWND
    _user32.CreateWindowExW.argtypes = [wt.DWORD, wt.LPCWSTR, wt.LPCWSTR, wt.DWORD, ctypes.c_int, ctypes.c_int,
                                        ctypes.c_int, ctypes.c_int, wt.HWND, wt.HMENU, wt.HINSTANCE, wt.LPVOID]
    _user32.RegisterPowerSettingNotification.restype = wt.HANDLE
    _user32.RegisterPowerSettingNotification.argtypes = [wt.HANDLE, ctypes.POINTER(GUID), wt.DWORD]
    _user32.GetMessageW.restype = wt.BOOL
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
    _user32.TranslateMessage.argtypes = [ctypes.POINTER(wt.MSG)]
    _user32.DispatchMessageW.restype = LRESULT
    _user32.DispatchMessageW.argtypes = [ctypes.POINTER(wt.MSG)]
