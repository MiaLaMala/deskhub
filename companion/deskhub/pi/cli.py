"""deskhub-pi: the Desk Hub companion for Linux (Raspberry Pi) and the CYD display.

    deskhub-pi [run] --config companion.toml [-v]     send data to the display
    deskhub-pi flash --ota firmware.bin               install over Wi-Fi
    deskhub-pi flash --serial /dev/ttyUSB0 firmware.bin
    deskhub-pi backup --serial /dev/ttyUSB0 backup.bin
"""
import argparse
import asyncio
import logging
import pathlib
import sys
import tomllib


def load_config(arg: str | None) -> dict:
    path = pathlib.Path(arg).expanduser() if arg else None
    if path is None:
        for cand in (pathlib.Path.cwd() / "config.toml", pathlib.Path.home() / ".config" / "deskhub" / "config.toml"):
            if cand.is_file():
                path = cand
                break
    if path is None or not path.is_file():
        sys.exit("Config not found. Copy cyd/companion.example.toml and pass it with --config.")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def _common(ap: argparse.ArgumentParser):
    ap.add_argument("--config", help="config file (TOML)")
    ap.add_argument("-v", "--verbose", action="store_true")


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv.pop(0) if argv and argv[0] in ("run", "flash", "backup") else "run"
    ap = argparse.ArgumentParser(prog=f"deskhub-pi {cmd}".strip(), description=__doc__.splitlines()[0])
    _common(ap)
    if cmd == "flash":
        g = ap.add_mutually_exclusive_group(required=True)
        g.add_argument("--ota", action="store_true", help="over Wi-Fi (host and token from the config)")
        g.add_argument("--serial", metavar="PORT", help="by cable with esptool, e.g. /dev/ttyUSB0")
        ap.add_argument("--host", help="display address, overrides the config")
        ap.add_argument("image", help="app image (firmware.bin from PlatformIO)")
    elif cmd == "backup":
        ap.add_argument("--serial", metavar="PORT", required=True)
        ap.add_argument("file", help="target file for the 4 MB flash image")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("websockets", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    if cmd == "run":
        from .app import PiCompanion

        cfg = load_config(args.config)
        try:
            asyncio.run(PiCompanion(cfg).run())
        except KeyboardInterrupt:
            pass
        return 0

    from . import flash

    if cmd == "backup":
        return 0 if flash.serial_backup(args.serial, pathlib.Path(args.file).expanduser()) else 1
    if args.ota:
        cfg = load_config(args.config)
        hub = cfg.get("hub") or {}
        ok = flash.ota(pathlib.Path(args.image).expanduser(), args.host or hub.get("host") or "deskhub.local",
                       hub.get("token", ""))
    else:
        ok = flash.serial_flash(args.serial, pathlib.Path(args.image).expanduser())
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
