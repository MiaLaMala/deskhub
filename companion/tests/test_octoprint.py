"""OctoPrint printer support without a printer: message building from sample replies, the
worker and probe against a tiny local HTTP server, and the CLI.

    uv run python tests/test_octoprint.py
Prints OK or the problems found. Never touches the OS credential store.
"""
import builtins
import functools
import getpass
import json
import pathlib
import sys
import tempfile
import threading
import time
import tomllib
import types
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


store: dict = {}
kr = types.ModuleType("keyring")
kr.errors = types.SimpleNamespace(PasswordDeleteError=type("PasswordDeleteError", (Exception,), {}))
kr.set_password = lambda s, k, v: store.__setitem__((s, k), v)
kr.get_password = lambda s, k: store.get((s, k))


def _del(s, k):
    if (s, k) not in store:
        raise kr.errors.PasswordDeleteError()
    del store[(s, k)]


kr.delete_password = _del
sys.modules["keyring"] = kr

from deskhub import octoprint as op  # noqa: E402
from deskhub import printer as pr  # noqa: E402
from deskhub import printer_poll as poll  # noqa: E402
from deskhub import printers_cli  # noqa: E402
from deskhub.pages import enabled_pages  # noqa: E402


# ---- sample replies --------------------------------------------------------------
def job(state="Printing", completion=31.4, left=5400, name="parts/Bracket v2.gcode", display=None):
    f = {"name": name, "origin": "local"}
    if display:
        f["display"] = display
    return {"state": state, "job": {"file": f if name else {}},
            "progress": {"completion": completion, "printTime": 1800, "printTimeLeft": left}}


def printer(nozzle=(214.8, 215), bed=(59.9, 60), chamber=None):
    t = {"tool0": {"actual": nozzle[0], "target": nozzle[1], "offset": 0},
         "bed": {"actual": bed[0], "target": bed[1], "offset": 0}}
    if chamber is not None:
        t["chamber"] = {"actual": chamber, "target": None, "offset": 0}
    return {"temperature": t, "state": {"text": "Printing", "flags": {}}}


m = op.build_message("Ender", "Ender 3", job(), printer(chamber=31.2), (60, 250))
check(m == {"name": "Ender", "model": "Ender 3", "online": True, "state": "RUNNING", "pct": 31,
            "remaining_min": 90, "layer": 60, "layers": 250, "file": "Bracket v2", "nozzle": 214.8,
            "nozzle_target": 215, "bed": 59.9, "bed_target": 60, "chamber": 31.2, "speed": "",
            "error": "", "ams": []}, f"printing: {m}")
json.dumps(m)

m = op.build_message("E", "O", job(display="Nice Name.gcode"), printer())
check(m["file"] == "Nice Name" and m["chamber"] is None and m["layers"] == 0, f"display name: {m}")
m = op.build_message("E", "O", job(state="Printing from SD"), printer())
check(m["state"] == "RUNNING", f"printing from SD: {m}")
m = op.build_message("E", "O", job(completion=0, left=None), printer(nozzle=(120, 215)))
check(m["state"] == "PREPARE" and m["remaining_min"] == 0, f"heating: {m}")
m = op.build_message("E", "O", job(state="Starting", completion=None), printer())
check(m["state"] == "PREPARE", f"starting: {m}")
for text in ("Paused", "Pausing"):
    m = op.build_message("E", "O", job(state=text), printer())
    check(m["state"] == "PAUSE" and m["pct"] == 31, f"{text}: {m}")
m = op.build_message("E", "O", job(state="Finishing"), printer())
check(m["state"] == "RUNNING", f"finishing: {m}")
m = op.build_message("E", "O", job(state="Cancelling"), printer())
check(m["state"] == "IDLE" and m["file"] == "" and m["pct"] == 0, f"cancelling: {m}")
m = op.build_message("E", "O", job(state="Operational", completion=100, left=0), printer((30, 0), (25, 0)), (250, 250))
check(m["state"] == "FINISH" and m["pct"] == 100 and m["file"] == "Bracket v2" and m["remaining_min"] == 0
      and m["layers"] == 250 and m["nozzle"] == 30, f"finished: {m}")
m = op.build_message("E", "O", job(state="Operational", completion=None, name=None), printer((30, 0), (25, 0)))
check(m["state"] == "IDLE" and m["file"] == "" and m["error"] == "", f"idle: {m}")
m = op.build_message("E", "O", job(state="Operational", completion=40), printer((30, 0), (25, 0)))
check(m["state"] == "IDLE", f"operational, cancelled partway: {m}")
m = op.build_message("E", "O", job(state="Error: Heating failed, system stopped!", completion=12), printer())
check(m["state"] == "FAILED" and m["error"].startswith("Heating failed") and len(m["error"]) <= 47, f"error: {m}")
m = op.build_message("E", "O", job(state="Offline after error"), printer())
check(m["state"] == "FAILED", f"offline after error: {m}")
# Offline after error comes with a 409 from /api/printer: still FAILED, not "not connected".
m = op.build_message("E", "O", job(state="Offline after error"), None)
check(m["state"] == "FAILED" and m["error"] == "Printer error" and m["online"], f"offline after error, 409: {m}")
m = op.build_message("E", "O", job(state="Error: Heating failed"), None)
check(m["state"] == "FAILED" and m["error"] == "Heating failed", f"error, 409: {m}")
m = op.build_message("E", "O", job(state="Resuming"), printer(), (60, 250))
check(m["state"] == "RUNNING" and m["file"] == "Bracket v2" and m["pct"] == 31 and m["layer"] == 60,
      f"resuming: {m}")
# 409 from /api/printer: OctoPrint is up, the printer is not connected to it.
m = op.build_message("E", "O", job(state="Offline", completion=None, name=None), None)
check(m["online"] and m["state"] == "IDLE" and m["error"] == "OctoPrint isn't connected to the printer"
      and m["nozzle"] is None, f"not connected: {m}")


# ---- a tiny OctoPrint ------------------------------------------------------------
class Fake:
    job = job()
    printer = printer()
    api_key = None
    layers = {"layer": {"current": "60", "total": "250"}}  # None: plugin not installed
    layer_hits = 0
    settings_ok = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if Fake.api_key and self.headers.get("X-Api-Key") != Fake.api_key:
            return self._send(403, {"error": "Forbidden"})
        path = self.path.split("?")[0]
        if path == "/api/version":
            return self._send(200, {"api": "0.1", "server": "1.10.2", "text": "OctoPrint 1.10.2"})
        if path == "/api/settings":
            if not Fake.settings_ok:
                return self._send(403, {"error": "Forbidden"})
            return self._send(200, {"appearance": {"name": "Garage Ender"}})
        if path == "/api/job":
            return self._send(200, Fake.job)
        if path == "/api/printer":
            if Fake.printer is None:
                return self._send(409, "Printer is not operational")
            return self._send(200, Fake.printer)
        if path == "/plugin/DisplayLayerProgress/values":
            Fake.layer_hits += 1
            if Fake.layers is None:
                return self._send(404, {"error": "not found"})
            return self._send(200, Fake.layers)
        self._send(404, {"error": "not found"})


srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]


def wait_for(cond, secs=8):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


op.OctoPrintWorker.POLL_S = 0.1
entry = {"name": "Ender", "type": "octoprint", "host": "127.0.0.1", "port": PORT, "model": "Ender 3"}
svc = pr.PrinterService([entry, {"name": "x", "type": "octoprint"}],
                        secret_getter=lambda s, k: store.get((s, k)))
check(len(svc.workers) == 1 and type(svc.workers[0]).__name__ == "OctoPrintWorker", "entry without host skipped")
svc.start()
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "RUNNING"), "octoprint: state arrives")
p = svc.message()["printers"][0]
check(p["layer"] == 60 and p["layers"] == 250 and p["model"] == "Ender 3" and p["nozzle"] == 214.8,
      f"service message: {p}")
Fake.printer = None
Fake.job = job(state="Offline", completion=None, name=None)
check(wait_for(lambda: svc.message()["printers"][0]["error"] == op.NOT_CONNECTED), "409 -> online, idle, error")
check(svc.message()["printers"][0]["state"] == "IDLE" and svc.message()["printers"][0]["online"], "409 state")
Fake.printer = printer((30, 0), (25, 0))
Fake.job = job(state="Operational", completion=100, left=0)
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "FINISH"), "octoprint: finish arrives")
w = svc.workers[0]
check(w.message(now=time.monotonic() + pr.STALE_S + 1)["state"] == "OFFLINE", "stale -> OFFLINE")
svc.stop()

# Without the layer plugin: no layers, and the endpoint is left alone after the first 404.
Fake.layers, Fake.layer_hits = None, 0
Fake.job, Fake.printer = job(), printer()
nolayer = pr.PrinterService([entry], secret_getter=lambda s, k: None)
nolayer.start()
check(wait_for(lambda: nolayer.message()["printers"][0]["state"] == "RUNNING"), "no plugin: state arrives")
time.sleep(0.5)
check(nolayer.message()["printers"][0]["layers"] == 0 and Fake.layer_hits == 1,
      f"no plugin: layers 0, endpoint asked {Fake.layer_hits} times")
nolayer.stop()
Fake.layers = {"layer": {"current": "60", "total": "250"}}

# Unreachable: offline, one log line, no crash.
logs = []
handler = type("H", (poll.logging.Handler,), {"emit": lambda self, rec: logs.append(rec.getMessage())})()
poll.log.addHandler(handler)
dead = pr.PrinterService([{"name": "Gone", "type": "octoprint", "host": "127.0.0.1", "port": 1}],
                         secret_getter=lambda s, k: None)
op.OctoPrintWorker.RETRY_S = 0.1
dead.start()
check(wait_for(lambda: len(logs) >= 1), "unreachable logs a line")
time.sleep(0.5)
check(len(logs) == 1 and dead.message()["printers"][0]["state"] == "OFFLINE", f"unreachable: {logs}")
dead.stop()

# API key: rejected without it (clear hint), works with it from the credential store.
Fake.api_key = "KEY123"
logs.clear()
store[(poll.SERVICE, poll.secret_key("octoprint", "127.0.0.1", PORT))] = "KEY123"
keyed = pr.PrinterService([entry], secret_getter=lambda s, k: store.get((s, k)))
keyed.start()
check(wait_for(lambda: keyed.message()["printers"][0]["online"]), "api key from credential store")
keyed.stop()
store.clear()
nokey = pr.PrinterService([entry], secret_getter=lambda s, k: store.get((s, k)))
nokey.start()
check(wait_for(lambda: any("rejected the API key" in line for line in logs)), f"403 hint: {logs}")
check(not any("KEY123" in line for line in logs), "key not logged")
nokey.stop()
poll.log.removeHandler(handler)

r = op.probe({"host": "127.0.0.1", "port": PORT}, "KEY123")
check(r.ok and r.name == "Garage Ender" and "1.10.2" in r.message, f"probe ok: {r}")
Fake.settings_ok = False
r = op.probe({"host": "127.0.0.1", "port": PORT}, "KEY123")
check(r.ok and r.name == "", f"probe ok without settings: {r}")
Fake.settings_ok = True
r = op.probe({"host": "127.0.0.1", "port": PORT}, "WRONG")
check(not r.ok and "rejected the API key" in r.message and "WRONG" not in r.message, f"probe 403: {r}")
r = op.probe({"host": "127.0.0.1", "port": 1}, "KEY123", timeout=1)
check(not r.ok and "No answer" in r.message and "KEY123" not in r.message, f"probe unreachable: {r}")
Fake.api_key = None

check("printer" in enabled_pages({"printers": [entry]}), "printer page auto-added for octoprint")

# ---- the CLI --------------------------------------------------------------------
tmp = pathlib.Path(tempfile.mkdtemp()) / "config.toml"
tmp.write_text('# my config\n[hub]\nhost = "x"\n', encoding="utf-8")

ADD = functools.partial(printers_cli.cmd_add_polled, spec=op.SPEC)


def run(cmd, answers, passwords):
    a, p = iter(answers), iter(passwords)
    builtins.input = lambda prompt="": next(a)
    getpass.getpass = lambda prompt="": next(p)
    cmd(tmp)


Fake.api_key = "KEY123"
run(ADD, ["127.0.0.1", str(PORT), "", "Ender 3 V2"], ["KEY123"])
cfg = tomllib.loads(tmp.read_text())
check(cfg["printers"] == [{"name": "Garage Ender", "type": "octoprint", "host": "127.0.0.1", "port": PORT,
                           "model": "Ender 3 V2"}], f"octoprint saved: {cfg.get('printers')}")
check(store.get((poll.SERVICE, poll.secret_key("octoprint", "127.0.0.1", PORT))) == "KEY123"
      and "KEY123" not in tmp.read_text(), "api key in credential store only")
Fake.api_key = None
op.SPEC.probe = lambda *a, **k: poll.ProbeResult(False, "No answer (stubbed)")
run(ADD, ["192.168.1.90", "", "y", "", ""], ["SECRETKEY"])
cfg = tomllib.loads(tmp.read_text())
check(cfg["printers"][1] == {"name": "OctoPrint", "type": "octoprint", "host": "192.168.1.90"},
      f"default port and model left out: {cfg['printers'][1]}")
check(store.get((poll.SERVICE, "octoprint:192.168.1.90:80")) == "SECRETKEY" and "SECRETKEY" not in tmp.read_text(),
      "key stored under octoprint:host:80")
check("OctoPrint 192.168.1.90:80" in printers_cli.describe(cfg["printers"][1]), "describe")

srv.shutdown()
print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
