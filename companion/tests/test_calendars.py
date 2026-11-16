"""CalDAV fetch against a local Radicale server, compared with the ICS path.

    uv run python tests/test_calendars.py
Prints OK or the problems found. Never touches the OS credential store.
"""
import asyncio
import datetime as dt
import logging
import pathlib
import socket
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

import caldav  # noqa: E402

from deskhub import calendar_feed as cf  # noqa: E402

PASSWORD = "s3cret-app-pw"
SECRET_PATH = "/private/abc123secrettoken/basic.ics"
DAY = (82800, 86400, 90000)  # all-day span, allowing for DST changes


def utc(t: dt.datetime) -> str:
    return t.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def vevent(uid, summary, extra, loc=""):
    lines = ["BEGIN:VEVENT", f"UID:{uid}@test", f"DTSTAMP:{utc(dt.datetime.now())}",
             f"SUMMARY:{summary}", *extra]
    if loc:
        lines.append(f"LOCATION:{loc}")
    lines.append("END:VEVENT")
    return lines


def wrap(*events):
    body = ["BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//deskhub test//EN"]
    for e in events:
        body += e
    body.append("END:VCALENDAR")
    return "\r\n".join(body) + "\r\n"


def build_events():
    now = dt.datetime.now().astimezone()
    hour = now.replace(minute=0, second=0, microsecond=0)
    tomorrow = (now + dt.timedelta(days=1)).date()
    after = tomorrow + dt.timedelta(days=1)
    ymd = lambda x: x.strftime("%Y%m%d")  # noqa: E731
    base = hour - dt.timedelta(days=14)
    return {
        "timed": vevent("timed", "Café – standup", [
            f"DTSTART:{utc(now + dt.timedelta(minutes=30))}",
            f"DTEND:{utc(now + dt.timedelta(minutes=90))}"], "Room “A”"),
        "weekly": vevent("weekly", "Weekly sync", [
            f"DTSTART:{utc(base + dt.timedelta(hours=2))}",
            f"DTEND:{utc(base + dt.timedelta(hours=3))}", "RRULE:FREQ=WEEKLY"]),
        "allday": vevent("allday", "Holiday", [
            f"DTSTART;VALUE=DATE:{ymd(tomorrow)}", f"DTEND;VALUE=DATE:{ymd(after)}"]),
        "allday_nodtend": vevent("allday2", "Birthday", [f"DTSTART;VALUE=DATE:{ymd(after)}"]),
        "duration": vevent("dur", "Duration only", [
            f"DTSTART:{utc(now + dt.timedelta(hours=5))}", "DURATION:PT45M"]),
        "nodtend": vevent("nodtend", "No end", [f"DTSTART:{utc(now + dt.timedelta(hours=6))}"]),
        "cancelled": vevent("cancelled", "Cancelled one", [
            f"DTSTART:{utc(now + dt.timedelta(hours=2))}",
            f"DTEND:{utc(now + dt.timedelta(hours=3))}", "STATUS:CANCELLED"]),
        "ended": vevent("ended", "Already over", [
            f"DTSTART:{utc(now - dt.timedelta(hours=3))}",
            f"DTEND:{utc(now - dt.timedelta(hours=2))}"]),
    }


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_radicale(folder, port):
    proc = subprocess.Popen(
        [sys.executable, "-m", "radicale", "--storage-filesystem-folder", folder,
         "--auth-type", "none", "--server-hosts", f"127.0.0.1:{port}",
         "--logging-level", "warning"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(100):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            return proc
        except OSError:
            time.sleep(0.1)
    proc.terminate()
    raise RuntimeError("radicale did not start")


def main():
    problems = []

    def check(cond, msg):
        if not cond:
            problems.append(msg)

    events = build_events()
    tmp = tempfile.TemporaryDirectory()
    store = pathlib.Path(tmp.name) / "radicale"
    store.mkdir()
    port = free_port()
    proc = start_radicale(str(store), port)
    try:
        url = f"http://127.0.0.1:{port}/"
        with caldav.DAVClient(url=url, username="tester", password=PASSWORD) as client:
            principal = client.principal()
            for name in ("Home", "Work"):
                principal.make_calendar(name=name)
            cals = {c.get_display_name(): c for c in principal.calendars()}
            for lines in events.values():
                cals["Home"].save_event(wrap(lines))
            later = dt.datetime.now().astimezone() + dt.timedelta(hours=8)
            cals["Work"].save_event(wrap(vevent("w1", "Work item", [f"DTSTART:{utc(later)}"])))

        now = dt.datetime.now().astimezone()
        start, stop = now - dt.timedelta(days=1), now + dt.timedelta(days=7)
        feed = {"type": "caldav", "name": "iCloud", "url": url, "username": "tester",
                "color": "#ff5a5f", "calendars": ["home"]}
        got = cf._caldav_events(feed, start, stop, now, PASSWORD)
        got.sort(key=lambda x: (x["start"], not x["all_day"]))

        # The same events through the ICS path must give identical dicts.
        ics = pathlib.Path(tmp.name) / "same.ics"
        ics.write_bytes(wrap(*events.values()).encode())
        ics_feed = {"name": "iCloud", "url": str(ics), "color": "#ff5a5f"}
        want = asyncio.run(cf.fetch_events([ics_feed], 7))
        check(got == want, f"caldav and ics results differ:\n caldav={got}\n ics={want}")

        titles = [e["title"] for e in got]
        check("Cafe - standup" in titles, f"timed event / ascii fold missing: {titles}")
        check(any(e["loc"] == 'Room "A"' for e in got), "location not folded")
        check(titles.count("Weekly sync") >= 1, "recurring event not expanded")
        check("Cancelled one" not in titles, "cancelled event returned")
        check("Already over" not in titles, "ended event returned")
        check("Work item" not in titles, "calendar filter ignored")
        by = {e["title"]: e for e in got}
        h = by.get("Holiday")
        if h:
            midnight = dt.datetime.combine(now.date() + dt.timedelta(days=1), dt.time.min).astimezone()
            check(h["all_day"] and h["start"] == int(midnight.timestamp()), f"all-day wrong: {h}")
            check(h["end"] - h["start"] in DAY, "all-day span")
        else:
            check(False, "all-day event missing")
        b = by.get("Birthday")
        check(b and b["end"] - b["start"] in DAY, "all-day without DTEND not +1 day")
        d = by.get("Duration only", {})
        check(d.get("end", 0) - d.get("start", 0) == 2700, "DURATION not used")
        n = by.get("No end", {})
        check(n.get("end", 0) - n.get("start", 0) == 3600, "missing DTEND not +1h")
        check(bool(got) and set(got[0]) == {"title", "loc", "cal", "start", "end", "all_day", "color"},
              "dict shape")

        # No calendar filter returns the Work calendar too.
        all_titles = [e["title"] for e in
                      cf._caldav_events(dict(feed, calendars=[]), start, stop, now, PASSWORD)]
        check("Work item" in all_titles, "empty calendars filter should return all")

        # Failures: nothing leaks, other feeds still work.
        records = []
        handler = logging.Handler()
        handler.emit = lambda r: records.append(r.getMessage())
        cf.log.addHandler(handler)
        bad_port = free_port()
        feeds = [
            {"type": "caldav", "name": "Broken", "url": f"http://127.0.0.1:{bad_port}/",
             "username": "tester"},
            {"name": "BadIcs", "url": f"http://127.0.0.1:{bad_port}{SECRET_PATH}"},
            ics_feed,
        ]
        # fetch_events looks the password up in keyring; stub that so the real store is untouched.
        cf.get_caldav_password = lambda user: PASSWORD
        res = asyncio.run(cf.fetch_events(feeds, 7))
        check(res == want, "good feed affected by failing feeds")
        check(len(records) == 2, f"expected 2 warnings, got {records}")
        text = " ".join(records)
        check(PASSWORD not in text, "password in log")
        check("abc123secrettoken" not in text, "secret URL in log")

        try:
            cf._caldav_events(dict(feed, url=f"http://127.0.0.1:{bad_port}/"), start, stop, now, PASSWORD)
        except RuntimeError as e:
            check(PASSWORD not in str(e), "password in error")
        else:
            check(False, "expected failure for unreachable server")

        check(len(asyncio.run(cf.fetch_events([ics_feed] * 5, 7))) <= cf.MAX_EVENTS, "event limit")
    finally:
        proc.terminate()
        proc.wait(timeout=10)
        try:
            tmp.cleanup()
        except OSError:
            pass
    print("OK" if not problems else "PROBLEMS:\n" + "\n".join(problems))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
