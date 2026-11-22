"""The Linux entry point must import without any Windows or desktop package. Blocks them
(import raises) in a fresh interpreter, then imports every deskhub.pi module and runs
`--help`. Run it inside a venv that has only cyd/companion-requirements.txt to be sure.

    python tests/test_pi_imports.py
"""
import pathlib
import subprocess
import sys

root = pathlib.Path(__file__).resolve().parents[1]
code = r'''
import importlib, sys

BLOCKED = {"win32api", "win32con", "win32gui", "win32com", "pythoncom", "pywintypes", "winsdk", "winrt", "pystray",
           "pynput", "keyring", "icalendar", "recurring_ical_events", "caldav", "PIL", "pynvml", "paho", "serial",
           "tomlkit", "msvcrt", "winreg", "_winapi"}

class Block:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in BLOCKED:
            raise ModuleNotFoundError(f"blocked: {name}")

sys.meta_path.insert(0, Block())
for mod in ("cli", "app", "sources", "flash", "__main__"):
    if mod == "__main__":
        continue
    importlib.import_module("deskhub.pi." + mod)
from deskhub.pi import cli
try:
    cli.main(["--help"])
except SystemExit as e:
    assert e.code == 0
loaded = sorted(m for m in sys.modules if m.split(".")[0] in BLOCKED)
assert not loaded, loaded
print("imported:", sorted(m for m in sys.modules if m.startswith("deskhub.")))
'''
r = subprocess.run([sys.executable, "-c", code], cwd=root, capture_output=True, text=True,
                   env={"PYTHONPATH": str(root), "PATH": "/usr/bin:/bin"})
print(r.stdout[-1500:], r.stderr[-1500:])
print("\nOK" if r.returncode == 0 else "\nPROBLEMS: import check failed")
sys.exit(r.returncode)
