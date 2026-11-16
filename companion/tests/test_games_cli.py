"""deskhub-games: picking an open window, the suggested entry, and editing
config.toml (keeps comments, adds the Games page). Uses fake windows; never
touches the real config.

    uv run python tests/test_games_cli.py
"""
import builtins
import pathlib
import shutil
import sys
import tempfile
import tomllib

from deskhub import games_cli as g

problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


# Suggestions: generic programs match by title, others by process.
s = g.suggest({"title": "GT: New Horizons 2.9.0", "process": "javaw.exe", "exe": "C:/jdk/javaw.exe"})
check(s == {"name": "GT: New Horizons", "title": "GT: New Horizons", "process": ["java.exe", "javaw.exe"],
            "launch": ""}, f"java game by title, version dropped: {s}")
s = g.suggest({"title": "Dolphin 5.0-21460", "process": "dolphin.exe", "exe": "C:/Dolphin/Dolphin.exe"})
check(s == {"name": "Dolphin", "process": "dolphin.exe", "launch": "C:/Dolphin/Dolphin.exe"},
      f"normal game by process, launch from its exe: {s}")

fake = [(1, "GT: New Horizons 2.9.0", "javaw.exe"), (2, "Program Manager", "explorer.exe"),
        (3, "", "ghost.exe"), (4, "GT: New Horizons 2.9.0", "javaw.exe")]
fake_windows = lambda: [(pid, t, (lambda n=n: n)) for pid, t, n in fake]
wins = g.open_windows(fake_windows)
check([w["title"] for w in wins] == ["GT: New Horizons 2.9.0"], f"system, untitled and duplicate windows skipped: {wins}")

root = pathlib.Path(tempfile.mkdtemp())
conf = root / "config.toml"
shutil.copy(pathlib.Path(__file__).parent.parent / "config.example.toml", conf)
text = conf.read_text(encoding="utf-8")
conf.write_text(text + '\n[pages]\nenabled = ["home", "stats"]\n' if "[pages]" not in text else text, encoding="utf-8")


def run(answers, fn, *a):
    it = iter(answers)
    builtins.input = lambda prompt="": next(it)
    fn(*a)


# Pick the window, keep every suggestion, add an image path.
run(["1", "", "", "C:/pics/gtnh.png", ""], g.cmd_add, conf, fake_windows)
cfg = tomllib.loads(conf.read_text(encoding="utf-8"))
check(cfg.get("games") == [{"name": "GT: New Horizons", "title": "GT: New Horizons",
                            "process": ["java.exe", "javaw.exe"], "image": "C:/pics/gtnh.png"}],
      f"game written: {cfg.get('games')}")
check("games" in cfg["pages"]["enabled"], f"Games page turned on: {cfg['pages']}")
check("# Shortcut tiles" in conf.read_text(encoding="utf-8"), "comments kept")

# Typed by hand.
run(["0", "Retro", "retroarch.exe", "", "", r"C:\RetroArch\retroarch.exe"], g.cmd_add, conf, fake_windows)
cfg = tomllib.loads(conf.read_text(encoding="utf-8"))
check(cfg["games"][1] == {"name": "Retro", "process": "retroarch.exe", "launch": "C:/RetroArch/retroarch.exe"},
      f"manual entry: {cfg['games'][1]}")

# Duplicates refused; remove works and drops the empty list.
run(["1", "", "", "", ""], g.cmd_add, conf, fake_windows)
check(len(tomllib.loads(conf.read_text(encoding="utf-8"))["games"]) == 2, "duplicate name refused")
run(["1"], g.cmd_remove, conf)
run(["1"], g.cmd_remove, conf)
check("games" not in tomllib.loads(conf.read_text(encoding="utf-8")), "removing the last game drops [[games]]")

# The result loads in the companion.
from deskhub.custom_games import load_games
run(["1", "", "", "", ""], g.cmd_add, conf, fake_windows)
check(len(load_games({**tomllib.loads(conf.read_text(encoding="utf-8")), "game_presets": {"enabled": False}})) == 1,
      "companion loads it")

shutil.rmtree(root)
print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
