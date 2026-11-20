"""Home on a 5 x 3 grid: sizes, bounds, overlaps, placement and the old columns."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from deskhub.pages import columns_to_grid, grid_problem, home_grid, home_message, place, widget_sizes

problems = []


def check(ok, what):
    print(("ok  " if ok else "BAD ") + what)
    if not ok:
        problems.append(what)


def G(n, x, y, w, h):
    return {"widget": n, "x": x, "y": y, "w": w, "h": h}


check(widget_sizes("weather")[:2] == ["1x1", "2x1"], "weather comes in 1x1 and up")
check("2x3" in widget_sizes("events") and "1x1" not in widget_sizes("events"), "Up next needs 2 wide, can be 3 tall")
check("2x2" in widget_sizes("clock") and "2x3" not in widget_sizes("clock"), "clock up to 2 tall")
check(grid_problem([G("weather", 0, 0, 2, 1), G("net", 2, 0, 1, 1)]) == [], "side by side is fine")
check("overlaps weather" in grid_problem([G("weather", 0, 0, 2, 1), G("net", 1, 0, 1, 1)])[0], "overlap caught")
check("runs off" in grid_problem([G("media", 4, 0, 2, 1)])[0], "past the right edge caught")
check("runs off" in grid_problem([G("events", 0, 1, 2, 3)])[0], "past the bottom caught")
check("isn't a size" in grid_problem([G("media", 0, 0, 1, 1)])[0], "unsupported size caught")
check("no such widget" in grid_problem([G("radio", 0, 0, 1, 1)])[0], "unknown widget caught")

placed, left = place([("events", 2, 3), ("clock", 3, 1), ("stats", 3, 1), ("net", 1, 1), ("weather", 2, 1)])
check(placed[:3] == [G("events", 0, 0, 2, 3), G("clock", 2, 0, 3, 1), G("stats", 2, 1, 3, 1)], f"placed in order: {placed}")
check(G("net", 2, 2, 1, 1) in placed and G("weather", 3, 2, 2, 1) in placed and not left, "fills the last row")
_, left = place([("media", 5, 1), ("game", 5, 1), ("printer", 5, 1), ("stats", 1, 1)])
check(left == ["stats"], "a full grid leaves the rest out")

check(columns_to_grid(["weather", "stats", "claude"], ["net", "printer", "game"]) ==
      [G("weather", 0, 0, 3, 1), G("stats", 0, 1, 3, 1), G("claude", 0, 2, 3, 1),
       G("net", 3, 0, 2, 1), G("printer", 3, 1, 2, 1), G("game", 3, 2, 2, 1)], "two columns become 3 + 2 wide")
check(columns_to_grid(["claude", "events"], []) == [G("claude", 0, 0, 3, 1), G("events", 0, 1, 3, 2)],
      "Up next at the bottom of a column takes the rest")

cfg = {"home": {"header": False, "grid": [
    {"widget": "Weather", "x": 0, "y": 0, "w": 2, "h": 1},
    {"widget": "media", "x": 1, "y": 0, "w": 2, "h": 1},      # overlaps: dropped
    {"widget": "clock", "x": 2, "y": 0, "w": 3, "h": 2},
    {"widget": "net", "x": "zero"},                            # not a number: dropped
]}}
check(home_grid(cfg) == [G("weather", 0, 0, 2, 1), G("clock", 2, 0, 3, 2)], f"bad entries dropped: {home_grid(cfg)}")
m = home_message(cfg)
check(m["header"] is False and m["grid"] == home_grid(cfg), "message carries the grid")
check(m["left"] == ["weather", "clock"] and m["right"] == [], "and columns for older firmware")

# The setup step: undo takes the last widget off, clear starts over.
import builtins
import tempfile

import tomlkit
from deskhub import setup_cli

answers = iter(["n",                      # no slim top bar
                "n",                      # don't keep today's layout
                "clock", "3x1", "media", "2x1", "undo",
                "net", "1x1", "clear", "undo",
                "weather", "2x1", "stats", "2x1", "undo", "events", "2x2", ""])
real_input = builtins.input
builtins.input = lambda prompt="": next(answers)
try:
    with tempfile.TemporaryDirectory() as d:
        path = pathlib.Path(d) / "config.toml"
        path.write_text("", encoding="utf-8")
        setup_cli.step_home(path)
        saved = tomlkit.parse(path.read_text(encoding="utf-8")).unwrap()["home"]["grid"]
finally:
    builtins.input = real_input
check(saved == [G("weather", 0, 0, 2, 1), G("events", 2, 0, 2, 2)], f"undo and clear in setup: {saved}")

# Navigation bar order follows [pages] enabled; Home leads; unknown names and repeats go.
from deskhub.pages import enabled_pages, layout_message

ordered = enabled_pages({"pages": {"enabled": ["shortcuts", "github", "Stats", "bogus", "home", "stats"]}})
check(ordered == ["home", "shortcuts", "github", "stats"], f"pages in listed order: {ordered}")
msg = layout_message({"pages": {"enabled": ["timer", "ai"]}})
check(msg["pages"] == ["home", "timer", "ai"] and msg["ordered"] is True, f"layout sends the order: {msg}")
default = enabled_pages({"printers": [{}], "games": [{}]})
check(default[-1] == "shortcuts" and default[0] == "home" and "github" not in default,
      f"default order keeps Shortcuts last: {default}")

# Setup's Pages step keeps the order; a page turned on goes at the end.
with tempfile.TemporaryDirectory() as d:
    path = pathlib.Path(d) / "config.toml"
    path.write_text('[pages]\nenabled = ["home", "timer", "stats"]\n', encoding="utf-8")
    # One answer per page after Home: turn on "ai", keep timer and stats, then the nav bar.
    answers = iter(["", "y", "", "", "", "", "", "", "", "", "", "", "left"])
    builtins.input = lambda prompt="": next(answers)
    try:
        setup_cli.step_pages(path)
    finally:
        builtins.input = real_input
    got = tomlkit.parse(path.read_text(encoding="utf-8")).unwrap()["pages"]["enabled"]
check(got == ["home", "timer", "stats", "ai"], f"setup keeps the order: {got}")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
