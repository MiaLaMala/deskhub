"""Steam Web API extras with a fake API: friends in game, playtime merged into the
snapshot, refresh intervals, back-off on errors, and the setup key prompt (fake
credential store). Never contacts Steam.

    uv run python tests/test_steam_web.py
"""
import builtins
import getpass
import sys

from deskhub import setup_cli, steam_web as sw
from deskhub.steam import Steam

problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


check(sw.steamid64(123975586) == 76561198084241314, "steamid64 from the userdata folder")

calls = []
now = [1000.0]
friends_list = {"friendslist": {"friends": [{"steamid": str(i)} for i in range(150)]}}


def fake_get(url, params):
    calls.append(url.rsplit("/", 3)[-3])
    if "GetFriendList" in url:
        return friends_list
    if "GetPlayerSummaries" in url:
        ids = params["steamids"].split(",")
        return {"response": {"players": [
            {"personaname": f"Friend {i}", "gameextrainfo": "Café Game" if i in ("7", "120") else None}
            for i in ids]}}
    if "GetOwnedGames" in url:
        return {"response": {"games": [{"appid": 1363080, "playtime_forever": 2950}, {"appid": 10, "playtime_forever": 0}]}}
    raise AssertionError(url)


w = sw.SteamWeb("k" * 32, get=fake_get, clock=lambda: now[0])
f = w.friends_in_game(1)
check(f == [{"name": "Friend 120", "game": "Cafe Game"}, {"name": "Friend 7", "game": "Cafe Game"}],
      f"friends in game, 150 friends in two summary calls: {f}")
check(calls == ["GetFriendList", "GetPlayerSummaries", "GetPlayerSummaries"], f"one friend list + two summary pages: {calls}")
calls.clear()
now[0] += 30
w.friends_in_game(1)
check(calls == [], "cached for a minute")
now[0] += 31
w.friends_in_game(1)
check(len(calls) == 3, "refreshed after a minute")

check(w.playtimes(1) == {1363080: 2950, 10: 0}, "playtime per appid")
calls.clear()
now[0] += 600
w.playtimes(1)
check(calls == [], "playtime cached for 30 minutes")


def failing(url, params):
    raise OSError("403")


wf = sw.SteamWeb("bad", get=failing, clock=lambda: now[0])
check(wf.friends_in_game(1) == [] and wf.playtimes(1) == {}, "errors give empty results")
attempts = []
wf._get = lambda url, params: attempts.append(url) or {}
wf.friends_in_game(1)
wf.playtimes(1)
check(attempts == [], "backs off after an error")

# A private friends list must not stop playtime.
def friends_private(url, params):
    if "GetFriendList" in url:
        import httpx
        raise httpx.HTTPStatusError("401", request=httpx.Request("GET", url), response=httpx.Response(401))
    return fake_get(url, params)


wp = sw.SteamWeb("k", get=friends_private, clock=lambda: now[0])
check(wp.friends_in_game(1) == [] and wp.playtimes(1).get(1363080) == 2950, "playtime still works with a private friends list")

# Merged into the Steam snapshot.
s = Steam(web=w)
s.account_id = 5
s._steam_part = lambda root, running: (None, [{"appid": 1363080, "name": "Manor Lords", "last": 1, "total_min": 0}])
import deskhub.steam as stm
stm.read_registry = lambda: (sys.prefix, 0)   # any existing folder counts as Steam installed
snap = s.snapshot()
check(snap["recent"][0]["total_min"] == 2950, f"Web API fills in playtime: {snap['recent']}")
check(snap["friends"] and snap["friends"][0]["game"] == "Cafe Game", "friends in the snapshot")
s2 = Steam()
s2._steam_part = s._steam_part
check(s2.snapshot()["friends"] == [], "no key: no friends, no calls")

# Setup prompt, with a fake credential store and fake Steam check.
store = {}
sw.get_key = lambda: store.get("k", "")
sw.set_key = lambda k: store.__setitem__("k", k) if k else store.pop("k", None)
checked = []
sw._http_get = lambda url, params: checked.append(params["key"]) or {}
import deskhub.steam
deskhub.steam.steam_installed = lambda: True


def run(answers, secret=""):
    it = iter(answers)
    builtins.input = lambda prompt="": next(it)
    getpass.getpass = lambda prompt="": secret
    setup_cli.step_steam_key()


run(["y"], "not-a-key")
check(store == {}, "malformed key refused")
run(["y"], "A" * 32)
check(store == {"k": "A" * 32} and checked == ["A" * 32], "key checked with Steam, then saved")
run([""])
check(store == {"k": "A" * 32}, "Enter keeps the saved key")
run(["n"])
check(store == {}, "key can be removed")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
