"""The Pi companion: polls its sources on their own schedules, keeps the last good message of
each kind, and sends them to the display after cyd/PROTOKOLL.md."""
import asyncio
import json
import logging
import os
import pathlib
import time
from zoneinfo import ZoneInfo

import websockets

from . import sources as src

log = logging.getLogger("deskhub.pi")

ALL_PAGES = ["home", "claude", "calendar", "weather", "timer", "github", "homelab", "net"]
# Which source a page asks for when the display switches to it.
PAGE_SOURCES = {"home": ["ai", "events", "weather", "homelab"], "claude": ["ai"], "calendar": ["events"],
                "weather": ["weather"], "github": ["github"], "homelab": ["homelab"], "net": ["net"]}
INTERVALS = {"ai": 60, "events": 120, "homelab": 120, "weather": 900, "github": 3600, "time": 600, "net": 5}
RETRY_MAX_S = 600          # a failed source is asked again after min(its interval, this)
MIN_GAP_S = 15             # the display's page/refresh never makes a source fetch more often than this
BACKOFF_START_S, BACKOFF_MAX_S = 1, 60


def read_secret(value: str = "", file: str = "", env: str = "") -> str:
    """A secret from the environment, else from a file (never from the config text itself
    unless `value` is given). Whitespace and quotes are stripped."""
    if env and os.environ.get(env):
        return os.environ[env].strip()
    if file:
        try:
            return pathlib.Path(file).expanduser().read_text(encoding="utf-8").strip().strip("\"'")
        except OSError as e:
            log.warning("secret file %s unreadable: %s", file, e.__class__.__name__)
    return value.strip()


def page_list(cfg: dict) -> list[str]:
    """Pages for the navigation bar: [pages] enabled if given, else every page whose source is
    configured. `home` is always there."""
    explicit = (cfg.get("pages") or {}).get("enabled")
    if isinstance(explicit, list):
        pages = [p for p in dict.fromkeys(str(p).lower() for p in explicit) if p in ALL_PAGES and p != "home"]
        return ["home"] + pages
    has = {"claude": bool((cfg.get("claude") or {}).get("url")),
           "calendar": bool((cfg.get("miaos") or {}).get("url")),
           "homelab": bool((cfg.get("miaos") or {}).get("url")),
           "weather": "latitude" in (cfg.get("weather") or {}),
           "github": bool((cfg.get("github") or {}).get("user") or os.environ.get("DESKHUB_GITHUB_TOKEN")
                          or (cfg.get("github") or {}).get("token_file"))}
    return [p for p in ALL_PAGES if p == "home" or has.get(p, True)]


def layout_message(cfg: dict) -> dict:
    return {"type": "layout", "pages": page_list(cfg)}


class Source:
    def __init__(self, name: str, interval: float, fetch, on_error=None):
        self.name, self.interval, self.fetch, self.on_error = name, interval, fetch, on_error
        self.next_at = 0.0       # monotonic time of the next scheduled fetch
        self.last_try = -1e9
        self.kick = asyncio.Event()


class PiCompanion:
    def __init__(self, cfg: dict, clock=time.time, mono=time.monotonic, sources: list[Source] | None = None):
        self.cfg = cfg
        hub = cfg.get("hub") or {}
        self.host = hub.get("host") or "deskhub.local"
        self.token = hub.get("token", "")
        self.clock, self.mono = clock, mono
        iv = {**INTERVALS, **{k: float(v) for k, v in (cfg.get("intervals") or {}).items()}}
        self.intervals = iv
        self.ws = None
        self.cache: dict[str, dict] = {}     # last good message per type, resent after a reconnect
        self.sources = sources if sources is not None else self.build_sources(iv)
        self.hello_count = 0

    # ---- wiring ---------------------------------------------------------------------------

    def build_sources(self, iv: dict) -> list[Source]:
        cfg, out = self.cfg, []
        tz = ZoneInfo((cfg.get("miaos") or {}).get("timezone") or "Europe/Berlin")
        c = cfg.get("claude") or {}
        if c.get("url"):
            key = read_secret(c.get("key", ""), c.get("key_file", ""), "KONTINGENT_KEY")
            if not key:
                log.warning("[claude] url is set but no key (env KONTINGENT_KEY or key_file); page stays empty")
            else:
                hist = src.History(c.get("history_file", "~/.deskhub/claude_history.json"), self.clock)

                def fetch_ai(url=c["url"], key=key, hist=hist):
                    limits = src.fetch_kontingent(url, key, clock=self.clock)
                    if limits is None:
                        raise ValueError("quota answer without a usable window")
                    if "seven_day" in limits:
                        hist.add(limits["seven_day"]["pct"])
                    return src.ai_message(limits, hist.sent())
                out.append(Source("ai", iv["ai"], fetch_ai))
        m = cfg.get("miaos") or {}
        if m.get("url"):
            days = int(m.get("days", 7))
            skip = m.get("skip_calendars", [])
            out.append(Source("events", iv["events"],
                              lambda: src.fetch_events(m["url"], days, tz, skip, clock=self.clock)))
            lab = src.Homelab(self.clock)
            out.append(Source("homelab", iv["homelab"], lambda: lab.fetch(m["url"]), on_error=lab.failed))
        w = cfg.get("weather") or {}
        if "latitude" in w and "longitude" in w:
            out.append(Source("weather", iv["weather"], lambda: src.fetch_weather(
                float(w["latitude"]), float(w["longitude"]), w.get("place", ""), w.get("timezone", "Europe/Berlin"),
                clock=self.clock)))
        g = cfg.get("github") or {}
        token = read_secret("", g.get("token_file", ""), "DESKHUB_GITHUB_TOKEN")
        if g.get("user") or token:
            out.append(Source("github", iv["github"], lambda: src.fetch_github(g.get("user", ""), token)))
        out.append(self.net_source(iv["net"]))
        return out

    def net_source(self, interval: float) -> Source:
        from ..netstats import NetStats

        n = self.cfg.get("net") or {}
        state = pathlib.Path(n.get("state_file", "~/.deskhub/net_usage.json")).expanduser()
        iface = n.get("interface", "")

        def counters():
            import psutil

            if iface:
                return psutil.net_io_counters(pernic=True)[iface]
            per = psutil.net_io_counters(pernic=True)
            tot = type("T", (), {"bytes_sent": 0, "bytes_recv": 0})()
            for name, c in per.items():
                if name != "lo":
                    tot.bytes_sent += c.bytes_sent
                    tot.bytes_recv += c.bytes_recv
            return tot

        stats = NetStats(clock=self.clock, counters=counters, state_file=state)
        stats.speed = None      # no speed test on the Pi: it would load the line the display shares

        def fetch():
            stats.tick()
            return stats.message()
        return Source("net", interval, fetch)

    # ---- sending --------------------------------------------------------------------------

    async def send(self, msg: dict, remember: bool = True):
        if remember and msg.get("type") not in ("hello", "time"):
            self.cache[msg["type"]] = msg
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.send(json.dumps(msg, separators=(",", ":")))
        except websockets.WebSocketException as e:
            log.info("send failed (%s); the session loop reconnects", e.__class__.__name__)

    async def run_source(self, s: Source):
        """Fetch now if due, send the result; on failure keep the last state (a homelab source
        sends ok:false instead) and try again sooner than the normal interval."""
        s.last_try = self.mono()
        try:
            msg = await asyncio.to_thread(s.fetch)
        except Exception as e:      # network, HTTP status, bad JSON: never log URLs or answers
            status = getattr(getattr(e, "response", None), "status_code", None)
            log.warning("source %s failed: %s %s", s.name, e.__class__.__name__, status or "")
            s.next_at = self.mono() + min(s.interval, RETRY_MAX_S)
            if s.on_error:
                await self.send(s.on_error())
            return
        s.next_at = self.mono() + s.interval
        if msg:
            await self.send(msg)

    async def source_loop(self, s: Source):
        while True:
            wait = s.next_at - self.mono()
            if wait > 0:
                try:
                    await asyncio.wait_for(s.kick.wait(), wait)
                except asyncio.TimeoutError:
                    pass
            s.kick.clear()
            await self.run_source(s)

    async def time_loop(self):
        while True:
            await asyncio.sleep(self.intervals["time"])
            await self.send({"type": "time", "unix": self.clock()}, remember=False)

    def kick(self, names):
        """The display looked at a page: send what we have, and refresh a source unless it
        was fetched within the last MIN_GAP_S seconds."""
        now = self.mono()
        for s in self.sources:
            if s.name in names and now - s.last_try >= MIN_GAP_S:
                s.next_at = 0
                s.kick.set()

    async def on_message(self, raw):
        try:
            m = json.loads(raw)
        except (ValueError, TypeError):
            return
        if not isinstance(m, dict):
            return
        kind = m.get("type")
        if kind == "page":
            names = PAGE_SOURCES.get(str(m.get("name", "")), [])
        elif kind == "refresh":
            names = [s.name for s in self.sources]
        else:
            return
        types = {"ai": "ai", "events": "events", "weather": "weather", "homelab": "homelab", "github": "github",
                 "net": "net"}
        for n in names:                              # what we have goes out at once
            if types[n] in self.cache:
                await self.send(self.cache[types[n]], remember=False)
        self.kick(names)

    # ---- connection -----------------------------------------------------------------------

    async def session(self):
        async with websockets.connect(f"ws://{self.host}/ws", max_size=2**20, ping_interval=10,
                                      ping_timeout=10, open_timeout=10) as ws:
            await ws.send(json.dumps({"type": "hello", "token": self.token}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if reply.get("type") != "hello_ok":
                raise RuntimeError("display refused hello")
            log.info("connected (firmware %s, board %s)", reply.get("version", "?"), reply.get("board", "?"))
            self.hello_count += 1
            self.ws = ws
            await self.send({"type": "time", "unix": self.clock()}, remember=False)
            await self.send(layout_message(self.cfg))
            for kind in ("events", "ai", "weather", "homelab", "github", "net"):
                if kind in self.cache:
                    await self.send(self.cache[kind], remember=False)
            async for raw in ws:
                if isinstance(raw, str):
                    await self.on_message(raw)

    async def run(self, stop: asyncio.Event | None = None):
        tasks = [asyncio.create_task(self.source_loop(s)) for s in self.sources]
        tasks.append(asyncio.create_task(self.time_loop()))
        delay = BACKOFF_START_S
        try:
            while not (stop and stop.is_set()):
                before = self.hello_count
                try:
                    await self.session()
                except (OSError, asyncio.TimeoutError, websockets.WebSocketException, RuntimeError, ValueError) as e:
                    log.info("display %s not reachable (%s), retrying in %ds", self.host, e.__class__.__name__, delay)
                finally:
                    self.ws = None
                delay = BACKOFF_START_S if self.hello_count > before else min(delay * 2, BACKOFF_MAX_S)
                await asyncio.sleep(delay)
        finally:
            for t in tasks:
                t.cancel()
