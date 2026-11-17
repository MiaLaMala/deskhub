"""One-stop setup for the desk hub: Wi-Fi, location, units, calendars, printers, pages, then flash.

    uv run deskhub-setup [--config companion/config.toml] [--firmware ../firmware]

Every question shows the current value; press Enter to keep it. Run it again
any time to change something.
"""
import argparse
import getpass
import importlib.resources
import importlib.util
import json
import os
import pathlib
import re
import secrets
import subprocess
import sys

import httpx
import tomlkit

from .__main__ import find_config
from .pages import ALL_PAGES, PAGE_LABELS, enabled_pages

GEOCODE_URL = "https://geocoding-api.open-meteo.com/v1/search"


# ---- small prompt helpers --------------------------------------------------

def ask(prompt: str, default: str = "") -> str:
    hint = f" [{default}]" if default else ""
    value = input(f"{prompt}{hint}: ").strip()
    return value or default


def yes(prompt: str, default: bool) -> bool:
    answer = ask(f"{prompt} ({'Y/n' if default else 'y/N'})").lower()
    return default if not answer else answer.startswith("y")


def heading(text: str):
    print(f"\n== {text} ==")


# ---- sdkconfig -------------------------------------------------------------

def read_kconfig(text: str, key: str) -> str | None:
    m = re.search(rf'^CONFIG_{key}=(.*)$', text, re.M)
    if not m:
        return None
    raw = m.group(1)
    if raw.startswith('"'):
        return raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return raw


def set_kconfig(text: str, key: str, value) -> str:
    """Set CONFIG_<key>. Strings are quoted; booleans become y / '# is not set'."""
    pattern = re.compile(rf"^(CONFIG_{key}=.*|# CONFIG_{key} is not set)$", re.M)
    if isinstance(value, bool):
        line = f"CONFIG_{key}=y" if value else f"# CONFIG_{key} is not set"
    else:
        line = 'CONFIG_%s="%s"' % (key, str(value).replace("\\", "\\\\").replace('"', '\\"'))
    if pattern.search(text):
        return pattern.sub(lambda _: line, text)
    return text.rstrip("\n") + "\n" + line + "\n"


# ---- location --------------------------------------------------------------

def geocode(query: str) -> list[dict]:
    """City search via Open-Meteo. 'Charlotte, NC' style input is split so the
    part after the comma narrows the results by state or country."""
    name, _, region = (p.strip() for p in query.partition(","))
    r = httpx.get(GEOCODE_URL, params={"name": name, "count": 10, "language": "en"}, timeout=15)
    r.raise_for_status()
    results = r.json().get("results") or []
    if region:
        reg = region.lower()
        narrowed = [x for x in results if reg in " ".join(
            str(x.get(k, "")) for k in ("admin1", "country", "country_code")).lower()
            or reg == _US_STATES.get(str(x.get("admin1", "")).lower(), "")]
        results = narrowed or results
    return results[:6]


_US_STATES = {
    "alabama": "al", "alaska": "ak", "arizona": "az", "arkansas": "ar", "california": "ca",
    "colorado": "co", "connecticut": "ct", "delaware": "de", "florida": "fl", "georgia": "ga",
    "hawaii": "hi", "idaho": "id", "illinois": "il", "indiana": "in", "iowa": "ia",
    "kansas": "ks", "kentucky": "ky", "louisiana": "la", "maine": "me", "maryland": "md",
    "massachusetts": "ma", "michigan": "mi", "minnesota": "mn", "mississippi": "ms",
    "missouri": "mo", "montana": "mt", "nebraska": "ne", "nevada": "nv", "new hampshire": "nh",
    "new jersey": "nj", "new mexico": "nm", "new york": "ny", "north carolina": "nc",
    "north dakota": "nd", "ohio": "oh", "oklahoma": "ok", "oregon": "or", "pennsylvania": "pa",
    "rhode island": "ri", "south carolina": "sc", "south dakota": "sd", "tennessee": "tn",
    "texas": "tx", "utah": "ut", "vermont": "vt", "virginia": "va", "washington": "wa",
    "west virginia": "wv", "wisconsin": "wi", "wyoming": "wy",
}


def posix_tz(iana: str) -> str:
    """POSIX TZ string (what the ESP32's C library understands) for an IANA zone.
    It is the footer line of the zone's TZif file in the tzdata package."""
    parts = iana.split("/")
    res = importlib.resources.files("tzdata.zoneinfo").joinpath(*parts)
    data = res.read_bytes()
    footer = data.rstrip(b"\n").rsplit(b"\n", 1)[-1].decode()
    if not footer:
        raise ValueError(f"no POSIX rule for {iana}")
    return footer


def describe_place(p: dict) -> str:
    bits = [p.get("name"), p.get("admin1"), p.get("country")]
    return ", ".join(b for b in bits if b)


# ---- steps -----------------------------------------------------------------

def step_wifi(cfg: str) -> str:
    heading("Wi-Fi (2.4 GHz only)")
    ssid = ask("Network name", read_kconfig(cfg, "HUB_WIFI_SSID") or "")
    if ssid and len(ssid.encode()) > 32:
        sys.exit("SSID must be at most 32 bytes.")
    cfg = set_kconfig(cfg, "HUB_WIFI_SSID", ssid)
    has_pw = bool(read_kconfig(cfg, "HUB_WIFI_PASSWORD"))
    pw = getpass.getpass("Password (hidden" + (", Enter keeps the saved one" if has_pw else "") + "): ")
    if pw:
        if not 8 <= len(pw.encode()) <= 63:
            sys.exit("WPA passwords are 8-63 characters.")
        cfg = set_kconfig(cfg, "HUB_WIFI_PASSWORD", pw)
    return cfg


def step_location(cfg: str) -> tuple[str, str]:
    heading("Location (weather and time zone)")
    current = read_kconfig(cfg, "HUB_CITY") or ""
    country = ""
    while True:
        query = ask("City, e.g. 'Charlotte, NC' or 'Paris, France'", current)
        if query == current and current:
            return cfg, country
        try:
            places = geocode(query)
        except httpx.HTTPError as e:
            print(f"City search failed ({type(e).__name__}); check your internet and try again.")
            continue
        if not places:
            print("No match. Try adding the state or country after a comma.")
            continue
        for i, p in enumerate(places, 1):
            print(f"  {i}. {describe_place(p)}  ({p['latitude']:.3f}, {p['longitude']:.3f}, {p.get('timezone', '?')})")
        pick = ask("Which one", "1")
        if not pick.isdigit() or not 1 <= int(pick) <= len(places):
            continue
        p = places[int(pick) - 1]
        tz = posix_tz(p["timezone"])
        cfg = set_kconfig(cfg, "HUB_CITY", p["name"])
        cfg = set_kconfig(cfg, "HUB_LATITUDE", f"{p['latitude']:.4f}")
        cfg = set_kconfig(cfg, "HUB_LONGITUDE", f"{p['longitude']:.4f}")
        cfg = set_kconfig(cfg, "HUB_TZ", tz)
        print(f"Set {describe_place(p)}, time zone {p['timezone']} ({tz}).")
        return cfg, p.get("country_code", "")


def step_units(cfg: str, country: str) -> str:
    heading("Units")
    is_f = read_kconfig(cfg, "HUB_FAHRENHEIT")
    default_f = (is_f == "y") if is_f is not None else country in ("US", "LR", "MM", "")
    cfg = set_kconfig(cfg, "HUB_FAHRENHEIT", yes("Fahrenheit and mph", default_f))
    is_24 = read_kconfig(cfg, "HUB_24H") == "y"
    cfg = set_kconfig(cfg, "HUB_24H", yes("24-hour clock", is_24))
    return cfg


def step_token(cfg: str, config_path: pathlib.Path) -> str:
    """Make sure firmware and companion share the same random token."""
    token = read_kconfig(cfg, "HUB_TOKEN")
    if not token or token == "change-me":
        token = secrets.token_urlsafe(18)
        cfg = set_kconfig(cfg, "HUB_TOKEN", token)
    doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    hub = doc.setdefault("hub", tomlkit.table())
    if hub.get("token") != token:
        hub["token"] = token
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
        print("Companion token updated to match the firmware.")
    return cfg


def step_live_limits(config_path: pathlib.Path):
    heading("Claude Code limits")
    print("By default the 5-hour and weekly limits update only while you use `claude` in a\n"
          "terminal. With live limits on, the companion asks Anthropic for them every minute\n"
          "using the sign-in Claude Code saved on this PC. It sends no messages, so it uses no\n"
          "tokens or credits, but the endpoint is undocumented and may stop working.")
    doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    claude = doc.get("claude") or tomlkit.table()
    on = yes("Turn on live limits", bool(claude.get("live_limits", False)))
    if claude.get("live_limits") != on:
        claude["live_limits"] = on
        doc["claude"] = claude
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")


CLAUDE_SETTINGS = pathlib.Path.home() / ".claude" / "settings.json"
INSTALLER = pathlib.Path(__file__).resolve().parent.parent / "install_claude.py"


def hook_events_installed() -> set[str]:
    """Claude Code hook events that already run the desk hub's hook_bridge.py."""
    try:
        hooks = json.loads(CLAUDE_SETTINGS.read_text(encoding="utf-8")).get("hooks") or {}
    except (OSError, ValueError):
        return set()
    return {ev for ev, entries in hooks.items() if "hook_bridge.py" in json.dumps(entries)}


def hook_events_wanted() -> set[str]:
    spec = importlib.util.spec_from_file_location("install_claude", INSTALLER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return set(mod.HOOK_EVENTS)


def run_installer(*args: str) -> bool:
    return subprocess.run([sys.executable, str(INSTALLER), *args]).returncode == 0


def step_alerts(config_path: pathlib.Path):
    heading("Waiting alerts")
    print("When a Claude Code session needs a permission, asks a question, or has finished and\n"
          "is waiting for your reply, the board shows it on the Home usage card and the AI\n"
          "page. This needs small hooks in Claude Code's settings (~/.claude/settings.json);\n"
          "your other hooks are left alone and a backup is kept.")
    doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    claude = doc.get("claude") or tomlkit.table()
    installed = hook_events_installed()
    on = yes("Show waiting alerts on the board", bool(claude.get("alerts", True)))
    if claude.get("alerts") != on:
        claude["alerts"] = on
        doc["claude"] = claude
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")
    if on and not installed:
        if yes("Add the hooks to Claude Code now", True) and run_installer("hooks"):
            print("Hooks added. Sessions you start from now on will report to the board.")
    elif on and installed != hook_events_wanted():
        if yes("Your hooks are from an older version. Update them", True):
            run_installer("hooks")
    elif not on and installed:
        if yes("Remove the hooks from Claude Code too", True):
            run_installer("hooks", "--remove")


def step_agent(config_path: pathlib.Path):
    heading("AI agent")
    print("The AI page can show Claude Code or OpenAI Codex usage. 'auto' shows whichever\n"
          "you used most recently.")
    doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    ai = doc.get("ai") or tomlkit.table()
    current = str(ai.get("agent", "auto"))
    while True:
        agent = ask("Which AI agent should the AI page show? auto/claude/codex", current).lower()
        if agent in ("auto", "claude", "codex"):
            break
        print("Type auto, claude or codex.")
    if ai.get("agent") != agent:
        ai["agent"] = agent
        doc["ai"] = ai
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def step_printers(config_path: pathlib.Path):
    heading("3D printers")
    print("Show the status of Bambu Lab printers (A1, P1, X1, H2D) on the board.")
    if yes("Add or change 3D printers", False):
        from .printers_cli import menu
        menu(config_path)


def step_games(config_path: pathlib.Path):
    heading("Games")
    print("The Games page shows your Steam games by itself. Games from elsewhere, like\n"
          "Minecraft, emulators or other launchers, can show there too. Start the game\n"
          "first, then pick its window from the list.")
    if yes("Add or change games that aren't on Steam", False):
        from .games_cli import menu
        menu(config_path)
    step_steam_key()


def step_steam_key():
    """Optional Steam Web API key: friends in game and total playtime for every game."""
    from .steam import steam_installed
    from . import steam_web

    if not steam_installed():
        return
    have = bool(steam_web.get_key())
    print("\nWith your own Steam Web API key the Games page also shows which friends are in a\n"
          "game, and total playtime for every game. Get one at\n"
          "https://steamcommunity.com/dev/apikey (any domain name works). It's kept in the\n"
          "Windows credential store, not in config.toml.")
    if have:
        if yes("A Steam key is saved. Keep using it", True):
            return
        steam_web.set_key(None)
        print("Removed the Steam key.")
        return
    if not yes("Add a Steam Web API key", False):
        return
    key = getpass.getpass("Steam Web API key (hidden): ").strip()
    if not re.fullmatch(r"[0-9A-Fa-f]{32}", key):
        print("That doesn't look like a Steam key (32 letters and digits); not saved.")
        return
    try:
        steam_web._http_get(f"{steam_web.API}/ISteamWebAPIUtil/GetSupportedAPIList/v1/", {"key": key})
    except Exception as e:
        print(f"Steam didn't accept the key ({getattr(getattr(e, 'response', None), 'status_code', e)}); not saved.")
        return
    steam_web.set_key(key)
    print("Saved. Restart the companion to show friends and playtime.")


def step_pages(config_path: pathlib.Path):
    heading("Pages")
    print("Choose which pages the board shows. Home is always shown.")
    doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    current = enabled_pages(doc.unwrap())
    chosen = ["home"] + [p for p in ALL_PAGES if p != "home"
                         and yes(f"Show {PAGE_LABELS[p]}", p in current)]
    pages = doc.get("pages")
    if pages is None:
        pages = tomlkit.table()
        pages.add(tomlkit.comment("Home is always shown. Remove names to hide pages."))
        doc["pages"] = pages
    arr = tomlkit.array()
    arr.extend(chosen)
    pages["enabled"] = arr
    from .pages import NAV_POSITIONS, nav_position

    current_nav = nav_position(doc.unwrap())
    while True:
        nav = ask("Navigation bar: left, right or bottom", current_nav).lower()
        if nav in NAV_POSITIONS:
            break
        print("Type left, right or bottom.")
    if nav != "left" or "nav" in pages:
        pages["nav"] = nav
    config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def step_display(config_path: pathlib.Path):
    heading("Screen sleep and night mode")
    from .pages import PC_SLEEP_MODES, pc_sleep_mode

    print("When Windows turns your monitor off, the board can go dark too, show a dim\n"
          "clock, or stay as it is. A touch brings the board back for a minute.")
    doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    current = pc_sleep_mode(doc.unwrap())
    while True:
        mode = ask("Board while the PC sleeps: off, clock or none", current).lower()
        if mode in PC_SLEEP_MODES:
            break
        print("Type off, clock or none.")
    from .pages import NIGHT_STYLES, night_schedule, night_style

    print("\nNight mode darkens the board on a schedule, PC or not (it keeps the hours itself).")
    night = night_schedule(doc.unwrap())
    current_night = f"{night[0] // 60:02d}:{night[0] % 60:02d}-{night[1] // 60:02d}:{night[1] % 60:02d}" if night else "off"
    while True:
        hours = ask("Night mode hours, like 23:00-07:00, or off", current_night).strip().lower()
        if hours == "off" or night_schedule({"display": {"night": hours}}):
            break
        print("Type two times like 23:00-07:00, or off.")
    style = night_style(doc.unwrap())
    if hours != "off":
        while True:
            style = ask("At night the board goes dark (off) or shows a clock (clock)", style).lower()
            if style in NIGHT_STYLES:
                break
            print("Type off or clock.")
    if (mode, hours, style) != (current, current_night, night_style(doc.unwrap())) or "display" not in doc:
        display = doc.get("display") or tomlkit.table()
        display["pc_sleep"] = mode
        display["night"] = "" if hours == "off" else hours
        display["night_style"] = style
        doc["display"] = display
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def step_home(config_path: pathlib.Path):
    heading("Home screen")
    from .pages import HOME_WIDGETS, home_columns, home_header

    doc = tomlkit.parse(config_path.read_text(encoding="utf-8"))
    left, right = home_columns(doc.unwrap())
    header = home_header(doc.unwrap())
    print("The time and date can be the big clock widget, or a slim bar across the top of\n"
          "Home, which leaves room for another widget.")
    new_header = yes("Time and date in a slim top bar", header)
    print("Home shows widgets in two columns, top to bottom. Available widgets:")
    for name, label in HOME_WIDGETS.items():
        print(f"  {name:<8} {label}")
    print("The left column is wider and fits the big clock. 'events' stretches to fill its column.")
    if new_header:
        print("With the top bar, 'clock' is skipped if you list it.")

    def ask_column(label: str, current: list[str]) -> list[str]:
        while True:
            raw = ask(f"{label} column, comma-separated", ", ".join(current))
            names = [n.strip().lower() for n in raw.split(",") if n.strip()]
            bad = [n for n in names if n not in HOME_WIDGETS]
            if not bad:
                return names
            print(f"Unknown widget(s): {', '.join(bad)}")

    new_left = ask_column("Left", left)
    new_right = [n for n in ask_column("Right", right) if n not in new_left]
    if (new_left, new_right, new_header) != (left, right, header) or "home" not in doc:
        home = doc.get("home") or tomlkit.table()
        home["header"] = new_header
        for key, value in (("left", new_left), ("right", new_right)):
            arr = tomlkit.array()
            arr.extend(value)
            home[key] = arr
        doc["home"] = home
        config_path.write_text(tomlkit.dumps(doc), encoding="utf-8")


def find_idf() -> pathlib.Path | None:
    candidates = [os.environ.get("IDF_PATH", "")]
    candidates += sorted((pathlib.Path.home() / "esp").glob("esp-idf*"), reverse=True)
    # Espressif's Windows installer puts frameworks here.
    candidates += sorted(pathlib.Path("C:/Espressif/frameworks").glob("esp-idf*"), reverse=True)
    # Espressif's newer installer (EIM) uses C:/esp/v5.5/esp-idf.
    candidates += sorted(pathlib.Path("C:/esp").glob("v*/esp-idf"), reverse=True)
    for c in candidates:
        if c and (pathlib.Path(c) / "export.ps1").is_file():
            return pathlib.Path(c)
    return None


def find_idf_python_env(idf: pathlib.Path) -> pathlib.Path | None:
    """ESP-IDF's own Python environment, e.g. ~/.espressif/python_env/idf5.5_py3.13_env.
    Prefers one for the same ESP-IDF version (from the folder name, like v5.5.6)."""
    roots = [os.environ.get("IDF_TOOLS_PATH", ""), str(pathlib.Path.home() / ".espressif"), "C:/Espressif"]
    envs = []
    for root in roots:
        if root:
            envs += [p for p in pathlib.Path(root).glob("python_env/idf*_env")
                     if (p / "Scripts" / "python.exe").is_file()]
    if not envs:
        return None
    m = re.search(r"v(\d+\.\d+)", str(idf))
    if m:
        same = [p for p in envs if p.name.startswith(f"idf{m.group(1)}_")]
        envs = same or envs
    return sorted(envs, key=lambda p: p.name)[-1]


def find_port() -> str | None:
    from serial.tools import list_ports

    ports = [p.device for p in list_ports.comports() if p.vid == 0x303A]
    return ports[0] if len(ports) == 1 else None


def step_flash(firmware: pathlib.Path):
    heading("Build and flash")
    if not yes("Build the firmware and flash the board now", True):
        print(f"Later: in {firmware}, run `idf.py -p COMx flash`.")
        return
    idf = find_idf()
    if not idf:
        print("ESP-IDF not found (looked in IDF_PATH, ~/esp, C:/Espressif/frameworks and C:/esp).\n"
              "The board was NOT flashed. Install ESP-IDF 5.5 and run setup again, or flash by hand (see README).")
        return
    port = find_port() or ask("Board's COM port (Device Manager > Ports)", "")
    if not port:
        print("No port given, so the board was NOT flashed.")
        return
    env = find_idf_python_env(idf)
    if env:
        # Run ESP-IDF with the Python it was installed with. export.ps1 looks for a
        # python_env matching whichever `python` comes first on PATH.
        script = (f'$env:IDF_PYTHON_ENV_PATH = "{env}"; '
                  f'$env:PATH = "{env / "Scripts"};" + $env:PATH; ')
    else:
        script = f'$env:PATH = "{pathlib.Path(sys.base_prefix)};" + $env:PATH; '
    script += f'. "{idf / "export.ps1"}" | Out-Null; Set-Location "{firmware}"; idf.py -p {port} flash'
    print(f"Building and flashing on {port}. The first build takes a few minutes.")
    # ESP-IDF refuses to run when it sees an MSYS/Git Bash environment, even from PowerShell.
    env_vars = {k: v for k, v in os.environ.items() if k not in ("MSYSTEM", "MSYSTEM_PREFIX", "MINGW_PREFIX")}
    r = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], env=env_vars)
    print("Done. The hub restarts with the new settings." if r.returncode == 0
          else "Flashing failed; see the output above.")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config", help="companion config.toml")
    ap.add_argument("--firmware", help="firmware folder (default: ../firmware)")
    args = ap.parse_args()

    here = pathlib.Path(__file__).resolve().parents[1]
    if not args.config and not (here / "config.toml").is_file() and (here / "config.example.toml").is_file():
        # First run: start from the example config.
        (here / "config.toml").write_text((here / "config.example.toml").read_text(encoding="utf-8"),
                                          encoding="utf-8")
        print("Created config.toml from config.example.toml.")
    config_path = find_config(args.config)
    firmware = pathlib.Path(args.firmware) if args.firmware else \
        pathlib.Path(__file__).resolve().parents[2] / "firmware"
    sdk = firmware / "sdkconfig"
    cfg = sdk.read_text(encoding="utf-8") if sdk.is_file() else ""

    print("Desk Hub setup. Press Enter to keep the value shown in brackets.")
    cfg = step_wifi(cfg)
    cfg, country = step_location(cfg)
    cfg = step_units(cfg, country)
    cfg = step_token(cfg, config_path)
    sdk.write_text(cfg, encoding="utf-8")
    print(f"\nSaved hub settings to {sdk}.")

    heading("Calendars")
    if yes("Add or change calendars (Google, Apple, links)", False):
        from .calendars_cli import menu
        menu(config_path)

    step_printers(config_path)
    step_games(config_path)
    step_pages(config_path)
    step_home(config_path)
    step_display(config_path)
    step_live_limits(config_path)
    step_alerts(config_path)
    step_agent(config_path)

    step_flash(firmware)
    print("\nRestart the companion (uv run python -m deskhub) to pick up calendar or token changes.")


if __name__ == "__main__":
    main()
