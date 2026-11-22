"""deskhub-pi flash/backup: the commands it builds (offsets from min_spiffs.csv), image checks,
the Wi-Fi upload request, and the command line. Never touches a serial port or the network.

    python tests/test_pi_flash.py
"""
import pathlib
import sys
import tempfile
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import httpx

from deskhub import flash_cli
from deskhub.pi import cli, flash

problems = []


def check(ok, what):
    print(("ok  " if ok else "BAD ") + what)
    if not ok:
        problems.append(what)


tmp = pathlib.Path(tempfile.mkdtemp())
img = tmp / "firmware.bin"
img.write_bytes(b"\xe9" + b"\0" * 300_000)

# Partition table min_spiffs.csv: app0 ota_0 at 0x10000, 0x1E0000 long; otadata at 0xe000.
check((flash.APP_OFFSET, flash.APP_SIZE, flash.OTADATA_OFFSET, flash.OTADATA_SIZE) == (0x10000, 1_966_080, 0xE000, 0x2000),
      "offsets from the partition table")

# image checks
check(flash.check_image(img) is None, "a normal app image passes")
bad = tmp / "bad.bin"
bad.write_bytes(b"\x00" * 100)
check("0xE9" in (flash.check_image(bad) or ""), "wrong magic byte refused (e.g. a full backup)")
big = tmp / "big.bin"
big.write_bytes(b"\xe9" + b"\0" * flash.APP_SIZE)
check("app slot" in (flash.check_image(big) or ""), "image larger than the app slot refused")
check("not found" in (flash.check_image(tmp / "none.bin") or ""), "missing file reported")

# serial flash
ran = []


def fake_run(rc=(0, 0)):
    codes = list(rc)

    def run(cmd):
        ran.append(cmd)
        return types.SimpleNamespace(returncode=codes.pop(0))
    return run


ran.clear()
check(flash.serial_flash("/dev/ttyUSB0", img, run=fake_run()), "serial flash succeeds")
tools = [c[3:] for c in ran]
check(ran[0][1:3] == ["-m", "esptool"], "runs esptool as a module of the same Python")
check(ran[0][3:] == ["--chip", "esp32", "--port", "/dev/ttyUSB0", "--baud", "460800", "write_flash", "0x10000", str(img)],
      f"write_flash at 0x10000: {ran[0][3:]}")
check(ran[1][3:] == ["--chip", "esp32", "--port", "/dev/ttyUSB0", "erase_region", "0xe000", "0x2000"],
      f"then erases otadata: {ran[1][3:]}")
ran.clear()
check(not flash.serial_flash("/dev/ttyUSB0", img, run=fake_run((1, 0))) and len(ran) == 1, "failed write: stops, otadata untouched")
ran.clear()
check(not flash.serial_flash("p", bad, run=fake_run()) and ran == [], "a bad image is not flashed")

# backup
ran.clear()
out = tmp / "sicherung.bin"


def backup_run(cmd):
    ran.append(cmd)
    with open(cmd[-1], "wb") as f:
        f.truncate(flash.FLASH_SIZE)
    return types.SimpleNamespace(returncode=0)


check(flash.serial_backup("/dev/ttyUSB0", out, run=backup_run), "backup succeeds")
check(ran[0][3:] == ["--chip", "esp32", "--port", "/dev/ttyUSB0", "--baud", "460800", "read_flash", "0x0", "0x400000", str(out)],
      f"read_flash 0x0 0x400000: {ran[0][3:]}")
check(not flash.serial_backup("/dev/ttyUSB0", out, run=backup_run), "an existing backup is never overwritten")
short = tmp / "kurz.bin"
check(not flash.serial_backup("p", short, run=lambda c: (short.write_bytes(b"x"), types.SimpleNamespace(returncode=0))[1]),
      "a short file counts as failed")

# Wi-Fi
sent = {}


def post_ok(status, text=""):
    def post(url, params, content, headers, timeout):
        sent.update(url=url, params=params, size=len(content))
        return httpx.Response(status, text=text)
    return post


check(flash.ota(img, "display.example", "tok", post=post_ok(200)), "OTA ok")
check(sent == {"url": "http://display.example/firmware", "params": {"token": "tok"}, "size": 300_001}, f"OTA request: {sent}")
check(not flash.ota(img, "h", "t", post=post_ok(403, "denied")), "OTA denied on the display")
check(not flash.ota(img, "h", "t", post=post_ok(408)), "OTA nobody tapped")
check(not flash.ota(bad, "h", "t", post=post_ok(200)), "OTA refuses a bad image before sending")

# command line
cfg = tmp / "c.toml"
cfg.write_text('[hub]\nhost = "d.example:81"\ntoken = "abc"\n')
calls = []
flash.ota = lambda image, host, token, post=None: calls.append(("ota", image.name, host, token)) or True
flash.serial_flash = lambda port, image: calls.append(("serial", port, image.name)) or True
flash.serial_backup = lambda port, target: calls.append(("backup", port, target.name)) or True
check(cli.main(["flash", "--ota", "--config", str(cfg), "x.bin"]) == 0 and calls[-1] == ("ota", "x.bin", "d.example:81", "abc"),
      f"flash --ota reads host and token from the config: {calls[-1]}")
cli.main(["flash", "--ota", "--host", "other.example", "--config", str(cfg), "x.bin"])
check(calls[-1][2] == "other.example", "--host overrides")
cli.main(["flash", "--serial", "/dev/ttyUSB1", "x.bin"])
check(calls[-1] == ("serial", "/dev/ttyUSB1", "x.bin"), "flash --serial")
cli.main(["backup", "--serial", "/dev/ttyUSB1", "b.bin"])
check(calls[-1] == ("backup", "/dev/ttyUSB1", "b.bin"), "backup --serial")
for argv in (["flash", "x.bin"], ["flash", "--ota", "--serial", "p", "x.bin"], ["backup", "b.bin"]):
    try:
        cli.main(argv)
        check(False, f"{argv} is rejected")
    except SystemExit as e:
        check(e.code == 2, f"{argv} is rejected")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
