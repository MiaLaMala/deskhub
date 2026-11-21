"""Printers driven by OctoPrint, for the board's printer page.

Covers older Creality Enders, Prusa MK3S, Anycubic i3 Mega and Marlin printers generally. Each
printer gets a worker thread that polls `/api/job` and `/api/printer` with an application key
(or the global API key). Layer numbers come from the DisplayLayerProgress plugin when it is
installed.
"""
import re

import httpx

from .calendar_feed import _safe_error
from .printer import _int, _num
from .printer_poll import BackendSpec, PollingWorker, ProbeResult, host_port, make_message

DEFAULT_PORT = 80
NOT_CONNECTED = "OctoPrint isn't connected to the printer"
_LAYER_PATH = "/plugin/DisplayLayerProgress/values"


def _file_name(job_file: dict) -> str:
    name = str(job_file.get("display") or job_file.get("name") or "")
    name = name.replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(gcode|gco|g)$", "", name, flags=re.I)


def _temp(printer: dict, key: str) -> tuple:
    t = (printer.get("temperature") or {}).get(key)
    t = t if isinstance(t, dict) else {}
    return _num(t.get("actual")), _num(t.get("target"))


def build_message(name: str, model: str, job: dict, printer: dict | None, layers=(0, 0)) -> dict:
    """The board's `printer` entry from /api/job, /api/printer (None when OctoPrint answered
    409: it isn't connected to the printer) and the optional (layer, layers)."""
    text = str(job.get("state") or "").strip()
    low = text.lower()
    progress = job.get("progress") if isinstance(job.get("progress"), dict) else {}
    jfile = (job.get("job") or {}).get("file")
    fname = _file_name(jfile) if isinstance(jfile, dict) else ""
    completion = _num(progress.get("completion")) or 0
    nozzle, nozzle_t = _temp(printer or {}, "tool0")
    bed, bed_t = _temp(printer or {}, "bed")
    chamber, _ = _temp(printer or {}, "chamber")

    error = ""
    if low.startswith("error") or "after error" in low:  # before the 409 check: OctoPrint is closed then
        state = "FAILED"
        error = text.split(":", 1)[1].strip() if ":" in text else "Printer error"
    elif printer is None or low.startswith(("offline", "opening serial", "detecting serial",
                                            "connecting", "closed")):
        state, error = "IDLE", NOT_CONNECTED
    elif low in ("paused", "pausing"):
        state = "PAUSE"
    elif low in ("starting", "starting print from sd", "sending file to sd", "transferring file to sd"):
        state = "PREPARE"
    elif low.startswith("printing") or low in ("finishing", "resuming"):
        state = "RUNNING"
        if not completion and nozzle_t and nozzle is not None and nozzle < nozzle_t - 5:
            state = "PREPARE"  # heating: nothing printed yet
    elif low == "operational" and fname and completion >= 100:
        state = "FINISH"
    else:  # Operational, Cancelling, Unknown
        state = "IDLE"
    active = state in ("RUNNING", "PAUSE", "PREPARE")
    shown = active or state == "FINISH"

    left = _num(progress.get("printTimeLeft"))
    layer, total = layers if shown else (0, 0)
    return make_message(name, model, state=state, pct=100 if state == "FINISH" else completion if active else 0,
                        remaining_min=(left or 0) / 60 if active else 0,
                        layer=layer, layers=total, file=fname if shown else "",
                        nozzle=nozzle, nozzle_target=nozzle_t, bed=bed, bed_target=bed_t,
                        chamber=chamber, error=error)


class OctoPrintClient:
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
        data = r.json()
        return data if isinstance(data, dict) else {}

    def job(self) -> dict:
        return self._get("/api/job")

    def printer(self) -> dict | None:
        """None on 409: OctoPrint is up but not connected to the printer."""
        try:
            return self._get("/api/printer")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 409:
                return None
            raise

    def layers(self) -> tuple[int, int]:
        layer = self._get(_LAYER_PATH).get("layer") or {}
        return _int(layer.get("current")), _int(layer.get("total"))

    def version(self) -> dict:
        return self._get("/api/version")

    def settings(self) -> dict:
        return self._get("/api/settings")


class OctoPrintWorker(PollingWorker):
    type = "octoprint"
    default_port = DEFAULT_PORT
    default_model = "OctoPrint"

    def __init__(self, entry: dict, secret_getter, client_factory=OctoPrintClient):
        super().__init__(entry, secret_getter)
        self.factory = client_factory
        self._layer_plugin = True  # cleared when the plugin endpoint answers with an error status

    def open(self):
        return self.factory(self.host, self.port, self.secret)

    def reset(self):
        self._layer_plugin = True

    def hint(self, e):
        if getattr(getattr(e, "response", None), "status_code", None) in (401, 403):
            return ("OctoPrint rejected the API key. Create an application key under OctoPrint "
                    "Settings > Application Keys and re-run `deskhub-printers`.")
        return None

    def poll(self, client) -> dict:
        job = client.job()
        printer = client.printer()
        layers = (0, 0)
        if printer is not None and self._layer_plugin and str(job.get("state") or "").lower() in (
                "printing", "pausing", "paused", "printing from sd", "finishing", "resuming",
                "operational"):
            try:
                layers = client.layers()
            except httpx.HTTPStatusError:
                self._layer_plugin = False
            except (httpx.HTTPError, ValueError):
                pass  # a hiccup: try again next poll
        return build_message(self.label, self.model, job, printer, layers)


def probe(entry: dict, api_key: str | None, timeout: float = 5) -> ProbeResult:
    """Check the key works; suggests OctoPrint's instance name (appearance.name) as the name."""
    host, port = str(entry["host"]), int(entry.get("port") or DEFAULT_PORT)
    client = OctoPrintClient(host, port, api_key, timeout=timeout)
    try:
        version = client.version()
        name = ""
        try:
            name = str((client.settings().get("appearance") or {}).get("name") or "")
        except (httpx.HTTPError, ValueError):
            pass  # settings need more rights than a read-only key may have
        v = str(version.get("text") or version.get("server") or "OctoPrint")
        return ProbeResult(True, f"Connected to {v}.", name)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return ProbeResult(False, "OctoPrint rejected the API key. Create an application key under "
                                      "OctoPrint Settings > Application Keys and enter it here.")
        return ProbeResult(False, f"OctoPrint answered with HTTP {e.response.status_code}. Is this the right port?")
    except (httpx.HTTPError, ValueError) as e:
        return ProbeResult(False, f"No answer from {host_port(host, port)} ({_safe_error(e, api_key or '')}). "
                                  "Check the IP address and port (OctoPrint is on 80 behind OctoPi's proxy, "
                                  "5000 when run directly).")
    finally:
        client.close()


SPEC = BackendSpec(
    type="octoprint",
    menu="OctoPrint: Ender, Prusa MK3S, Anycubic i3 Mega and other Marlin printers...",
    intro="""OctoPrint
  For printers controlled through OctoPrint (OctoPi on a Raspberry Pi): older Creality Enders,
  Prusa MK3S, Anycubic i3 Mega and Marlin printers generally.
  OctoPi listens on port 80; use 5000 if you run OctoPrint directly.
  You need an API key: OctoPrint Settings > Application Keys (or the global API key under
  Settings > API). The key is kept in the OS credential store, not in config.toml.""",
    default_port=DEFAULT_PORT,
    default_model="OctoPrint",
    probe=probe,
    secret_prompt="API key (hidden)",
    secret_required=True,
    brand="OctoPrint",
)
WORKER = OctoPrintWorker
