"""Built-in game presets: what's on by default, turning them off, overriding them,
launch targets, and telling League of Legends from Teamfight Tactics. Fake
processes and clients only; launches nothing and never contacts Riot.

    uv run python tests/test_game_presets.py
"""
import json
import pathlib
import sys
import tempfile

from deskhub import custom_games as cg
from deskhub import game_presets as gp

problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


tmp = pathlib.Path(tempfile.mkdtemp())

# Riot client found through Riot's own install record.
rc = tmp / "RiotClientServices.exe"
rc.write_text("")
installs = tmp / "RiotClientInstalls.json"
installs.write_text(json.dumps({"rc_default": str(rc).replace("\\", "/")}))
gp.RIOT_INSTALLS = installs

names = [p["name"] for p in gp.PRESETS]
check(len(names) == len(set(n.lower() for n in names)), "preset names are unique")
check({"League of Legends", "Teamfight Tactics", "VALORANT", "Fortnite", "Minecraft", "Roblox"} <= set(names),
      "popular games included")
for p in gp.PRESETS:
    check(all(x == x.lower() and x.endswith(".exe") for x in p["process"]), f"{p['name']}: lower-case .exe names")

entries = {e["name"]: e for e in gp.preset_entries({}, set())}
check(len(entries) == len(gp.PRESETS), "all presets on by default")
lol = entries["League of Legends"]
check(lol["launch"] == f'"{str(rc).replace(chr(92), "/")}" --launch-product=league_of_legends --launch-patchline=live',
      f"LoL launches through the Riot Client: {lol.get('launch')}")
check(entries["Teamfight Tactics"]["launch"] == lol["launch"], "TFT opens the same client")
check(entries["Fortnite"]["launch"].startswith("com.epicgames.launcher://"), "Epic link")
check(entries["Rocket League"]["image"].endswith("/252950/header.jpg"), "cover from Steam's CDN")
check("image" not in entries["League of Legends"], "no made-up art")

gp.RIOT_INSTALLS = tmp / "missing.json"
check("launch" not in gp.preset_entries({}, set())[0], "no Riot Client -> no launch target")
gp.RIOT_INSTALLS = installs

off = gp.preset_entries({"game_presets": {"enabled": False}}, set())
check(off == [], "presets can be turned off")
some = [e["name"] for e in gp.preset_entries({"game_presets": {"disabled": ["roblox", "Fortnite"]}}, set())]
check("Roblox" not in some and "Fortnite" not in some and "VALORANT" in some, "single presets can be skipped")

# Your own entry with the same name replaces the preset.
games = cg.load_games({"games": [{"name": "Minecraft", "process": "javaw.exe", "title": "GT: New Horizons"}]})
mc = [g for g in games if g["name"] == "Minecraft"]
check(len(mc) == 1 and mc[0]["title"] == "gt: new horizons", f"user entry wins over the preset: {mc}")

# League client's local API decides between LoL and TFT.
class FakeProc:
    def __init__(self, name, args):
        self.info = {"name": name}
        self._args = args

    def cmdline(self):
        return self._args


client = [FakeProc("LeagueClientUx.exe", ["x.exe", "--app-port=51234", "--remoting-auth-token=abc"])]
asked = []


def fake_get(mode):
    def get(url, auth):
        asked.append((url, auth))
        return {"gameData": {"queue": {"gameMode": mode}}}
    return get


check(gp.league_mode(lambda attrs: client, fake_get("TFT")) == "tft", "TFT game")
check(asked[-1] == ("https://127.0.0.1:51234/lol-gameflow/v1/session", ("riot", "abc")), f"local API only: {asked}")
check(gp.league_mode(lambda attrs: client, fake_get("CLASSIC")) == "lol", "Summoner's Rift is LoL")
check(gp.league_mode(lambda attrs: [], fake_get("TFT")) == "lol", "no client -> LoL")


def broken(url, auth):
    raise OSError("refused")


check(gp.league_mode(lambda attrs: client, broken) == "lol", "API error -> LoL")

# In the tracker: the running game follows the client's mode.
now = [1000.0]
procs = [("league of legends.exe", "")]
fake_processes = lambda wanted: ((n, (lambda c=c: c)) for n, c in procs if n in wanted)
games = cg.load_games({})
c = cg.CustomGames(games, clock=lambda: now[0], processes=fake_processes, windows=lambda: [],
                   state_file=tmp / "s.json")
mode = ["tft"]
c.league_mode = lambda: mode[0]
check(c.poll()["name"] == "Teamfight Tactics", "TFT shown while a TFT game runs")
mode[0] = "lol"
now[0] += 10
check(c.poll()["name"] == "Teamfight Tactics", "mode is re-checked at most every 30 s")
now[0] += 30
p = c.poll()
check(p["name"] == "League of Legends", f"then follows the client: {p}")
procs[:] = [("valorant-win64-shipping.exe", "")]
now[0] += 5
check(c.poll()["name"] == "VALORANT", "VALORANT")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
