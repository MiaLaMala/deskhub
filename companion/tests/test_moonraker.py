"""Klipper/Moonraker printer support without a printer: message building from sample
status, the worker and probe against a tiny local HTTP server, and the CLI.

    uv run python tests/test_moonraker.py
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
from urllib.parse import parse_qs, unquote, urlsplit

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

from deskhub import moonraker as mr  # noqa: E402
from deskhub import printer as pr  # noqa: E402
from deskhub import printer_poll as poll  # noqa: E402
from deskhub import printers_cli  # noqa: E402
from deskhub.pages import enabled_pages  # noqa: E402

# ---- sample status ---------------------------------------------------------------
META = {"estimated_time": 7200, "layer_count": 250, "first_layer_height": 0.2, "layer_height": 0.2,
        "gcode_start_byte": 1000, "gcode_end_byte": 11000,
        "filament_colors": ["#FF0000", "#00FF00"], "filament_type": "PLA;PETG"}


def status(**over):
    s = {"webhooks": {"state": "ready", "state_message": "Printer is ready"},
         "print_stats": {"state": "printing", "filename": "parts/Bracket v2.gcode", "print_duration": 1800,
                         "filament_used": 523.1, "message": "", "info": {"current_layer": 60, "total_layer": 250}},
         "virtual_sdcard": {"progress": 0.31, "file_position": 4000},
         "display_status": {"progress": 0},
         "gcode_move": {"speed_factor": 1.2, "gcode_position": [10, 20, 12.0, 100]},
         "toolhead": {"extruder": "extruder1"},
         "extruder": {"temperature": 30.04, "target": 0},
         "extruder1": {"temperature": 244.96, "target": 245},
         "heater_bed": {"temperature": 99.8, "target": 100},
         "temperature_sensor chamber": {"temperature": 48.2}}
    for k, v in over.items():
        s[k] = {**s.get(k, {}), **v} if isinstance(v, dict) else v
    return s


m = mr.build_message("Voron", "Voron 2.4", status(), META)
check(m == {"name": "Voron", "model": "Voron 2.4", "online": True, "state": "RUNNING", "pct": 30,
            "remaining_min": 90, "layer": 60, "layers": 250, "file": "Bracket v2", "nozzle": 245,
            "nozzle_target": 245, "bed": 99.8, "bed_target": 100, "chamber": 48.2, "speed": "120%",
            "error": "", "ams": [{"color": "#FF0000", "type": "PLA", "active": False},
                                 {"color": "#00FF00", "type": "PETG", "active": True}]}, f"printing: {m}")
json.dumps(m)

# M73 from the slicer wins over the file position.
m = mr.build_message("V", "K", status(display_status={"progress": 0.5}), META)
check(m["pct"] == 50, f"M73 progress: {m['pct']}")
# No slicer metadata: raw file progress, time from elapsed/progress, no layers.
m = mr.build_message("V", "K", status(print_stats={"info": {}}), {})
check(m["pct"] == 31 and m["remaining_min"] == round((1800 / 0.31 - 1800) / 60) and m["layers"] == 0
      and m["ams"] == [], f"no metadata: {m}")
# No SET_PRINT_STATS_INFO: layer from the nozzle height (z 12.0 at 0.2 mm -> layer 60).
m = mr.build_message("V", "K", status(print_stats={"info": {"current_layer": None, "total_layer": None}}), META)
check((m["layer"], m["layers"]) == (60, 250), f"layer from z: {m['layer']}/{m['layers']}")
# Heating before anything is extruded.
m = mr.build_message("V", "K", status(print_stats={"filament_used": 0, "print_duration": 0}), META)
check(m["state"] == "PREPARE" and m["remaining_min"] == 120, f"preparing: {m}")
m = mr.build_message("V", "K", status(print_stats={"state": "paused"}), META)
check(m["state"] == "PAUSE" and m["speed"] == "120%", f"paused: {m}")
m = mr.build_message("V", "K", status(print_stats={"state": "complete"}), META)
check(m["state"] == "FINISH" and m["pct"] == 100 and m["file"] == "Bracket v2" and m["remaining_min"] == 0
      and m["speed"] == "" and not any(a["active"] for a in m["ams"]), f"complete: {m}")
m = mr.build_message("V", "K", status(print_stats={"state": "standby", "filename": ""}), {})
check(m["state"] == "IDLE" and m["pct"] == 0 and m["file"] == "" and m["layers"] == 0 and m["nozzle"] == 245,
      f"standby: {m}")
m = mr.build_message("V", "K", status(print_stats={"state": "cancelled"}), META)
check(m["state"] == "IDLE" and m["file"] == "", f"cancelled: {m}")
m = mr.build_message("V", "K", status(print_stats={"state": "error", "message": "Move out of range: 0 400\nmore"}), META)
check(m["state"] == "FAILED" and m["error"] == "Move out of range: 0 400", f"print error: {m}")
m = mr.build_message("V", "K", status(webhooks={"state": "shutdown",
                                                "state_message": "MCU 'mcu' shutdown: Timer too close\nOnce..."}), META)
check(m["state"] == "FAILED" and m["error"].startswith("MCU 'mcu' shutdown") and len(m["error"]) <= 47,
      f"klipper shutdown: {m}")
one = mr.build_message("V", "K", status(toolhead={"extruder": "extruder"}),
                       {**META, "filament_colors": ["#123456"], "filament_type": "ASA"})
check(one["ams"] == [{"color": "#123456", "type": "ASA", "active": False}] and one["nozzle"] == 30,
      f"single extruder: {one}")
check(mr.chamber_object(["extruder", "temperature_sensor raspberry_pi", "heater_generic chamber_heater",
                         "temperature_sensor chamber"]) == "heater_generic chamber_heater", "chamber pick")
check(mr.chamber_object(["extruder", "heater_bed"]) is None, "no chamber")


# ---- a tiny Moonraker ------------------------------------------------------------
class Fake:
    status = status()
    api_key = None
    queries: list = []
    hits = {"meta": 0}


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
            return self._send(401, {"error": {"code": 401, "message": "Unauthorized"}})
        url = urlsplit(self.path)
        if url.path == "/printer/info":
            return self._send(200, {"result": {"state": "ready", "hostname": "voron24"}})
        if url.path == "/printer/objects/list":
            return self._send(200, {"result": {"objects": list(Fake.status)}})
        if url.path == "/printer/objects/query":
            names = [unquote(p.split("=")[0]) for p in url.query.split("&")]
            Fake.queries.append(names)
            return self._send(200, {"result": {"eventtime": 1.0,
                                               "status": {k: v for k, v in Fake.status.items() if k in names}}})
        if url.path == "/server/files/metadata":
            Fake.hits["meta"] += 1
            if parse_qs(url.query).get("filename") == ["parts/Bracket v2.gcode"]:
                return self._send(200, {"result": META})
            return self._send(404, {"error": {"code": 404, "message": "not found"}})
        self._send(404, {"error": {"code": 404}})


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


mr.MoonrakerWorker.POLL_S = 0.1
entry = {"name": "Voron", "type": "moonraker", "host": "127.0.0.1", "port": PORT, "model": "Voron 2.4"}
svc = pr.PrinterService([entry, {"name": "x", "type": "moonraker"}],
                        secret_getter=lambda s, k: store.get((s, k)))
check(len(svc.workers) == 1, "entry without host skipped")
svc.start()
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "RUNNING"), "moonraker: state arrives")
p = svc.message()["printers"][0]
check(p["chamber"] == 48.2 and p["layers"] == 250 and p["model"] == "Voron 2.4", f"service message: {p}")
check("temperature_sensor chamber" in Fake.queries[-1] and "extruder1" in Fake.queries[-1],
      f"queried objects: {Fake.queries[-1]}")
Fake.status = status(print_stats={"state": "complete"})
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "FINISH"), "moonraker: update arrives")
check(Fake.hits["meta"] == 1, f"metadata fetched once per file: {Fake.hits}")
w = svc.workers[0]
check(w.message(now=time.monotonic() + pr.STALE_S + 1)["state"] == "OFFLINE", "stale -> OFFLINE")
svc.stop()

# Unreachable: offline, one log line, no crash.
logs = []
handler = type("H", (poll.logging.Handler,), {"emit": lambda self, rec: logs.append(rec.getMessage())})()
poll.log.addHandler(handler)
dead = pr.PrinterService([{"name": "Gone", "type": "moonraker", "host": "127.0.0.1", "port": 1}],
                         secret_getter=lambda s, k: None)
mr.MoonrakerWorker.RETRY_S = 0.1
dead.start()
check(wait_for(lambda: len(logs) >= 1), "unreachable logs a line")
time.sleep(0.5)
check(len(logs) == 1 and dead.message()["printers"][0]["state"] == "OFFLINE", f"unreachable: {logs}")
dead.stop()

# API key: refused without it (clear hint), works with it from the credential store.
Fake.api_key = "KEY123"
logs.clear()
store[(poll.SERVICE, poll.secret_key("moonraker", "127.0.0.1", PORT))] = "KEY123"
keyed = pr.PrinterService([entry], secret_getter=lambda s, k: store.get((s, k)))
keyed.start()
check(wait_for(lambda: keyed.message()["printers"][0]["online"]), "api key from credential store")
keyed.stop()
store.clear()
nokey = pr.PrinterService([entry], secret_getter=lambda s, k: store.get((s, k)))
nokey.start()
check(wait_for(lambda: any("trusted_clients" in line for line in logs)), f"401 hint: {logs}")
check(not any("KEY123" in line for line in logs), "key not logged")
nokey.stop()
poll.log.removeHandler(handler)

r = mr.probe({"host": "127.0.0.1", "port": PORT}, "KEY123")
ok, text, host = r.ok, r.message, r.name
check(ok and host == "voron24", f"probe ok: {text}")
r = mr.probe({"host": "127.0.0.1", "port": PORT}, None)
ok, text, host = r.ok, r.message, r.name
check(not ok and "trusted_clients" in text, f"probe 401: {text}")
r = mr.probe({"host": "127.0.0.1", "port": 1}, None, timeout=1)
ok, text, host = r.ok, r.message, r.name
check(not ok and "7125" in text, f"probe unreachable: {text}")
Fake.api_key = None

# Bambu and Moonraker side by side; the printer page turns on for either.
mixed = pr.PrinterService([{"name": "P1S", "type": "local", "serial": "01P1", "host": "1.2.3.4"}, entry],
                          secret_getter=lambda s, k: None)
check([type(w).__name__ for w in mixed.workers] == ["Worker", "MoonrakerWorker"], "mixed brands")
check("printer" in enabled_pages({"printers": [entry]}), "printer page auto-added for moonraker")

# ---- the CLI --------------------------------------------------------------------
tmp = pathlib.Path(tempfile.mkdtemp()) / "config.toml"
tmp.write_text('# my config\n[hub]\nhost = "x"\n', encoding="utf-8")


ADD = functools.partial(printers_cli.cmd_add_polled, spec=mr.SPEC)


def run(cmd, answers, passwords):
    a, p = iter(answers), iter(passwords)
    builtins.input = lambda prompt="": next(a)
    getpass.getpass = lambda prompt="": next(p)
    cmd(tmp)


run(ADD, ["127.0.0.1", str(PORT), "", "SV08"], [""])
cfg = tomllib.loads(tmp.read_text())
check(cfg["printers"] == [{"name": "voron24", "type": "moonraker", "host": "127.0.0.1", "port": PORT,
                           "model": "SV08"}], f"moonraker saved: {cfg.get('printers')}")
run(ADD, ["127.0.0.1", str(PORT), "", ""], [""])
check(len(tomllib.loads(tmp.read_text())["printers"]) == 1, "duplicate host refused")
mr.SPEC.probe = lambda *a, **k: poll.ProbeResult(False, "No answer (stubbed)")
run(ADD, ["192.168.1.80", "", "y", "", ""], ["SECRETKEY"])
cfg = tomllib.loads(tmp.read_text())
check(cfg["printers"][1] == {"name": "Klipper", "type": "moonraker", "host": "192.168.1.80"},
      f"default port and model left out: {cfg['printers'][1]}")
check(store.get((poll.SERVICE, "moonraker:192.168.1.80:7125")) == "SECRETKEY" and "SECRETKEY" not in tmp.read_text(),
      "api key in credential store only")
check("Moonraker 192.168.1.80:7125" in printers_cli.describe(cfg["printers"][1]), "describe")
run(printers_cli.cmd_remove, ["2", "y"], [])
check((poll.SERVICE, "moonraker:192.168.1.80:7125") not in store and
      len(tomllib.loads(tmp.read_text())["printers"]) == 1, "remove deletes the key")
run(printers_cli.cmd_remove, ["1"], [])  # no stored key: no question asked
check(not tomllib.loads(tmp.read_text()).get("printers") and "# my config" in tmp.read_text(), "removed, comments kept")
run(ADD, ["not a host!", ], [])
run(ADD, ["1.2.3.4", "99999"], [])
check(not tomllib.loads(tmp.read_text()).get("printers"), "bad host/port rejected")

srv.shutdown()
print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
