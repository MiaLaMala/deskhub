"""Elegoo printers that speak SDCP v3 over a websocket (Centauri Carbon), for the board's printer page.

The printer serves `ws://<ip>:3030/websocket` and answers a UDP "M99999" on port 3000 with its
MainboardID, name and model. Requests go out on the topic `sdcp/request/<MainboardID>`; status
comes back on `sdcp/status/<MainboardID>` whenever it changes and after a status request (Cmd 0).
The worker keeps one websocket open and asks for a status refresh on every poll.

Sources the protocol details were checked against:
  - Elegoo's own SDCP spec: github.com/cbd-tech/SDCP-Smart-Device-Control-Protocol-V3.0.0
  - Elegoo's ElegooLink library, Centauri Carbon adapter:
    github.com/elegooofficial/elegoo-link src/lan/adapters/elegoo_fdm_cc/
  - Home Assistant integration: github.com/danielcherubini/elegoo-homeassistant (sdcp/)
  - OpenCentauri docs: github.com/OpenCentauri/OpenCentauri docs/software/api.md
"""
import inspect
import json
import re
import secrets
import socket
import time

from websockets.exceptions import InvalidStatus, WebSocketException
from websockets.sync.client import connect

from .calendar_feed import _safe_error
from .printer import _int, _num
from .printer_poll import BackendSpec, PollingWorker, ProbeResult, host_port, make_message
from .text import ascii_fold

DEFAULT_PORT = 3030        # websocket, fixed on the printer
DISCOVERY_PORT = 3000      # UDP, answers "M99999"
DISCOVERY_MESSAGE = b"M99999"
DEFAULT_MODEL = "Elegoo"
RESPONSE_S = 3.0           # wait this long for a status after a request
STALE_STATUS_S = 30.0      # reconnect when nothing has come in for this long

# Machine status, Status.CurrentStatus[0] on the Centauri Carbon (sdcp_machine_status_t in
# elegoo-link elegoo_fdm_cc_message_adapter.cpp; 0-4 also in the SDCP spec):
#   0 idle, 1 printing, 2 file transferring, 4 self-check, 5 auto leveling, 6 resonance testing,
#   7 busy, 8 file checking, 9 homing, 10 filament unloading, 11 PID detection.
M_PRINTING, M_FILE_TRANSFER = 1, 2
_MACHINE_PREPARE = {4, 5, 6, 8, 9, 11}

# Print sub-status, Status.PrintInfo.Status (sdcp_print_status_t in the same elegoo-link file;
# 0-10 also in the SDCP spec). The sub-status keeps its last value after a job ends ("the
# sub-status will always retain the most recent status", SDCP spec), so complete, stopped and
# error stay visible until the next job.
P_STOPPING, P_STOPPED, P_COMPLETE, P_ERROR = 7, 8, 9, 14
# 5 pausing, 6 paused, 25 filament unloading abnormal, 26 filament unloading paused.
_PRINT_PAUSE = {5, 6, 25, 26}
# 1 homing, 10 file checking, 11 printer checking, 15 auto leveling, 16 preheating,
# 17 resonance testing, 18 print started, 19-22 leveling/preheating/homing/resonance completed.
# The firmware can sit on a "completed" milestone for the whole job (noted in the Home Assistant
# integration's enums.py), so these only count as PREPARE until the first layer is under way.
_PRINT_PREPARE = {1, 10, 11, 15, 16, 17, 18, 19, 20, 21, 22}
# Everything else while the machine is printing (0, 12 resuming, 13 printing, 23 auto feeding,
# 24 filament unloading, codes newer than this table) is RUNNING, as elegoo-link treats them.

# PrintInfo.ErrorNumber (sdcp_print_error_t, SDCP spec).
_PRINT_ERRORS = {1: "File check (MD5) failed", 2: "Could not read the file",
                 3: "File resolution mismatch", 4: "Unknown file format",
                 5: "File is for another model"}

_ACTIVE = ("RUNNING", "PAUSE", "PREPARE")
# websockets 15 reads proxy settings from the environment; the printer is on the LAN.
_CONNECT_OPTS = {"proxy": None} if "proxy" in inspect.signature(connect).parameters else {}


def _file_name(path) -> str:
    name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(gcode|g|gco|bgcode)$", "", name, flags=re.I)


def _machine_status(status: dict) -> int:
    """CurrentStatus is a list on websocket printers (an int on older MQTT ones). Like
    elegoo-link, a file transfer gives way to whatever else the machine is doing."""
    cur = status.get("CurrentStatus")
    if isinstance(cur, list):
        codes = [c for c in cur if isinstance(c, int) and not isinstance(c, bool)]
        if len(codes) > 1 and codes[0] == M_FILE_TRANSFER:
            return codes[1]
        return codes[0] if codes else 0
    return _int(cur)


def board_state(status: dict) -> str:
    """One of the board's STATES from an SDCP Status object."""
    info = status.get("PrintInfo") if isinstance(status.get("PrintInfo"), dict) else {}
    machine = _machine_status(status)
    sub = _int(info.get("Status"))
    if sub == P_COMPLETE:
        return "FINISH"
    if sub == P_ERROR:
        return "FAILED"
    if machine != M_PRINTING:
        return "PREPARE" if machine in _MACHINE_PREPARE else "IDLE"
    if sub in (P_STOPPING, P_STOPPED):
        return "IDLE"  # cancelled, like Moonraker's "cancelled"
    if sub in _PRINT_PAUSE:
        return "PAUSE"
    if sub in _PRINT_PREPARE and not (_int(info.get("CurrentLayer")) or _int(info.get("Progress"))):
        return "PREPARE"
    return "RUNNING"


def build_message(name: str, model: str, status: dict) -> dict:
    """The board's `printer` entry from the `Status` object of an sdcp/status message."""
    info = status.get("PrintInfo") if isinstance(status.get("PrintInfo"), dict) else {}
    state = board_state(status)
    # PREPARE from the machine status (levelling, homing... with no print running) is not a job:
    # PrintInfo still holds the last job's file and progress then.
    active = state in _ACTIVE and _machine_status(status) == M_PRINTING
    job = active or state in ("FINISH", "FAILED")

    layer, layers = _int(info.get("CurrentLayer")), _int(info.get("TotalLayer"))
    progress = _num(info.get("Progress"))
    if progress is None and layers:
        progress = layer / layers * 100
    pct = 100 if state == "FINISH" else (progress or 0) if active else 0
    # CurrentTicks/TotalTicks are seconds on the Centauri Carbon (elegoo-link computes the
    # remaining time in seconds from them; Home Assistant scales FDM ticks by 1000 to get ms).
    # The SDCP spec's "ms" is for the resin printers.
    remaining_s = max(_int(info.get("TotalTicks")) - _int(info.get("CurrentTicks")), 0) if active else 0
    speed = _num(info.get("PrintSpeedPct"))
    if speed is None:
        speed = _num(info.get("PrintSpeed", status.get("PrintSpeed")))  # OpenCentauri's naming

    error = ""
    if state == "FAILED":
        error = _PRINT_ERRORS.get(_int(info.get("ErrorNumber")), "Print stopped by an error")
    return make_message(
        name, model, state=state, pct=pct, remaining_min=remaining_s / 60,
        layer=layer if job else 0, layers=layers if job else 0,
        file=_file_name(info.get("Filename")) if job else "",
        nozzle=status.get("TempOfNozzle"), nozzle_target=status.get("TempTargetNozzle"),
        bed=status.get("TempOfHotbed"), bed_target=status.get("TempTargetHotbed"),
        chamber=status.get("TempOfBox"),
        speed=f"{round(speed)}%" if speed and active else "", error=error)


def status_of(msg: dict) -> dict | None:
    """The Status object of an sdcp/status message (nested, or flat on some firmware), else None."""
    if not str(msg.get("Topic") or "").startswith("sdcp/status/"):
        return None
    st = msg.get("Status")
    return st if isinstance(st, dict) else msg


def request(mainboard: str, cmd: int, data: dict | None = None) -> str:
    """An SDCP request frame (SDCP spec "Request Message"; From 0 is local PC software)."""
    return json.dumps({
        "Id": secrets.token_hex(16),
        "Data": {"Cmd": cmd, "Data": data or {}, "RequestID": secrets.token_hex(8),
                 "MainboardID": mainboard, "TimeStamp": int(time.time()), "From": 0},
        "Topic": f"sdcp/request/{mainboard}"})


def discover(host: str, timeout: float = 2) -> dict:
    """Ask one printer for its discovery reply ({"Id", "Data": {"Name", "MachineName",
    "MainboardID", ...}}); returns the Data object, or {} when nothing usable comes back."""
    try:
        with socket.socket(socket.AF_INET6 if ":" in host else socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(timeout)
            s.sendto(DISCOVERY_MESSAGE, (host, DISCOVERY_PORT))
            end = time.monotonic() + timeout
            while (left := end - time.monotonic()) > 0:
                s.settimeout(left)
                data, _ = s.recvfrom(8192)
                try:
                    reply = json.loads(data.decode("utf-8"))
                except ValueError:
                    continue
                info = reply.get("Data") if isinstance(reply, dict) else None
                if isinstance(info, dict):
                    return info.get("Attributes", info) if isinstance(info.get("Attributes"), dict) else info
    except OSError:  # timeout, ICMP port unreachable, no route
        pass
    return {}


class Link:
    """One websocket to the printer, with the MainboardID its requests need."""

    def __init__(self, host: str, port: int, mainboard: str = "", timeout: float = 5):
        self.ws = connect(f"ws://{host_port(host, port)}/websocket", open_timeout=timeout,
                          close_timeout=1, compression=None, **_CONNECT_OPTS)
        self.mainboard = mainboard

    def close(self):
        self.ws.close()

    def send(self, cmd: int, data: dict | None = None):
        self.ws.send(request(self.mainboard, cmd, data))

    def recv(self, timeout: float) -> dict | None:
        """The next JSON message, or None when `timeout` runs out. Answers the printer's text
        keepalive (the SDCP heartbeat is "ping" / "pong"); websocket-level pings are handled
        by the websockets library."""
        end = time.monotonic() + timeout
        while (left := end - time.monotonic()) > 0:
            try:
                raw = self.ws.recv(timeout=left)
            except TimeoutError:
                return None
            if isinstance(raw, bytes):
                raw = raw.decode("utf-8", "replace")
            if raw.strip() == "ping":
                self.ws.send("pong")
                continue
            try:
                msg = json.loads(raw)
            except ValueError:
                continue  # "pong" and anything else that isn't JSON
            if isinstance(msg, dict):
                data = msg.get("Data")
                if not self.mainboard:
                    self.mainboard = str(msg.get("MainboardID") or
                                         (data.get("MainboardID") if isinstance(data, dict) else "") or "")
                return msg
        return None


class ElegooWorker(PollingWorker):
    type = "elegoo"
    default_port = DEFAULT_PORT
    default_model = DEFAULT_MODEL
    REOPEN_ON_ERROR = True

    def __init__(self, entry: dict, secret_getter):
        super().__init__(entry, secret_getter)
        self._mainboard = ""       # survives reconnects; it never changes
        self._status: dict | None = None
        self._status_at = 0.0

    def open(self):
        if not self._mainboard:
            self._mainboard = str(discover(self.host).get("MainboardID") or "")
        link = Link(self.host, self.port, self._mainboard)
        try:
            if not link.mainboard:
                # No discovery reply (some firmware stops answering it, and UDP can be
                # filtered): use the ID from the first message the printer pushes.
                self._take(link.recv(5))
                if not link.mainboard:
                    raise TimeoutError("the printer sent nothing to identify itself")
            self._mainboard = link.mainboard
        except Exception:
            link.close()
            raise
        return link

    def _take(self, msg: dict | None) -> bool:
        st = status_of(msg) if msg else None
        if st is not None:
            self._status, self._status_at = st, time.monotonic()
        return st is not None

    def poll(self, link) -> dict:
        link.send(0)  # Cmd 0: report the latest status on the status topic
        got = False
        end = time.monotonic() + RESPONSE_S
        while (left := end - time.monotonic()) > 0:
            msg = link.recv(left if not got else 0.01)  # once a status is in, drain what's queued
            if msg is None:
                break
            got = self._take(msg) or got
        if self._status is None or time.monotonic() - self._status_at > STALE_STATUS_S:
            raise TimeoutError("no status from the printer")
        return build_message(self.label, self.model, self._status)

    def reset(self):
        self._status = None

    def hint(self, e):
        if isinstance(e, InvalidStatus) and e.response.status_code == 500:
            # pycentauri notes the printer allows 5 websockets and answers a 6th with
            # HTTP 500 "too many client".
            return ("the printer refused the connection; it may already have 5 open (Elegoo "
                    "slicer, apps, Home Assistant). Close one and it reconnects.")
        return None


def probe(entry: dict, secret: str | None = None, timeout: float = 5) -> ProbeResult:
    """Check the websocket answers; suggests the printer's name and model from the discovery
    reply, or from the attributes (Cmd 1) when discovery goes unanswered."""
    host, port = str(entry["host"]), int(entry.get("port") or DEFAULT_PORT)
    info = discover(host, min(timeout, 2))
    name, model = str(info.get("Name") or ""), str(info.get("MachineName") or "")
    try:
        link = Link(host, port, str(info.get("MainboardID") or ""), timeout=timeout)
    except InvalidStatus as e:
        if e.response.status_code == 500:
            return ProbeResult(False, "The printer refused the connection; it may already have 5 "
                                      "open (Elegoo slicer, apps). Close one and try again.", name, model)
        return ProbeResult(False, f"{host_port(host, port)} answered with HTTP {e.response.status_code}. "
                                  "Is this an Elegoo Centauri Carbon?", name, model)
    except (OSError, WebSocketException) as e:
        heard = "It answered discovery, but there is no" if info else "No"
        return ProbeResult(False, f"{heard} websocket at {host_port(host, port)} ({_safe_error(e, '')}). "
                                  "Check the IP address and that the printer is on and on this network.",
                           name, model)
    try:
        end = time.monotonic() + timeout
        if not link.mainboard:
            link.recv(min(timeout, 3))  # the first push carries the MainboardID
        if link.mainboard and not (name and model):
            link.send(1)  # Cmd 1: report attributes on the attributes topic
            while (left := end - time.monotonic()) > 0:
                msg = link.recv(left)
                if msg is None:
                    break
                attrs = msg.get("Attributes")
                if isinstance(attrs, dict):
                    name = name or str(attrs.get("Name") or "")
                    model = model or str(attrs.get("MachineName") or "")
                    break
    except (OSError, WebSocketException):
        pass  # the websocket opened, which is what the worker needs
    finally:
        link.close()
    shown = ascii_fold(model, 15) or DEFAULT_MODEL
    return ProbeResult(True, f"Connected to the {shown}.", name, ascii_fold(model, 15))


SPEC = BackendSpec(
    type="elegoo",
    menu="Elegoo Centauri Carbon (SDCP)",
    intro="""Elegoo Centauri Carbon
  Talks to the printer over its local network connection (port 3030), the same way Elegoo's
  slicer does. No password or access code is needed; the printer and this PC just have to be
  on the same network. The printer takes at most 5 connections at once (slicer, apps, Home
  Assistant...).""",
    default_port=DEFAULT_PORT,
    default_model=DEFAULT_MODEL,
    probe=probe,
    secret_prompt=None,
    ask_port=False,
    brand="Elegoo",
)
WORKER = ElegooWorker
