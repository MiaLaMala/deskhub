"""Shared pieces for printers the companion polls over the local network (everything except
Bambu, which pushes over MQTT in printer.py).

A backend module (moonraker.py, prusalink.py...) provides:
  - a `PollingWorker` subclass: `open()` returns a connection, `poll(conn)` returns the board's
    entry (build it with `make_message`), `close(conn)` and optionally `reset()` after a failure;
  - a `probe(entry, secret)` function for setup, returning a `ProbeResult`;
  - `SPEC`, a `BackendSpec` that `deskhub-printers` uses to ask for the printer's details.
The backend is registered by its `type` in printer_types.py.
"""
import dataclasses
import logging
import threading
import time
from typing import Callable

from .calendar_feed import _safe_error
from .printer import MAX_AMS, STALE_S, offline_message
from .text import ascii_fold

log = logging.getLogger("deskhub.printer")

SERVICE = "deskhub-printers"
STATES = ("IDLE", "PREPARE", "RUNNING", "PAUSE", "FINISH", "FAILED")


def secret_key(kind: str, host: str, port: int) -> str:
    """Credential store key for one printer's password, API key, token or access code."""
    return f"{kind}:{host}:{port}"


def host_port(host: str, port: int) -> str:
    """host:port for URLs, with IPv6 addresses bracketed."""
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def make_message(name: str, model: str, *, state: str, pct: float = 0, remaining_min: float = 0,
                 layer: int = 0, layers: int = 0, file: str = "", nozzle=None, nozzle_target=None,
                 bed=None, bed_target=None, chamber=None, speed: str = "", error: str = "",
                 ams: list[dict] | None = None) -> dict:
    """The board's `printer` entry, clipped to what the firmware holds.

    state: one of STATES. pct 0-100. Temperatures in C or None when unknown.
    ams: up to 8 {"color": "#RRGGBB", "type": "PLA", "active": bool}.
    """
    assert state in STATES, state

    def temp(v):
        if v is None or isinstance(v, bool):
            return None
        try:
            f = round(float(v), 1)
        except (TypeError, ValueError):
            return None
        return int(f) if f.is_integer() else f

    return {"name": ascii_fold(name, 24), "model": ascii_fold(model, 15), "online": True,
            "state": state, "pct": max(0, min(int(pct or 0), 100)),
            "remaining_min": max(0, round(remaining_min or 0)),
            "layer": max(0, int(layer or 0)), "layers": max(0, int(layers or 0)),
            "file": ascii_fold(file or "", 40),
            "nozzle": temp(nozzle), "nozzle_target": temp(nozzle_target),
            "bed": temp(bed), "bed_target": temp(bed_target), "chamber": temp(chamber),
            "speed": ascii_fold(speed or "", 11), "error": ascii_fold(error or "", 47),
            "ams": [{"color": str(a["color"]), "type": ascii_fold(a.get("type") or "", 7),
                     "active": bool(a.get("active"))} for a in (ams or [])][:MAX_AMS]}


@dataclasses.dataclass
class ProbeResult:
    ok: bool
    message: str                 # shown to the user as is
    name: str = ""               # suggested printer name
    model: str = ""              # suggested model
    secret: str | None = None    # a credential the probe obtained (e.g. an approved token)


@dataclasses.dataclass
class Field:
    key: str                     # config.toml key
    prompt: str
    default: str = ""
    required: bool = True


@dataclasses.dataclass
class BackendSpec:
    type: str                    # config.toml `type`
    menu: str                    # one line in the deskhub-printers menu
    intro: str                   # printed before the questions
    default_port: int
    default_model: str
    probe: Callable[[dict, str | None], ProbeResult]
    fields: list[Field] = dataclasses.field(default_factory=list)  # asked after host and port
    secret_prompt: str | None = None   # None: this backend takes no secret
    secret_required: bool = False
    ask_port: bool = True
    brand: str = ""               # short name in `deskhub-printers list`, e.g. "PrusaLink"


class PollingWorker(threading.Thread):
    """Polls one printer every POLL_S seconds; after a failure, waits RETRY_S (or POLL_S if it
    has worked before). Logs one line per outage, never the secret."""

    POLL_S = 2.0
    RETRY_S = 15.0
    REOPEN_ON_ERROR = False  # drop the connection after a failure (sockets, websockets)
    type = ""
    default_port = 80
    default_model = "Printer"

    def __init__(self, entry: dict, secret_getter):
        super().__init__(daemon=True, name=f"{self.type}-{entry.get('name', '')}")
        self.entry = entry
        self.host = str(entry["host"])
        try:
            self.port = int(entry.get("port") or self.default_port)
        except (TypeError, ValueError):
            self.port = self.default_port
        self.label = str(entry.get("name") or self.host)
        self.model = ascii_fold(entry.get("model") or self.default_model, 15)
        self.get_secret = secret_getter
        self.secret: str | None = None
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.last: dict | None = None
        self.last_at = 0.0
        self._warned = False

    # ---- for subclasses ----
    def open(self):
        """-> a connection object (httpx.Client, socket...). May raise; retried later."""
        raise NotImplementedError

    def poll(self, conn) -> dict:
        """-> the board entry from make_message(self.label, self.model, ...)."""
        raise NotImplementedError

    def close(self, conn):
        close = getattr(conn, "close", None)
        if close:
            close()

    def reset(self):
        """Forget cached per-connection state after a failure."""

    def hint(self, e: Exception) -> str | None:
        """A friendlier log line for errors the user can fix (bad password...), or None."""
        return None

    # ---- the loop ----
    def _fail(self, e: Exception):
        if not self._warned:
            text = self.hint(e) or _safe_error(e, self.secret or "")
            log.warning("printer %s: %s; retrying", self.label, text)
            self._warned = True

    def run(self):
        self.secret = self.get_secret(SERVICE, secret_key(self.type, self.host, self.port))
        conn = None
        try:
            while not self.stop_event.is_set():
                try:
                    if conn is None:
                        conn = self.open()
                    msg = self.poll(conn)
                    with self.lock:
                        self.last, self.last_at = msg, time.monotonic()
                    if self._warned:
                        log.info("printer %s: connected", self.label)
                        self._warned = False
                    wait = self.POLL_S
                except Exception as e:  # odd replies must not kill the thread
                    self._fail(e)
                    self.reset()
                    if conn is not None and self.REOPEN_ON_ERROR:
                        try:
                            self.close(conn)
                        except Exception:
                            pass
                        conn = None
                    wait = self.POLL_S if self.last else self.RETRY_S
                self.stop_event.wait(wait)
        finally:
            if conn is not None:
                try:
                    self.close(conn)
                except Exception:
                    pass

    def stop(self):
        self.stop_event.set()

    def message(self, now: float | None = None) -> dict:
        now = time.monotonic() if now is None else now
        with self.lock:
            if self.last and now - self.last_at <= STALE_S:
                return dict(self.last)
        return offline_message(self.label, self.model)
