"""Pi companion against a fake display: login with token, one message of every type from
cyd/PROTOKOLL.md checked field by field, page/refresh handling, a failing source, reconnect
with backoff. Sources are fakes built on the real mapping functions; no network.

    python tests/test_pi_app.py
"""
import asyncio
import datetime as dt
import pathlib
import sys
import tempfile
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from deskhub import github as gh
from deskhub.netstats import NetStats
from deskhub.pi import app as pa
from deskhub.pi import sources as s
from fake_cyd_hub import ALL_TYPES, TOKEN, FakeCyd
from pi_protocol import validate

problems = []


def check(ok, what):
    print(("ok  " if ok else "BAD ") + what)
    if not ok:
        problems.append(what)


pa.BACKOFF_START_S = 0.2
pa.BACKOFF_MAX_S = 0.5
pa.MIN_GAP_S = 0.4
NOW = 1_795_400_000
BERLIN = ZoneInfo("Europe/Berlin")

# Upstream answers, invented.
quota = {"ok": True, "stand": "2026-11-22T19:00:29+00:00",
         "sitzung": {"prozent": 11.0, "zurueck": "2036-11-22T22:39:59+00:00"},
         "woche": {"prozent": 45.0, "zurueck": "2036-11-29T23:59:59+00:00"}}
termine = {"termine": [{"title": "Beispiel", "start": "2036-11-23T07:30:00", "end": "2036-11-23T09:00:00", "allDay": False,
                        "kalender": "K", "ort": "Ort", "farbe": "#c8607f"}]}
lagen = {"lage": {"gesamt": 54, "oben": 53}, "stoerungen": [{"name": "Dienst"}]}
days = [{"date": (dt.date(2026, 11, 15) + dt.timedelta(days=i)).isoformat(), "weekday": i % 7,
         "contributionCount": i % 3, "contributionLevel": list(gh.LEVELS)[i % 3]} for i in range(7)]
cal = {"login": "beispiel", "total": 7, "days": days, "kinds": {}, "repos": []}
t0 = NOW // 3600 * 3600
wjson = {"current": {"temperature_2m": 7.2, "apparent_temperature": 4.1, "weather_code": 3, "is_day": 1,
                     "relative_humidity_2m": 81, "wind_speed_10m": 18},
         "hourly": {"time": [t0 + 3600 * k for k in range(30)], "temperature_2m": [6.0] * 30, "weather_code": [3] * 30,
                    "precipitation_probability": [40] * 30},
         "daily": {"time": [t0 + 86400 * k for k in range(7)], "weather_code": [61] * 7, "temperature_2m_max": [8.0] * 7,
                   "temperature_2m_min": [3.0] * 7, "precipitation_probability_max": [70] * 7}}

tmp = pathlib.Path(tempfile.mkdtemp())
hist = s.History(tmp / "h.json", clock=lambda: NOW)
lab = s.Homelab(lambda: NOW)
net = NetStats(clock=lambda: NOW, probe=lambda: 12.5, counters=lambda: type("C", (), {"bytes_sent": 5, "bytes_recv": 7})(),
               state_file=tmp / "net.json")
calls = {k: 0 for k in ("ai", "events", "homelab", "weather", "github", "net")}
fail = {k: False for k in calls}


def fake(name, build):
    def fetch():
        calls[name] += 1
        if fail[name]:
            raise RuntimeError("upstream down")
        return build()
    return fetch


def fetch_ai():
    lim = s.limits_from_kontingent(quota, NOW)
    hist.add(lim["seven_day"]["pct"])
    return s.ai_message(lim, hist.sent())


def fetch_net():
    net.tick()
    return net.message()


def make_sources(interval=30.0):
    return [
        pa.Source("ai", interval, fake("ai", fetch_ai)),
        pa.Source("events", interval, fake("events", lambda: s.events_message(termine, NOW, 7, BERLIN))),
        pa.Source("homelab", interval, fake("homelab", lambda: lab.message(lagen)), on_error=lab.failed),
        pa.Source("weather", interval, fake("weather", lambda: s.weather_message(wjson, "Hamburg", NOW))),
        pa.Source("github", interval, fake("github", lambda: gh.message(cal))),
        pa.Source("net", interval, fake("net", fetch_net)),
    ]


async def until(cond, timeout=6.0):
    end = asyncio.get_running_loop().time() + timeout
    while asyncio.get_running_loop().time() < end:
        if cond():
            return True
        await asyncio.sleep(0.05)
    return False


async def scenario():
    cfg = {"pages": {"enabled": ["claude", "calendar", "weather", "timer", "github", "homelab", "net"]}}
    async with FakeCyd() as hub:
        cfg["hub"] = {"host": hub.host, "token": TOKEN}
        comp = pa.PiCompanion(cfg, clock=lambda: NOW, sources=make_sources())
        stop = asyncio.Event()
        task = asyncio.create_task(comp.run(stop))
        got = await until(lambda: all(t in hub.types() for t in ALL_TYPES))
        check(got, f"login, then every message type arrives: {hub.types()}")
        check(hub.hellos[0] == {"type": "hello", "token": TOKEN}, "hello carries the token")
        check([m["type"] for m in hub.log[:2]] == ["time", "layout"], f"time and layout first: {[m['type'] for m in hub.log[:3]]}")
        check(hub.problems == [], f"every field matches the protocol: {hub.problems}")
        check(abs(hub.log[0]["unix"] - NOW) < 1, "time = the companion's clock")
        check(hub.last("layout")["pages"] == ["home", "claude", "calendar", "weather", "timer", "github", "homelab", "net"],
              "layout: all pages in protocol names")
        check(hub.last("ai")["limits"]["five_hour"]["pct"] == 11.0 and "history" in hub.last("ai"), "ai: limits and history")
        check(hub.last("homelab")["ok"] is True and hub.last("homelab")["down"][0]["name"] == "Dienst", "homelab with a down entry")
        check(hub.last("net")["speed"] is None, "net without speed test")

        # page: what is known goes out at once, and the source refreshes
        before_w, n_before = calls["weather"], hub.types().get("weather", 0)
        await asyncio.sleep(pa.MIN_GAP_S + 0.1)
        await hub.say({"type": "page", "name": "weather"})
        check(await until(lambda: hub.types().get("weather", 0) >= n_before + 2), "page weather: cached copy at once, then a fresh one")
        check(calls["weather"] == before_w + 1, "page weather: one fetch")
        await hub.say({"type": "page", "name": "weather"})
        await hub.say({"type": "page", "name": "weather"})
        await asyncio.sleep(0.3)
        check(calls["weather"] == before_w + 1, "page spam within the minimum gap does not fetch again")
        await hub.say({"type": "page", "name": "nonsense"})
        await hub.say({"type": "bogus"})
        await hub.say({"type": "refresh"})
        await asyncio.sleep(0.5)
        check(all(calls[k] >= 2 for k in ("ai", "events", "homelab", "github")), f"refresh asks every source: {calls}")

        # a failing source
        await asyncio.sleep(pa.MIN_GAP_S + 0.1)
        fail["homelab"] = fail["events"] = fail["github"] = fail["ai"] = True
        ev_count, ai_count, gh_count = (hub.types().get(k, 0) for k in ("events", "ai", "github"))
        hl_before = hub.types().get("homelab", 0)
        await hub.say({"type": "refresh"})
        check(await until(lambda: hub.types().get("homelab", 0) >= hl_before + 2), "homelab keeps being answered while down")
        down = hub.last("homelab")
        check(down["ok"] is False and down["up"] == 53 and down["total"] == 54 and down["updated"] == NOW,
              f"homelab ok:false with the last state: {down}")
        await asyncio.sleep(0.3)
        # the cached copy comes out on refresh, but nothing new is invented
        check(hub.last("events")["events"][0]["title"] == "Beispiel", "failed events source: last state stays")
        check(hub.last("ai")["limits"]["five_hour"]["pct"] == 11.0 and hub.last("github")["login"] == "beispiel",
              "failed ai/github sources: last state stays")
        check(hub.problems == [], "no protocol problems while sources fail")
        fail["homelab"] = fail["events"] = fail["github"] = fail["ai"] = False

        # reconnect: the display drops, the companion comes back and resends its state
        sess = hub.sessions
        start_log = len(hub.log)
        await hub.drop()
        check(await until(lambda: hub.sessions == sess + 1), "reconnects after the display drops the link")
        check(await until(lambda: all(t in {m["type"] for m in hub.log[start_log:]} for t in ALL_TYPES if t != "hello")),
              "after reconnect time, layout and all cached state are resent")
        check(hub.hellos[-1]["token"] == TOKEN, "the new session logs in with the token again")
        stop.set()
        task.cancel()
    check(hub.problems == [], f"no protocol problems in the whole run: {hub.problems}")

    # wrong token: refused, retried, never any data
    async with FakeCyd(token="other") as hub:
        comp = pa.PiCompanion({"hub": {"host": hub.host, "token": TOKEN}}, clock=lambda: NOW, sources=make_sources())
        task = asyncio.create_task(comp.run())
        await until(lambda: hub.refused >= 3, 8)
        check(hub.refused >= 3 and hub.log == [], f"wrong token: refused {hub.refused}x with backoff, nothing sent")
        task.cancel()

    # display not there at all: no crash, sources keep running
    comp = pa.PiCompanion({"hub": {"host": "127.0.0.1:9", "token": TOKEN}}, clock=lambda: NOW, sources=make_sources(0.2))
    task = asyncio.create_task(comp.run())
    await asyncio.sleep(1.2)
    check(not task.done() and comp.cache.get("weather"), "display unreachable: keeps running, state collected for later")
    task.cancel()


asyncio.run(scenario())

# defaults
check(pa.PiCompanion({"hub": {}}, sources=[]).host == "deskhub.local", "display address defaults to deskhub.local")
check(pa.layout_message({"claude": {"url": "u"}, "weather": {"latitude": 1, "longitude": 2}})["pages"]
      == ["home", "claude", "weather", "timer", "net"], "pages follow the configured sources")
check(pa.layout_message({"pages": {"enabled": ["net", "bogus", "claude", "net"]}})["pages"] == ["home", "net", "claude"],
      "explicit [pages] enabled: order kept, unknown dropped, home first")
check(not validate(pa.layout_message({})), "layout validates")
check(pa.INTERVALS == {"ai": 60, "events": 120, "homelab": 120, "weather": 900, "github": 3600, "time": 600, "net": 5},
      "intervals: quota 60 s, events and homelab 2 min, weather 15 min, GitHub 1 h, time 10 min")

# the example config loads, and builds the sources it describes (no fetch)
import os
import tomllib

example = tomllib.loads((pathlib.Path(__file__).resolve().parents[2] / "cyd" / "companion.example.toml").read_text(encoding="utf-8"))
os.environ["KONTINGENT_KEY"] = "dummy"
built = pa.PiCompanion({**example, "net": {**example["net"], "state_file": str(tmp / "n2.json")},
                        "claude": {**example["claude"], "history_file": str(tmp / "h2.json")}})
check(sorted(x.name for x in built.sources) == ["ai", "events", "github", "homelab", "net", "weather"],
      f"example config builds all six sources: {[x.name for x in built.sources]}")
check(built.host == "deskhub.local" and pa.page_list(example) == ["home", "claude", "calendar", "weather", "timer", "github", "homelab", "net"],
      "example config: default display address, all pages")
check(all(x.name != "net" or x.interval == 5 for x in built.sources), "intervals default from the table")
check(pa.read_secret("", str(tmp / "nokey"), "UNSET_VAR_FOR_TEST") == "", "a missing key file gives an empty secret, not a crash")
(tmp / "k").write_text('"abc"\n')
check(pa.read_secret("", str(tmp / "k"), "UNSET_VAR_FOR_TEST") == "abc", "key file is stripped of quotes and newline")
os.environ.pop("KONTINGENT_KEY")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
