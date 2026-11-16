"""Games that aren't on Steam (Minecraft, emulators, other launchers), shown on the
board like Steam games. Each `[[games]]` block in config.toml names the process to
watch for:

    [[games]]
    name = "Minecraft"
    process = "javaw.exe"        # one name or a list; matched case-insensitively
    match = "minecraft"          # optional: text the command line must contain
    image = "C:/pics/mc.png"     # optional: a local file or an https URL
    launch = "C:/XboxGames/Minecraft Launcher/Content/Minecraft.exe"   # optional

The companion records when each one was last played and for how long in
~/.deskhub/custom_games.json; nothing else is stored or sent anywhere.
"""
import json
import logging
import os
import pathlib
import subprocess
import sys
import time
import zlib

import psutil

from .text import ascii_fold

log = logging.getLogger(__name__)

STATE_FILE = pathlib.Path.home() / ".deskhub" / "custom_games.json"
ID_BASE = 0xC0000000   # above every Steam appid, so the two never collide
SAVE_EVERY_S = 60


def game_id(name: str) -> int:
    """Stable id for a custom game, derived from its name."""
    return ID_BASE | (zlib.crc32(name.strip().lower().encode()) & 0x3FFFFFFF)


def is_custom(appid: int) -> bool:
    return appid >= ID_BASE


def load_games(cfg: dict) -> list[dict]:
    games = []
    for g in cfg.get("games", []) or []:
        name = str(g.get("name", "")).strip()
        procs = g.get("process", [])
        procs = [procs] if isinstance(procs, str) else list(procs)
        procs = [str(p).strip().lower() for p in procs if str(p).strip()]
        if not name or not procs:
            log.warning("custom game %r needs a name and a process", name or g)
            continue
        games.append({
            "id": game_id(name),
            "name": ascii_fold(name, 40),
            "process": procs,
            "match": str(g.get("match", "")).strip().lower(),
            "image": str(g.get("image", "")).strip(),
            "launch": str(g.get("launch", "")).strip(),
        })
    return games


class CustomGames:
    def __init__(self, games: list[dict], clock=time.time, processes=None, state_file=STATE_FILE):
        self.games = games
        self.by_id = {g["id"]: g for g in games}
        self._clock = clock
        self._processes = processes or _running_processes
        self._state_file = state_file
        self._state = self._load()        # id -> {"last": epoch, "total_s": seconds}
        self._running: int = 0            # id of the custom game running now
        self._start = 0.0
        self._saved_at = 0.0

    def _load(self) -> dict[int, dict]:
        try:
            raw = json.loads(self._state_file.read_text(encoding="utf-8"))
            return {int(k): {"last": int(v.get("last", 0)), "total_s": int(v.get("total_s", 0))}
                    for k, v in raw.items()}
        except (OSError, ValueError, AttributeError):
            return {}

    def _save(self):
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps({str(k): v for k, v in self._state.items()}),
                                        encoding="utf-8")
        except OSError as e:
            log.debug("could not save custom games: %s", e)
        self._saved_at = self._clock()

    def _find_running(self) -> int:
        wanted = {p for g in self.games for p in g["process"]}
        if not wanted:
            return 0
        for name, cmdline in self._processes(wanted):
            for g in self.games:
                if name in g["process"] and (not g["match"] or g["match"] in cmdline()):
                    return g["id"]
        return 0

    def poll(self) -> dict | None:
        """Track the running custom game. Returns it (with session_s and total_min)
        or None. Blocking (lists processes); call from a thread."""
        if not self.games:
            return None
        now = self._clock()
        running = self._find_running()
        if running != self._running:
            if self._running:
                self._stop(now)
            self._running, self._start = running, now
            if running:
                log.info("custom game started: %s", self.by_id[running]["name"])
        if not running:
            return None
        st = self._state.setdefault(running, {"last": 0, "total_s": 0})
        st["last"] = int(now)
        if now - self._saved_at >= SAVE_EVERY_S:
            self._save()
        g = self.by_id[running]
        session = max(0, int(now - self._start))
        return {"appid": running, "name": g["name"], "session_s": session,
                "total_min": (st["total_s"] + session) // 60}

    def _stop(self, now: float):
        st = self._state.setdefault(self._running, {"last": 0, "total_s": 0})
        st["total_s"] += max(0, int(now - self._start))
        st["last"] = int(now)
        self._save()

    def recent(self) -> list[dict]:
        """Configured games played before, newest first, in the shape of Steam's recent list."""
        out = []
        for g in self.games:
            st = self._state.get(g["id"])
            if st and st["last"] > 0:
                out.append({"appid": g["id"], "name": g["name"], "last": st["last"],
                            "total_min": st["total_s"] // 60})
        return sorted(out, key=lambda x: -x["last"])

    def image_bytes(self, appid: int) -> bytes | None:
        g = self.by_id.get(appid)
        src = g and g["image"]
        if not src:
            return None
        try:
            if src.startswith(("http://", "https://")):
                import httpx

                r = httpx.get(src, timeout=15, follow_redirects=True)
                r.raise_for_status()
                return r.content
            return pathlib.Path(os.path.expandvars(os.path.expanduser(src))).read_bytes()
        except Exception as e:  # missing file, network
            log.warning("custom game %r: image %s: %s", g["name"], src, e)
            return None

    def launch(self, appid: int) -> bool:
        g = self.by_id.get(appid)
        if not g or not g["launch"]:
            log.warning("custom game %s has nothing to launch", appid)
            return False
        target = os.path.expandvars(os.path.expanduser(g["launch"]))
        log.info("launching custom game %r: %s", g["name"], target)
        if "://" in target or os.path.exists(target):
            os.startfile(target)
        else:
            flags = subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
            subprocess.Popen(target, shell=True, creationflags=flags)
        return True


def _running_processes(wanted: set[str]):
    """(lower-case process name, lazy command line) for processes named in `wanted`."""
    for p in psutil.process_iter(["name"]):
        name = (p.info.get("name") or "").lower()
        if name in wanted:
            def cmdline(p=p):
                try:
                    return " ".join(p.cmdline()).lower()
                except (psutil.Error, OSError):
                    return ""
            yield name, cmdline
