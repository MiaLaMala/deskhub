"""Stand-in for the CYD display's web socket (cyd/PROTOKOLL.md): checks the login token and
every message field by field (pi_protocol.py). For tests, and for trying the Pi companion
without hardware:

    python tests/fake_cyd_hub.py --config my.toml --seconds 20 [--port 8765]

(starts the companion against itself; the config's [hub] host is overridden)
"""
import argparse
import asyncio
import json
import pathlib
import sys

import websockets

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from pi_protocol import validate  # noqa: E402

TOKEN = "test-token"
ALL_TYPES = ["hello", "time", "layout", "events", "ai", "weather", "homelab", "github", "net"]


class FakeCyd:
    def __init__(self, port: int = 0, token: str = TOKEN, version: str = "fake"):
        self.port, self.token, self.version = port, token, version
        self.log: list[dict] = []          # every message after login, in order (hello included first)
        self.hellos: list[dict] = []
        self.problems: list[str] = []
        self.refused = 0
        self.sessions = 0
        self.conns: list = []
        self.server = None

    async def handler(self, ws):
        try:
            first = json.loads(await ws.recv())
        except (ValueError, websockets.WebSocketException):
            return
        self.problems += validate(first)
        if first.get("type") != "hello" or first.get("token") != self.token:
            self.refused += 1
            await ws.close()
            return
        self.hellos.append(first)
        self.sessions += 1
        self.conns.append(ws)
        await ws.send(json.dumps({"type": "hello_ok", "version": self.version, "board": "cyd"}))
        try:
            async for raw in ws:
                if isinstance(raw, bytes):
                    self.problems.append("binary frame")
                    continue
                m = json.loads(raw)
                self.problems += validate(m)
                self.log.append(m)
        except websockets.WebSocketException:
            pass

    async def __aenter__(self):
        self.server = await websockets.serve(self.handler, "127.0.0.1", self.port, max_size=2**20)
        self.port = self.server.sockets[0].getsockname()[1]
        return self

    async def __aexit__(self, *a):
        self.server.close()
        await self.server.wait_closed()

    @property
    def host(self):
        return f"127.0.0.1:{self.port}"

    def types(self) -> dict[str, int]:
        out: dict[str, int] = {"hello": len(self.hellos)}
        for m in self.log:
            out[m["type"]] = out.get(m["type"], 0) + 1
        return out

    def last(self, kind):
        return next((m for m in reversed(self.log) if m["type"] == kind), None)

    async def say(self, msg: dict):
        for ws in list(self.conns):
            try:
                await ws.send(json.dumps(msg))
            except websockets.WebSocketException:
                self.conns.remove(ws)

    async def drop(self):
        for ws in list(self.conns):
            await ws.close()
        self.conns.clear()


async def main(config: str, seconds: float, port: int):
    import tomllib

    from deskhub.pi.app import PiCompanion

    cfg = tomllib.loads(pathlib.Path(config).read_text(encoding="utf-8"))
    async with FakeCyd(port) as hub:
        cfg["hub"] = {"host": hub.host, "token": TOKEN}
        comp = PiCompanion(cfg)
        stop = asyncio.Event()
        task = asyncio.create_task(comp.run(stop))
        await asyncio.sleep(seconds / 2)
        await hub.say({"type": "page", "name": "weather"})
        await hub.say({"type": "refresh"})
        await asyncio.sleep(seconds / 2)
        stop.set()
        task.cancel()
    types = hub.types()
    print("messages:", types)
    missing = [t for t in ALL_TYPES if t not in types]
    print("never received:", missing or "-")
    print("PROBLEMS:" if hub.problems else "OK", hub.problems or "")
    sys.exit(1 if hub.problems or missing else 0)


if __name__ == "__main__":
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--seconds", type=float, default=15)
    ap.add_argument("--port", type=int, default=0)
    a = ap.parse_args()
    asyncio.run(main(a.config, a.seconds, a.port))
