"""Shortcut buttons for the board's Shortcuts page: list, add, change, move and remove.

    uv run deskhub-setup shortcuts

Edits the [[tiles]] blocks in config.toml, keeping their order and any comments.
Restart the companion afterwards to send the new buttons to the board.
"""
import pathlib
import re
import textwrap

import tomlkit

from .shortcuts import MAX_TILES, combo_problem

# Names the board has a glyph for (firmware/main/icons.h, HUB_ICONS).
ICONS = [
    "home", "insights", "memory", "speed", "music_note", "event", "calendar_today",
    "wb_sunny", "cloud", "grid_view", "apps", "wifi", "computer", "desktop_windows",
    "play_arrow", "pause", "skip_next", "skip_previous", "volume_up", "volume_down",
    "volume_off", "mic", "mic_off", "lock", "photo_camera", "screenshot_monitor", "terminal",
    "code", "public", "folder", "keyboard", "power_settings_new", "schedule", "timer",
    "mail", "chat", "sports_esports", "rocket_launch", "bolt", "star", "favorite",
    "settings", "refresh", "dark_mode", "headphones", "videocam", "movie",
    "developer_board", "lan", "shuffle", "repeat",
]

# action: (what it does, what the target is, the choices for it or None for free text)
ACTIONS = {
    "keys":   ("press a key combination", "Keys, e.g. ctrl+shift+m, win+shift+s or f13", None),
    "run":    ("run a program or command", "Program or command, e.g. wt.exe or code C:\\Code\\project", None),
    "open":   ("open a file, folder or URL", "File, folder or URL, e.g. ~/Downloads or https://...", None),
    "media":  ("play/pause, next or previous track", "Which", ["toggle", "next", "prev"]),
    "volume": ("volume up, down or mute", "Which", ["up", "down", "mute"]),
    "mic":    ("mute or unmute the microphone in Windows", None, None),
    "lock":   ("lock the PC", None, None),
}

# A first icon for each action (and media/volume target), so most tiles need no choice.
DEFAULT_ICON = {
    "keys": "keyboard", "run": "terminal", "open": "folder", "mic": "mic_off", "lock": "lock",
    "media:toggle": "play_arrow", "media:next": "skip_next", "media:prev": "skip_previous",
    "volume:up": "volume_up", "volume:down": "volume_down", "volume:mute": "volume_off",
}
DEFAULT_COLOR = "#3a4256"
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{prompt}{suffix}: ").strip() or default


def _load(path: pathlib.Path):
    doc = tomlkit.parse(path.read_text(encoding="utf-8"))
    if "tiles" not in doc:
        doc["tiles"] = tomlkit.aot()
    return doc, doc["tiles"]


def _save(path: pathlib.Path, doc):
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def describe(t) -> str:
    action, target = t.get("action", ""), str(t.get("target", ""))
    what = f"{action} {target}".strip()
    return f"{t.get('label', '')!s:<16} {what:<34} {t.get('icon', '')} {t.get('color', '')}"


def _list(tiles) -> bool:
    if not len(tiles):
        print("  No buttons yet.")
        return False
    for i, t in enumerate(tiles, 1):
        print(f"  {i:>2}. {describe(t)}")
    return True


def _pick(tiles, verb: str) -> int | None:
    if not _list(tiles):
        return None
    raw = ask(f"Which button to {verb} (number, or empty to go back)")
    if raw.isdigit() and 1 <= int(raw) <= len(tiles):
        return int(raw) - 1
    return None


def ask_icon(default: str) -> str:
    while True:
        value = ask("Icon (? lists them)", default).lower()
        if value in ICONS:
            return value
        if value != "?":
            print(f"  No icon called {value!r}.")
        print(textwrap.fill(", ".join(ICONS), 78, initial_indent="  ", subsequent_indent="  "))


def ask_color(default: str) -> str:
    while True:
        value = ask("Colour as #rrggbb", default)
        if _HEX.fullmatch(value):
            return value.lower()
        print("  Use six hex digits, for example #3a4256.")


def ask_tile(old=None) -> dict:
    """Questions for one button; `old` gives the defaults when changing one."""
    old = old or {}
    while True:
        label = ask("Label", str(old.get("label", "")))
        if label and len(label) <= 30:
            break
        print("  A label of 1 to 30 characters.")
    names = list(ACTIONS)
    print("What it does:")
    for i, name in enumerate(names, 1):
        print(f"  {i}. {name:<7} {ACTIONS[name][0]}")
    current = str(old.get("action", ""))
    while True:
        raw = ask(f"Choose 1-{len(names)} or a name", current).lower()
        action = names[int(raw) - 1] if raw.isdigit() and 1 <= int(raw) <= len(names) else raw
        if action in ACTIONS:
            break
        print("  Pick one of the numbers above.")
    _, prompt, choices = ACTIONS[action]
    target = ""
    old_target = str(old.get("target", "")) if old.get("action") == action else ""
    if choices:
        while True:
            target = ask(f"{prompt}: {', '.join(choices)}", old_target or choices[0]).lower()
            if target in choices:
                break
            print(f"  Type {', '.join(choices)}.")
    elif prompt:
        while True:
            target = ask(prompt, old_target)
            if not target:
                print("  This needs a value.")
            elif action == "keys" and (problem := combo_problem(target)):
                print(f"  {problem[0].upper()}{problem[1:]}. Keys are joined with +, like ctrl+alt+t.")
            else:
                break
    icon_default = (str(old["icon"]) if old.get("icon") and old.get("action") == action
                    else DEFAULT_ICON.get(f"{action}:{target}", DEFAULT_ICON.get(action, "apps")))
    icon = ask_icon(icon_default)
    color = ask_color(str(old.get("color", DEFAULT_COLOR)))
    return {"label": label, "icon": icon, "color": color, "action": action, "target": target}


def _table(values: dict, keep=None):
    """A [[tiles]] table with these values; extra keys from `keep` (like state) stay."""
    t = keep if keep is not None else tomlkit.table()
    for k, v in values.items():
        t[k] = v
    return t


def add(path: pathlib.Path):
    doc, tiles = _load(path)
    if len(tiles) >= MAX_TILES:
        print(f"  The board shows at most {MAX_TILES} buttons; remove one first.")
        return
    tiles.append(_table(ask_tile()))
    _save(path, doc)
    print(f"  Added. {len(tiles)} buttons; 4, 6, 8, 12 or 16 make an even grid.")


def change(path: pathlib.Path):
    doc, tiles = _load(path)
    i = _pick(tiles, "change")
    if i is None:
        return
    _table(ask_tile(tiles[i]), keep=tiles[i])
    _save(path, doc)
    print("  Changed.")


def move(path: pathlib.Path):
    doc, tiles = _load(path)
    i = _pick(tiles, "move")
    if i is None:
        return
    raw = ask(f"New position, 1-{len(tiles)}")
    if not (raw.isdigit() and 1 <= int(raw) <= len(tiles)):
        return
    items = [tiles[k] for k in range(len(tiles))]
    items.insert(int(raw) - 1, items.pop(i))
    new = tomlkit.aot()
    for t in items:
        new.append(t)
    doc["tiles"] = new
    _save(path, doc)
    print("  Moved.")


def remove(path: pathlib.Path):
    doc, tiles = _load(path)
    i = _pick(tiles, "remove")
    if i is None:
        return
    label = tiles[i].get("label", "")
    del tiles[i]
    _save(path, doc)
    print(f"  Removed {label}.")


def menu(path: pathlib.Path):
    """Interactive shortcut menu; used by `deskhub-setup shortcuts`."""
    commands = [("List buttons", lambda p: _list(_load(p)[1])), ("Add a button", add),
                ("Change a button", change), ("Move a button", move), ("Remove a button", remove)]
    while True:
        print(f"\nShortcut buttons in {path}")
        for i, (label, _) in enumerate(commands, 1):
            print(f"  {i}. {label}")
        choice = ask(f"Choose 1-{len(commands)}, or empty to finish")
        if not choice:
            return
        if choice.isdigit() and 1 <= int(choice) <= len(commands):
            commands[int(choice) - 1][1](path)
