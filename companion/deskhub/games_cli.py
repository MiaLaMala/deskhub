"""Add games that aren't on Steam (Minecraft, emulators, other launchers) to the board.

    uv run deskhub-games [--config path/to/config.toml] [list|add|remove]

`add` lists the programs that have a window open right now, so start the game first
and pick it from the list (or type its details by hand).
"""
import argparse
import os
import pathlib
import re

import psutil
import tomlkit

from .__main__ import find_config
from .calendars_cli import ask, load, write
from .custom_games import _window_titles

# Programs that run many different apps, so a window title tells them apart better.
GENERIC = {"java.exe", "javaw.exe", "python.exe", "pythonw.exe", "electron.exe", "node.exe",
           "dosbox.exe", "retroarch.exe", "wine.exe", "mono.exe"}
# Windows that are never games.
SKIP = {"explorer.exe", "applicationframehost.exe", "textinputhost.exe", "systemsettings.exe",
        "shellexperiencehost.exe", "searchhost.exe", "startmenuexperiencehost.exe",
        "windowsterminal.exe", "conhost.exe", "taskmgr.exe", "lockapp.exe"}
_VERSION = re.compile(r"[\s\-:]*v?\d+(\.\d+)+\S*$")


def games_of(doc) -> tomlkit.items.AoT:
    if "games" not in doc:
        doc["games"] = tomlkit.aot()
    return doc["games"]


def open_windows(windows=None) -> list[dict]:
    """Programs with a visible titled window: [{"title", "process", "exe"}], one per window."""
    out, seen = [], set()
    for pid, title, name in (windows or _window_titles)():
        proc = name()
        if not proc or proc in SKIP or not title.strip() or (proc, title) in seen:
            continue
        seen.add((proc, title))
        try:
            exe = psutil.Process(pid).exe()
        except (psutil.Error, OSError):
            exe = ""
        out.append({"title": title.strip(), "process": proc, "exe": exe})
    return sorted(out, key=lambda w: (w["process"], w["title"].lower()))


def suggest(win: dict) -> dict:
    """A [[games]] entry for a picked window: match the title for generic programs
    (java.exe runs every Java game), the process otherwise."""
    name = _VERSION.sub("", win["title"]).strip() or win["title"]
    if win["process"] in GENERIC:
        procs = ["java.exe", "javaw.exe"] if win["process"] in ("java.exe", "javaw.exe") else [win["process"]]
        return {"name": name, "title": name, "process": procs, "launch": ""}
    return {"name": name, "process": win["process"], "launch": win["exe"]}


def describe(g) -> str:
    how = []
    if g.get("title"):
        how.append(f'title "{g["title"]}"')
    procs = g.get("process")
    if procs:
        how.append(", ".join(procs) if isinstance(procs, list) else str(procs))
    if g.get("match"):
        how.append(f'command line has "{g["match"]}"')
    extra = []
    if g.get("image"):
        extra.append("image")
    if g.get("launch"):
        extra.append("launch")
    return f'{g.get("name", "?")}: {"; ".join(how)}' + (f'  ({", ".join(extra)})' if extra else "")


def _ensure_page(doc):
    """With an explicit [pages] list, the Games page must be in it to show up."""
    pages = doc.get("pages")
    enabled = pages.get("enabled") if pages is not None else None
    if enabled is not None and "games" not in enabled:
        enabled.append("games")
        print('Added "games" to [pages] enabled so the page shows.')


def cmd_list(path: pathlib.Path):
    doc = load(path)
    games = doc.get("games") or []
    if not games:
        print("No custom games yet. Add one with `uv run deskhub-games add`.")
        return
    for i, g in enumerate(games, 1):
        print(f"  {i}. {describe(g)}")


def _pick_window(windows=None) -> dict | None:
    wins = open_windows(windows)
    print("\nStart the game first, so its window is open. Programs with a window open now:")
    for i, w in enumerate(wins, 1):
        print(f"  {i}. {w['title'][:60]}  ({w['process']})")
    print("  0. Not listed: type the details myself")
    while True:
        choice = ask(f"Choose 0-{len(wins)}, or empty to cancel")
        if not choice:
            return None
        if choice.isdigit() and int(choice) <= len(wins):
            return wins[int(choice) - 1] if int(choice) else {}
        print("  Type a number from the list.")


def cmd_add(path: pathlib.Path, windows=None):
    picked = _pick_window(windows)
    if picked is None:
        return
    entry = suggest(picked) if picked else {"name": "", "process": "", "launch": ""}
    print()
    name = ask("Name to show on the board", entry["name"])
    if not name:
        print("A name is needed.")
        return
    row = tomlkit.table()
    row["name"] = name
    if picked and "title" in entry:
        print(f'{picked["process"]} runs many programs, so the game is recognised by its window title.')
        title = ask("Text the window title contains", entry["title"])
        row["title"] = title
        row["process"] = entry["process"]
    else:
        proc = ask("Program file name (Task Manager > Details)", entry.get("process", ""))
        title = "" if picked else ask("Or text in its window title (optional)")
        if not proc and not title:
            print("A program name or a window title is needed.")
            return
        if proc:
            row["process"] = proc
        if title:
            row["title"] = title
    image = ask("Cover picture: a file path or https URL (optional)")
    if image:
        image = image.strip('"')
        if not image.startswith(("http://", "https://")) and not os.path.isfile(os.path.expanduser(image)):
            print("  That file doesn't exist; added anyway, fix it in config.toml if needed.")
        row["image"] = image.replace("\\", "/")
    launch = ask("What tapping it on the board opens: a program, shortcut or URL (optional)",
                 entry.get("launch", ""))
    if launch:
        row["launch"] = launch.strip('"').replace("\\", "/")

    doc = load(path)
    games = games_of(doc)
    if any(str(g.get("name", "")).lower() == name.lower() for g in games):
        print(f'"{name}" is already configured. Remove it first to change it.')
        return
    games.append(row)
    _ensure_page(doc)
    write(path, doc)
    print(f"Added {describe(row)}.\nRestart the companion to pick it up.")


def cmd_remove(path: pathlib.Path):
    doc = load(path)
    games = doc.get("games") or []
    if not games:
        print("No custom games to remove.")
        return
    for i, g in enumerate(games, 1):
        print(f"  {i}. {describe(g)}")
    choice = ask(f"Remove which (1-{len(games)}), or empty to cancel")
    if choice.isdigit() and 1 <= int(choice) <= len(games):
        gone = games[int(choice) - 1].get("name")
        del games[int(choice) - 1]
        if not games:
            del doc["games"]
        write(path, doc)
        print(f"Removed {gone}. Restart the companion to pick it up.")


COMMANDS = {"list": cmd_list, "add": cmd_add, "remove": cmd_remove}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config")
    ap.add_argument("command", nargs="?", choices=list(COMMANDS))
    args = ap.parse_args()
    path = find_config(args.config)
    if args.command:
        COMMANDS[args.command](path)
        return
    menu(path)


def menu(path: pathlib.Path):
    """Interactive custom-games menu; also used by `deskhub-setup`."""
    names = list(COMMANDS)
    labels = ["List custom games", "Add a game (pick its open window)", "Remove a game"]
    while True:
        print(f"\nCustom games in {path}")
        for i, label in enumerate(labels, 1):
            print(f"  {i}. {label}")
        choice = ask(f"Choose 1-{len(labels)}, or empty to quit")
        if not choice:
            return
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            COMMANDS[names[int(choice) - 1]](path)


if __name__ == "__main__":
    main()
