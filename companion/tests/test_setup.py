"""Exercises deskhub-setup against temp copies: city search, POSIX time zones,
sdkconfig edits and token sync. Uses the live Open-Meteo geocoding API.

    uv run python tests/test_setup.py
"""
import builtins
import getpass
import pathlib
import shutil
import sys
import tempfile

from deskhub import setup_cli as s
import deskhub.pages as _pg
_pg.steam_installed = lambda: False

problems = []

def check(cond, msg):
    if not cond:
        problems.append(msg)

# Time zones -> POSIX strings the ESP32 understands.
check(s.posix_tz("America/New_York") == "EST5EDT,M3.2.0,M11.1.0", "New York tz")
check(s.posix_tz("Europe/London") == "GMT0BST,M3.5.0/1,M10.5.0", "London tz")
check(s.posix_tz("Asia/Kolkata") == "IST-5:30", "Kolkata tz")

# City search, including "City, ST" narrowing.
places = s.geocode("Charlotte, NC")
check(places and places[0]["admin1"] == "North Carolina", f"Charlotte NC -> {places[:1]}")
places = s.geocode("Paris, France")
check(places and places[0]["country_code"] == "FR", "Paris FR")

# Kconfig edits keep other lines and handle quoting and booleans.
cfg = 'CONFIG_A=1\nCONFIG_HUB_CITY="New York"\n# CONFIG_HUB_24H is not set\n'
cfg = s.set_kconfig(cfg, "HUB_CITY", 'Say "hi"')
cfg = s.set_kconfig(cfg, "HUB_24H", True)
cfg = s.set_kconfig(cfg, "HUB_NEW", "x")
check(s.read_kconfig(cfg, "HUB_CITY") == 'Say "hi"', "quote round trip")
check("CONFIG_HUB_24H=y" in cfg and "CONFIG_A=1" in cfg and 'CONFIG_HUB_NEW="x"' in cfg, "kconfig edits")

# Full flow on temp copies: keep Wi-Fi, pick Charlotte, keep units, skip calendars and flash.
root = pathlib.Path(tempfile.mkdtemp())
fw = root / "firmware"; fw.mkdir()
(fw / "sdkconfig").write_text('CONFIG_HUB_WIFI_SSID="home"\nCONFIG_HUB_WIFI_PASSWORD="secret123"\n'
                              'CONFIG_HUB_TOKEN="change-me"\nCONFIG_HUB_CITY="New York"\n'
                              'CONFIG_HUB_FAHRENHEIT=y\n# CONFIG_HUB_24H is not set\n')
conf = root / "config.toml"
shutil.copy(pathlib.Path(__file__).parent.parent / "config.example.toml", conf)
# Wi-Fi, city, pick, F, 24h, calendars, printers, games, 9 pages (hide Weather and Games), top bar, home left+right, live limits, flash
answers = iter(["", "Charlotte, NC", "1", "", "", "n", "n", "n",
                "", "", "", "n", "", "", "", "", "n", "y", "clock, events", "media, bogus", "printer", "y", "", "", "codex", "n"])
builtins.input = lambda prompt="": next(answers)
# Never touch the real Claude Code settings: point the alerts step at a temp file.
s.CLAUDE_SETTINGS = root / "claude_settings.json"
installer_calls = []
s.run_installer = lambda *a: installer_calls.append(a) or True
getpass.getpass = lambda prompt="": ""
sys.argv = ["deskhub-setup", "--config", str(conf), "--firmware", str(fw)]
s.main()
out = (fw / "sdkconfig").read_text()
check(s.read_kconfig(out, "HUB_CITY") == "Charlotte", "city saved")
check(s.read_kconfig(out, "HUB_LATITUDE", ).startswith("35.2"), "lat saved")
check(s.read_kconfig(out, "HUB_TZ") == "EST5EDT,M3.2.0,M11.1.0", "tz saved")
check(s.read_kconfig(out, "HUB_WIFI_PASSWORD") == "secret123", "password kept")
token = s.read_kconfig(out, "HUB_TOKEN")
check(token != "change-me" and f'token = "{token}"' in conf.read_text(), "token synced to config.toml")
check("# Shortcut tiles" in conf.read_text(), "config comments kept")
import tomllib as _t
_home = _t.loads(conf.read_text())["home"]
check(_home == {"header": True, "left": ["clock", "events"], "right": ["printer"]}, f"home layout saved: {_home}")
check("live_limits = true" in conf.read_text(), "live limits turned on")
check('agent = "codex"' in conf.read_text(), "AI agent saved")
check(installer_calls == [("hooks",)], f"alerts step installs the hooks: {installer_calls}")
check("alerts = true" in conf.read_text(), "alerts kept on")

# Turning alerts off with hooks installed offers to remove them; old hooks get updated.
import json as _j
s.CLAUDE_SETTINGS.write_text(_j.dumps({"hooks": {"Stop": [{"matcher": "", "hooks": [{"type": "command", "command": "py hook_bridge.py Stop"}]}]}}))
installer_calls.clear()
answers = iter(["n", ""])
s.step_alerts(conf)
check(installer_calls == [("hooks", "--remove")] and "alerts = false" in conf.read_text(), f"alerts off removes hooks: {installer_calls}")
installer_calls.clear()
answers = iter(["y", ""])
s.step_alerts(conf)
check(installer_calls == [("hooks",)], f"outdated hooks get updated: {installer_calls}")
import tomllib
pages = tomllib.loads(conf.read_text())["pages"]["enabled"]
check(pages == ["home", "stats", "ai", "calendar", "media", "printer", "shortcuts", "timer"], f"pages saved: {pages}")
check("# Home is always shown" in conf.read_text(), "pages comment kept")
shutil.rmtree(root)

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
