"""Desk hub companion: streams PC data to the hub and runs its commands.

    uv run python -m deskhub [--config path/to/config.toml] [--verbose]
"""
import argparse
import asyncio
import json
import logging
import pathlib
import sys
import tomllib

import websockets

from .calendar_feed import fetch_events
from .claude_alerts import ClaudeAlerts
from .claude_usage import ClaudeUsage
from .codex_usage import CodexUsage, codex_home
from .media import Media
from .pages import enabled_pages, home_message, layout_message
from .printer import PrinterService
from .shortcuts import hub_view, load_tiles, run_tile
from .stats import Stats

log = logging.getLogger("deskhub")

CALENDAR_REFRESH_S = 600
PRINTER_TICK_S = 2
PRINTER_KEEPALIVE_S = 30


def find_config(arg: str | None) -> pathlib.Path:
    candidates = [pathlib.Path(arg)] if arg else [
        pathlib.Path.cwd() / "config.toml",
        pathlib.Path(__file__).resolve().parent.parent / "config.toml",
    ]
    for p in candidates:
        if p.is_file():
            return p
    sys.exit("config.toml not found. Copy config.example.toml to config.toml and edit it.")


def pick_ai(agent: str, claude: dict | None, codex: dict | None) -> dict:
    """The AI page message. "auto" shows whichever agent was active last (Claude on a tie)."""
    if agent == "codex" and codex is not None:
        provider = "codex"
    elif agent == "auto" and codex is not None and claude is not None \
            and codex.get("last_active", 0) > claude.get("last_active", 0):
        provider = "codex"
    elif claude is not None:
        provider = "claude"
    else:
        provider = "codex"
    snap = codex if provider == "codex" else claude
    return {**snap, "type": "ai", "provider": provider}


class Companion:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        hub = cfg.get("hub", {})
        self.url = f"ws://{hub.get('host', 'deskhub.local')}/ws"
        self.token = hub.get("token", "")
        self.stats = Stats()
        self.media = Media()
        self.tiles = load_tiles(cfg)
        self.events: list[dict] = []
        live = None
        if cfg.get("claude", {}).get("live_limits"):
            from .claude_live import LiveLimits
            live = LiveLimits()
            log.info("live Claude limits enabled")
        self.agent = cfg.get("ai", {}).get("agent", "auto")
        if self.agent not in ("auto", "claude", "codex"):
            log.warning("[ai] agent = %r is not auto, claude or codex; using auto", self.agent)
            self.agent = "auto"
        self.claude = ClaudeUsage(live=live) if self.agent != "codex" else None
        self.codex = CodexUsage() if self.agent == "codex" or (
            self.agent == "auto" and codex_home().is_dir()) else None
        self.claude_msg = None
        self.alerts = ClaudeAlerts() if cfg.get("claude", {}).get("alerts", True) else None
        self.printer_msg = None
        self.connected_once = False
        self.ws = None

    async def send(self, msg: dict | bytes):
        ws = self.ws
        if ws is None:
            return
        try:
            await ws.send(msg if isinstance(msg, bytes) else json.dumps(msg, separators=(",", ":")))
        except websockets.ConnectionClosed:
            pass

    # ---- producers --------------------------------------------------------

    async def stats_loop(self):
        while True:
            await self.send(self.stats.sample())
            await asyncio.sleep(1)

    async def media_loop(self):
        await self.media.start()
        while True:
            try:
                msg, art = await self.media.snapshot()
                if art:
                    await self.send(art)
                await self.send(msg)
            except Exception as e:
                log.debug("media poll failed: %s", e)
            await asyncio.sleep(1)

    def ai_snapshot(self) -> dict:
        claude = self.claude.snapshot() if self.claude else None
        codex = self.codex.snapshot() if self.codex else None
        return pick_ai(self.agent, claude, codex)

    async def claude_loop(self):
        while True:
            try:
                self.claude_msg = await asyncio.to_thread(self.ai_snapshot)
                await self.send(self.claude_msg)
            except Exception as e:
                log.warning("AI usage failed: %s", e)
            await asyncio.sleep(5)

    async def alerts_loop(self):
        while True:
            try:
                msg = await asyncio.to_thread(self.alerts.poll)
                if msg:
                    await self.send(msg)
            except Exception as e:
                log.warning("claude alerts failed: %s", e)
            await asyncio.sleep(1)

    async def calendar_loop(self):
        cal = self.cfg.get("calendar", {})
        feeds, days = cal.get("feeds", []), int(cal.get("days", 7))
        while True:
            self.events = await fetch_events(feeds, days)
            log.info("calendar: %d upcoming events", len(self.events))
            await self.send({"type": "events", "events": self.events})
            await asyncio.sleep(CALENDAR_REFRESH_S)

    async def printer_loop(self):
        service = PrinterService(self.cfg.get("printers", []))
        if not service.workers:
            return
        service.start()
        sent_at = 0.0
        while True:
            msg = service.message()
            now = asyncio.get_running_loop().time()
            # Send on change (checked every 2 s) and at least every 30 s.
            if msg != self.printer_msg or now - sent_at >= PRINTER_KEEPALIVE_S:
                self.printer_msg = msg
                sent_at = now
                await self.send(msg)
            await asyncio.sleep(PRINTER_TICK_S)

    # ---- hub commands -----------------------------------------------------

    async def handle(self, raw):
        if isinstance(raw, bytes):
            return
        msg = json.loads(raw)
        kind = msg.get("type")
        if kind == "media":
            await self.media.command(msg.get("cmd", ""), int(msg.get("value", 0)))
        elif kind == "alert_action" and self.alerts:
            sid, action = str(msg.get("id", "")), msg.get("action")
            if action == "dismiss":
                self.alerts.dismiss(sid)
            elif action == "focus":
                await asyncio.to_thread(self.alerts.focus, sid)
        elif kind == "shortcut":
            i = int(msg.get("id", -1))
            if 0 <= i < len(self.tiles):
                try:
                    pending = run_tile(self.tiles[i], self.media)
                    if pending is not None:
                        await pending
                except Exception as e:
                    log.warning("shortcut %d failed: %s", i, e)

    async def session(self):
        async with websockets.connect(self.url, max_size=2**20, ping_interval=10,
                                      ping_timeout=10, open_timeout=10) as ws:
            await ws.send(json.dumps({"type": "hello", "token": self.token}))
            reply = json.loads(await asyncio.wait_for(ws.recv(), 10))
            if reply.get("type") != "hello_ok":
                raise RuntimeError(f"hub refused hello: {reply}")
            log.info("connected to hub (firmware %s)", reply.get("version", "?"))
            self.connected_once = True
            self.ws = ws
            # Everything the hub keeps in RAM, resent after each (re)connect.
            await self.send(layout_message(self.cfg))
            await self.send(home_message(self.cfg))
            await self.send(hub_view(self.tiles))
            await self.send({"type": "events", "events": self.events})
            if self.claude_msg:
                await self.send(self.claude_msg)
            if self.alerts and self.alerts.msg:
                await self.send(self.alerts.msg)
            if self.printer_msg:
                await self.send(self.printer_msg)
            art = self.media.current_art()
            if art:
                await self.send(art)
            async for raw in ws:
                try:
                    await self.handle(raw)
                except Exception as e:
                    log.warning("bad message from hub: %s", e)

    async def run(self):
        asyncio.create_task(self.stats_loop())
        asyncio.create_task(self.media_loop())
        asyncio.create_task(self.calendar_loop())
        asyncio.create_task(self.claude_loop())
        if self.alerts:
            asyncio.create_task(self.alerts_loop())
        if "printer" in enabled_pages(self.cfg):
            asyncio.create_task(self.printer_loop())
        delay = 2
        while True:
            try:
                await self.session()
                delay = 2
            except (OSError, asyncio.TimeoutError, websockets.WebSocketException, RuntimeError) as e:
                log.info("hub not reachable at %s (%s), retrying in %ds", self.url, e, delay)
            finally:
                self.ws = None
            # A link that came up and later dropped (e.g. the hub rebooted) retries fast.
            if self.connected_once:
                self.connected_once = False
                delay = 2
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config")
    ap.add_argument("--verbose", "-v", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    path = find_config(args.config)
    cfg = tomllib.loads(path.read_text(encoding="utf-8"))
    log.info("using %s", path)
    try:
        asyncio.run(Companion(cfg).run())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
