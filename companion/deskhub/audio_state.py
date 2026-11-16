"""Windows speaker and microphone mute, read (and set) through Core Audio.

Standard library only: plain ctypes calls into the COM interfaces
IMMDeviceEnumerator -> IMMDevice -> IAudioEndpointVolume, so no extra package
is needed. Every call runs on the caller's thread, which must have COM
initialised (see `com_thread`).
"""
import ctypes
import sys
import uuid
from ctypes import wintypes

E_RENDER, E_CAPTURE = 0, 1   # EDataFlow: speakers, microphone
E_CONSOLE = 0                # ERole
CLSCTX_ALL = 0x17

CLSID_MMDeviceEnumerator = "{BCDE0395-E52F-467C-8E3D-C4579291692E}"
IID_IMMDeviceEnumerator = "{A95664D2-9614-4F35-A746-DE8DB63617E6}"
IID_IAudioEndpointVolume = "{5CDF2C82-841E-4546-9722-0CF74078229A}"

# vtable slots (IUnknown takes 0-2)
_ENUM_GET_DEFAULT = 4      # IMMDeviceEnumerator::GetDefaultAudioEndpoint
_DEVICE_ACTIVATE = 3       # IMMDevice::Activate
_VOL_SET_MUTE = 14         # IAudioEndpointVolume::SetMute
_VOL_GET_MUTE = 15         # IAudioEndpointVolume::GetMute
_RELEASE = 2


class GUID(ctypes.Structure):
    _fields_ = [("data", ctypes.c_byte * 16)]

    def __init__(self, text: str):
        super().__init__()
        ctypes.memmove(self.data, uuid.UUID(text).bytes_le, 16)


def _method(obj: ctypes.c_void_p, slot: int, *argtypes):
    vtable = ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    return ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)(vtable[slot])


def _release(obj: ctypes.c_void_p):
    if obj:
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(
            ctypes.cast(obj, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents[_RELEASE])(obj)


def _endpoint_volume(flow: int) -> ctypes.c_void_p:
    ole32 = ctypes.windll.ole32
    enum, dev, vol = ctypes.c_void_p(), ctypes.c_void_p(), ctypes.c_void_p()
    ole32.CoCreateInstance(ctypes.byref(GUID(CLSID_MMDeviceEnumerator)), None, CLSCTX_ALL,
                           ctypes.byref(GUID(IID_IMMDeviceEnumerator)), ctypes.byref(enum))
    try:
        _method(enum, _ENUM_GET_DEFAULT, ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p))(
            enum, flow, E_CONSOLE, ctypes.byref(dev))
        try:
            _method(dev, _DEVICE_ACTIVATE, ctypes.POINTER(GUID), wintypes.DWORD, ctypes.c_void_p,
                    ctypes.POINTER(ctypes.c_void_p))(
                dev, ctypes.byref(GUID(IID_IAudioEndpointVolume)), CLSCTX_ALL, None, ctypes.byref(vol))
        finally:
            _release(dev)
    finally:
        _release(enum)
    return vol


def is_muted(flow: int) -> bool | None:
    """Mute state of the default speaker (E_RENDER) or microphone (E_CAPTURE).
    None when there is no such device."""
    if sys.platform != "win32":
        return None
    try:
        vol = _endpoint_volume(flow)
    except OSError:
        return None  # e.g. no microphone plugged in
    try:
        muted = wintypes.BOOL()
        _method(vol, _VOL_GET_MUTE, ctypes.POINTER(wintypes.BOOL))(vol, ctypes.byref(muted))
        return bool(muted.value)
    finally:
        _release(vol)


def set_muted(flow: int, muted: bool) -> bool:
    if sys.platform != "win32":
        return False
    try:
        vol = _endpoint_volume(flow)
    except OSError:
        return False
    try:
        _method(vol, _VOL_SET_MUTE, wintypes.BOOL, ctypes.c_void_p)(vol, bool(muted), None)
        return True
    finally:
        _release(vol)


def toggle_mic() -> bool | None:
    """Flip the default microphone's mute; returns the new state."""
    now = is_muted(E_CAPTURE)
    if now is None:
        return None
    set_muted(E_CAPTURE, not now)
    return not now


def com_thread():
    """Initialiser for the worker thread that makes these calls."""
    if sys.platform == "win32":
        ctypes.windll.ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED


def read_states() -> dict[str, bool]:
    out = {}
    for name, flow in (("speaker_mute", E_RENDER), ("mic_mute", E_CAPTURE)):
        m = is_muted(flow)
        if m is not None:
            out[name] = m
    return out
