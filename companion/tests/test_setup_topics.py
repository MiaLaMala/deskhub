"""`deskhub-setup <topic>` runs one part of setup on its own. Temp files only."""
import builtins
import contextlib
import io
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import tomlkit
from deskhub import calendars_cli
from deskhub import setup_cli as s

problems = []


def check(ok, what):
    print(("ok  " if ok else "BAD ") + what)
    if not ok:
        problems.append(what)


def run(argv, answers):
    """Run deskhub-setup with these arguments and typed answers; returns (output, exit code)."""
    it = iter(answers)
    real_input, real_argv = builtins.input, sys.argv
    builtins.input = lambda prompt="": next(it)
    sys.argv = ["deskhub-setup", *argv]
    out, code = io.StringIO(), 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            s.main()
    except SystemExit as e:
        code = e.code or 0
    finally:
        builtins.input, sys.argv = real_input, real_argv
    return out.getvalue(), code


check(s.topic_name("Calendars") == "calendar" and s.topic_name("grid") == "home"
      and s.topic_name("ai") == "claude" and s.topic_name("radio") is None, "names and aliases")

with tempfile.TemporaryDirectory() as d:
    d = pathlib.Path(d)
    config = d / "config.toml"
    config.write_text('[hub]\ntoken = "abc"\n', encoding="utf-8")
    fw = d / "firmware"
    fw.mkdir()
    sdk = fw / "sdkconfig"
    sdk.write_text('CONFIG_HUB_CITY="Charlotte"\nCONFIG_HUB_TOKEN="abc"\nCONFIG_HUB_FAHRENHEIT=y\n'
                   '# CONFIG_HUB_24H is not set\n', encoding="utf-8")
    base = ["--config", str(config), "--firmware", str(fw)]

    out, code = run(["--help"], [])
    check(code == 0 and "calendar" in out and "weather" in out and "internet" in out, "--help lists the topics")

    out, code = run(["radio", *base], [])
    check(code == 2 and "Unknown topic: radio" in out, "unknown topic explained")

    out, _ = run(["internet", *base], ["6", "y"])
    net = tomlkit.parse(config.read_text(encoding="utf-8"))["internet"]
    check(net["speedtest_hours"] == 6 and net["show_ip"] is True, f"internet saved: {dict(net)}")
    check("Restart the companion" in out, "says to restart the companion")
    check("Wi-Fi" not in out and "Calendars" not in out, "only that topic runs")

    out, _ = run(["internet", *base], ["", ""])
    check("Restart the companion" not in out, "nothing changed, no restart note")

    out, _ = run(["grid", *base], ["y", "n", "weather", "2x1", ""])
    home = tomlkit.parse(config.read_text(encoding="utf-8"))["home"]
    check(home["grid"] == [{"widget": "weather", "x": 0, "y": 0, "w": 2, "h": 1}], "alias grid runs the Home step")

    # Weather keeps the city on Enter, flips the clock to 24-hour, then offers to flash.
    out, _ = run(["weather", *base], ["", "", "y", "n"])
    check('CONFIG_HUB_24H=y' in sdk.read_text(encoding="utf-8"), "weather topic saves units to sdkconfig")
    check("Build and flash" in out and "Later: uv run deskhub-flash" in out, "firmware topic offers to flash")

    out, _ = run(["weather", *base], ["", "", "y"])
    check("Nothing changed" in out and "Build and flash" not in out, "no change, no flash")

    # The calendar topic goes straight to the menu, with no "Add or change" question.
    opened = []
    calendars_cli.menu = lambda path: opened.append(path)
    run(["calendar", *base], [])
    check(opened == [config], "calendar opens the calendar menu directly")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
