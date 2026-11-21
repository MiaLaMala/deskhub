"""Flashforge printer support without a printer: message building from sample /detail replies
and G-code port replies, the worker and probe against tiny local servers, and the CLI.

    uv run python tests/test_flashforge.py
Prints OK or the problems found. Never touches the OS credential store.
"""
import builtins
import functools
import getpass
import json
import pathlib
import socketserver
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

from deskhub import flashforge as ff  # noqa: E402
from deskhub import printer as pr  # noqa: E402
from deskhub import printer_poll as poll  # noqa: E402
from deskhub import printers_cli  # noqa: E402

SERIAL, CODE = "SNMOMC9900123", "3f9a0c1e"


# ---- sample /detail ----------------------------------------------------------------
def detail(**over):
    d = {"status": "printing", "pid": 36, "name": "Workshop 5M", "printProgress": 0.45,
         "estimatedTime": 3600.0, "printDuration": 1800, "printLayer": 50, "targetPrintLayer": 200,
         "printFileName": "Benchy.gcode", "rightTemp": 219.96, "rightTargetTemp": 220.0,
         "leftTemp": 0.0, "leftTargetTemp": 0.0, "platTemp": 59.8, "platTargetTemp": 60.0,
         "chamberTemp": 0.0, "printSpeedAdjust": 100, "errorCode": "", "firmwareVersion": "3.2.7"}
    d.update(over)
    return d


AD5X_STATION = {"hasMatlStation": 1, "pid": "0026", "matlStationInfo": {
    "currentLoadSlot": 0, "currentSlot": 2, "slotCnt": 4, "stateAction": 0, "stateStep": 0,
    "slotInfos": [{"slotId": 1, "hasFilament": True, "materialName": "PLA", "materialColor": "#ffffff"},
                  {"slotId": 2, "hasFilament": True, "materialName": "PETG", "materialColor": "#FF0000"},
                  {"slotId": 3, "hasFilament": False, "materialName": "", "materialColor": ""},
                  {"slotId": 4, "hasFilament": True, "materialName": "Silk PLA", "materialColor": "odd"}]}}

m = ff.build_message("Workshop", "AD5M Pro", detail())
check(m == {"name": "Workshop", "model": "AD5M Pro", "online": True, "state": "RUNNING", "pct": 45,
            "remaining_min": 60, "layer": 50, "layers": 200, "file": "Benchy", "nozzle": 220,
            "nozzle_target": 220, "bed": 59.8, "bed_target": 60, "chamber": None, "speed": "100%",
            "error": "", "ams": []}, f"printing: {m}")
json.dumps(m)

m = ff.build_message("W", "M", detail(status="printing", printProgress=0.0, printLayer=0))
check(m["state"] == "PREPARE" and m["file"] == "Benchy" and m["remaining_min"] == 60, f"printing, nothing yet: {m}")
m = ff.build_message("W", "M", detail(status="heating", printProgress=0.0, printLayer=0))
check(m["state"] == "PREPARE" and m["file"] == "Benchy", f"heating: {m}")
m = ff.build_message("W", "M", detail(status="busy", printFileName="", printProgress=0, estimatedTime=0))
check(m["state"] == "PREPARE" and m["pct"] == 0 and m["file"] == "" and m["layers"] == 0, f"busy: {m}")
m = ff.build_message("W", "M", detail(status="calibrate_doing"))
check(m["state"] == "PREPARE" and m["file"] == "" and m["speed"] == "", f"calibrating: {m}")
m = ff.build_message("W", "M", detail(status="pausing", printSpeedAdjust=120))
check(m["state"] == "PAUSE" and m["speed"] == "120%" and m["pct"] == 45, f"pausing: {m}")
m = ff.build_message("W", "M", detail(status="pause"))
check(m["state"] == "PAUSE" and m["layer"] == 50, f"pause: {m}")
m = ff.build_message("W", "M", detail(status="paused"))
check(m["state"] == "PAUSE", f"paused: {m}")
m = ff.build_message("W", "M", detail(status="completed", printProgress=1.0, estimatedTime=0))
check(m["state"] == "FINISH" and m["pct"] == 100 and m["file"] == "Benchy" and m["remaining_min"] == 0
      and m["speed"] == "", f"completed: {m}")
for raw in ("cancel", "canceling"):
    m = ff.build_message("W", "M", detail(status=raw))
    check(m["state"] == "IDLE" and m["file"] == "" and m["pct"] == 0 and m["layers"] == 0, f"{raw}: {m}")
m = ff.build_message("W", "M", detail(status="ready", printFileName="", printProgress=0, printLayer=0,
                                      targetPrintLayer=0, estimatedTime=0, rightTemp=25.1, rightTargetTemp=0))
check(m["state"] == "IDLE" and m["nozzle"] == 25.1 and m["nozzle_target"] == 0 and m["file"] == "", f"ready: {m}")
m = ff.build_message("W", "M", detail(status="error", errorCode="E0100"))
check(m["state"] == "FAILED" and m["error"] == "Error E0100" and m["file"] == "", f"error with code: {m}")
m = ff.build_message("W", "M", detail(status="error"))
check(m["state"] == "FAILED" and m["error"] == "Printer error", f"error without code: {m}")
for zero in ("0", 0, " "):
    m = ff.build_message("W", "M", detail(errorCode=zero))
    check(m["error"] == "" and m["state"] == "RUNNING", f"errorCode {zero!r} is no error: {m}")
m = ff.build_message("W", "M", detail(status="error", errorCode="0"))
check(m["error"] == "Printer error", f"error status with code 0: {m}")
nan, inf = float("nan"), float("inf")
for bad in (nan, inf, -inf):
    try:
        m = ff.build_message("W", "M", detail(printProgress=bad, estimatedTime=bad, printLayer=bad, targetPrintLayer=bad,
                                              rightTemp=bad, platTargetTemp=bad, chamberTemp=bad,
                                              printSpeedAdjust=bad, **AD5X_STATION))
        json.dumps(m, allow_nan=False)
        check(m["nozzle"] is None and m["bed_target"] is None and m["chamber"] is None and m["speed"] == ""
              and m["layers"] == 0 and m["remaining_min"] == 0, f"{bad} values dropped: {m}")
    except Exception as e:
        problems.append(f"{bad} values raised {e!r}")
m = ff.build_message("W", "M", detail(**{**AD5X_STATION, "matlStationInfo": {**AD5X_STATION["matlStationInfo"],
                                                                         "currentSlot": inf}}))
check(len(m["ams"]) == 3 and not any(a["active"] for a in m["ams"]), f"inf currentSlot: {m['ams']}")
m = ff.build_message("W", "M", detail(status="something_new"))
check(m["state"] == "IDLE", f"unknown status: {m}")
m = ff.build_message("W", "M", detail(chamberTemp=38.5, printProgress=45))
check(m["chamber"] == 38.5 and m["pct"] == 45, f"chamber, percent progress: {m}")

m = ff.build_message("W", "AD5X", detail(**AD5X_STATION))
check(m["ams"] == [{"color": "#FFFFFF", "type": "PLA", "active": False},
                   {"color": "#FF0000", "type": "PETG", "active": True},
                   {"color": "#808080", "type": "Silk PL", "active": False}], f"ad5x slots: {m['ams']}")
m = ff.build_message("W", "AD5X", detail(status="ready", **AD5X_STATION))
check(not any(a["active"] for a in m["ams"]) and len(m["ams"]) == 3, f"ad5x idle slots: {m['ams']}")
m = ff.build_message("W", "AD5X", detail(hasMatlStation=0, indepMatlInfo={"materialName": "PLA",
                                                                          "materialColor": "#00ff00"}))
check(m["ams"] == [{"color": "#00FF00", "type": "PLA", "active": False}], f"ad5x direct feed: {m['ams']}")

check(ff.model_from_pid(36) == "AD5M Pro" and ff.model_from_pid("0026") == "AD5X" and ff.model_from_pid(35) == "AD5M"
      and ff.model_from_pid(None) == "" and ff.model_from_pid("zz") == "", "pid models")
check(ff.short_model("Flashforge Adventurer 5M Pro") == "AD5M Pro" and ff.short_model("Flashforge Finder") == "Finder"
      and ff.short_model("FlashForge Adventurer 4 Pro") == "Adv. 4 Pro" and ff.short_model("") == "", "short models")

# ---- G-code port replies --------------------------------------------------------
M119 = ("CMD M119 Received.\r\nEndstop: X-max: 110 Y-max: 110 Z-min: 0\r\nMachineStatus: {s}\r\n"
        "MoveMode: {mm}\r\nStatus: S:1 L:0 J:0 F:0\r\nLED: 1\r\nCurrentFile: {f}\r\nok\r\n")
M27 = "CMD M27 Received.\r\nSD printing byte 45/100\r\nLayer: 23/100\r\nok\r\n"
M105_NEW = "CMD M105 Received.\r\nT0:209.9/210.0 T1:0.0/0.0 B:50.2/50.0\r\nok\r\n"
M105_OLD = "CMD M105 Received.\r\nT0:22 /0 B:11/0\r\nok\r\n"


def legacy(s, mm="MOVING", f="cube.gx", m105=M105_NEW):
    return ff.build_legacy_message("A4", "Adventurer 4", M119.format(s=s, mm=mm, f=f), M27, m105)


m = legacy("BUILDING_FROM_SD")
check(m["state"] == "RUNNING" and m["pct"] == 45 and (m["layer"], m["layers"]) == (23, 100) and m["file"] == "cube"
      and (m["nozzle"], m["nozzle_target"], m["bed"], m["bed_target"]) == (209.9, 210, 50.2, 50), f"legacy printing: {m}")
m = legacy("BUILDING_FROM_SD", mm="PAUSED")
check(m["state"] == "PAUSE", f"legacy paused via MoveMode: {m}")
m = legacy("PAUSED")
check(m["state"] == "PAUSE", f"legacy PAUSED: {m}")
m = legacy("BUILDING_COMPLETED", mm="READY")
check(m["state"] == "FINISH" and m["pct"] == 100 and m["file"] == "cube", f"legacy completed: {m}")
m = legacy("READY", mm="READY", f="", m105=M105_OLD)
check(m["state"] == "IDLE" and m["pct"] == 0 and m["layers"] == 0 and (m["nozzle"], m["bed"]) == (22, 11),
      f"legacy ready, old temps: {m}")
m = legacy("BUSY", mm="HOMING")
check(m["state"] == "PREPARE", f"legacy busy: {m}")
m = legacy("ERROR")
check(m["state"] == "FAILED" and m["error"] == "Printer error", f"legacy error: {m}")


# ---- a tiny /detail server ---------------------------------------------------------
class Fake:
    detail = detail()
    lan_mode = True
    hits = 0


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        Fake.hits += 1
        if self.path != "/detail":
            reply = None
        elif not Fake.lan_mode:
            reply = {"code": -2, "message": "Lan mode error"}
        elif body.get("serialNumber") != SERIAL:
            reply = {"code": 1, "message": "SN is different"}
        elif body.get("checkCode") != CODE:
            reply = {"code": 1, "message": "Access code is different"}
        else:
            reply = {"code": 0, "message": "Success", "detail": Fake.detail}
        data = json.dumps(reply or {}).encode()
        self.send_response(200 if reply else 404)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.server_address[1]


# ---- a tiny G-code port ------------------------------------------------------------
class Legacy:
    status = "BUILDING_FROM_SD"
    sent: list = []
    sessions: list = []  # the commands of each connection
    open = 0
    refuse = False
    flood = False  # answer M105 with junk and no `ok`


class TcpHandler(socketserver.StreamRequestHandler):
    def handle(self):
        Legacy.open += 1
        session = []
        Legacy.sessions.append(session)
        try:
            self._serve(session)
        finally:
            Legacy.open -= 1

    def _serve(self, session):
        while True:
            line = self.rfile.readline()
            if not line:
                return
            cmd = line.decode().strip()
            Legacy.sent.append(cmd)
            session.append(cmd)
            if cmd == "~M105" and Legacy.flood:
                self.wfile.write(b"x" * 70000)
                continue
            if cmd == "~M601 S1":
                text = ("CMD M601 Received.\r\nControl failed.\r\nok\r\n" if Legacy.refuse
                        else "CMD M601 Received.\r\nControl Success V2.1.\r\nok\r\n")
            elif cmd == "~M115":
                text = ("CMD M115 Received.\r\nMachine Type: Flashforge Adventurer 4 Pro\r\nMachine Name: Garage A4\r\n"
                        "Firmware: v2.2.2\r\nSN: SNADVA4123\r\nX: 220 Y: 200 Z: 250\r\nTool Count: 1\r\nok\r\n")
            elif cmd == "~M119":
                text = M119.format(s=Legacy.status, mm="MOVING", f="0:/user/cube.gx")
            elif cmd == "~M27":
                text = M27
            elif cmd == "~M105":
                text = M105_NEW
            elif cmd == "~M602":
                text = "CMD M602 Received.\r\nControl Release.\r\nok\r\n"
            else:
                text = "Error: unknown\r\nok\r\n"
            # Split replies across packets to exercise the reader.
            data = text.encode()
            self.wfile.write(data[:10])
            self.wfile.flush()
            time.sleep(0.01)
            self.wfile.write(data[10:])


socketserver.ThreadingTCPServer.allow_reuse_address = True
tcp = socketserver.ThreadingTCPServer(("127.0.0.1", 0), TcpHandler)
tcp.daemon_threads = True
threading.Thread(target=tcp.serve_forever, daemon=True).start()
TCP = tcp.server_address[1]


def wait_for(cond, secs=8):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


ff.FlashforgeWorker.POLL_S = 0.1
ff.FlashforgeWorker.RETRY_S = 0.1
logs = []
handler = type("H", (poll.logging.Handler,), {"emit": lambda self, rec: logs.append(rec.getMessage())})()
poll.log.addHandler(handler)

# HTTP API end to end: model from pid when the entry has none.
entry = {"name": "Workshop", "type": "flashforge", "host": "127.0.0.1", "port": PORT, "serial": SERIAL}
store[(poll.SERVICE, poll.secret_key("flashforge", "127.0.0.1", PORT))] = CODE
svc = pr.PrinterService([entry], secret_getter=lambda s, k: store.get((s, k)))
check(type(svc.workers[0]).__name__ == "FlashforgeWorker", "flashforge worker picked")
svc.start()
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "RUNNING"), "flashforge: state arrives")
p = svc.message()["printers"][0]
check(p["model"] == "AD5M Pro" and p["pct"] == 45 and p["layers"] == 200, f"service message: {p}")
Fake.detail = detail(status="completed", printProgress=1.0)
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "FINISH"), "flashforge: update arrives")
w = svc.workers[0]
check(w.message(now=time.monotonic() + pr.STALE_S + 1)["state"] == "OFFLINE", "stale -> OFFLINE")
svc.stop()

# A model in the entry wins over the pid.
fixed = pr.PrinterService([{**entry, "model": "My 5M"}], secret_getter=lambda s, k: store.get((s, k)))
fixed.start()
check(wait_for(lambda: fixed.message()["printers"][0]["online"]), "fixed model online")
check(fixed.message()["printers"][0]["model"] == "My 5M", f"entry model kept: {fixed.message()['printers'][0]}")
fixed.stop()

# Wrong check code: one clear log line, the code never logged.
logs.clear()
store[(poll.SERVICE, poll.secret_key("flashforge", "127.0.0.1", PORT))] = "deadbeef"
bad = pr.PrinterService([entry], secret_getter=lambda s, k: store.get((s, k)))
bad.start()
check(wait_for(lambda: any("check code" in line for line in logs)), f"bad code hint: {logs}")
time.sleep(0.3)
check(len(logs) == 1 and bad.message()["printers"][0]["state"] == "OFFLINE", f"bad code once: {logs}")
check(not any("deadbeef" in line or CODE in line for line in logs), "check code not logged")
bad.stop()
logs.clear()
wrong_sn = pr.PrinterService([{**entry, "serial": "SNWRONG"}], secret_getter=lambda s, k: CODE)
wrong_sn.start()
check(wait_for(lambda: any("serial number" in line for line in logs)), f"bad serial hint: {logs}")
wrong_sn.stop()
logs.clear()
Fake.lan_mode = False
store[(poll.SERVICE, poll.secret_key("flashforge", "127.0.0.1", PORT))] = CODE
off = pr.PrinterService([entry], secret_getter=lambda s, k: store.get((s, k)))
off.start()
check(wait_for(lambda: any("LAN-only" in line for line in logs)), f"lan mode hint: {logs}")
off.stop()
Fake.lan_mode = True

# Legacy G-code port end to end: one short session per poll (control taken, queried, released,
# disconnected), M115 only until the model is known, nothing open between polls.
Legacy.sent.clear()
Legacy.sessions.clear()
check(ff.FlashforgeWorker({"host": "h"}, None).POLL_S == ff.FlashforgeWorker.LEGACY_POLL_S == 5.0,
      "legacy polls slowly")
check(ff.FlashforgeWorker({"host": "h", "serial": "SN1"}, None).POLL_S == 0.1, "http polls at POLL_S")
ff.FlashforgeWorker.LEGACY_POLL_S = 0.2
old = pr.PrinterService([{"name": "Garage", "type": "flashforge", "host": "127.0.0.1", "port": TCP}],
                        secret_getter=lambda s, k: None)
old.start()
check(wait_for(lambda: old.message()["printers"][0]["state"] == "RUNNING"), "legacy: state arrives")
p = old.message()["printers"][0]
check(p["model"] == "Adv. 4 Pro" and p["file"] == "cube" and p["pct"] == 45 and p["nozzle"] == 209.9,
      f"legacy service message: {p}")
Legacy.status = "PAUSED"
check(wait_for(lambda: old.message()["printers"][0]["state"] == "PAUSE"), "legacy: update arrives")
check(wait_for(lambda: len(Legacy.sessions) >= 4), f"legacy reconnects per poll: {len(Legacy.sessions)}")
check(wait_for(lambda: Legacy.open == 0, 2), "no connection open between polls")
old.stop()
old.workers[0].join(3)
check(wait_for(lambda: Legacy.open == 0, 2), "no connection left after stop")
check(Legacy.sessions[0] == ["~M601 S1", "~M119", "~M27", "~M105", "~M115", "~M602"],
      f"first session asks M115: {Legacy.sessions[0]}")
check(all(s == ["~M601 S1", "~M119", "~M27", "~M105", "~M602"] for s in Legacy.sessions[1:]),
      f"later sessions released with M602, no M115: {Legacy.sessions[1:]}")
check(ff.FlashforgeWorker({"host": "h", "port": 8898}, None)._tcp_port() == 8899, "default port -> 8899 for legacy")

# A failing query still releases control and disconnects.
Legacy.sessions.clear()
Legacy.flood = True
try:
    ff.legacy_query("127.0.0.1", TCP, ["M119", "M105", "M27"], timeout=2)
    problems.append("flooded M105 should raise")
except ValueError:
    pass
check(wait_for(lambda: Legacy.open == 0, 3), "failed session disconnected")
check(Legacy.sessions == [["~M601 S1", "~M119", "~M105", "~M602"]], f"failed session released: {Legacy.sessions}")
Legacy.sessions.clear()
logs.clear()
flooded = pr.PrinterService([{"name": "Garage", "type": "flashforge", "host": "127.0.0.1", "port": TCP,
                              "model": "A4"}], secret_getter=lambda s, k: None)
flooded.start()
check(wait_for(lambda: len(logs) >= 1 and len(Legacy.sessions) >= 2), f"worker survives a failing poll: {logs}")
flooded.stop()
flooded.workers[0].join(3)
check(wait_for(lambda: Legacy.open == 0, 3), "worker leaves nothing open after failures")
check(all(s[-1] == "~M602" for s in Legacy.sessions), f"worker releases after failures: {Legacy.sessions}")
check(flooded.message()["printers"][0]["state"] == "OFFLINE", "failing legacy printer is offline")
Legacy.flood = False

# Unreachable: offline, one log line.
logs.clear()
dead = pr.PrinterService([{**entry, "port": 1}], secret_getter=lambda s, k: CODE)
dead.start()
check(wait_for(lambda: len(logs) >= 1), "unreachable logs a line")
time.sleep(0.3)
check(len(logs) == 1 and dead.message()["printers"][0]["state"] == "OFFLINE", f"unreachable: {logs}")
dead.stop()
poll.log.removeHandler(handler)

# ---- probe ----------------------------------------------------------------------
r = ff.probe({"host": "127.0.0.1", "port": PORT, "serial": SERIAL}, CODE)
check(r.ok and r.name == "Workshop 5M" and r.model == "AD5M Pro", f"probe ok: {r}")
r = ff.probe({"host": "127.0.0.1", "port": PORT, "serial": SERIAL}, "deadbeef")
check(not r.ok and "check code" in r.message and "deadbeef" not in r.message, f"probe bad code: {r}")
r = ff.probe({"host": "127.0.0.1", "port": PORT, "serial": "SNWRONG"}, CODE)
check(not r.ok and "serial number is wrong" in r.message, f"probe bad serial: {r}")
r = ff.probe({"host": "127.0.0.1", "port": PORT, "serial": SERIAL}, None)
check(not r.ok and "check code" in r.message, f"probe no code: {r}")
Fake.lan_mode = False
r = ff.probe({"host": "127.0.0.1", "port": PORT, "serial": SERIAL}, CODE)
check(not r.ok and "LAN-only" in r.message, f"probe lan mode off: {r}")
Fake.lan_mode = True
r = ff.probe({"host": "127.0.0.1", "port": 1, "serial": SERIAL}, CODE, timeout=1)
check(not r.ok and "No answer" in r.message and CODE not in r.message, f"probe unreachable: {r}")
r = ff.probe({"host": "127.0.0.1", "port": TCP}, None)
check(r.ok and r.name == "Garage A4" and r.model == "Adv. 4 Pro", f"probe legacy: {r}")
Legacy.refuse = True
r = ff.probe({"host": "127.0.0.1", "port": TCP}, None)
check(not r.ok and "refused control" in r.message, f"probe legacy refused: {r}")
Legacy.refuse = False
r = ff.probe({"host": "127.0.0.1", "port": 1}, None, timeout=1)
check(not r.ok and "127.0.0.1:1" in r.message, f"probe legacy unreachable: {r}")

# ---- the CLI --------------------------------------------------------------------
tmp = pathlib.Path(tempfile.mkdtemp()) / "config.toml"
tmp.write_text('# my config\n[hub]\nhost = "x"\n', encoding="utf-8")
ADD = functools.partial(printers_cli.cmd_add_polled, spec=ff.SPEC)


def run(cmd, answers, passwords):
    a, p = iter(answers), iter(passwords)
    builtins.input = lambda prompt="": next(a)
    getpass.getpass = lambda prompt="": next(p)
    cmd(tmp)


store.clear()
run(ADD, ["127.0.0.1", str(PORT), SERIAL, "", ""], [CODE])
cfg = tomllib.loads(tmp.read_text())
check(cfg["printers"] == [{"name": "Workshop 5M", "type": "flashforge", "host": "127.0.0.1", "port": PORT,
                           "serial": SERIAL, "model": "AD5M Pro"}], f"flashforge saved: {cfg.get('printers')}")
check(store.get((poll.SERVICE, poll.secret_key("flashforge", "127.0.0.1", PORT))) == CODE
      and CODE not in tmp.read_text(), "check code in credential store only")
run(ADD, ["127.0.0.1", str(TCP), "", "", ""], [""])
cfg = tomllib.loads(tmp.read_text())
check(cfg["printers"][1] == {"name": "Garage A4", "type": "flashforge", "host": "127.0.0.1", "port": TCP,
                             "model": "Adv. 4 Pro"}, f"legacy saved without serial: {cfg['printers'][1]}")
check(len(store) == 1, f"no secret stored for legacy: {store}")
check("Flashforge 127.0.0.1" in printers_cli.describe(cfg["printers"][0]), "describe")

srv.shutdown()
tcp.shutdown()
print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
