"""Upcoming events from ICS feeds (Google, Outlook, local files) and CalDAV (iCloud)."""
import asyncio
import datetime as dt
import logging
import pathlib
import re

import httpx
import icalendar
import recurring_ical_events

from .text import ascii_fold

log = logging.getLogger(__name__)

MAX_EVENTS = 16
KEYRING_SERVICE = "deskhub-caldav"
DEFAULT_CALDAV_URL = "https://caldav.icloud.com/"
_URL_RE = re.compile(r"(?:https?|webcal)://([^/\s'\"]+)\S*")


def _epoch(value, end=False) -> tuple[int, bool]:
    """ICS start/end to epoch seconds. Dates (all-day) become local midnight."""
    if isinstance(value, dt.datetime):
        if value.tzinfo is None:
            value = value.astimezone()  # floating time = local
        return int(value.timestamp()), False
    midnight = dt.datetime.combine(value, dt.time.min).astimezone()
    return int(midnight.timestamp()), True


async def _load(client: httpx.AsyncClient, source: str) -> bytes:
    if source.startswith(("http://", "https://", "webcal://")):
        url = "https://" + source[len("webcal://"):] if source.startswith("webcal://") else source
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
        return r.content
    return pathlib.Path(source).expanduser().read_bytes()


def _safe_error(e: Exception, *secrets: str) -> str:
    """Error text for logs: no URL paths (secret ICS addresses) and no passwords."""
    status = getattr(getattr(e, "response", None), "status_code", None)
    msg = f"HTTP {status}" if status else f"{type(e).__name__}: {e}"
    msg = _URL_RE.sub(lambda m: m.group(1), msg)
    for secret in secrets:
        if secret:
            msg = msg.replace(secret, "***")
    return msg[:200]


def _collect(cal: icalendar.Calendar, start: dt.datetime, stop: dt.datetime,
             now: dt.datetime, name: str, color: str) -> list[dict]:
    """Turn the VEVENTs of one calendar (recurrences expanded) into event dicts."""
    events = []
    for ev in recurring_ical_events.of(cal).between(start, stop):
        if str(ev.get("STATUS", "")).upper() == "CANCELLED":
            continue
        s, all_day = _epoch(ev.decoded("DTSTART"))
        if ev.get("DTEND") is not None:
            e, _ = _epoch(ev.decoded("DTEND"))
        elif ev.get("DURATION") is not None:
            e = s + int(ev.decoded("DURATION").total_seconds())
        else:
            e = s + (86400 if all_day else 3600)
        if e <= s:  # recurring_ical_events fills a missing DTEND with DTSTART
            e = s + (86400 if all_day else 3600)
        if e <= now.timestamp():
            continue
        events.append({
            "title": ascii_fold(str(ev.get("SUMMARY", "(no title)")), 78),
            "loc": ascii_fold(str(ev.get("LOCATION", "")), 62),
            "cal": ascii_fold(name, 30),
            "start": s,
            "end": e,
            "all_day": all_day,
            "color": color,
        })
    return events


def get_caldav_password(username: str) -> str | None:
    import keyring
    return keyring.get_password(KEYRING_SERVICE, username)


def caldav_calendars(url: str, username: str, password: str) -> list:
    """Connect and return the account's calendars. Blocking."""
    import caldav
    with caldav.DAVClient(url=url, username=username, password=password) as client:
        cals = client.principal().calendars()
        # Entries are bound to the client, so read what callers need now.
        return [(c.get_display_name() or "(unnamed)", c.url) for c in cals]


def _caldav_events(feed: dict, start: dt.datetime, stop: dt.datetime, now: dt.datetime,
                   password: str | None) -> list[dict]:
    import caldav
    url = (feed.get("url") or DEFAULT_CALDAV_URL).strip()
    username = (feed.get("username") or "").strip()
    if password is None:
        password = get_caldav_password(username)
    if not password:
        raise RuntimeError(f"no app-specific password stored for {username!r}; "
                           "run: uv run deskhub-calendars")
    wanted = {str(n).strip().casefold() for n in feed.get("calendars") or []}
    color = feed.get("color", "#7c9cff")
    events = []
    try:
        with caldav.DAVClient(url=url, username=username, password=password) as client:
            for calendar in client.principal().calendars():
                cname = calendar.get_display_name() or ""
                if wanted and cname.strip().casefold() not in wanted:
                    continue
                # Recurring events come back unexpanded; _collect expands them,
                # same as for ICS feeds.
                for obj in calendar.search(start=start, end=stop, event=True):
                    cal = icalendar.Calendar.from_ical(obj.data)
                    events += _collect(cal, start, stop, now, feed.get("name") or cname, color)
    except Exception as e:
        raise RuntimeError(_safe_error(e, password)) from None
    return events


async def fetch_events(feeds: list[dict], days: int) -> list[dict]:
    now = dt.datetime.now().astimezone()
    start = now - dt.timedelta(days=1)
    stop = now + dt.timedelta(days=days)
    events = []
    async with httpx.AsyncClient(timeout=20) as client:
        for feed in feeds:
            name = feed.get("name", "")
            kind = str(feed.get("type", "ics")).lower()
            source = (feed.get("url") or "").strip()
            try:
                if kind == "caldav":
                    if not feed.get("username"):
                        continue
                    events += await asyncio.to_thread(
                        _caldav_events, feed, start, stop, now, None)
                    continue
                if not source:
                    continue
                cal = icalendar.Calendar.from_ical(await _load(client, source))
                events += _collect(cal, start, stop, now, name, feed.get("color", "#7c9cff"))
            except Exception as e:
                log.warning("calendar %r failed: %s", name or kind, _safe_error(e))
    # All-day events first within a day, then by start time.
    events.sort(key=lambda x: (x["start"], not x["all_day"]))
    return events[:MAX_EVENTS]
