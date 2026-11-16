"""The Steam game you are playing and your recent games, from Steam's local files.

Only local files and the registry are read. Cover art comes from Steam's public CDN and
names of games that are no longer installed from the public Store API; both are looked
up by appid alone and cached under ~/.deskhub.
"""
import io
import json
import logging
import os
import pathlib
import struct
import time

import httpx
from PIL import Image

from .custom_games import is_custom
from .text import ascii_fold

log = logging.getLogger(__name__)

CACHE_S = 60
RECENT_MAX = 5
RETRY_ART_S = 300
CDN = "https://cdn.cloudflare.steamstatic.com/steam/apps"
STORE_API = "https://store.steampowered.com/api/appdetails"
ART_DIR = pathlib.Path.home() / ".deskhub" / "steam_art"
NAMES_FILE = pathlib.Path.home() / ".deskhub" / "steam_names.json"

KIND_HEADER, KIND_THUMB, KIND_PORTRAIT = 0, 1, 2
# The Home thumbnail is a small portrait cover (2:3), shown at the card's full height.
KIND_SIZES = {KIND_HEADER: (340, 159), KIND_THUMB: (64, 96), KIND_PORTRAIT: (96, 144)}
_TALL = (KIND_THUMB, KIND_PORTRAIT)

_SKIP_IDS = {228980}
_SKIP_WORDS = ("redistributable", "proton", "steam linux runtime", "steamworks")


# ---- VDF (KeyValues text) ----------------------------------------------------

def parse_vdf(text: str) -> dict:
    """Tolerant parser: quoted or bare tokens, nested braces, // comments, escapes.
    Returns nested dicts; a repeated key keeps its last value."""
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c in " \t\r\n﻿":
            i += 1
        elif c == "/" and text[i:i + 2] == "//":
            while i < n and text[i] != "\n":
                i += 1
        elif c in "{}":
            tokens.append((c, False))
            i += 1
        elif c == '"':
            i += 1
            buf = []
            while i < n and text[i] != '"':
                if text[i] == "\\" and i + 1 < n:
                    buf.append({"n": "\n", "t": "\t"}.get(text[i + 1], text[i + 1]))
                    i += 2
                else:
                    buf.append(text[i])
                    i += 1
            i += 1
            tokens.append(("".join(buf), True))
        else:
            j = i
            while j < n and text[j] not in " \t\r\n{}\"":
                j += 1
            tokens.append((text[i:j], True))
            i = j

    pos = 0

    def block() -> dict:
        nonlocal pos
        out = {}
        while pos < len(tokens):
            tok, is_str = tokens[pos]
            if tok == "}" and not is_str:
                pos += 1
                return out
            if tok == "{" and not is_str:  # stray brace
                pos += 1
                continue
            key = tok
            pos += 1
            if pos >= len(tokens):
                break
            nxt, nxt_str = tokens[pos]
            if nxt == "{" and not nxt_str:
                pos += 1
                out[key] = block()
            elif nxt == "}" and not nxt_str:
                continue  # key without a value; the brace closes this block
            else:
                out[key] = nxt
                pos += 1
        return out

    return block()


def _get(d, *path):
    """Case-insensitive descent through nested dicts; {} when something is missing."""
    for key in path:
        if not isinstance(d, dict):
            return {}
        hit = next((v for k, v in d.items() if k.lower() == key.lower()), None)
        if hit is None:
            return {}
        d = hit
    return d


def _int(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ---- Windows registry / install detection ------------------------------------

def read_registry() -> tuple[str | None, int]:
    """(SteamPath, RunningAppID) from HKCU; (None, 0) when Steam isn't installed."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
            try:
                path = winreg.QueryValueEx(k, "SteamPath")[0]
            except OSError:
                path = None
            try:
                running = int(winreg.QueryValueEx(k, "RunningAppID")[0])
            except (OSError, ValueError):
                running = 0
        return path, running
    except (ImportError, OSError):
        return None, 0


def steam_installed() -> bool:
    path, _ = read_registry()
    return bool(path) and pathlib.Path(path).is_dir()


# ---- pixels ------------------------------------------------------------------

def _pack565(im: Image.Image) -> bytes:
    px = im.convert("RGB").tobytes()
    out = bytearray(len(px) // 3 * 2)
    j = 0
    for i in range(0, len(px), 3):
        v = ((px[i] & 0xF8) << 8) | ((px[i + 1] & 0xFC) << 3) | (px[i + 2] >> 3)
        out[j] = v & 0xFF
        out[j + 1] = v >> 8
        j += 2
    return bytes(out)


def _crop_to(im: Image.Image, aspect: float) -> Image.Image:
    """Centre crop to width/height = aspect (custom game images can be any shape)."""
    iw, ih = im.size
    if iw / ih > aspect:
        cw = round(ih * aspect)
        return im.crop(((iw - cw) // 2, 0, (iw - cw) // 2 + cw, ih))
    ch = round(iw / aspect)
    return im.crop((0, (ih - ch) // 2, iw, (ih - ch) // 2 + ch))


def build_frame(appid: int, kind: int, header: bytes | None, portrait: bytes | None) -> bytes:
    """STM1 frame for one (appid, kind) from the raw header / portrait JPEG bytes."""
    w, h = KIND_SIZES[kind]
    if kind in _TALL and portrait:
        im = Image.open(io.BytesIO(portrait)).convert("RGB")
    elif kind in _TALL:
        im = Image.open(io.BytesIO(header)).convert("RGB")
        iw, ih = im.size
        cw = min(iw, round(ih * 2 / 3))
        im = im.crop(((iw - cw) // 2, 0, (iw + cw) // 2, ih))
    else:
        im = Image.open(io.BytesIO(header)).convert("RGB")
    im = _crop_to(im, w / h)
    im = im.resize((w, h), Image.LANCZOS)
    return b"STM1" + struct.pack("<IHHHH", appid, w, h, kind, 0) + _pack565(im)


# ---- the service ---------------------------------------------------------------

class Steam:
    def __init__(self, clock=time.time, custom=None, use_steam=True, web=None):
        self._clock = clock
        self.web = web            # steam_web.SteamWeb with your API key, or None
        self.account_id = 0       # Steam account of the newest userdata folder
        self.use_steam = use_steam  # False: only the custom games
        self.custom = custom  # custom_games.CustomGames, or None
        self._run_appid = 0
        self._run_start = 0.0
        self._cache_at = -1e9
        self._installed: dict[int, str] = {}
        self._apps: dict[int, dict] = {}
        self._names: dict[int, str] | None = None
        self._mem_names: dict[int, str] = {}
        self._snap: dict = {"type": "steam", "found": False, "playing": None, "recent": []}
        self._frames: dict[tuple[int, int], bytes] = {}
        self._sent: set[tuple[int, int]] = set()
        self._art_fail: dict[tuple[int, int], float] = {}

    # -- local data

    def _libraries(self, root: pathlib.Path) -> list[pathlib.Path]:
        libs = [root]
        try:
            vdf = parse_vdf((root / "steamapps" / "libraryfolders.vdf").read_text(
                encoding="utf-8", errors="replace"))
            for entry in _get(vdf, "libraryfolders").values():
                if isinstance(entry, dict) and entry.get("path"):
                    libs.append(pathlib.Path(entry["path"]))
                elif isinstance(entry, str) and entry.strip():
                    libs.append(pathlib.Path(entry))
        except OSError as e:
            log.debug("libraryfolders.vdf: %s", e)
        seen, out = set(), []
        for p in libs:
            key = os.path.normcase(os.path.abspath(p))
            if key not in seen:
                seen.add(key)
                out.append(p)
        return out

    def _refresh(self, root: pathlib.Path):
        now = self._clock()
        if now - self._cache_at < CACHE_S:
            return
        self._cache_at = now
        installed = {}
        for lib in self._libraries(root):
            try:
                manifests = list((lib / "steamapps").glob("appmanifest_*.acf"))
            except OSError:
                continue
            for m in manifests:
                try:
                    state = _get(parse_vdf(m.read_text(encoding="utf-8", errors="replace")), "AppState")
                except OSError:
                    continue
                appid, name = _int(state.get("appid")), state.get("name")
                if appid and name:
                    installed[appid] = name
        self._installed = installed

        apps = {}
        configs = []
        for p in (root / "userdata").glob("*/config/localconfig.vdf"):
            try:
                configs.append((p.stat().st_mtime, p))
            except OSError:
                pass
        if configs:
            newest = max(configs, key=lambda t: t[0])[1]
            folder = newest.parent.parent.name
            self.account_id = int(folder) if folder.isdigit() else 0
            try:
                cfg = parse_vdf(newest.read_text(encoding="utf-8", errors="replace"))
                raw = _get(cfg, "UserLocalConfigStore", "Software", "Valve", "Steam", "apps")
                for k, v in raw.items():
                    if isinstance(v, dict) and k.isdigit():
                        apps[int(k)] = {"last": _int(v.get("LastPlayed")),
                                        "total_min": _int(v.get("Playtime"))}
            except OSError as e:
                log.debug("localconfig.vdf: %s", e)
        self._apps = apps

    # -- names

    def _store_name(self, appid: int) -> str:
        if self._names is None:
            try:
                self._names = {int(k): v for k, v in json.loads(
                    NAMES_FILE.read_text(encoding="utf-8")).items()}
            except (OSError, ValueError):
                self._names = {}
        if appid in self._names:
            return self._names[appid]
        if appid in self._mem_names:
            return self._mem_names[appid]
        name = None
        try:
            r = httpx.get(STORE_API, params={"appids": appid, "filters": "basic"}, timeout=10)
            r.raise_for_status()
            name = r.json()[str(appid)]["data"]["name"]
        except Exception as e:  # network, bad JSON, delisted app
            log.debug("store name for %s failed: %s", appid, e)
        if name:
            self._names[appid] = name
            try:
                NAMES_FILE.parent.mkdir(parents=True, exist_ok=True)
                NAMES_FILE.write_text(json.dumps({str(k): v for k, v in self._names.items()}),
                                      encoding="utf-8")
            except OSError as e:
                log.debug("could not save names: %s", e)
            return name
        self._mem_names[appid] = f"App {appid}"
        return self._mem_names[appid]

    def _name(self, appid: int) -> str:
        return self._installed.get(appid) or self._store_name(appid)

    @staticmethod
    def _is_game(appid: int, name: str) -> bool:
        low = name.lower()
        return appid not in _SKIP_IDS and not any(w in low for w in _SKIP_WORDS)

    # -- snapshot

    def snapshot(self) -> dict:
        """Steam's playing game and recent games, merged with the custom games from
        config.toml (a running Steam game wins over a custom one)."""
        path, running = read_registry()
        steam_ok = self.use_steam and bool(path) and pathlib.Path(path).is_dir()
        custom_now = self.custom.poll() if self.custom else None
        playing, recent = None, []
        if steam_ok:
            playing, recent = self._steam_part(pathlib.Path(path), running)
        if playing is None and custom_now:
            playing = custom_now
        if self.custom:
            skip = playing["appid"] if playing else None
            recent += [g for g in self.custom.recent() if g["appid"] != skip]
            recent = sorted(recent, key=lambda g: -g["last"])[:RECENT_MAX]
        found = steam_ok or bool(self.custom and self.custom.games)
        friends = []
        if self.web and steam_ok and self.account_id:
            from .steam_web import steamid64

            sid = steamid64(self.account_id)
            minutes = self.web.playtimes(sid)
            for g in ([playing] if playing else []) + recent:
                if g["appid"] in minutes:  # the Web API knows every game's total
                    g["total_min"] = max(g["total_min"], minutes[g["appid"]])
            friends = self.web.friends_in_game(sid)
        self._snap = {"type": "steam", "found": found, "playing": playing, "recent": recent,
                      "friends": friends}
        return self._snap

    def _steam_part(self, root: pathlib.Path, running: int) -> tuple[dict | None, list[dict]]:
        self._refresh(root)
        now = self._clock()
        if running != self._run_appid:
            self._run_appid = running
            self._run_start = now

        playing = None
        if running:
            name = self._name(running)
            if self._is_game(running, name):
                info = self._apps.get(running, {})
                playing = {"appid": running, "name": ascii_fold(name, 40),
                           "session_s": max(0, int(now - self._run_start)),
                           "total_min": info.get("total_min", 0)}
        else:
            self._run_start = now

        recent = []
        for appid, info in sorted(self._apps.items(), key=lambda kv: kv[1]["last"], reverse=True):
            if len(recent) >= RECENT_MAX:
                break
            if info["last"] <= 0 or appid == running or appid in _SKIP_IDS:
                continue
            name = self._name(appid)
            if not self._is_game(appid, name):
                continue
            recent.append({"appid": appid, "name": ascii_fold(name, 40),
                           "last": info["last"], "total_min": info["total_min"]})
        return playing, recent

    # -- art

    @staticmethod
    def _store_header_url(appid: int) -> str | None:
        try:
            r = httpx.get(STORE_API, params={"appids": appid, "filters": "basic"}, timeout=10)
            r.raise_for_status()
            return r.json()[str(appid)]["data"].get("header_image")
        except Exception as e:  # network, bad JSON, delisted app
            log.debug("store header for %s failed: %s", appid, e)
            return None

    def _fetch_art(self, appid: int, portrait: bool) -> bytes | None:
        """Raw JPEG from the disk cache or the CDN; None when unavailable."""
        stem = f"{appid}_{'portrait' if portrait else 'header'}"
        jpg, none = ART_DIR / f"{stem}.jpg", ART_DIR / f"{stem}.none"
        try:
            if jpg.is_file():
                return jpg.read_bytes()
            if portrait and none.is_file():
                return None
        except OSError:
            pass
        url = f"{CDN}/{appid}/{'library_600x900.jpg' if portrait else 'header.jpg'}"
        try:
            r = httpx.get(url, timeout=15, follow_redirects=True)
            if r.status_code == 404 and not portrait:
                # Newer games keep their art under a hashed path; the Store API knows it.
                alt = self._store_header_url(appid)
                if alt:
                    url = alt
                    r = httpx.get(url, timeout=15, follow_redirects=True)
            if r.status_code == 404 and portrait:
                ART_DIR.mkdir(parents=True, exist_ok=True)
                none.write_bytes(b"")
                return None
            r.raise_for_status()
            ART_DIR.mkdir(parents=True, exist_ok=True)
            jpg.write_bytes(r.content)
            return r.content
        except (httpx.HTTPError, OSError) as e:
            log.debug("art %s failed: %s", url, e)
            return None

    def _wanted(self) -> list[tuple[int, int]]:
        snap = self._snap
        if not snap.get("found"):
            return []
        keys = []
        playing, recent = snap["playing"], snap["recent"]
        if playing:
            keys += [(playing["appid"], KIND_HEADER), (playing["appid"], KIND_THUMB)]
        elif recent:
            keys.append((recent[0]["appid"], KIND_THUMB))
        keys += [(g["appid"], KIND_PORTRAIT) for g in recent]
        return keys

    def _build(self, key: tuple[int, int]) -> bytes | None:
        appid, kind = key
        if is_custom(appid):
            image = self.custom.image_bytes(appid) if self.custom else None
            if not image:
                return None  # the board shows its placeholder
            header, portrait = image, None
        elif kind in _TALL:
            portrait = self._fetch_art(appid, True)
            header = None if portrait else self._fetch_art(appid, False)
            if not portrait and not header:
                return None
        else:
            header, portrait = self._fetch_art(appid, False), None
            if not header:
                return None
        try:
            return build_frame(appid, kind, header, portrait)
        except Exception as e:  # corrupt image
            log.debug("frame %s failed: %s", key, e)
            return None

    def frames(self, only_changed: bool = True) -> list[bytes]:
        """STM1 frames for the current snapshot: those not sent yet (the default), or all
        of them for a resend after reconnect. Blocking (network); call from a thread."""
        wanted = self._wanted()
        self._frames = {k: v for k, v in self._frames.items() if k in wanted}
        self._sent &= set(wanted)
        out = []
        now = self._clock()
        for key in wanted:
            if key not in self._frames:
                if now - self._art_fail.get(key, -1e9) < RETRY_ART_S:
                    continue
                frame = self._build(key)
                if frame is None:
                    self._art_fail[key] = now
                    continue
                self._frames[key] = frame
            if not only_changed or key not in self._sent:
                self._sent.add(key)
                out.append(self._frames[key])
        return out

    def all_frames(self) -> list[bytes]:
        return self.frames(only_changed=False)

    # -- launch

    def launch(self, appid: int) -> bool:
        playing = self._snap.get("playing")
        allowed = {g["appid"] for g in self._snap.get("recent", [])}
        if playing:
            allowed.add(playing["appid"])
        if appid not in allowed:
            log.warning("steam launch refused for appid %s", appid)
            return False
        if is_custom(appid):
            return bool(self.custom) and self.custom.launch(appid)
        log.info("launching Steam game %s", appid)
        os.startfile(f"steam://rungameid/{appid}")
        return True
