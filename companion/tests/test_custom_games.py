"""Custom (non-Steam) games: config parsing, process detection, playtime tracking,
merging with the Steam list, images and launching. Uses fake processes and clocks;
never launches anything.

    uv run python tests/test_custom_games.py
"""
import os
import pathlib
import struct
import sys
import tempfile

from PIL import Image

from deskhub import custom_games as cg
from deskhub import steam as st

problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


tmp = pathlib.Path(tempfile.mkdtemp())
img = tmp / "mc.png"
Image.new("RGB", (800, 800), (40, 160, 60)).save(img)

NOPRESETS = {"game_presets": {"enabled": False}}
games = cg.load_games({**NOPRESETS, "games": [
    {"name": "Minecraft", "process": "javaw.exe", "match": "Minecraft", "image": str(img),
     "launch": "minecraft://"},
    {"name": "Dolphin", "process": ["Dolphin.exe", "DolphinWX.exe"]},
    {"name": "", "process": "x.exe"},       # no name -> skipped
    {"name": "No process"},                 # no process -> skipped
]})
check([g["name"] for g in games] == ["Minecraft", "Dolphin"], f"invalid entries skipped: {games}")
check(games[0]["process"] == ["javaw.exe"] and games[0]["match"] == "minecraft", "process and match lower-cased")
check(games[1]["process"] == ["dolphin.exe", "dolphinwx.exe"], "process list")
mc, dol = games[0]["id"], games[1]["id"]
check(mc == cg.game_id("minecraft ") and cg.is_custom(mc) and mc > 2**31, "stable id above Steam appids")
check(mc != dol, "distinct ids")

# Fake processes and clock.
procs: list[tuple[str, str]] = []
now = [1_000_000.0]


def fake_processes(wanted):
    for name, cmd in procs:
        if name in wanted:
            yield name, (lambda c=cmd: c.lower())


state = tmp / "custom_games.json"
c = cg.CustomGames(games, clock=lambda: now[0], processes=fake_processes, state_file=state)
check(c.poll() is None and c.recent() == [], "nothing running, nothing played")

procs[:] = [("javaw.exe", "javaw -cp foo.jar com.example.OtherApp")]
check(c.poll() is None, "javaw without 'minecraft' in its command line is ignored")

procs[:] = [("javaw.exe", "javaw -Dminecraft.launcher.brand=x net.minecraft.client.main.Main")]
p = c.poll()
check(p and p["appid"] == mc and p["session_s"] == 0, f"minecraft detected: {p}")
now[0] += 1800
p = c.poll()
check(p["session_s"] == 1800 and p["total_min"] == 30, f"session counts: {p}")

procs[:] = []
now[0] += 5
check(c.poll() is None, "stopped")
r = c.recent()
check(len(r) == 1 and r[0]["appid"] == mc and r[0]["total_min"] == 30 and r[0]["last"] == int(now[0]),
      f"played game is recent with its playtime: {r}")
check(state.is_file(), "state saved")

# State survives a restart, and playtime adds up.
c2 = cg.CustomGames(games, clock=lambda: now[0], processes=fake_processes, state_file=state)
check(c2.recent() == r, "state reloaded")
procs[:] = [("Dolphin.exe".lower(), "")]
now[0] += 100
c2.poll()
now[0] += 600
c2.poll()
procs[:] = []
now[0] += 1
c2.poll()
check([g["appid"] for g in c2.recent()] == [dol, mc], "newest first")

# Merged into the Steam snapshot (Steam itself off here).
s = st.Steam(clock=lambda: now[0], custom=c2, use_steam=False)
snap = s.snapshot()
check(snap["found"] and snap["playing"] is None and [g["appid"] for g in snap["recent"]] == [dol, mc],
      f"custom games in the snapshot: {snap}")
procs[:] = [("javaw.exe", "net.minecraft.client.main.Main")]
snap = s.snapshot()
check(snap["playing"] and snap["playing"]["appid"] == mc and [g["appid"] for g in snap["recent"]] == [dol],
      f"playing custom game leaves the recent list: {snap}")

# Art from the configured image, cropped to each shape.
frames = s.frames()
sizes = {struct.unpack("<IHHHH", f[4:16])[3]: struct.unpack("<IHHHH", f[4:16])[1:3] for f in frames
         if struct.unpack("<I", f[4:8])[0] == mc}
check(sizes.get(0) == (340, 159) and sizes.get(1) == (64, 96), f"header and thumb frames: {sizes}")
check(all(f.startswith(b"STM1") and len(f) == 16 + 2 * struct.unpack("<HH", f[8:12])[0] * struct.unpack("<HH", f[8:12])[1]
          for f in frames), "frame sizes")
check(not any(struct.unpack("<I", f[4:8])[0] == dol for f in frames), "no image -> no frame (board placeholder)")

# Window title matching (a modpack that runs as a generic java.exe).
tg = cg.load_games({**NOPRESETS, "games": [
    {"name": "GT: New Horizons", "title": "New Horizons", "process": ["java.exe", "javaw.exe"]},
    {"name": "Any window", "title": "Some Emulator"},   # title alone is enough
]})
check(len(tg) == 2 and tg[1]["process"] == [] and tg[0]["title"] == "new horizons", f"title games load: {tg}")
wins: list[tuple[int, str, str]] = []
fake_windows = lambda: [(pid, t, (lambda n=n: n)) for pid, t, n in wins]
ct = cg.CustomGames(tg, clock=lambda: now[0], processes=fake_processes, windows=fake_windows,
                    state_file=tmp / "t.json")
check(ct.poll() is None, "no windows, nothing running")
wins[:] = [(10, "GT: New Horizons 2.9.0", "chrome.exe")]
check(ct.poll() is None, "title in the wrong program (e.g. a browser tab) is ignored")
wins[:] = [(11, "GT: New Horizons 2.9.0", "javaw.exe")]
p = ct.poll()
check(p and p["name"] == "GT: New Horizons", f"title + process match: {p}")
wins[:] = [(12, "Some Emulator - Zelda", "whatever.exe")]
p = ct.poll()
check(p and p["name"] == "Any window", f"title alone matches any program: {p}")

# Launching: only listed games, and only those with a launch target.
opened = []
cg.os.startfile = lambda t: opened.append(t)
check(s.launch(dol) is False, "game without launch refused")
check(s.launch(cg.game_id("unknown")) is False, "unknown id refused")
check(s.launch(mc) is True and opened == ["minecraft://"], f"launch opens the target: {opened}")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
