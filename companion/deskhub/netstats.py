"""Internet connection stats: latency probe, jitter, loss, uptime, data used, speed test."""
import json
import logging
import pathlib
import socket
import statistics
import threading
import time
from datetime import datetime

import httpx
import psutil

log = logging.getLogger(__name__)

STATE_FILE = pathlib.Path.home() / ".deskhub" / "net_usage.json"
TARGETS = [("1.1.1.1", 443), ("8.8.8.8", 443)]
WINDOW = 60
SAVE_EVERY_S = 60
IP_REFRESH_S = 30 * 60
CF = "https://speed.cloudflare.com"
DOWN_BYTES = 25_000_000
UP_BYTES = 10_000_000


def tcp_probe() -> float | None:
    """TCP connect time in ms to the first reachable target, None if all fail."""
    for host, port in TARGETS:
        t = time.perf_counter()
        try:
            with socket.create_connection((host, port), timeout=1):
                return (time.perf_counter() - t) * 1000
        except OSError:
            continue
    return None


class NetStats:
    def __init__(self, clock=time.time, probe=None, counters=None, state_file=STATE_FILE,
                 http=None, show_ip=False):
        self.clock = clock
        self.probe = probe or tcp_probe
        self.counters = counters or psutil.net_io_counters
        self.state_file = pathlib.Path(state_file)
        self.http = http
        self.show_ip = show_ip
        self.samples: list[float | None] = []
        self.online = False
        self.up_since: float | None = None
        self.last_drop: dict | None = None
        self._went_offline: float | None = None
        self.testing = False
        self.speed: dict | None = None
        self.ip = ""
        self._ip_at = 0.0
        self._last_total: int | None = None
        self._day = self._month = ""
        self.today_bytes = self.month_bytes = 0
        self._saved_at = 0.0
        self._lock = threading.Lock()
        self._load()

    # ---- persistence ------------------------------------------------------

    def _load(self):
        try:
            d = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(d, dict):
            return
        self.speed = d.get("speed") if isinstance(d.get("speed"), dict) else None
        self._day, self._month = str(d.get("day", "")), str(d.get("month", ""))
        self.today_bytes, self.month_bytes = int(d.get("today", 0)), int(d.get("month_bytes", 0))

    def _save(self):
        self._saved_at = self.clock()
        data = {"day": self._day, "month": self._month, "today": self.today_bytes,
                "month_bytes": self.month_bytes, "speed": self.speed}
        try:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(data), encoding="utf-8")
        except OSError as e:
            log.debug("net usage save failed: %s", e)

    # ---- ticking ----------------------------------------------------------

    def tick(self):
        now = self.clock()
        ms = self.probe()
        with self._lock:
            self.samples.append(ms)
            del self.samples[:-WINDOW]
            self._update_status(now, ms)
            self._update_usage(now)
        if self.show_ip and now - self._ip_at >= IP_REFRESH_S:
            self._ip_at = now
            self._refresh_ip()

    def _update_status(self, now: float, ms):
        online = any(s is not None for s in self.samples[-3:])
        if online and not self.online:
            if self._went_offline is not None:
                self.last_drop = {"at": int(self._went_offline), "dur_s": int(now - self._went_offline)}
                self._went_offline = None
            self.up_since = now
        elif not online and self.online:
            self._went_offline = now
        self.online = online

    def _update_usage(self, now: float):
        try:
            c = self.counters()
            total = c.bytes_sent + c.bytes_recv
        except Exception as e:
            log.debug("net counters failed: %s", e)
            return
        delta = 0 if self._last_total is None else max(total - self._last_total, 0)
        self._last_total = total
        local = datetime.fromtimestamp(now)
        day, month = local.strftime("%Y-%m-%d"), local.strftime("%Y-%m")
        changed = False
        if day != self._day:
            self._day, self.today_bytes, changed = day, 0, True
        if month != self._month:
            self._month, self.month_bytes, changed = month, 0, True
        self.today_bytes += delta
        self.month_bytes += delta
        if changed or now - self._saved_at >= SAVE_EVERY_S:
            self._save()

    # ---- derived numbers --------------------------------------------------

    def _ok(self) -> list[float]:
        return [s for s in self.samples if s is not None]

    @property
    def latency_ms(self) -> float | None:
        recent = [s for s in self.samples if s is not None][-5:]
        return statistics.median(recent) if recent else None

    @property
    def jitter_ms(self) -> float | None:
        ok = self._ok()
        if len(ok) < 2:
            return None
        return sum(abs(b - a) for a, b in zip(ok, ok[1:])) / (len(ok) - 1)

    @property
    def loss_pct(self) -> int:
        if not self.samples:
            return 0
        return round(100 * sum(s is None for s in self.samples) / len(self.samples))

    # ---- speed test and IP ------------------------------------------------

    def _client(self):
        return self.http or httpx.Client(timeout=30, follow_redirects=True)

    def run_speedtest(self):
        """Blocking; call from a thread. Keeps the previous result on failure."""
        if self.testing:
            return
        self.testing = True
        try:
            http = self._client()
            pings = []
            for _ in range(5):
                t = self.clock()
                http.get(f"{CF}/__down?bytes=0").raise_for_status()
                pings.append((self.clock() - t) * 1000)
            t = self.clock()
            body = http.get(f"{CF}/__down?bytes={DOWN_BYTES}")
            body.raise_for_status()
            down_s = max(self.clock() - t, 1e-6)
            nbytes = len(body.content)
            t = self.clock()
            http.post(f"{CF}/__up", content=b"\0" * UP_BYTES).raise_for_status()
            up_s = max(self.clock() - t, 1e-6)
            self.speed = {"down_mbps": round(nbytes * 8 / down_s / 1e6, 1),
                          "up_mbps": round(UP_BYTES * 8 / up_s / 1e6, 1),
                          "ping_ms": round(statistics.median(pings), 1),
                          "at": int(self.clock())}
            self._save()
        except Exception as e:
            log.warning("speed test failed: %s", e)
        finally:
            self.testing = False

    def _refresh_ip(self):
        try:
            r = self._client().get(f"{CF}/cdn-cgi/trace")
            for line in r.text.splitlines():
                if line.startswith("ip="):
                    self.ip = line[3:].strip()
        except Exception as e:
            log.debug("public ip lookup failed: %s", e)

    # ---- message ----------------------------------------------------------

    def message(self) -> dict:
        def r1(v):
            return None if v is None else round(v, 1)

        with self._lock:
            return {
                "type": "net",
                "online": self.online,
                "latency_ms": r1(self.latency_ms),
                "jitter_ms": r1(self.jitter_ms),
                "loss_pct": self.loss_pct,
                "hist": [-1 if s is None else round(s) for s in self.samples],
                "up_since": None if self.up_since is None else int(self.up_since),
                "last_drop": self.last_drop,
                "today_bytes": self.today_bytes,
                "month_bytes": self.month_bytes,
                "speed": self.speed,
                "testing": self.testing,
                "ip": self.ip if self.show_ip else "",
            }
