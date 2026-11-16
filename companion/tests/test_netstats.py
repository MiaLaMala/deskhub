"""NetStats: latency math, status, data used, persistence, speed test. No network.

    uv run --no-sync python tests/test_netstats.py
"""
import pathlib
import sys
import tempfile
from collections import namedtuple
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from deskhub.netstats import NetStats  # noqa: E402

problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


class Clock:
    def __init__(self, t=1_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


C = namedtuple("C", "bytes_sent bytes_recv")
tmp = pathlib.Path(tempfile.mkdtemp())


def make(probes, counters=None, state=None, clock=None, http=None, **kw):
    it = iter(probes)
    clock = clock or Clock()
    n = NetStats(clock=clock, probe=lambda: next(it), counters=counters or (lambda: C(0, 0)),
                 state_file=state or tmp / "a.json", http=http, **kw)
    return n, clock


def run(n, clock, count, step=2):
    for _ in range(count):
        n.tick()
        clock.t += step


# latency / jitter / loss
n, clk = make([10, 20, None, 30, 40, 50, 60])
run(n, clk, 7)
check(n.latency_ms == 40, f"median of last 5 ok: {n.latency_ms}")  # 10,20,30,40,50,60 -> last5 = 20,30,40,50,60
check(abs(n.jitter_ms - 10) < 1e-9, f"jitter {n.jitter_ms}")
check(n.loss_pct == 14, f"loss {n.loss_pct}")  # 1/7
m = n.message()
check(m["hist"] == [10, 20, -1, 30, 40, 50, 60], f"hist {m['hist']}")
check(m["type"] == "net" and m["online"] and m["ip"] == "" and m["speed"] is None and not m["testing"],
      "message shape")
check(set(m) == {"type", "online", "latency_ms", "jitter_ms", "loss_pct", "hist", "up_since", "last_drop",
                 "today_bytes", "month_bytes", "speed", "testing", "ip"}, "message keys")

# window of 60
n, clk = make([5] * 100)
run(n, clk, 100)
check(len(n.message()["hist"]) == 60, "window 60")

# no successes
n, clk = make([None] * 4)
run(n, clk, 4)
m = n.message()
check(m["latency_ms"] is None and m["jitter_ms"] is None and m["loss_pct"] == 100 and not m["online"]
      and m["up_since"] is None, f"all lost {m}")

# online/offline transitions
n, clk = make([10, None, None, None, None, 12, 12])
start = clk.t
run(n, clk, 1)
check(n.online and n.up_since == start, "up_since at first success")
run(n, clk, 2)
check(n.online, "still online with a success in the last 3")
run(n, clk, 1)  # probes: 10, None, None, None -> offline at t+6
check(not n.online, "offline after 3 failures")
off_at = start + 6
run(n, clk, 1)
run(n, clk, 1)  # success at t+10
check(n.online and n.up_since == start + 10, f"back online {n.up_since}")
check(n.last_drop == {"at": int(off_at), "dur_s": 4}, f"last_drop {n.last_drop}")

# data used: day and month boundaries, counter reset
t0 = datetime(2026, 1, 31, 23, 59, 0).timestamp()
vals = iter([C(100, 100), C(150, 150), C(200, 250), C(10, 10), C(60, 60), C(60, 60)])
n, clk = make([1] * 6, counters=lambda: next(vals), clock=Clock(t0), state=tmp / "b.json")
n.tick()
check(n.today_bytes == 0, "first sample has no delta")
clk.t = t0 + 30
n.tick()
check(n.today_bytes == 100 and n.month_bytes == 100, f"delta {n.today_bytes}")
clk.t = t0 + 50
n.tick()
check(n.today_bytes == 250, f"delta2 {n.today_bytes}")
clk.t = t0 + 70  # past midnight, and the counter reset (negative delta -> 0)
n.tick()
check(n.today_bytes == 0 and n.month_bytes == 0, f"new day+month reset {n.today_bytes} {n.month_bytes}")
clk.t = t0 + 72
n.tick()
check(n.today_bytes == 100 and n.month_bytes == 100, f"after reset {n.today_bytes}")

# persistence: written on date change, readable by a new instance
n2, _ = make([], state=tmp / "b.json", clock=Clock(t0 + 80))
check(n2.today_bytes == 0 and n2._day == "2026-02-01", f"loaded {n2._day} {n2.today_bytes}")
vals = iter([C(0, 0), C(500, 500)])
n3, c3 = make([1, 1], counters=lambda: next(vals), clock=Clock(t0 + 100), state=tmp / "c.json")
run(n3, c3, 1)
c3.t += 61
n3.tick()
n4, _ = make([], state=tmp / "c.json", clock=Clock(t0 + 200))
check(n4.today_bytes == 1000, f"round trip {n4.today_bytes}")
(tmp / "bad.json").write_text("{nope")
check(make([], state=tmp / "bad.json")[0].today_bytes == 0, "bad state file ignored")


# speed test with a fake http
class Resp:
    def __init__(self, n=0):
        self.content = b"x" * n
        self.text = "fl=1\nip=203.0.113.9\nts=1\n"

    def raise_for_status(self):
        pass


class Http:
    def __init__(self, clock, fail=False):
        self.clock, self.fail, self.calls = clock, fail, []

    def get(self, url, **kw):
        self.calls.append(("GET", url))
        if self.fail:
            raise OSError("down")
        if url.endswith("bytes=0"):
            self.clock.t += 0.02
            return Resp()
        if "bytes=25000000" in url:
            self.clock.t += 2.0
            return Resp(25_000_000)
        return Resp()

    def post(self, url, content=None, **kw):
        self.calls.append(("POST", url, len(content)))
        self.clock.t += 4.0
        return Resp()


clk = Clock(5000.0)
http = Http(clk)
n, _ = make([], clock=clk, http=http, state=tmp / "d.json")
n.run_speedtest()
check(n.speed == {"down_mbps": 100.0, "up_mbps": 20.0, "ping_ms": 20.0, "at": int(clk.t)}, f"speed {n.speed}")
check(not n.testing, "testing cleared")
check(http.calls.count(("GET", "https://speed.cloudflare.com/__down?bytes=0")) == 5
      and ("POST", "https://speed.cloudflare.com/__up", 10_000_000) in http.calls, "requests made")
n5, _ = make([], state=tmp / "d.json")
check(n5.speed and n5.speed["down_mbps"] == 100.0, "speed persisted")
bad = Http(clk, fail=True)
n5.http = bad
n5.run_speedtest()
check(n5.speed["down_mbps"] == 100.0 and not n5.testing, "failed test keeps the previous result")

# public IP
n, clk = make([5], clock=Clock(), http=Http(Clock()), state=tmp / "e.json", show_ip=True)
n.tick()
check(n.message()["ip"] == "203.0.113.9", f"ip {n.message()['ip']}")
n, clk = make([5], http=Http(Clock()), state=tmp / "f.json")
n.tick()
check(n.message()["ip"] == "" and not n.http.calls, "ip off by default")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
