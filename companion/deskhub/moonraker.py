"""Klipper printers through Moonraker's HTTP API, for the board's printer page.

Covers anything running Klipper with Moonraker: Voron and other self-built printers, Sovol SV08,
Qidi, Elegoo Neptune 4, Snapmaker U1, and Creality K1/K2 where Moonraker is reachable. Each
printer gets a worker thread that polls `/printer/objects/query`; the slicer metadata for the
current file (estimated time, layer heights, filament colours) is fetched once per file.
"""
import math
import re
from urllib.parse import quote

import httpx

from .calendar_feed import _safe_error
from .printer import MAX_AMS, _COLOR, _int, _num
from .printer_poll import BackendSpec, PollingWorker, ProbeResult, host_port
from .text import ascii_fold

DEFAULT_PORT = 7125
_STATES = {"printing": "RUNNING", "paused": "PAUSE", "complete": "FINISH", "error": "FAILED",
           "cancelled": "IDLE", "standby": "IDLE"}
_BASE_OBJECTS = ["webhooks", "print_stats", "virtual_sdcard", "display_status", "gcode_move",
                 "toolhead", "heater_bed"]


def chamber_object(objects: list[str]) -> str | None:
    """The sensor or heater that reads chamber temperature, if the printer has one."""
    for kind in ("heater_generic", "temperature_sensor", "temperature_fan"):
        for o in objects:
            if o.startswith(kind + " ") and "chamber" in o.lower():
                return o
    return None


def _file_name(path: str) -> str:
    name = str(path or "").replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(gcode|g|gco|bgcode)$", "", name, flags=re.I)


def _colors(meta: dict) -> list[str]:
    raw = meta.get("filament_colors") or []
    if isinstance(raw, str):
        raw = raw.split(";")
    return [c.strip().lstrip("#") for c in raw if isinstance(c, str)]


def _float(v) -> float | None:
    """Like printer._num but unrounded (progress is a 0-1 fraction)."""
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return float(v)


def _progress(status: dict, meta: dict) -> float:
    """0-1. M73 from the slicer when it sends one, else the position in the file's G-code
    section (what Mainsail and Fluidd show), else the raw file position."""
    disp = _float((status.get("display_status") or {}).get("progress")) or 0
    if disp > 0:
        return min(disp, 1.0)
    sd = status.get("virtual_sdcard") or {}
    start, end = _float(meta.get("gcode_start_byte")), _float(meta.get("gcode_end_byte"))
    pos = _float(sd.get("file_position"))
    if start is not None and end and end > start and pos is not None:
        return max(0.0, min((pos - start) / (end - start), 1.0))
    return max(0.0, min(_float(sd.get("progress")) or 0, 1.0))


def build_message(name: str, model: str, status: dict, meta: dict) -> dict:
    """The board's `printer` entry from a Moonraker objects query and the file's metadata."""
    ps = status.get("print_stats") or {}
    hooks = status.get("webhooks") or {}
    raw_state = str(ps.get("state") or "standby")
    state = _STATES.get(raw_state, "IDLE")
    duration = float(_num(ps.get("print_duration")) or 0)
    if state == "RUNNING" and not _num(ps.get("filament_used")):
        state = "PREPARE"  # heating, homing, probing: nothing extruded yet
    active = state in ("RUNNING", "PAUSE", "PREPARE")

    error = ""
    if hooks.get("state") not in (None, "ready"):
        if hooks.get("state") in ("shutdown", "error"):
            state = "FAILED"
        error = str(hooks.get("state_message") or "").strip() or "Klipper is not ready"
    elif raw_state == "error":
        error = str(ps.get("message") or "").strip()
    error = error.splitlines()[0] if error else ""

    progress = _progress(status, meta) if active else (1.0 if state == "FINISH" else 0.0)
    remaining = 0
    if active:
        est = _num(meta.get("estimated_time"))
        if est:
            remaining = max(est - duration, 0)
        elif progress > 0.01 and duration > 0:
            remaining = duration / progress - duration

    info = ps.get("info") if isinstance(ps.get("info"), dict) else {}
    layers = _int(info.get("total_layer")) or _int(meta.get("layer_count"))
    layer = _int(info.get("current_layer"))
    if not layer and active and layers:
        # No SET_PRINT_STATS_INFO from the slicer: work it out from the nozzle height.
        pos = (status.get("gcode_move") or {}).get("gcode_position")
        z = _num(pos[2]) if isinstance(pos, list) and len(pos) > 2 else None
        first, height = _num(meta.get("first_layer_height")), _num(meta.get("layer_height"))
        if z and first and height:
            layer = max(1, min(math.ceil((z - first) / height + 1 - 1e-6), layers))
    if not active and state != "FINISH":
        layer = layers = 0

    toolhead = status.get("toolhead") or {}
    ext_name = str(toolhead.get("extruder") or "extruder")
    ext = status.get(ext_name) or status.get("extruder") or {}
    bed = status.get("heater_bed") or {}
    chamber = next((v for k, v in status.items() if k not in _BASE_OBJECTS and isinstance(v, dict)
                    and "chamber" in k.lower()), {})
    speed_factor = _num((status.get("gcode_move") or {}).get("speed_factor"))

    ams = []
    if active or state == "FINISH":
        # The file's filament colours, one per tool; on a toolchanger (Snapmaker U1...) the
        # tool in use is marked active.
        colors = _colors(meta)[:MAX_AMS]
        types = meta.get("filament_type") or ""
        types = [str(t) for t in types] if isinstance(types, list) else str(types).split(";")
        suffix = ext_name[len("extruder"):]
        tool = int(suffix) if suffix.isdigit() else 0
        for i, color in enumerate(colors):
            ams.append({"color": "#" + color[:6].upper() if _COLOR.fullmatch(color) else "#808080",
                        "type": ascii_fold(types[i].strip() if i < len(types) else "", 12),
                        "active": active and len(colors) > 1 and i == tool})

    return {"name": ascii_fold(name, 24), "model": model, "online": True,
            "state": state, "pct": int(progress * 100), "remaining_min": round(remaining / 60),
            "layer": layer, "layers": layers,
            "file": ascii_fold(_file_name(ps.get("filename")), 40) if active or state == "FINISH" else "",
            "nozzle": _num(ext.get("temperature")), "nozzle_target": _num(ext.get("target")),
            "bed": _num(bed.get("temperature")), "bed_target": _num(bed.get("target")),
            "chamber": _num(chamber.get("temperature")),
            "speed": f"{round(speed_factor * 100)}%" if speed_factor and active else "",
            "error": ascii_fold(error, 47), "ams": ams}


class MoonrakerClient:
    def __init__(self, host: str, port: int = DEFAULT_PORT, api_key: str | None = None,
                 timeout: float = 5):
        headers = {"X-Api-Key": api_key} if api_key else {}
        self.http = httpx.Client(base_url=f"http://{host_port(host, port)}", headers=headers,
                                 timeout=timeout)

    def close(self):
        self.http.close()

    def _get(self, path: str) -> dict:
        r = self.http.get(path)
        r.raise_for_status()
        return r.json().get("result") or {}

    def objects(self) -> list[str]:
        return list(self._get("/printer/objects/list").get("objects") or [])

    def query(self, objects: list[str]) -> dict:
        q = "&".join(quote(o, safe="") for o in objects)
        return self._get(f"/printer/objects/query?{q}").get("status") or {}

    def metadata(self, filename: str) -> dict:
        try:
            return self._get(f"/server/files/metadata?filename={quote(filename, safe='')}")
        except httpx.HTTPStatusError:
            return {}

    def info(self) -> dict:
        return self._get("/printer/info")


class MoonrakerWorker(PollingWorker):
    type = "moonraker"
    default_port = DEFAULT_PORT
    default_model = "Klipper"

    def __init__(self, entry: dict, secret_getter, client_factory=MoonrakerClient):
        super().__init__(entry, secret_getter)
        self.factory = client_factory
        self._objects: list[str] | None = None
        self._meta_for: str | None = None
        self._meta: dict = {}
        self._was_printing = False

    def open(self):
        return self.factory(self.host, self.port, self.secret)

    def reset(self):
        self._objects = None  # Klipper may come back with other sensors

    def hint(self, e):
        if getattr(getattr(e, "response", None), "status_code", None) in (401, 403):
            return ("Moonraker refused the request. Add this PC to trusted_clients in moonraker.conf, "
                    "or set an API key with `deskhub-printers`.")
        return None

    def poll(self, client) -> dict:
        if self._objects is None:
            available = client.objects()
            extruders = [o for o in available if re.fullmatch(r"extruder\d*", o)]
            chamber = chamber_object(available)
            self._objects = _BASE_OBJECTS + (extruders or ["extruder"]) + ([chamber] if chamber else [])
        status = client.query(self._objects)
        ps = status.get("print_stats") or {}
        filename = str(ps.get("filename") or "")
        printing = ps.get("state") in ("printing", "paused")
        # Refetch for a new file, a new job (the same name may have been re-sliced), or after
        # a failed fetch.
        if filename != self._meta_for or (printing and not self._was_printing) or (filename and not self._meta):
            self._meta = client.metadata(filename) if filename else {}
            self._meta_for = filename
        self._was_printing = printing
        return build_message(self.label, self.model, status, self._meta)


def probe(entry: dict, api_key: str | None, timeout: float = 5) -> ProbeResult:
    """Check that Moonraker answers; suggests the printer's hostname as its name."""
    host, port = str(entry["host"]), int(entry.get("port") or DEFAULT_PORT)
    client = MoonrakerClient(host, port, api_key, timeout=timeout)
    try:
        info = client.info()
        state = str(info.get("state") or "")
        name = str(info.get("hostname") or "")
        if state and state != "ready":
            return ProbeResult(True, f"Moonraker answered, but Klipper is {state}. It is saved anyway.", name)
        return ProbeResult(True, "Connected and Klipper is ready.", name)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return ProbeResult(False, "Moonraker wants authorization. Add this PC's network to trusted_clients "
                                      "in moonraker.conf, or enter an API key (Mainsail/Fluidd settings).")
        return ProbeResult(False, f"Moonraker answered with HTTP {e.response.status_code}. Is this the right port?")
    except (httpx.HTTPError, ValueError) as e:
        return ProbeResult(False, f"No answer from {host_port(host, port)} ({_safe_error(e, api_key or '')}). "
                                  "Check the IP address and port (Moonraker is usually 7125; try 80 if "
                                  "Mainsail or Fluidd is in front of it).")
    finally:
        client.close()


SPEC = BackendSpec(
    type="moonraker",
    menu="Klipper (Moonraker): Voron, Sovol, Qidi, Creality K1/K2, Snapmaker U1...",
    intro="""Klipper printer (Moonraker)
  For printers running Klipper with Moonraker: Voron and other self-built printers, Sovol SV08,
  Qidi, Elegoo Neptune 4, Snapmaker U1, and Creality K1/K2 with Moonraker enabled. If you open
  Mainsail or Fluidd in a browser to control the printer, this is the one.
  Moonraker listens on port 7125; use 80 if you only reach it through Mainsail/Fluidd.
  Most setups let devices on the home network in without a key (trusted_clients in
  moonraker.conf); otherwise enter an API key from Mainsail/Fluidd's settings.""",
    default_port=DEFAULT_PORT,
    default_model="Klipper",
    probe=probe,
    secret_prompt="API key (hidden, empty if none)",
    brand="Moonraker",
)
WORKER = MoonrakerWorker
