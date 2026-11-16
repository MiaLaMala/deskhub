"""Which board pages are shown. Home is always on."""

ALL_PAGES = ["home", "stats", "ai", "calendar", "weather", "media", "printer", "shortcuts", "timer"]
PAGE_LABELS = {
    "stats": "PC stats", "ai": "AI agent usage", "calendar": "Calendar", "weather": "Weather",
    "media": "Now playing", "printer": "3D printer", "shortcuts": "Shortcuts",
    "timer": "Timer",
}


def enabled_pages(cfg: dict) -> list[str]:
    """Page names to show, in board order. Without a [pages] block everything is on except
    the printer page, which turns on by itself once a printer is configured."""
    pages = cfg.get("pages")
    if not isinstance(pages, dict) or not isinstance(pages.get("enabled"), list):
        want = {p for p in ALL_PAGES if p != "printer"}
        if cfg.get("printers"):
            want.add("printer")
    else:
        want = {str(p).lower() for p in pages["enabled"]}
    return [p for p in ALL_PAGES if p == "home" or p in want]


def layout_message(cfg: dict) -> dict:
    return {"type": "layout", "pages": enabled_pages(cfg)}


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
