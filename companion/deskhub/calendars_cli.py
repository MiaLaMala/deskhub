"""Connect Google Calendar and Apple (iCloud) calendars.

    uv run deskhub-calendars [--config path/to/config.toml] [list|add-google|add-apple|remove]
"""
import argparse
import getpass
import pathlib
import re

import httpx
import icalendar
import tomlkit

from .__main__ import find_config
from .calendar_feed import (DEFAULT_CALDAV_URL, KEYRING_SERVICE, _safe_error,
                            caldav_calendars)

GOOGLE_COLOR = "#4285f4"
APPLE_COLOR = "#ff5a5f"
LINK_COLOR = "#2dd4bf"
_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    return input(f"{prompt}{suffix}: ").strip() or default


def ask_color(default: str) -> str:
    while True:
        value = ask("Colour as #rrggbb", default)
        if _HEX.fullmatch(value):
            return value.lower()
        print("  Use six hex digits, for example #4285f4.")


def load(path: pathlib.Path):
    with open(path, encoding="utf-8", newline="") as f:  # keep CRLF/LF as is
        return tomlkit.parse(f.read())


def write(path: pathlib.Path, doc):
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(tomlkit.dumps(doc))


def feeds_of(doc) -> tomlkit.items.AoT:
    cal = doc.get("calendar")
    if cal is None:
        cal = tomlkit.table()
        doc["calendar"] = cal
    if "feeds" not in cal:
        cal["feeds"] = tomlkit.aot()
    return cal["feeds"]


def save(path: pathlib.Path, doc, feed: dict):
    feeds = feeds_of(doc)
    entry = tomlkit.table()
    for k, v in feed.items():
        entry[k] = v
    feeds.append(entry)
    write(path, doc)


def describe(feed) -> str:
    kind = str(feed.get("type", "ics")).lower()
    if kind == "caldav":
        cals = ", ".join(feed.get("calendars") or []) or "all calendars"
        return f"{feed.get('name', '')}  [iCloud {feed.get('username', '')}: {cals}]"
    url = str(feed.get("url", ""))
    if not url:
        return f"{feed.get('name', '')}  [empty]"
    host = re.sub(r"^\w+://", "", url).split("/")[0]
    shown = host if url.startswith(("http", "webcal")) else url
    return f"{feed.get('name', '')}  [ICS {shown}{'/...' if shown == host else ''}]"


def cmd_list(path):
    feeds = feeds_of(load(path))
    if not feeds:
        print("No calendars configured yet.")
    for i, feed in enumerate(feeds, 1):
        print(f"  {i}. {describe(feed)}")


def cmd_add_google(path):
    _add_link(path, """
Google Calendar
  1. Open calendar.google.com on a computer, then Settings (gear icon).
  2. Under "Settings for my calendars" pick the calendar.
  3. Scroll to "Integrate calendar" and copy "Secret address in iCal format".
Anyone with that address can read the calendar, so don't share it.
""", "Google", GOOGLE_COLOR)


def cmd_add_link(path):
    _add_link(path, """
Calendar link (ICS / webcal)
Any calendar you can subscribe to has a link like webcal://... or https://....ics:
  - iPhone subscribed calendar: Settings > Apps > Calendar > Calendar Accounts >
    Subscribed Calendars > tap it, then copy the "Server" address.
  - Outlook: Settings > Calendar > Shared calendars > Publish a calendar > ICS link.
  - Sports schedules, holidays, school calendars: look for "subscribe" or "iCal".
""", "Subscribed", LINK_COLOR)


def _add_link(path, intro: str, default_name: str, default_color: str):
    print(intro)
    url = ask("Paste the address (empty to cancel)")
    if not url:
        return
    fetch = "https://" + url[len("webcal://"):] if url.startswith("webcal://") else url
    try:
        r = httpx.get(fetch, follow_redirects=True, timeout=20)
        r.raise_for_status()
        count = len(icalendar.Calendar.from_ical(r.content).walk("VEVENT"))
    except Exception as e:
        print(f"Could not read that address: {_safe_error(e)}")
        return
    host = re.sub(r"^\w+://", "", url).split("/")[0]
    print(f"OK: fetched {host}/... and found {count} events.")
    name = ask("Name for this calendar", default_name)
    color = ask_color(default_color)
    save(path, load(path), {"name": name, "url": url, "color": color})
    print(f"Saved to {path}. Restart the companion to pick it up.")


def cmd_add_apple(path):
    print("""
Apple (iCloud) Calendar
  Apple needs an app-specific password, not your Apple ID password.
  1. Sign in at account.apple.com.
  2. Open Sign-In and Security, then App-Specific Passwords.
  3. Create one (name it "deskhub") and copy it.
It is stored in your OS credential store, never in config.toml.
""")
    username = ask("Apple ID email (empty to cancel)")
    if not username:
        return
    password = getpass.getpass("App-specific password (hidden): ").strip()
    if not password:
        return
    try:
        found = caldav_calendars(DEFAULT_CALDAV_URL, username, password)
    except Exception as e:
        print(f"Could not connect: {_safe_error(e, password)}")
        return
    if not found:
        print("Connected, but no calendars were found.")
        return
    print("Calendars found:")
    for i, (name, _) in enumerate(found, 1):
        print(f"  {i}. {name}")
    pick = ask("Numbers to use, comma separated, or 'all'", "all")
    chosen = []
    if pick.lower() != "all":
        try:
            chosen = [found[int(n) - 1][0] for n in pick.replace(" ", "").split(",") if n]
        except (ValueError, IndexError):
            print("Didn't understand that selection.")
            return
    color = ask_color(APPLE_COLOR)
    import keyring
    keyring.set_password(KEYRING_SERVICE, username, password)
    feed = {"type": "caldav", "name": "iCloud", "url": DEFAULT_CALDAV_URL,
            "username": username, "color": color}
    if chosen:
        feed["calendars"] = chosen
    save(path, load(path), feed)
    print(f"Password saved to the credential store, feed saved to {path}.")
    print("Restart the companion to pick it up.")


def cmd_remove(path):
    doc = load(path)
    feeds = feeds_of(doc)
    if not feeds:
        print("Nothing to remove.")
        return
    cmd_list(path)
    n = ask("Number to remove (empty to cancel)")
    if not n.isdigit() or not 1 <= int(n) <= len(feeds):
        return
    feed = feeds[int(n) - 1]
    username = feed.get("username") if str(feed.get("type", "")).lower() == "caldav" else None
    del feeds[int(n) - 1]
    write(path, doc)
    print("Removed.")
    still_used = any(f.get("username") == username for f in feeds)
    if username and not still_used and ask("Also delete the stored password? (y/n)", "y").lower() == "y":
        import keyring
        try:
            keyring.delete_password(KEYRING_SERVICE, username)
        except keyring.errors.PasswordDeleteError:
            pass


COMMANDS = {"list": cmd_list, "add-google": cmd_add_google,
            "add-apple": cmd_add_apple, "add-link": cmd_add_link, "remove": cmd_remove}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config")
    ap.add_argument("command", nargs="?", choices=list(COMMANDS))
    args = ap.parse_args()
    path = find_config(args.config)
    if args.command:
        COMMANDS[args.command](path)
        return
    menu(path)


def menu(path: pathlib.Path):
    """Interactive calendar menu; also used by `deskhub-setup`."""
    names = list(COMMANDS)
    labels = ["List calendars", "Add Google Calendar", "Add Apple (iCloud) calendar",
              "Add a calendar link (subscribed, Outlook, ICS)", "Remove a calendar"]
    while True:
        print(f"\nCalendars in {path}")
        for i, label in enumerate(labels, 1):
            print(f"  {i}. {label}")
        choice = ask(f"Choose 1-{len(labels)}, or empty to quit")
        if not choice:
            return
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            COMMANDS[names[int(choice) - 1]](path)


if __name__ == "__main__":
    main()
