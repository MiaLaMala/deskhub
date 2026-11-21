"""Prusa printers through PrusaLink's local v1 HTTP API, for the board's printer page.

Covers the MK4/MK4S, MK3.9, MK3.5, XL, MINI/MINI+ and CORE One. Each printer gets a worker
thread that polls `/api/v1/status`; the file name comes from `/api/v1/job`, fetched once per job.
Authentication is HTTP Digest (user "maker" by default, plus the password shown on the printer
under Settings > Network > PrusaLink).
"""
import re

import httpx

from .calendar_feed import _safe_error
from .printer import _num
from .printer_poll import BackendSpec, Field, PollingWorker, ProbeResult, host_port
from .text import ascii_fold

DEFAULT_PORT = 80
DEFAULT_USER = "maker"
ATTENTION_TEXT = "Needs attention on the printer"
# PrusaLink printer states (spec/openapi.yaml, StatusPrinter.state) -> the board's.
_STATES = {"IDLE": "IDLE", "READY": "IDLE", "STOPPED": "IDLE", "BUSY": "PREPARE",
           "PRINTING": "RUNNING", "PAUSED": "PAUSE", "FINISHED": "FINISH", "ERROR": "FAILED",
           "ATTENTION": "FAILED"}


def _file_name(file: dict) -> str:
    name = str(file.get("display_name") or file.get("name") or "").replace("\\", "/").rsplit("/", 1)[-1]
    return re.sub(r"\.(gcode|g|gco|bgcode)$", "", name, flags=re.I)


def build_message(name: str, model: str, status: dict, job: dict) -> dict:
    """The board's `printer` entry from /api/v1/status and the current job (/api/v1/job, or {})."""
    printer = status.get("printer") or {}
    raw = str(printer.get("state") or "").upper()
    sj = status.get("job") or {}
    state = _STATES.get(raw, "IDLE")
    if raw == "ATTENTION" and sj.get("id") is not None:
        state = "PAUSE"  # filament runout, crash, confirm dialog mid-print; the job resumes after
    active = state in ("RUNNING", "PAUSE", "PREPARE")

    error = ""
    if raw == "ATTENTION":
        error = ATTENTION_TEXT
    elif raw == "ERROR":
        msg = printer.get("status_printer")
        text = str(msg.get("message") or "") if isinstance(msg, dict) and not msg.get("ok", True) else ""
        error = text.strip().splitlines()[0] if text.strip() else "Printer error"

    progress = _num(sj.get("progress")) if "progress" in sj else _num(job.get("progress"))
    remaining = _num(sj.get("time_remaining")) if "time_remaining" in sj else _num(job.get("time_remaining"))
    pct = max(0.0, min(progress or 0, 100)) if active else (100.0 if state == "FINISH" else 0.0)
    shows_file = (active or state == "FINISH") and isinstance(job.get("file"), dict)
    speed = _num(printer.get("speed"))

    return {"name": ascii_fold(name, 24), "model": ascii_fold(model, 15), "online": True,
            "state": state, "pct": int(pct),
            "remaining_min": round(max(remaining or 0, 0) / 60) if active else 0,
            "layer": 0, "layers": 0,
            "file": ascii_fold(_file_name(job["file"]), 40) if shows_file else "",
            "nozzle": _num(printer.get("temp_nozzle")), "nozzle_target": _num(printer.get("target_nozzle")),
            "bed": _num(printer.get("temp_bed")), "bed_target": _num(printer.get("target_bed")),
            "chamber": None, "speed": f"{round(speed)}%" if speed and active else "",
            "error": ascii_fold(error, 47), "ams": []}


class PrusaLinkClient:
    def __init__(self, host: str, port: int = DEFAULT_PORT, user: str = DEFAULT_USER,
                 password: str | None = None, timeout: float = 5):
        auth = httpx.DigestAuth(user or DEFAULT_USER, password) if password else None
        # Digest only: never send the password itself over plain HTTP.
        self.http = httpx.Client(base_url=f"http://{host_port(host, port)}", auth=auth,
                                 timeout=timeout)

    def close(self):
        self.http.close()

    def status(self) -> dict:
        r = self.http.get("/api/v1/status")
        r.raise_for_status()
        return r.json()

    def job(self) -> dict:
        r = self.http.get("/api/v1/job")
        if r.status_code in (204, 404):
            return {}
        r.raise_for_status()
        return r.json()

    def info(self) -> dict:
        """/api/v1/info where it exists, else {} (older PrusaLink only has /api/version)."""
        r = self.http.get("/api/v1/info")
        if r.status_code == 404:
            return {}
        r.raise_for_status()
        return r.json()


class PrusaLinkWorker(PollingWorker):
    type = "prusalink"
    default_port = DEFAULT_PORT
    default_model = "Prusa"

    def __init__(self, entry: dict, secret_getter, client_factory=PrusaLinkClient):
        super().__init__(entry, secret_getter)
        self.user = str(entry.get("user") or DEFAULT_USER)
        self.factory = client_factory
        self._job_id = None
        self._job: dict = {}

    def open(self):
        return self.factory(self.host, self.port, self.user, self.secret)

    def reset(self):
        self._job_id, self._job = None, {}

    def hint(self, e):
        if getattr(getattr(e, "response", None), "status_code", None) in (401, 403):
            return ("PrusaLink refused the login. Check the PrusaLink password on the printer's screen "
                    "(Settings > Network > PrusaLink) and the user name, then run `deskhub-printers` again.")
        return None

    def poll(self, client) -> dict:
        status = client.status()
        sj = status.get("job") or {}
        job_id = sj.get("id")
        if job_id is None:
            self._job_id, self._job = None, {}
        elif job_id != self._job_id or not self._job:
            self._job = client.job()
            self._job_id = job_id
        return build_message(self.label, self.model, status, self._job)


def probe(entry: dict, password: str | None, timeout: float = 5) -> ProbeResult:
    """Check that PrusaLink answers and the login works; suggests the printer's hostname."""
    host, port = str(entry["host"]), int(entry.get("port") or DEFAULT_PORT)
    client = PrusaLinkClient(host, port, str(entry.get("user") or DEFAULT_USER), password, timeout=timeout)
    try:
        status = client.status()
        try:
            info = client.info()
        except (httpx.HTTPError, ValueError):
            info = {}
        name = str(info.get("hostname") or info.get("name") or "")
        state = str((status.get("printer") or {}).get("state") or "").upper()
        return ProbeResult(True, f"Connected, printer is {state.lower() or 'reachable'}.", name)
    except httpx.HTTPStatusError as e:
        if e.response.status_code in (401, 403):
            return ProbeResult(False, "PrusaLink refused the login. Check the user name and the PrusaLink "
                                      "password on the printer's screen (Settings > Network > PrusaLink).")
        return ProbeResult(False, f"PrusaLink answered with HTTP {e.response.status_code}. Is this the right port?")
    except (httpx.HTTPError, ValueError) as e:
        return ProbeResult(False, f"No answer from {host_port(host, port)} ({_safe_error(e, password or '')}). "
                                  "Check the printer's IP address (PrusaLink is on port 80).")
    finally:
        client.close()


SPEC = BackendSpec(
    type="prusalink",
    menu="Prusa (PrusaLink): MK4/MK4S, MK3.9, MK3.5, XL, MINI, CORE One",
    intro="""Prusa printer (PrusaLink)
  For Prusa printers with PrusaLink enabled: MK4/MK4S, MK3.9, MK3.5, XL, MINI/MINI+ and CORE One.
  On the printer, open Settings > Network > PrusaLink for the IP address, the user name (usually
  "maker") and the password.""",
    default_port=DEFAULT_PORT,
    default_model="Prusa",
    probe=probe,
    fields=[Field(key="user", prompt="PrusaLink user name", default=DEFAULT_USER)],
    secret_prompt="PrusaLink password (hidden)",
    secret_required=True,
    brand="PrusaLink",
)
WORKER = PrusaLinkWorker
