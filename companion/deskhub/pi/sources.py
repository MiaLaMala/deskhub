"""Data sources for the Pi companion: each one turns an upstream answer into a message
from cyd/PROTOKOLL.md. The mapping functions are pure (tested without network); the
fetch_* functions do the HTTP and pass the answer through them.

Privacy: log lines never contain titles, places or URLs with secrets.
"""
import datetime as dt
import json
import logging
import pathlib
import re
import time
from html import unescape
from zoneinfo import ZoneInfo

from .. import github as gh

log = logging.getLogger(__name__)

MAX_EVENTS = 16
MAX_DOWN = 8
MAX_HISTORY = 48
HISTORY_GAP_S = 30 * 60
HISTORY_KEEP_S = 8 * 86400
UA = "deskhub-pi/0.1 (+https://github.com/zacharyinserra/deskhub)"

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def fold(s, limit: int = 120) -> str:
    """Text for the display: German umlauts spelled out, everything else folded to ASCII."""
    from ..text import ascii_fold

    return ascii_fold(str(s or "").translate(_UMLAUTS), limit)


def _get(url: str, *, params=None, headers=None, timeout: float = 20, http=None):
    import httpx

    r = (http or httpx).get(url, params=params, headers={"User-Agent": UA, **(headers or {})},
                            timeout=timeout, follow_redirects=True)
    r.raise_for_status()
    return r


# ---- Claude quota ----------------------------------------------------------------

def parse_iso(value) -> int | None:
    """ISO 8601 with offset ("2026-11-22T22:39:59.871704+00:00" or "...Z") -> unix seconds."""
    if not isinstance(value, str) or not value:
        return None
    try:
        t = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return int(t.timestamp())


def limits_from_kontingent(data: dict, now: float) -> dict | None:
    """The quota service's answer -> `limits` of the ai message, or None when it holds no
    usable window. sitzung = five-hour window, woche = seven-day window. Windows whose
    reset time has passed are dropped, like the original does."""
    if not isinstance(data, dict) or data.get("ok") is not True:
        return None
    out = {}
    for src, name in (("sitzung", "five_hour"), ("woche", "seven_day")):
        w = data.get(src)
        if not isinstance(w, dict):
            continue
        pct, reset = w.get("prozent"), parse_iso(w.get("zurueck"))
        if isinstance(pct, bool) or not isinstance(pct, (int, float)) or reset is None or reset <= now:
            continue
        out[name] = {"pct": round(float(pct), 1), "reset": reset}
    if not out:
        return None
    out["updated"] = parse_iso(data.get("stand")) or int(now)
    return out


def downsample(points: list, n: int = MAX_HISTORY) -> list:
    """At most n points, evenly spread, always including the newest."""
    if len(points) <= n:
        return list(points)
    step = (len(points) - 1) / (n - 1)
    return [points[round(i * step)] for i in range(n)]


class History:
    """Own record of the seven-day percentage, one point per 30 minutes, kept for 8 days."""

    def __init__(self, path, clock=time.time):
        self.path = pathlib.Path(path).expanduser() if path else None
        self.clock = clock
        self.points: list[list] = []
        if self.path:
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self.points = [[int(t), float(p)] for t, p in raw if isinstance(t, (int, float))]
            except (OSError, ValueError, TypeError):
                self.points = []

    def add(self, pct: float):
        now = int(self.clock())
        if self.points and now - self.points[-1][0] < HISTORY_GAP_S:
            return
        self.points.append([now, round(float(pct), 1)])
        self.points = [p for p in self.points if now - p[0] <= HISTORY_KEEP_S]
        if self.path:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_text(json.dumps(self.points), encoding="utf-8")
            except OSError as e:
                log.debug("history not saved: %s", e)

    def sent(self) -> list:
        return downsample(self.points)


def ai_message(limits: dict, history: list | None = None) -> dict:
    msg = {"type": "ai", "provider": "claude", "limits": limits}
    if history:
        msg["history"] = history
    return msg


def fetch_kontingent(url: str, key: str, *, http=None, clock=time.time) -> dict | None:
    """Returns the limits or raises. None means the service answered but had nothing usable."""
    r = _get(url, headers={"Authorization": f"Bearer {key}"}, http=http)
    return limits_from_kontingent(r.json(), clock())


# ---- Mia OS: events and homelab ----------------------------------------------------------

def _local_epoch(text: str, tz: ZoneInfo) -> int:
    """Naive local ISO date or datetime from Mia OS -> unix seconds."""
    t = dt.datetime.fromisoformat(text)
    if t.tzinfo is None:
        t = t.replace(tzinfo=tz)
    return int(t.timestamp())


def events_message(data: dict, now: float, days: int, tz: ZoneInfo, skip_calendars=()) -> dict:
    """Mia OS `/api/termine` -> events message. Past events are left out, the rest sorted
    (all-day first within a day) and cut to 16."""
    skip = {str(c).casefold() for c in skip_calendars}
    events = []
    for e in data.get("termine") or []:
        cal = str(e.get("kalender") or "")
        if cal.casefold() in skip or not e.get("start"):
            continue
        try:
            all_day = bool(e.get("allDay"))
            start = _local_epoch(str(e["start"]), tz)
            end = _local_epoch(str(e["end"]), tz) if e.get("end") else 0
        except (ValueError, KeyError):
            continue
        if end <= start:
            end = start + (86400 if all_day else 3600)
        if end <= now:
            continue
        events.append({"title": fold(e.get("title") or "(no title)", 78), "loc": fold(e.get("ort"), 62),
                       "cal": fold(cal, 30), "start": start, "end": end, "all_day": all_day,
                       "color": str(e.get("farbe") or "#7c9cff")})
    events.sort(key=lambda x: (x["start"], not x["all_day"]))
    return {"type": "events", "events": events[:MAX_EVENTS], "days": int(days)}


def fetch_events(base: str, days: int, tz: ZoneInfo, skip_calendars=(), *, http=None, clock=time.time) -> dict:
    now = clock()
    today = dt.datetime.fromtimestamp(now, tz).date()
    r = _get(base.rstrip("/") + "/api/termine", http=http,
             params={"von": (today - dt.timedelta(days=1)).isoformat(),
                     "bis": (today + dt.timedelta(days=days)).isoformat()})
    return events_message(r.json(), now, days, tz, skip_calendars)


class Homelab:
    """Mia OS `/api/homelab` -> homelab message. Remembers since when a service is down
    (Mia OS only says that it is) and the last good state for ok:false messages."""

    def __init__(self, clock=time.time):
        self.clock = clock
        self.down_since: dict[str, int] = {}
        self.last: dict | None = None

    def message(self, data: dict) -> dict:
        lage = data.get("lage") or {}
        total, up = lage.get("gesamt"), lage.get("oben")
        if not isinstance(total, int) or not isinstance(up, int):
            raise ValueError("no counts in the homelab answer")
        now = int(self.clock())
        names = [fold(s.get("name") or "?", 40) for s in data.get("stoerungen") or [] if isinstance(s, dict)]
        self.down_since = {n: self.down_since.get(n, now) for n in names}
        msg = {"type": "homelab", "ok": True, "updated": now, "up": up, "total": total,
               "down": [{"name": n, "since": self.down_since[n]} for n in names[:MAX_DOWN]]}
        self.last = msg
        return msg

    def failed(self) -> dict:
        """The source is unreachable: ok:false, with the last good numbers so the display
        can show them with their time."""
        last = self.last or {"updated": 0, "up": 0, "total": 0, "down": []}
        return {"type": "homelab", "ok": False, "updated": last["updated"], "up": last["up"],
                "total": last["total"], "down": last["down"]}

    def fetch(self, base: str, *, http=None) -> dict:
        return self.message(_get(base.rstrip("/") + "/api/homelab", http=http).json())


# ---- GitHub ----------------------------------------------------------------------------

_TAG = re.compile(r"<(td|tool-tip)\b([^>]*)>([^<]*)", re.S)
_ATTR = re.compile(r'([\w-]+)="([^"]*)"')
_COUNT = re.compile(r"^\s*(No|[\d,.]+)\s+contributions?\b")


def parse_contribution_html(html: str, login: str) -> dict:
    """The public `https://github.com/users/<name>/contributions` page -> the calendar dict
    `deskhub.github.message()` takes. Raises ValueError when the page has no calendar."""
    cells, tips = {}, {}
    for tag, attrs, text in _TAG.findall(html):
        a = dict(_ATTR.findall(attrs))
        if tag == "td" and "data-date" in a and "id" in a:
            cells[a["id"]] = (a["data-date"], int(a.get("data-level", 0) or 0))
        elif tag == "tool-tip" and "for" in a:
            m = _COUNT.match(unescape(text))
            if m:
                tips[a["for"]] = 0 if m.group(1) == "No" else int(re.sub(r"\D", "", m.group(1)))
    if not cells:
        raise ValueError("no contribution calendar in the page")
    names = list(gh.LEVELS)
    days = []
    for cid, (date, level) in cells.items():
        d = dt.date.fromisoformat(date)
        days.append({"date": date, "weekday": (d.weekday() + 1) % 7,
                     "contributionCount": tips.get(cid, 0), "contributionLevel": names[min(level, 4)]})
    days.sort(key=lambda d: d["date"])
    return {"login": login, "total": sum(d["contributionCount"] for d in days), "days": days,
            "kinds": {}, "repos": []}


def fetch_github(user: str = "", token: str = "", *, http=None, post=None) -> dict:
    """The github message: GraphQL when a token is configured, otherwise the public page."""
    if token:
        return gh.message(gh.fetch(token, post) if post else gh.fetch(token))
    if not user:
        raise ValueError("no GitHub user configured")
    page = _get(f"https://github.com/users/{user}/contributions", http=http, timeout=30).text
    return gh.message(parse_contribution_html(page, user))


# ---- Weather ---------------------------------------------------------------------------

OPEN_METEO = "https://api.open-meteo.com/v1/forecast"


def weather_message(data: dict, place: str, now: float) -> dict:
    """Open-Meteo answer (timeformat=unixtime) -> weather message: 12 hours, 6 days."""
    cur, hourly, daily = data["current"], data["hourly"], data["daily"]
    msg_now = {"temp": round(float(cur["temperature_2m"]), 1), "feels": round(float(cur["apparent_temperature"]), 1),
               "code": int(cur["weather_code"]), "is_day": bool(cur["is_day"]),
               "humidity": int(round(cur["relative_humidity_2m"])), "wind": int(round(cur["wind_speed_10m"]))}
    first = int(now) // 3600 * 3600
    hours = []
    for i, t in enumerate(hourly["time"]):
        if t < first or len(hours) >= 12:
            continue
        hours.append({"t": int(t), "temp": round(float(hourly["temperature_2m"][i]), 1),
                      "code": int(hourly["weather_code"][i]),
                      "precip": int(hourly["precipitation_probability"][i] or 0)})
    day_list = []
    for i, t in enumerate(daily["time"][:6]):
        day_list.append({"t": int(t), "min": round(float(daily["temperature_2m_min"][i]), 1),
                         "max": round(float(daily["temperature_2m_max"][i]), 1),
                         "code": int(daily["weather_code"][i]),
                         "precip": int(daily["precipitation_probability_max"][i] or 0)})
    return {"type": "weather", "place": fold(place, 30), "updated": int(now), "now": msg_now,
            "hours": hours, "days": day_list}


def fetch_weather(lat: float, lon: float, place: str, tz_name: str = "Europe/Berlin", *, http=None,
                  clock=time.time) -> dict:
    r = _get(OPEN_METEO, http=http, params={
        "latitude": lat, "longitude": lon, "timezone": tz_name, "timeformat": "unixtime", "forecast_days": 7,
        "wind_speed_unit": "kmh", "temperature_unit": "celsius",
        "current": "temperature_2m,apparent_temperature,weather_code,is_day,relative_humidity_2m,wind_speed_10m",
        "hourly": "temperature_2m,weather_code,precipitation_probability",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"})
    return weather_message(r.json(), place, clock())
