"""Flashforge printers, for the board's printer page.

Adventurer 5M / 5M Pro and AD5X (also Creator 5 and Guider 4) answer a JSON API on port 8898:
POST /detail with the printer's serial number and check code (the code on the printer's network
settings screen, the one Orca-Flashforge asks for). Older printers (Adventurer 3/4, Creator Pro,
Finder...) only have the text G-code port 8899. Each poll connects, takes control with ~M601 S1,
asks ~M119 (state, file), ~M27 (progress, layers) and ~M105 (temperatures), releases with ~M602
and disconnects, so FlashPrint and the printer's other clients aren't locked out in between.

A printer entry with a `serial` uses the HTTP API; without one it uses port 8899.
Protocol reference: the Parallel-7 flashforge-api-docs wiki and endpoint specs, and FlashNetwork.h
in FlashForge's Orca-Flashforge.
"""
import functools
import math
import re
import socket

import httpx

from .calendar_feed import _safe_error
from .printer import _COLOR
from .printer_poll import BackendSpec, Field, PollingWorker, ProbeResult, host_port, make_message
from .text import ascii_fold

DEFAULT_PORT = 8898
TCP_PORT = 8899
DEFAULT_MODEL = "Flashforge"

# /detail `status`. "pausing" is on its way to a pause; "cancel"/"canceling" end in ready.
_STATES = {"ready": "IDLE", "printing": "RUNNING", "heating": "PREPARE", "busy": "PREPARE",
           "calibrate_doing": "PREPARE", "downloading": "PREPARE", "sending": "PREPARE",
           "unzipping": "PREPARE", "cloud_slicing": "PREPARE", "pausing": "PAUSE",
           "pause": "PAUSE", "paused": "PAUSE", "completed": "FINISH", "cancel": "IDLE",
           "canceling": "IDLE", "error": "FAILED"}
# Busy, but not with a print job: no progress, file or ETA.
_NOT_A_JOB = {"busy", "calibrate_doing"}
# Product ids from /detail `pid`; names kept within the board's 15 characters.
_MODELS = {35: "AD5M", 36: "AD5M Pro", 37: "Guider 4", 38: "AD5X", 39: "Guider 4 Pro",
           40: "Creator 5", 41: "Creator 5 Pro"}
_SHORT = {"adventurer 5m": "AD5M", "adventurer 5m pro": "AD5M Pro", "adventurer 5x": "AD5X"}


class FlashforgeError(Exception):
    """A /detail reply with a non-zero code (bad serial or check code, LAN mode off)."""

    def __init__(self, code, message: str):
        super().__init__(f"Flashforge API code {code}: {message}")
        self.code = code
        self.text = message


def model_from_pid(pid) -> str:
    """The 5M sends pid as a number, the AD5X as a hex string ("0026")."""
    try:
        n = int(pid, 16) if isinstance(pid, str) else int(pid)
    except (TypeError, ValueError):
        return ""
    return _MODELS.get(n, "")


def short_model(name: str) -> str:
    """"Flashforge Adventurer 5M Pro" -> "AD5M Pro"; others fit or get "Adv." to fit."""
    name = re.sub(r"^flash\s*forge\s+", "", str(name or "").strip(), flags=re.I)
    if name.lower() in _SHORT:
        return _SHORT[name.lower()]
    if len(name) > 15:
        name = re.sub(r"^Adventurer\s+", "Adv. ", name)
    return name


def _finite(v) -> float | None:
    """A number from the printer, or None for missing, odd, NaN or infinite values."""
    if isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        f = float(v)
    except (ValueError, OverflowError):
        return None
    return f if math.isfinite(f) else None


def _whole(v) -> int:
    f = _finite(v)
    return int(f) if f is not None else 0


def _file_name(path) -> str:
    name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(gcode|gx|g|3mf)$", "", name, flags=re.I)


def _slots(d: dict, active: bool) -> list[dict]:
    """AD5X material station slots (or the direct-feed spool) as board AMS slots."""
    out = []
    if d.get("hasMatlStation"):
        info = d.get("matlStationInfo") or {}
        current = _whole(info.get("currentSlot"))
        for s in info.get("slotInfos") or []:
            if not isinstance(s, dict) or not s.get("hasFilament"):
                continue
            color = str(s.get("materialColor") or "").lstrip("#")
            out.append({"color": "#" + color[:6].upper() if _COLOR.fullmatch(color) else "#808080",
                        "type": str(s.get("materialName") or ""),
                        "active": active and _whole(s.get("slotId")) == current})
    else:
        indep = d.get("indepMatlInfo") or {}
        color = str(indep.get("materialColor") or "").lstrip("#") if isinstance(indep, dict) else ""
        if _COLOR.fullmatch(color):
            out.append({"color": "#" + color[:6].upper(), "type": str(indep.get("materialName") or ""),
                        "active": False})
    return out


def build_message(name: str, model: str, d: dict) -> dict:
    """The board's `printer` entry from a /detail `detail` object."""
    raw = str(d.get("status") or "ready").lower()
    state = _STATES.get(raw, "IDLE")
    progress = max(_finite(d.get("printProgress")) or 0.0, 0.0)
    if progress > 1:  # a ratio by the docs; tolerate a percentage
        progress /= 100
    layer, layers = _whole(d.get("printLayer")), _whole(d.get("targetPrintLayer"))
    if state == "RUNNING" and progress <= 0 and layer <= 0:
        state = "PREPARE"  # job started, nothing printed yet (levelling, heating)
    active = state in ("RUNNING", "PAUSE", "PREPARE") and raw not in _NOT_A_JOB
    shows_job = active or state == "FINISH"

    error = str(d.get("errorCode") or "").strip()
    if error and error != "0":
        error = f"Error {error}"
    elif state == "FAILED":
        error = "Printer error"
    else:
        error = ""

    speed = _finite(d.get("printSpeedAdjust"))
    chamber = _finite(d.get("chamberTemp"))
    return make_message(
        name, model, state=state,
        pct=100 if state == "FINISH" else (progress * 100 if active else 0),
        remaining_min=(max(_finite(d.get("estimatedTime")) or 0, 0) / 60) if active else 0,
        layer=layer if shows_job else 0, layers=layers if shows_job else 0,
        file=_file_name(d.get("printFileName")) if shows_job else "",
        nozzle=_finite(d.get("rightTemp")), nozzle_target=_finite(d.get("rightTargetTemp")),
        bed=_finite(d.get("platTemp")), bed_target=_finite(d.get("platTargetTemp")),
        chamber=chamber if chamber else None,  # 0 on printers without a chamber sensor
        speed=f"{round(speed)}%" if speed and active else "", error=error,
        ams=_slots(d, active))


class FlashforgeClient:
    """The HTTP API on port 8898."""

    def __init__(self, host: str, port: int, serial: str, check_code: str | None, timeout: float = 5):
        self.http = httpx.Client(base_url=f"http://{host_port(host, port)}", timeout=timeout)
        self.auth = {"serialNumber": serial, "checkCode": check_code or ""}

    def close(self):
        self.http.close()

    def detail(self) -> dict:
        r = self.http.post("/detail", json=self.auth)
        r.raise_for_status()
        body = r.json()
        if body.get("code") != 0:
            raise FlashforgeError(body.get("code"), str(body.get("message") or ""))
        return body.get("detail") or {}


# ---- the G-code port (8899) -------------------------------------------------------
_OK = re.compile(rb"(^|\n)ok\r?\n")
_LEGACY_STATES = {"READY": "IDLE", "IDLE": "IDLE", "BUILDING_COMPLETED": "FINISH", "PAUSED": "PAUSE",
                  "BUSY": "PREPARE", "ERROR": "FAILED", "PRINTING": "RUNNING"}


class LegacyClient:
    """Port 8899: `~` prefixed G-codes, replies end with a line `ok`."""

    def __init__(self, host: str, port: int = TCP_PORT, timeout: float = 5):
        self.sock = socket.create_connection((host, port), timeout=timeout)
        try:
            reply = self.command("M601 S1")
        except Exception:
            self.sock.close()
            raise
        if "control success" not in reply.lower():
            self.sock.close()
            raise ConnectionError("the printer refused control (is another program connected to it?)")

    def command(self, cmd: str) -> str:
        self.sock.sendall(f"~{cmd}\r\n".encode())
        buf = b""
        while not _OK.search(buf):
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("the printer closed the connection")
            buf += chunk
            if len(buf) > 65536:
                raise ValueError("reply too long")
        return buf.decode("utf-8", "replace")

    def close(self):
        try:
            self.command("M602")
        except (OSError, ValueError):
            pass
        finally:
            self.sock.close()


def legacy_query(host: str, port: int, commands: list[str], timeout: float = 5) -> list[str]:
    """One short session: take control, run the commands, always release and disconnect."""
    client = LegacyClient(host, port, timeout=timeout)
    try:
        return [client.command(c) for c in commands]
    finally:
        client.close()


def _fields(reply: str) -> dict:
    out = {}
    for line in reply.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip():
            out.setdefault(key.strip(), value.strip())
    return out


def build_legacy_message(name: str, model: str, m119: str, m27: str, m105: str) -> dict:
    """The board's `printer` entry from the ~M119, ~M27 and ~M105 replies."""
    f = _fields(m119)
    raw = f.get("MachineStatus", "").upper()
    state = "RUNNING" if raw.startswith("BUILDING") and raw != "BUILDING_COMPLETED" else _LEGACY_STATES.get(raw, "IDLE")
    if state == "RUNNING" and f.get("MoveMode", "").upper() == "PAUSED":
        state = "PAUSE"
    active = state in ("RUNNING", "PAUSE")
    shows_job = active or state == "FINISH"

    pct = 0.0
    m = re.search(r"byte\s+(\d+)\s*/\s*(\d+)", m27)
    if m and int(m.group(2)):
        pct = int(m.group(1)) / int(m.group(2)) * 100
    m = re.search(r"Layer:\s*(\d+)\s*/\s*(\d+)", m27)
    layer, layers = (int(m.group(1)), int(m.group(2))) if m else (0, 0)

    temps = {k: (float(cur), float(tgt)) for k, cur, tgt in
             re.findall(r"\b(T0|B):\s*(-?\d+(?:\.\d+)?)\s*/\s*(-?\d+(?:\.\d+)?)", m105)}
    nozzle, bed = temps.get("T0", (None, None)), temps.get("B", (None, None))
    return make_message(
        name, model, state=state, pct=100 if state == "FINISH" else (pct if active else 0),
        layer=layer if shows_job else 0, layers=layers if shows_job else 0,
        file=_file_name(f.get("CurrentFile")) if shows_job else "",
        nozzle=nozzle[0], nozzle_target=nozzle[1], bed=bed[0], bed_target=bed[1],
        error="Printer error" if state == "FAILED" else "")


def _hint(e: Exception) -> str | None:
    if isinstance(e, FlashforgeError):
        if e.code == 1 and "sn" in e.text.lower():
            return "the printer says the serial number is wrong. Fix it with `deskhub-printers`."
        if e.code == 1:
            return "the printer refused the check code. Enter the current one with `deskhub-printers`."
        if e.code == -2:
            return "the printer's HTTP API is off. Turn on LAN-only mode in its network settings."
    return None


class FlashforgeWorker(PollingWorker):
    type = "flashforge"
    default_port = DEFAULT_PORT
    default_model = DEFAULT_MODEL
    LEGACY_POLL_S = 5.0  # each legacy poll is a whole control session; keep them sparse

    def __init__(self, entry: dict, secret_getter, client_factory=FlashforgeClient):
        super().__init__(entry, secret_getter)
        self.serial = str(entry.get("serial") or "").strip()
        self.factory = client_factory
        self._fixed_model = bool(entry.get("model"))
        self._legacy_model = self._fixed_model
        if not self.serial:
            self.POLL_S = self.LEGACY_POLL_S

    def _tcp_port(self) -> int:
        # The setup asks for the HTTP port; legacy printers left on it use 8899.
        return TCP_PORT if self.port == DEFAULT_PORT else self.port

    def open(self):
        if self.serial:
            return self.factory(self.host, self.port, self.serial, self.secret)
        # Nothing stays open on the G-code port: each poll runs its own session.
        return functools.partial(legacy_query, self.host, self._tcp_port())

    def hint(self, e):
        return _hint(e)

    def poll(self, conn) -> dict:
        if self.serial:
            d = conn.detail()
            if not self._fixed_model:
                self.model = model_from_pid(d.get("pid")) or self.model
            return build_message(self.label, self.model, d)
        replies = conn(["M119", "M27", "M105"] + ([] if self._legacy_model else ["M115"]))
        if not self._legacy_model:
            found = short_model(_fields(replies[3]).get("Machine Type") or "")
            if found:
                self.model = ascii_fold(found, 15)
            self._legacy_model = True
        return build_legacy_message(self.label, self.model, *replies[:3])


def probe(entry: dict, check_code: str | None, timeout: float = 5) -> ProbeResult:
    """Check the serial number and check code (or, without a serial, the G-code port)."""
    host, port = str(entry["host"]), int(entry.get("port") or DEFAULT_PORT)
    serial = str(entry.get("serial") or "").strip()
    if not serial:
        tcp = TCP_PORT if port == DEFAULT_PORT else port
        try:
            info = _fields(legacy_query(host, tcp, ["M115"], timeout=timeout)[0])
        except (OSError, ValueError) as e:
            return ProbeResult(False, f"No answer from {host_port(host, tcp)} ({_safe_error(e)}). Check the IP "
                                      "address. Adventurer 5M/AD5X: enter the serial number and check code.")
        return ProbeResult(True, "Connected over the G-code port (8899).",
                           info.get("Machine Name", ""), short_model(info.get("Machine Type", "")))
    if not check_code:
        return ProbeResult(False, "The HTTP API needs the check code from the printer's network settings.")
    client = FlashforgeClient(host, port, serial, check_code, timeout=timeout)
    try:
        d = client.detail()
        return ProbeResult(True, "Connected; the serial number and check code are right.",
                           str(d.get("name") or ""), model_from_pid(d.get("pid")))
    except FlashforgeError as e:
        if e.code == 1 and "sn" in e.text.lower():
            return ProbeResult(False, "The printer says the serial number is wrong. It is on the printer's "
                                      "About screen and starts with SN.")
        if e.code == 1:
            return ProbeResult(False, "The printer refused the check code. Check it on the printer's network "
                                      "settings screen (it changes if a new one is generated).")
        if e.code == -2:
            return ProbeResult(False, "The printer's HTTP API is off. Turn on LAN-only mode in its network "
                                      "settings, then try again.")
        return ProbeResult(False, f"The printer answered: {e.text or e.code}.")
    except httpx.HTTPStatusError as e:
        return ProbeResult(False, f"The printer answered with HTTP {e.response.status_code}. Is this the right port?")
    except (httpx.HTTPError, ValueError) as e:
        return ProbeResult(False, f"No answer from {host_port(host, port)} ({_safe_error(e, check_code)}). Check "
                                  "the IP address, and turn on LAN-only mode in the printer's network settings "
                                  "(some firmware closes port 8898 otherwise).")
    finally:
        client.close()


SPEC = BackendSpec(
    type="flashforge",
    menu="Flashforge: Adventurer 5M / 5M Pro, AD5X, Adventurer 3/4, Finder...",
    intro="""Flashforge printer
  Adventurer 5M / 5M Pro and AD5X: enter the serial number (About screen, starts with SN) and
  the check code from the network settings screen, the same pair Orca-Flashforge uses in LAN
  mode. Turn on LAN-only mode if the printer doesn't answer. The port is 8898.
  Adventurer 3/4, Creator Pro, Finder and other older printers: leave the serial number empty;
  the companion then uses the G-code port 8899, which needs no code.""",
    default_port=DEFAULT_PORT,
    default_model=DEFAULT_MODEL,
    probe=probe,
    fields=[Field("serial", "Serial number (empty for Adventurer 3/4, Finder and older)", required=False)],
    secret_prompt="Check code (hidden, empty for older printers)",
    brand="Flashforge",
)
WORKER = FlashforgeWorker
