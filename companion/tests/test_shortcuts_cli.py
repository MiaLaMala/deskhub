"""`deskhub-setup shortcuts`: add, change, move and remove [[tiles]] in a temp config."""
import builtins
import contextlib
import io
import pathlib
import re
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import tomlkit
from deskhub import shortcuts_cli as sc
from deskhub.shortcuts import load_tiles

problems = []


def check(ok, what):
    print(("ok  " if ok else "BAD ") + what)
    if not ok:
        problems.append(what)


def drive(path, answers):
    it = iter(answers)
    real = builtins.input
    builtins.input = lambda prompt="": next(it)
    out = io.StringIO()
    try:
        with contextlib.redirect_stdout(out):
            sc.menu(path)
    finally:
        builtins.input = real
    return out.getvalue()


def tiles(path):
    return tomlkit.parse(path.read_text(encoding="utf-8")).unwrap().get("tiles", [])


# The icon list matches what the firmware can draw.
header = (pathlib.Path(__file__).resolve().parents[2] / "firmware" / "main" / "icons.h").read_text(encoding="utf-8")
table = header[header.index("HUB_ICONS[]"):header.index("};", header.index("HUB_ICONS[]"))]
check(sc.ICONS == re.findall(r'\{"(\w+)"', table), "icon names match firmware/main/icons.h")

with tempfile.TemporaryDirectory() as d:
    path = pathlib.Path(d) / "config.toml"
    path.write_text('[hub]\ntoken = "x"\n\n# My buttons\n[[tiles]]\nlabel = "Lock PC"\nicon = "lock"\n'
                    'color = "#5b3fa0"\naction = "lock"\ntarget = ""\nstate = ""\n', encoding="utf-8")

    # Add: a key combo (a bad one first), default icon, default colour.
    out = drive(path, ["2", "Mute Discord", "keys", "ctrl+shift+banana", "ctrl+shift+m", "", "", ""])
    t = tiles(path)
    check(len(t) == 2 and t[1] == {"label": "Mute Discord", "icon": "keyboard", "color": "#3a4256",
                                   "action": "keys", "target": "ctrl+shift+m"}, f"keys tile added: {t[-1:]}")
    check("Unknown key 'banana'" in out, "a bad key is explained")

    # Add: volume by number, picking a target; icon follows the target; ? lists icons; a bad colour.
    out = drive(path, ["2", "Vol +", "5", "up", "?", "", "blue", "#4285F4", ""])
    t = tiles(path)
    check(t[2] == {"label": "Vol +", "icon": "volume_up", "color": "#4285f4", "action": "volume",
                   "target": "up"}, f"volume tile added: {t[2]}")
    check("rocket_launch" in out, "? lists the icons")

    # Change the first tile: keep its label, make it open a folder; its own state key stays.
    drive(path, ["3", "1", "", "open", "~/Downloads", "", "#8a6d1f", ""])
    t = tiles(path)
    check(t[0]["action"] == "open" and t[0]["target"] == "~/Downloads" and t[0]["label"] == "Lock PC"
          and t[0]["icon"] == "folder" and t[0]["state"] == "", f"tile changed: {t[0]}")

    # Move the last to the top, then remove the middle one.
    drive(path, ["4", "3", "1", ""])
    check([x["label"] for x in tiles(path)] == ["Vol +", "Lock PC", "Mute Discord"], "moved to the top")
    drive(path, ["5", "2", ""])
    check([x["label"] for x in tiles(path)] == ["Vol +", "Mute Discord"], "removed")
    check("# My buttons" in path.read_text(encoding="utf-8"), "comments kept")
    check(len(load_tiles(tomlkit.parse(path.read_text(encoding="utf-8")).unwrap())) == 2,
          "the companion reads the result")

    # Empty to go back changes nothing; the 16-button limit is enforced.
    before = path.read_text(encoding="utf-8")
    drive(path, ["3", "", "5", "", ""])
    check(path.read_text(encoding="utf-8") == before, "going back changes nothing")
    doc = tomlkit.parse(before)
    for _ in range(14):
        doc["tiles"].append(tomlkit.table() | {"label": "x", "action": "lock", "target": ""})
    path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    out = drive(path, ["2", ""])
    check("at most 16" in out and len(tiles(path)) == 16, "no more than 16 buttons")

    # A config without any tiles yet.
    path.write_text('[hub]\ntoken = "x"\n', encoding="utf-8")
    drive(path, ["1", "2", "Lock", "lock", "", "", ""])
    check(tiles(path) == [{"label": "Lock", "icon": "lock", "color": "#3a4256", "action": "lock", "target": ""}],
          "first tile in an empty config")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
