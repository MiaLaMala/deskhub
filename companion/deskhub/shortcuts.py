"""Shortcut tiles: what the hub shows, and what a tap does on this PC."""
import ctypes
import logging
import os
import subprocess
import sys

from .text import ascii_fold

log = logging.getLogger(__name__)

MAX_TILES = 16
ACTIONS = {"keys", "run", "open", "media", "volume", "lock"}


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
        })
    return tiles


def hub_view(tiles: list[dict]) -> dict:
    return {"type": "tiles",
            "tiles": [{k: t[k] for k in ("label", "icon", "color")} for t in tiles]}


def _keyboard():
    from pynput.keyboard import Controller, Key

    return Controller(), Key


_KEY_ALIASES = {"win": "cmd", "windows": "cmd", "control": "ctrl", "escape": "esc",
                "return": "enter", "del": "delete", "pgup": "page_up", "pgdn": "page_down"}


def press_combo(combo: str):
    kb, Key = _keyboard()
    keys = []
    for part in combo.lower().replace(" ", "").split("+"):
        part = _KEY_ALIASES.get(part, part)
        if len(part) == 1:
            keys.append(part)
        elif hasattr(Key, part):
            keys.append(getattr(Key, part))
        else:
            raise ValueError(f"unknown key {part!r} in {combo!r}")
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
    elif action == "lock":
        ctypes.windll.user32.LockWorkStation()
    elif action == "media" and media is not None:
        return media.command(target)
    return None
