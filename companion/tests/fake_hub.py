"""Stand-in for the hub firmware's web socket protocol, for testing the companion
without hardware. Checks every frame the way hub_server.c parses it.

    uv run python tests/fake_hub.py [--seconds 8] [--port 8765]
Point a config at host = "127.0.0.1:8765".
"""
import argparse
import asyncio
import datetime as dt
import json
import struct

import websockets

TOKEN = "test-token"


async def main(seconds: float, port: int, send_cmds: bool):
    seen: dict[str, int] = {}
    problems: list[str] = []
    last: dict[str, dict] = {}

    async def handler(ws):
        hello = json.loads(await ws.recv())
        if hello.get("type") != "hello" or hello.get("token") != TOKEN:
            problems.append(f"bad hello {hello}")
            await ws.close()
            return
        await ws.send('{"type":"hello_ok","version":"fake"}')
        if send_cmds:
            await ws.send('{"type":"media","cmd":"bogus","value":0}')
        async for raw in ws:
            if isinstance(raw, bytes):
                seen["art"] = seen.get("art", 0) + 1
                if raw[:4] != b"ART1":
                    problems.append("art magic")
                    continue
                art_id, w, h = struct.unpack_from("<IHH", raw, 4)
                if len(raw) != 12 + w * h * 2 or not (0 < w <= 320 and 0 < h <= 320) or art_id == 0:
                    problems.append(f"art frame {w}x{h} id {art_id} len {len(raw)}")
                continue
            m = json.loads(raw)
            t = m.get("type")
            seen[t] = seen.get(t, 0) + 1
            last[t] = m
            if t == "events":
                for e in m["events"]:
                    if len(e["title"].encode()) > 79 or not e["title"].isascii():
                        problems.append(f"event title {e['title']!r}")
            if t == "tiles" and len(m["tiles"]) > 16:
                problems.append("too many tiles")
            if t == "media" and m.get("active"):
                for k in ("title", "artist", "album"):
                    if not m[k].isascii():
                        problems.append(f"non-ascii media {k}")

    async with websockets.serve(handler, "127.0.0.1", port, max_size=2**20):
        await asyncio.sleep(seconds)

    print("frames:", seen)
    for t in ("stats", "media", "events", "tiles"):
        if t in last:
            body = json.dumps(last[t])
            print(f"last {t}: {body[:300]}")
    if "events" in last:
        for e in last["events"]["events"]:
            print("  event:", dt.datetime.fromtimestamp(e["start"]).strftime("%a %H:%M"),
                  "all-day" if e["all_day"] else "", e["title"])
    missing = [t for t in ("stats", "media", "events", "tiles") if t not in seen]
    if missing:
        problems.append(f"never received {missing}")
    print("PROBLEMS:" if problems else "OK", problems if problems else "")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=8)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--send-cmds", action="store_true")
    a = ap.parse_args()
    asyncio.run(main(a.seconds, a.port, a.send_cmds))
