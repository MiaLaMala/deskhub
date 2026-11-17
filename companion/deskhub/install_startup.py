"""Start the companion when you sign in to Windows, hidden (no console window).

    uv run deskhub-install            # add the login shortcut
    uv run deskhub-install --remove   # take it away again

It puts a shortcut in your Startup folder that runs the companion with pythonw,
so no terminal window opens. Its log goes to ~/.deskhub/companion.log.
"""
import argparse
import os
import pathlib
import subprocess
import sys

COMPANION_DIR = pathlib.Path(__file__).resolve().parents[1]
LINK_NAME = "Desk Hub companion.lnk"


def startup_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("APPDATA", pathlib.Path.home() / "AppData/Roaming")) \
        / "Microsoft/Windows/Start Menu/Programs/Startup"


def link_path() -> pathlib.Path:
    return startup_dir() / LINK_NAME


def pythonw() -> pathlib.Path:
    """pythonw.exe next to the Python running this (the project's .venv under uv)."""
    here = pathlib.Path(sys.executable).with_name("pythonw.exe")
    return here if here.is_file() else COMPANION_DIR / ".venv" / "Scripts" / "pythonw.exe"


def installed() -> bool:
    return link_path().is_file()


def install(config: pathlib.Path | None = None) -> pathlib.Path:
    """Create (or refresh) the Startup shortcut. Returns its path."""
    config = (config or COMPANION_DIR / "config.toml").resolve()
    link = link_path()
    link.parent.mkdir(parents=True, exist_ok=True)
    # Paths travel in environment variables, so no quoting games in the script.
    env = {**os.environ, "DH_LINK": str(link), "DH_EXE": str(pythonw()),
           "DH_ARGS": f'-m deskhub --tray --config "{config}"', "DH_DIR": str(COMPANION_DIR)}
    script = ("$s = (New-Object -ComObject WScript.Shell).CreateShortcut($env:DH_LINK); "
              "$s.TargetPath = $env:DH_EXE; $s.Arguments = $env:DH_ARGS; "
              "$s.WorkingDirectory = $env:DH_DIR; $s.Description = 'Desk Hub companion'; "
              "$s.WindowStyle = 7; $s.Save()")
    subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                   env=env, check=True, capture_output=True)
    return link


def remove() -> bool:
    """Delete the shortcut. Returns whether there was one."""
    link = link_path()
    if link.is_file():
        link.unlink()
        return True
    return False


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--remove", action="store_true", help="stop starting with Windows")
    ap.add_argument("--config", help="config.toml to use (default: the companion's)")
    args = ap.parse_args()
    if args.remove:
        print("Removed: the companion no longer starts with Windows." if remove()
              else "The companion wasn't set to start with Windows.")
        return
    if not pythonw().is_file():
        sys.exit(f"pythonw.exe not found at {pythonw()}. Run `uv sync` in {COMPANION_DIR} first.")
    link = install(pathlib.Path(args.config) if args.config else None)
    print(f"Done: the companion starts hidden when you sign in ({link}).\n"
          f"Its log is ~/.deskhub/companion.log. To undo: uv run deskhub-install --remove")


if __name__ == "__main__":
    main()
