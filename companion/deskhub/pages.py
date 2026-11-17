"""Which board pages are shown. Home is always on."""
import re

from .steam import steam_installed

ALL_PAGES = ["home", "stats", "ai", "calendar", "weather", "media", "printer", "shortcuts", "timer", "games", "network"]
PAGE_LABELS = {
    "stats": "PC stats", "ai": "AI agent usage", "calendar": "Calendar", "weather": "Weather",
    "media": "Now playing", "printer": "3D printer", "shortcuts": "Shortcuts",
    "timer": "Timer", "games": "Games", "network": "Internet (a view on the Stats page)",
}


def enabled_pages(cfg: dict) -> list[str]:
    """Page names to show, in board order. Without a [pages] block everything is on except
    the printer page (on once a printer is configured) and the games page (on when Steam
    is installed or [[games]] are configured)."""
    pages = cfg.get("pages")
    if not isinstance(pages, dict) or not isinstance(pages.get("enabled"), list):
        want = {p for p in ALL_PAGES if p not in ("printer", "games")}
        if cfg.get("printers"):
            want.add("printer")
        if steam_installed() or cfg.get("games"):
            want.add("games")
    else:
        want = {str(p).lower() for p in pages["enabled"]}
    return [p for p in ALL_PAGES if p == "home" or p in want]


NAV_POSITIONS = ("left", "right", "bottom")


def nav_position(cfg: dict) -> str:
    """Where the board's navigation bar goes: [pages] nav = "left" (default),
    "right" or "bottom"."""
    nav = str((cfg.get("pages") or {}).get("nav", "left")).strip().lower()
    return nav if nav in NAV_POSITIONS else "left"


PC_SLEEP_MODES = ("off", "clock", "none")


def pc_sleep_mode(cfg: dict) -> str:
    """What the board does while the PC's display sleeps: [display] pc_sleep =
    "off" (screen dark, default), "clock" (a screensaver clock) or "none"."""
    mode = str((cfg.get("display") or {}).get("pc_sleep", "off")).strip().lower()
    return mode if mode in PC_SLEEP_MODES else "off"


NIGHT_STYLES = ("off", "clock")


def parse_hhmm(text: str) -> int | None:
    """"23:00", "7:30", "7" or "7pm" -> minutes after midnight, or None."""
    m = re.fullmatch(r"\s*(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?\s*", str(text).lower())
    if not m:
        return None
    h, mins, ampm = int(m.group(1)), int(m.group(2) or 0), m.group(3)
    if ampm:
        if not 1 <= h <= 12:
            return None
        h = h % 12 + (12 if ampm.startswith("p") else 0)
    if h > 23 or mins > 59:
        return None
    return h * 60 + mins


def night_schedule(cfg: dict) -> tuple[int, int] | None:
    """[display] night = "23:00-07:00": (start, end) in minutes, or None when off."""
    raw = str((cfg.get("display") or {}).get("night", "")).strip()
    if "-" not in raw:
        return None
    a, b = raw.split("-", 1)
    start, end = parse_hhmm(a), parse_hhmm(b)
    if start is None or end is None or start == end:
        return None
    return start, end


def night_style(cfg: dict) -> str:
    """[display] night_style = "off" (screen dark, default) or "clock"."""
    style = str((cfg.get("display") or {}).get("night_style", "off")).strip().lower()
    return style if style in NIGHT_STYLES else "off"


def layout_message(cfg: dict) -> dict:
    # The board restarts when "nav" changes, so it always gets one.
    night = night_schedule(cfg)
    return {"type": "layout", "pages": enabled_pages(cfg), "nav": nav_position(cfg),
            "pc_sleep": pc_sleep_mode(cfg),
            # Always sent, so removing the schedule turns night mode off on the board.
            "night_start": night[0] if night else -1, "night_end": night[1] if night else -1,
            "night_style": night_style(cfg)}


# Home screen widgets, placed in two columns top to bottom. "events" stretches to
# fill its column. The left column is wider (the big clock fits there).
HOME_WIDGETS = {
    "clock": "Clock and date",
    "claude": "Claude limits",
    "events": "Up next (calendar)",
    "weather": "Weather",
    "media": "Now playing",
    "stats": "PC stats",
    "printer": "3D print progress",
    "game": "Steam game",
    "net": "Internet",
}
# Defaults with the slim top bar (the default): the clock widget isn't needed.
DEFAULT_LEFT = ["claude", "events"]


def home_columns(cfg: dict) -> tuple[list[str], list[str]]:
    home = cfg.get("home") if isinstance(cfg.get("home"), dict) else {}
    right_default = ["weather", "media", "printer"] if cfg.get("printers") else ["weather", "media", "stats"]

    def column(key, default):
        value = home.get(key)
        if not isinstance(value, list):
            return list(default)
        return [w for w in (str(x).lower() for x in value) if w in HOME_WIDGETS]

    left = column("left", DEFAULT_LEFT)
    right = [w for w in column("right", right_default) if w not in left]
    return left, right


def home_header(cfg: dict) -> bool:
    """True: time and date in a slim bar across the top instead of the clock widget."""
    home = cfg.get("home") if isinstance(cfg.get("home"), dict) else {}
    return bool(home.get("header", True))


def home_message(cfg: dict) -> dict:
    left, right = home_columns(cfg)
    return {"type": "home", "left": left, "right": right, "header": home_header(cfg)}
