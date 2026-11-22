"""Pi companion: how upstream answers become protocol messages (quota, Mia OS events and
homelab, GitHub page, weather, history). Fixtures are invented; nothing touches the network.

    python tests/test_pi_sources.py
"""
import datetime as dt
import json
import pathlib
import sys
import tempfile
from zoneinfo import ZoneInfo

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import httpx

from deskhub import github as gh
from deskhub.pi import sources as s
from pi_protocol import validate

problems = []


def check(ok, what):
    print(("ok  " if ok else "BAD ") + what)
    if not ok:
        problems.append(what)


def valid(msg, what):
    p = validate(msg)
    check(not p, f"{what} matches the protocol" + (f": {p}" if p else ""))


BERLIN = ZoneInfo("Europe/Berlin")
utc = dt.timezone.utc


def ts(y, mo, d, h=0, mi=0, sec=0, tz=utc):
    return int(dt.datetime(y, mo, d, h, mi, sec, tzinfo=tz).timestamp())


# ---- quota -> ai.limits -----------------------------------------------------------------
NOW = ts(2026, 11, 22, 19, 5)
quota = {"ok": True, "fehler": None, "hinweis": None, "stand": "2026-11-22T19:00:29.977015+00:00",
         "sitzung": {"prozent": 11.0, "zurueck": "2026-11-22T22:39:59.871704+00:00"},
         "woche": {"prozent": 45, "zurueck": "2026-11-29T23:59:59Z"}, "cache_s": 185}
lim = s.limits_from_kontingent(quota, NOW)
check(lim == {"five_hour": {"pct": 11.0, "reset": ts(2026, 11, 22, 22, 39, 59)},
              "seven_day": {"pct": 45.0, "reset": ts(2026, 11, 29, 23, 59, 59)},
              "updated": ts(2026, 11, 22, 19, 0, 29)}, f"quota -> limits with times as unix seconds: {lim}")
q2 = {**quota, "sitzung": {"prozent": 5, "zurueck": "2026-11-22T23:39:59+01:00"}}
check(s.limits_from_kontingent(q2, NOW)["five_hour"]["reset"] == ts(2026, 11, 22, 22, 39, 59), "offset +01:00 converted to UTC")
check(s.limits_from_kontingent({**quota, "sitzung": {"prozent": 5, "zurueck": "2026-11-22T10:00:00+00:00"}}, NOW).keys()
      == {"seven_day", "updated"}, "a window whose reset has passed is dropped")
check(s.limits_from_kontingent({**quota, "woche": None}, NOW).keys() == {"five_hour", "updated"}, "null window left out")
check(s.limits_from_kontingent({**quota, "ok": False}, NOW) is None, "ok:false gives nothing")
check(s.limits_from_kontingent({"ok": True, "sitzung": None, "woche": None}, NOW) is None, "no windows gives nothing")
check(s.limits_from_kontingent({**quota, "sitzung": {"prozent": "x", "zurueck": 5}, "woche": None}, NOW) is None, "bad types give nothing")
check(s.limits_from_kontingent({**quota, "stand": None}, NOW)["updated"] == NOW, "missing stand falls back to now")

tmp = pathlib.Path(tempfile.mkdtemp())
clock = [1_800_000_000]
h = s.History(tmp / "h.json", clock=lambda: clock[0])
for i in range(200):
    clock[0] += 1800
    h.add(i % 100)
    clock[0] += 600
    h.add(99)            # inside the 30 minute gap: ignored
check(len(h.points) == 200, f"one history point per 30 minutes ({len(h.points)})")
sent = h.sent()
check(len(sent) == 48 and sent[-1] == h.points[-1] and sent[0] == h.points[0], "history cut to 48, newest kept")
check(all(clock[0] - p[0] <= s.HISTORY_KEEP_S for p in h.points), "old points forgotten after 8 days")
check(s.History(tmp / "h.json").points == h.points, "history survives a restart")
check(s.History(tmp / "missing" / "x.json").points == [], "no history file is fine")
msg = s.ai_message(lim, sent)
valid(msg, "ai message")
check("block" not in msg and "models" not in msg and "today" not in msg, "no fields the Pi cannot know")

# ---- Mia OS events -----------------------------------------------------------------------
now = ts(2026, 11, 22, 18, 5)      # 19:05 in Berlin


def ev(title, start, end=None, all_day=False, cal="Kalender A", ort="", farbe="#c8607f"):
    return {"id": "x", "title": title, "start": start, "end": end, "allDay": all_day, "kalender": cal, "ort": ort,
            "farbe": farbe, "hat_notiz": False, "offene_aufgaben": 0}


data = {"termine": [
    ev("Beispiel Zwei", "2026-11-24T10:00:00", "2026-11-24T11:30:00", ort="Raum 1"),
    ev("Beispiel Eins", "2026-11-23T07:30:00", "2026-11-23T09:00:00"),
    ev("Ganztag Beispiel", "2026-11-23T00:00:00", "2026-11-24T00:00:00", all_day=True),
    ev("Vorbei", "2026-11-22T08:00:00", "2026-11-22T09:00:00"),
    ev("Laeuft noch", "2026-11-22T18:00:00", "2026-11-22T20:00:00"),
    ev("Ohne Ende", "2026-11-25T12:00:00", None),
    ev("Aus Sammlung", "2026-11-25", None, all_day=True, cal="Sammlung"),
    ev("Aeussere Uebung \u00fcber Gr\u00f6\u00dfe " + "x" * 120, "2026-11-26T12:00:00", "2026-11-26T13:00:00"),
    {"title": "kaputt", "start": "kein Datum"},
], "kalender": [], "aufgaben_je_tag": {}}
m = s.events_message(data, now, 7, BERLIN, skip_calendars=["Sammlung"])
check(m["days"] == 7 and len(m["events"]) == 6, f"events: {len(m['events'])} kept of 9 (past, skipped, broken left out)")
valid(m, "events message")
titles = [e["title"] for e in m["events"]]
check(titles[:3] == ["Laeuft noch", "Ganztag Beispiel", "Beispiel Eins"] and titles[3] == "Beispiel Zwei", f"sorted by start: {titles[:4]}")
first = [e for e in m["events"] if e["title"] == "Beispiel Eins"][0]
check(first["start"] == ts(2026, 11, 23, 6, 30) and first["end"] == ts(2026, 11, 23, 8, 0), "local time Berlin (CET) -> UTC unix")
ad = [e for e in m["events"] if e["all_day"]][0]
check(ad["start"] == ts(2026, 11, 22, 23, 0) and ad["end"] == ts(2026, 11, 23, 23, 0), "all-day = local midnight to midnight")
check([e for e in m["events"] if e["title"] == "Ohne Ende"][0]["end"] == ts(2026, 11, 25, 11, 0) + 3600, "missing end = +1 h")
longt = [e for e in m["events"] if e["title"].startswith("Aeussere")][0]["title"]
check(longt.startswith("Aeussere Uebung ueber Groesse") and len(longt) == 78, "umlauts spelled out, title cut to 78")
check(any(e["title"] == "Laeuft noch" for e in m["events"]), "a running event stays")
summer = s.events_message({"termine": [ev("S", "2026-07-01T12:00:00", "2026-07-01T13:00:00")]}, ts(2026, 6, 30), 7, BERLIN)
check(summer["events"][0]["start"] == ts(2026, 7, 1, 10), "summer time (CEST) handled")
many = {"termine": [ev(f"E{i}", f"2026-11-{23 + i % 5}T{8 + i % 10:02d}:00:00", None) for i in range(40)]}
check(len(s.events_message(many, now, 7, BERLIN)["events"]) == 16, "at most 16 events")

# the HTTP wrapper asks for the right window
seen = {}


def handler(request):
    seen["url"] = str(request.url)
    return httpx.Response(200, json=data)


http = httpx.Client(transport=httpx.MockTransport(handler))
got = s.fetch_events("http://miaos.example:8080/", 7, BERLIN, ["Sammlung"], http=http, clock=lambda: now)
check(seen["url"] == "http://miaos.example:8080/api/termine?von=2026-11-21&bis=2026-11-29", f"events request: {seen['url']}")
check(got == m, "fetch_events = events_message")

# ---- Mia OS homelab ----------------------------------------------------------------------
clk = [1_800_000_000]
lab = s.Homelab(lambda: clk[0])
check(lab.failed() == {"type": "homelab", "ok": False, "updated": 0, "up": 0, "total": 0, "down": []}, "failure before any success")
valid(lab.failed(), "homelab ok:false")
all_up = {"lage": {"zustand": "oben", "satz": "Alles l\u00e4uft", "gesamt": 54, "oben": 54, "uptime": 99.9},
          "stoerungen": [], "dienste": [], "kennzahlen": [], "stand": "22.11., 19:00"}
m1 = lab.message(all_up)
check(m1 == {"type": "homelab", "ok": True, "updated": 1_800_000_000, "up": 54, "total": 54, "down": []}, f"all up: {m1}")
valid(m1, "homelab ok")
clk[0] += 120
bad = {**all_up, "lage": {**all_up["lage"], "oben": 52}, "stoerungen": [
    {"name": "Dienst \u00c4", "status": 0, "meldung": "x"}, {"name": "Dienst B", "status": 3}]}
m2 = lab.message(bad)
check(m2["up"] == 52 and m2["down"] == [{"name": "Dienst Ae", "since": 1_800_000_120}, {"name": "Dienst B", "since": 1_800_000_120}],
      "down list with since")
clk[0] += 300
m3 = lab.message({**bad, "stoerungen": bad["stoerungen"][:1]})
check(m3["down"] == [{"name": "Dienst Ae", "since": 1_800_000_120}], "since stays while a service stays down, recovered one leaves")
f = lab.failed()
check(f["ok"] is False and f["updated"] == m3["updated"] and f["up"] == 52 and f["down"] == m3["down"], "ok:false carries the last state and its time")
valid(f, "homelab ok:false with last state")
check(len(lab.message({**bad, "stoerungen": [{"name": f"S{i}"} for i in range(12)]})["down"]) == 8, "at most 8 down entries")
try:
    lab.message({"lage": {}})
    check(False, "an answer without counts raises")
except ValueError:
    check(True, "an answer without counts raises")

# ---- GitHub public page -------------------------------------------------------------------
start = dt.date(2025, 11, 23)       # a Sunday, like the real page
last = dt.date(2026, 11, 21)
rows, tips, counts = [], [], {}
d, i = start, 0
while d <= last:
    c = 0 if i % 4 == 0 else (i * 7) % 23
    if i == 100:
        c = 1234
    counts[d.isoformat()] = c
    lvl = 0 if c == 0 else min(4, 1 + c // 6)
    cid = f"contribution-day-component-{i % 7}-{i // 7}"
    rows.append(f'<td tabindex="0" data-ix="{i // 7}" aria-selected="false" style="width: 10px" data-date="{d.isoformat()}" '
                f'id="{cid}" data-level="{lvl}" role="gridcell" class="ContributionCalendar-day"></td>')
    word = "No contributions" if c == 0 else (f"{c:,} contribution" + ("" if c == 1 else "s"))
    tips.append(f'<tool-tip for="{cid}" popover="manual" class="sr-only position-absolute">{word} on {d:%B} {d.day}th.</tool-tip>')
    d += dt.timedelta(days=1)
    i += 1
page = "<html><h2>\n 4,343\n contributions\n in the last year</h2><table>" + "".join(rows) + "</table>" + "".join(tips) + "</html>"
cal = s.parse_contribution_html(page, "beispiel")
check(len(cal["days"]) == 364 and cal["days"][0]["date"] == "2025-11-23" and cal["days"][0]["weekday"] == 0, "364 days, first is a Sunday")
check(cal["total"] == sum(counts.values()) and all(x["contributionCount"] == counts[x["date"]] for x in cal["days"]),
      "counts from the tool-tips (with thousands separator)")
g = gh.message(cal)
valid(g, "github message")
check(g["login"] == "beispiel" and g["start_wday"] == 0 and len(g["levels"]) == 364 and g["today"] == counts["2026-11-21"], "github fields")
check(g["levels"][0] == "0" and g["kinds"] == {} and g["repos"] == [], "no private kinds or repos without a token")
http = httpx.Client(transport=httpx.MockTransport(lambda r: (seen.update(gurl=str(r.url), auth=r.headers.get("authorization")),
                                                              httpx.Response(200, text=page))[1]))
fg = s.fetch_github("beispiel", "", http=http)
check(fg == g and seen["gurl"] == "https://github.com/users/beispiel/contributions" and seen["auth"] is None,
      "no token: public page, no Authorization header")
try:
    s.parse_contribution_html("<html>login wall</html>", "x")
    check(False, "a page without a calendar raises")
except ValueError:
    check(True, "a page without a calendar raises")
calls = []


def fake_post(token, query, variables=None):
    calls.append(token)
    return {"viewer": {"id": "1", "login": "beispiel", "contributionsCollection": {
        "totalCommitContributions": 3, "totalPullRequestContributions": 0, "totalPullRequestReviewContributions": 0,
        "totalIssueContributions": 0, "restrictedContributionsCount": 0, "commitContributionsByRepository": [],
        "contributionCalendar": {"totalContributions": 3, "weeks": [{"contributionDays": [
            {"date": "2026-11-21", "weekday": 6, "contributionCount": 3, "contributionLevel": "SECOND_QUARTILE"}]}]}}}}


tg = s.fetch_github("", "tok", post=fake_post)
check(calls == ["tok"] and tg["total"] == 3 and not validate(tg), "with a token: GraphQL")

# ---- Weather ----------------------------------------------------------------------------
t0 = ts(2026, 11, 22, 18)         # hourly series: 48 h from 18:00 UTC
w = {"current": {"time": t0 + 3600, "temperature_2m": 7.24, "apparent_temperature": 4.06, "weather_code": 3, "is_day": 0,
                 "relative_humidity_2m": 81, "wind_speed_10m": 18.4},
     "hourly": {"time": [t0 + 3600 * k for k in range(48)], "temperature_2m": [5.0 + k / 10 for k in range(48)],
                "weather_code": [3] * 48, "precipitation_probability": [None if k == 5 else 40 for k in range(48)]},
     "daily": {"time": [ts(2026, 11, 21, 23) + 86400 * k for k in range(7)], "weather_code": [61] * 7,
               "temperature_2m_max": [8.0] * 7, "temperature_2m_min": [3.0] * 7, "precipitation_probability_max": [70] * 7}}
wm = s.weather_message(w, "Z\u00fcrich", t0 + 3600 + 900)
valid(wm, "weather message")
check(wm["now"] == {"temp": 7.2, "feels": 4.1, "code": 3, "is_day": False, "humidity": 81, "wind": 18}, f"now: {wm['now']}")
check(len(wm["hours"]) == 12 and wm["hours"][0]["t"] == t0 + 3600, "12 hours starting with the current hour")
check(len(wm["days"]) == 6 and wm["days"][0]["t"] == ts(2026, 11, 21, 23), "6 days")
check(wm["place"] == "Zuerich" and wm["updated"] == t0 + 3600 + 900, "place folded, updated = now")
check(wm["hours"][4]["precip"] == 0, "null precipitation -> 0")
req = {}
http = httpx.Client(transport=httpx.MockTransport(lambda r: (req.update(url=r.url), httpx.Response(200, json=w))[1]))
s.fetch_weather(53.55, 9.94, "Hamburg", http=http, clock=lambda: t0)
q = dict(req["url"].params)
check(q["latitude"] == "53.55" and q["longitude"] == "9.94" and q["timeformat"] == "unixtime" and q["timezone"] == "Europe/Berlin",
      "weather request: coordinates from config, unix times")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
