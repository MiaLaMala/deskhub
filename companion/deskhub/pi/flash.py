"""Install firmware on the CYD from the Pi: over Wi-Fi (POST /firmware) or by cable (esptool).

    deskhub-pi flash --ota firmware.bin
    deskhub-pi flash --serial /dev/ttyUSB0 firmware.bin
    deskhub-pi backup --serial /dev/ttyUSB0 sicherung.bin
"""
import pathlib
import subprocess
import sys

from .. import flash_cli

# From the partition table `min_spiffs.csv` (arduino-esp32, board_build.partitions in
# cyd/firmware/platformio.ini):  nvs 0x9000/0x5000, otadata 0xe000/0x2000,
# app0 (ota_0) 0x10000/0x1E0000, app1 (ota_1) 0x1F0000/0x1E0000, spiffs 0x3D0000/0x20000,
# coredump 0x3F0000/0x10000. The app image (PlatformIO's firmware.bin) belongs at app0.
APP_OFFSET = 0x10000
APP_SIZE = 0x1E0000
OTADATA_OFFSET, OTADATA_SIZE = 0xE000, 0x2000
FLASH_SIZE = 0x400000
ESP_IMAGE_MAGIC = 0xE9
BAUD = "460800"


def check_image(path: pathlib.Path) -> str | None:
    """None when the file can be an app image for this board, else what is wrong."""
    if not path.is_file():
        return f"{path} not found"
    data = path.read_bytes()
    if not data or data[0] != ESP_IMAGE_MAGIC:
        return "not an ESP32 app image (first byte is not 0xE9); use PlatformIO's firmware.bin, not a full backup"
    if len(data) > APP_SIZE:
        return f"image is {len(data)} bytes, the app slot holds {APP_SIZE}"
    return None


def esptool_cmd(*args: str) -> list[str]:
    return [sys.executable, "-m", "esptool", *args]


def serial_flash(port: str, image: pathlib.Path, run=subprocess.run) -> bool:
    """Write the app image at the app0 offset (esptool verifies the written data by default), then erase otadata so the
    bootloader starts app0 even if the display last ran from app1 after a Wi-Fi update."""
    bad = check_image(image)
    if bad:
        print(f"Not flashed: {bad}.")
        return False
    r = run(esptool_cmd("--chip", "esp32", "--port", port, "--baud", BAUD, "write_flash",
                        hex(APP_OFFSET), str(image)))
    if r.returncode != 0:
        print("Flashing failed (see above). Is the board in download mode (hold BOOT while plugging in)?")
        return False
    r = run(esptool_cmd("--chip", "esp32", "--port", port, "erase_region", hex(OTADATA_OFFSET), hex(OTADATA_SIZE)))
    if r.returncode != 0:
        print("The image is written, but erasing otadata failed; the display may keep running its old slot.")
        return False
    print("Done. The display restarts with the new firmware (press RESET if it does not).")
    return True


def serial_backup(port: str, target: pathlib.Path, run=subprocess.run) -> bool:
    """Read the whole 4 MB flash into a file (restore: write_flash 0x0 <file>)."""
    if target.exists():
        print(f"Not overwriting {target}.")
        return False
    r = run(esptool_cmd("--chip", "esp32", "--port", port, "--baud", BAUD, "read_flash",
                        "0x0", hex(FLASH_SIZE), str(target)))
    if r.returncode != 0 or not target.is_file() or target.stat().st_size != FLASH_SIZE:
        print("Backup failed (see above); the file may be incomplete.")
        return False
    print(f"Backup written to {target} ({FLASH_SIZE} bytes). Restore: python -m esptool --chip esp32 "
          f"--port {port} write_flash 0x0 {target}")
    return True


def ota(image: pathlib.Path, host: str, token: str, post=None) -> bool:
    bad = check_image(image)
    if bad:
        print(f"Not sent: {bad}.")
        return False
    print(f"Sending {image.name} to {host}. Tap Install on the display (60 s).")
    kwargs = {"post": post} if post else {}
    result = flash_cli.send_over_wifi(image, host, token, **kwargs)
    messages = {
        flash_cli.OK: "Installed. The display restarts; it falls back by itself if no hello arrives within 5 minutes.",
        flash_cli.DENIED: "Not installed: Deny was tapped on the display.",
        flash_cli.NO_ANSWER: "Not installed: nobody tapped Install within a minute. Run it again.",
        flash_cli.UNREACHABLE: f"The display is not reachable at {host}.",
        flash_cli.NO_OTA: "The firmware on the display has no Wi-Fi update; use --serial once.",
        flash_cli.BAD_TOKEN: "The display did not accept the token.",
        flash_cli.FAILED: "The Wi-Fi install failed.",
    }
    print(messages[result])
    return result == flash_cli.OK
