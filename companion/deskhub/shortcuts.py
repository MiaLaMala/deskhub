"""Shortcut tiles: what the hub shows, and what a tap does on this PC."""
import ctypes
import logging
import os
import subprocess
import sys

from .text import ascii_fold

log = logging.getLogger(__name__)

MAX_TILES = 16
ACTIONS = {"keys", "run", "open", "media", "volume", "lock", "mic"}
# Toggle tiles that light up on the board while their Windows state is on.
STATES = {"mic_mute", "speaker_mute"}


def tile_state(t: dict) -> str:
    """Which Windows state a tile shows: set with `state`, else guessed from what
    the tile does (the system mute tile, the mic action, a microphone icon).
    `state = ""` turns it off."""
    if "state" in t:
        st = str(t["state"])
        if st and st not in STATES:
            log.warning("tile %r: unknown state %r", t.get("label"), st)
        return st if st in STATES else ""
    action, target, icon = t.get("action", ""), str(t.get("target", "")), str(t.get("icon", ""))
    if action == "volume" and target == "mute":
        return "speaker_mute"
    if action == "mic" or icon in ("mic", "mic_off", "mic_none"):
        return "mic_mute"
    return ""


def load_tiles(cfg: dict) -> list[dict]:
    tiles = []
    for t in cfg.get("tiles", [])[:MAX_TILES]:
        action = t.get("action", "")
        if action not in ACTIONS:
            log.warning("tile %r: unknown action %r", t.get("label"), action)
        tiles.append({
            "label": ascii_fold(t.get("label", ""), 30),
            "icon": t.get("icon", "apps"),
            "color": t.get("color", "#2b2f3a"),
            "action": action,
            "target": str(t.get("target", "")),
            "state": tile_state(t),
        })
    return tiles


def hub_view(tiles: list[dict]) -> dict:
    return {"type": "tiles",
            "tiles": [{k: t[k] for k in ("label", "icon", "color")} for t in tiles]}


def lit_message(tiles: list[dict], states: dict[str, bool]) -> dict:
    """Which tiles are on, for the board: {"type": "tile_state", "on": [index, ...]}."""
    return {"type": "tile_state",
            "on": [i for i, t in enumerate(tiles) if t.get("state") and states.get(t["state"])]}


def _keyboard():
    from pynput.keyboard import Controller, Key

    return Controller(), Key


_KEY_ALIASES = {"win": "cmd", "windows": "cmd", "control": "ctrl", "escape": "esc",
                "return": "enter", "del": "delete", "pgup": "page_up", "pgdn": "page_down"}


def parse_combo(combo: str, Key) -> list:
    """The keys in "ctrl+shift+m"; ValueError names one it doesn't know."""
    keys = []
    for part in combo.lower().replace(" ", "").split("+"):
        part = _KEY_ALIASES.get(part, part)
        if len(part) == 1:
            keys.append(part)
        elif part and hasattr(Key, part):
            keys.append(getattr(Key, part))
        else:
            raise ValueError(f"unknown key {part!r} in {combo!r}")
    return keys


def combo_problem(combo: str) -> str | None:
    """Why a key combination can't be pressed, or None when it's fine."""
    _, Key = _keyboard()
    try:
        parse_combo(combo, Key)
    except ValueError as e:
        return str(e)
    return None


def press_combo(combo: str):
    kb, Key = _keyboard()
    keys = parse_combo(combo, Key)
    for k in keys:
        kb.press(k)
    for k in reversed(keys):
        kb.release(k)


def _tap(key_name: str):
    kb, Key = _keyboard()
    k = getattr(Key, key_name)
    kb.press(k)
    kb.release(k)


def run_tile(tile: dict, media=None):
    action, target = tile["action"], tile["target"]
    log.info("shortcut %r: %s %s", tile["label"], action, target)
    if action == "keys":
        press_combo(target)
    elif action == "run":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
        subprocess.Popen(target, shell=True, creationflags=flags)
    elif action == "open":
        path = os.path.expandvars(os.path.expanduser(target))
        os.startfile(path)
    elif action == "volume":
        _tap({"up": "media_volume_up", "down": "media_volume_down",
              "mute": "media_volume_mute"}[target])
    elif action == "mic":
        raise RuntimeError("mic tiles run on the audio thread")  # see Companion.handle
    elif action == "lock":
        ctypes.windll.user32.LockWorkStation()
    elif action == "media" and media is not None:
        return media.command(target)
    return None
