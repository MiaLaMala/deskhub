"""Elegoo (SDCP) printer support without a printer: state mapping from sample status, the
worker and probe against a tiny local SDCP websocket server and UDP discovery responder, and
the CLI.

    uv run python tests/test_elegoo.py
Prints OK or the problems found. Never touches the OS credential store.
"""
import builtins
import functools
import getpass
import json
import pathlib
import socket
import sys
import tempfile
import threading
import time
import tomllib
import types

from websockets.sync.server import serve

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

from deskhub import elegoo as el  # noqa: E402
from deskhub import printer as pr  # noqa: E402
from deskhub import printer_poll as poll  # noqa: E402
from deskhub import printers_cli  # noqa: E402
from deskhub.pages import enabled_pages  # noqa: E402

MB = "000000000001d354"


# ---- sample status (Centauri Carbon shape: Status nested, ticks in seconds) ---------
def status(machine=(1,), **info):
    pi = {"Status": 13, "CurrentLayer": 60, "TotalLayer": 250, "CurrentTicks": 1800, "TotalTicks": 7200,
          "Filename": "Bracket v2.gcode", "ErrorNumber": 0, "TaskId": "t1", "Progress": 31,
          "PrintSpeedPct": 130}
    pi.update(info)
    return {"CurrentStatus": list(machine), "PreviousStatus": 0, "TempOfNozzle": 244.96,
            "TempTargetNozzle": 245, "TempOfHotbed": 59.8, "TempTargetHotbed": 60, "TempOfBox": 31.2,
            "TempTargetBox": 0, "CurrenCoord": "10.0,20.0,12.0", "PrintInfo": pi}


m = el.build_message("CC", "Centauri Carbon", status())
check(m == {"name": "CC", "model": "Centauri Carbon", "online": True, "state": "RUNNING", "pct": 31,
            "remaining_min": 90, "layer": 60, "layers": 250, "file": "Bracket v2", "nozzle": 245,
            "nozzle_target": 245, "bed": 59.8, "bed_target": 60, "chamber": 31.2, "speed": "130%",
            "error": "", "ams": []}, f"printing: {m}")
json.dumps(m)


def state(machine=(1,), **info):
    return el.build_message("CC", "Centauri Carbon", status(machine, **info))


# Print sub-status while the machine is printing.
for sub, want in [(0, "RUNNING"), (12, "RUNNING"), (13, "RUNNING"), (23, "RUNNING"), (24, "RUNNING"),
                  (99, "RUNNING"), (5, "PAUSE"), (6, "PAUSE"), (25, "PAUSE"), (26, "PAUSE"),
                  (7, "IDLE"), (8, "IDLE"), (9, "FINISH"), (14, "FAILED")]:
    got = state(Status=sub)["state"]
    check(got == want, f"print status {sub}: {got}, want {want}")
# Preparation codes before the first layer, and the firmware parked on a milestone mid-job.
for sub in (1, 10, 11, 15, 16, 17, 18, 19, 20, 21, 22):
    got = state(Status=sub, CurrentLayer=0, Progress=0)
    check(got["state"] == "PREPARE" and got["file"] == "Bracket v2" and got["speed"] == "130%",
          f"prepare status {sub}: {got}")
    check(state(Status=sub)["state"] == "RUNNING", f"milestone {sub} mid-job -> RUNNING")
m = state(Status=6)
check(m["pct"] == 31 and m["remaining_min"] == 90 and m["layer"] == 60, f"paused keeps progress: {m}")

# Machine not printing: the sub-status keeps its last value after a job (SDCP spec).
m = state((0,), Status=9, CurrentTicks=7200)
check(m["state"] == "FINISH" and m["pct"] == 100 and m["file"] == "Bracket v2" and m["remaining_min"] == 0
      and m["speed"] == "" and (m["layer"], m["layers"]) == (60, 250), f"complete: {m}")
m = state((0,), Status=14)
check(m["state"] == "FAILED" and m["error"] == "Print stopped by an error" and m["file"] == "Bracket v2",
      f"error: {m}")
m = state((0,), Status=14, ErrorNumber=2)
check(m["error"] == "Could not read the file", f"error number: {m}")
m = state((0,), Status=8)
check(m["state"] == "IDLE" and m["file"] == "" and m["layers"] == 0 and m["pct"] == 0, f"stopped: {m}")
m = state((0,), Status=0, Filename="", CurrentLayer=0, TotalLayer=0)
check(m["state"] == "IDLE" and m["nozzle"] == 245 and m["chamber"] == 31.2 and m["speed"] == "", f"idle: {m}")
m = state((0,), Status=13)
check(m["state"] == "IDLE", f"stale printing sub-status, machine idle: {m}")
for machine in (4, 5, 6, 8, 9, 11):
    got = state((machine,), Status=0)["state"]
    check(got == "PREPARE", f"machine {machine} (calibrating/homing): {got}")
for machine in (2, 7, 10):
    got = state((machine,), Status=0)["state"]
    check(got == "IDLE", f"machine {machine}: {got}")
# Cancelled at 47%, then an auto-level / homing with no job: none of the old job shows.
m = state((0,), Status=8, Progress=47)
check(m["state"] == "IDLE" and m["pct"] == 0 and m["file"] == "", f"cancelled at 47%: {m}")
for machine in (5, 9):
    m = state((machine,), Status=8, Progress=47)
    check(m["state"] == "PREPARE" and m["pct"] == 0 and m["file"] == "" and (m["layer"], m["layers"]) == (0, 0)
          and m["remaining_min"] == 0 and m["speed"] == "" and m["nozzle"] == 245,
          f"machine {machine} after a cancel shows no old job: {m}")
check(state((2, 1), Status=13)["state"] == "RUNNING", "file transfer gives way to printing")
check(state((1, 2), Status=13)["state"] == "RUNNING", "printing while a file transfers")

# No Progress field: from layers. OpenCentauri's PrintSpeed naming.
m = el.build_message("CC", "X", {**status(), "PrintInfo": {"Status": 13, "CurrentLayer": 50, "TotalLayer": 200,
                                                           "PrintSpeed": 100}})
check(m["pct"] == 25 and m["speed"] == "100%", f"progress from layers: {m}")
# Flat status (no "Status" wrapper) and odd values don't crash.
check(el.status_of({"Topic": f"sdcp/status/{MB}", "CurrentStatus": [0]}) == {"Topic": f"sdcp/status/{MB}",
                                                                          "CurrentStatus": [0]}, "flat status")
check(el.status_of({"Topic": f"sdcp/response/{MB}", "Data": {}}) is None, "response is not status")
m = el.build_message("CC", "X", {"CurrentStatus": "junk", "PrintInfo": "junk", "TempOfNozzle": "hot"})
check(m["state"] == "IDLE" and m["nozzle"] is None, f"junk: {m}")
check(el.build_message("CC", "X", {})["state"] == "IDLE", "empty status")

req = json.loads(el.request(MB, 0))
check(req["Topic"] == f"sdcp/request/{MB}" and req["Data"]["Cmd"] == 0 and req["Data"]["MainboardID"] == MB
      and req["Data"]["From"] == 0 and isinstance(req["Data"]["TimeStamp"], int) and req["Data"]["RequestID"],
      f"request frame: {req}")


# ---- a tiny Centauri Carbon -----------------------------------------------------------
class Fake:
    status = status()
    push_on_connect = False
    send_ping = False
    drop_next = False
    connections = 0
    pongs = 0
    requests: list = []
    discovery = 0


def frame(topic, body):
    return json.dumps({**body, "MainboardID": MB, "TimeStamp": int(time.time()), "Topic": f"sdcp/{topic}/{MB}"})


def handler(ws):
    Fake.connections += 1
    if Fake.push_on_connect:
        ws.send(frame("status", {"Status": Fake.status}))
    if Fake.send_ping:
        ws.send("ping")
    for raw in ws:
        if raw == "pong":
            Fake.pongs += 1
            continue
        if raw == "ping":
            ws.send("pong")
            continue
        msg = json.loads(raw)
        Fake.requests.append(msg)
        if Fake.drop_next:
            Fake.drop_next = False
            ws.close()
            return
        data = msg["Data"]
        if msg["Topic"] != f"sdcp/request/{MB}" or data["MainboardID"] != MB:
            continue  # the real printer ignores requests for another board
        ws.send(json.dumps({"Id": msg["Id"], "Data": {"Cmd": data["Cmd"], "Data": {"Ack": 0},
                                                       "RequestID": data["RequestID"], "MainboardID": MB,
                                                       "TimeStamp": int(time.time())},
                            "Topic": f"sdcp/response/{MB}"}))
        ws.send("pong")  # stray keepalive text must be skipped
        if data["Cmd"] == 0:
            ws.send(frame("status", {"Status": Fake.status}))
        elif data["Cmd"] == 1:
            ws.send(frame("attributes", {"Attributes": {"Name": "Workshop CC", "MachineName": "Centauri Carbon",
                                                        "BrandName": "ELEGOO", "MainboardID": MB}}))


srv = serve(handler, "127.0.0.1", 0, compression=None)
threading.Thread(target=srv.serve_forever, daemon=True).start()
PORT = srv.socket.getsockname()[1]

udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
udp.bind(("127.0.0.1", 0))
UDP_PORT = udp.getsockname()[1]


def discovery_responder():
    while True:
        try:
            data, addr = udp.recvfrom(1024)
        except OSError:
            return
        if data == b"M99999":
            Fake.discovery += 1
            udp.sendto(json.dumps({"Id": "f25273b12b094c5a8b9513a30ca60049", "Data": {
                "Name": "Centauri", "MachineName": "Centauri Carbon", "BrandName": "ELEGOO",
                "MainboardIP": "127.0.0.1", "MainboardID": MB, "ProtocolVersion": "V3.0.0",
                "FirmwareVersion": "V1.1.46"}}).encode(), addr)


threading.Thread(target=discovery_responder, daemon=True).start()
el.DISCOVERY_PORT = UDP_PORT

# A port nothing answers on, for "no discovery reply".
_s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
_s.bind(("127.0.0.1", 0))
DEAD_UDP = _s.getsockname()[1]
_s.close()


def wait_for(cond, secs=8):
    end = time.time() + secs
    while time.time() < end:
        if cond():
            return True
        time.sleep(0.05)
    return False


el.ElegooWorker.POLL_S = 0.1
el.ElegooWorker.RETRY_S = 0.1
entry = {"name": "CC", "type": "elegoo", "host": "127.0.0.1", "port": PORT, "model": "Centauri Carbon"}
Fake.send_ping = True
svc = pr.PrinterService([entry, {"name": "x", "type": "elegoo"}], secret_getter=lambda s, k: store.get((s, k)))
check(len(svc.workers) == 1 and type(svc.workers[0]).__name__ == "ElegooWorker", "worker built, no-host skipped")
svc.start()
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "RUNNING"), "elegoo: state arrives")
p = svc.message()["printers"][0]
check(p["chamber"] == 31.2 and p["layers"] == 250 and p["model"] == "Centauri Carbon" and p["remaining_min"] == 90,
      f"service message: {p}")
check(Fake.discovery >= 1 and Fake.requests and Fake.requests[-1]["Data"]["Cmd"] == 0, "discovery, then Cmd 0")
check(wait_for(lambda: Fake.pongs >= 1), "answers the printer's ping")
Fake.status = status(Status=6)
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "PAUSE"), "elegoo: update arrives")
check(Fake.connections == 1, f"websocket kept open between polls: {Fake.connections}")

# The printer drops the connection: reconnect, keep going, no re-discovery needed.
logs = []
handler_ = type("H", (poll.logging.Handler,), {"emit": lambda self, rec: logs.append(rec.getMessage())})()
poll.log.addHandler(handler_)
seen = Fake.discovery
Fake.drop_next = True
check(wait_for(lambda: Fake.connections >= 2), f"reconnects after a drop: {Fake.connections}")
Fake.status = status((0,), Status=9)
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "FINISH"), "state after reconnect")
check(Fake.discovery == seen, "MainboardID kept across reconnects")
w = svc.workers[0]
check(w.message(now=time.monotonic() + pr.STALE_S + 1)["state"] == "OFFLINE", "stale -> OFFLINE")
svc.stop()
w.join(3)
Fake.send_ping = False

# No discovery reply: the MainboardID comes from the printer's first push.
el.DISCOVERY_PORT = DEAD_UDP
Fake.push_on_connect = True
Fake.status = status()
nodisc = pr.PrinterService([entry], secret_getter=lambda s, k: None)
nodisc.start()
check(wait_for(lambda: nodisc.message()["printers"][0]["state"] == "RUNNING"), "works without discovery")
nodisc.stop()

# Unreachable: offline, one log line, no crash.
logs.clear()
dead = pr.PrinterService([{"name": "Gone", "type": "elegoo", "host": "127.0.0.1", "port": 1}],
                         secret_getter=lambda s, k: None)
dead.start()
check(wait_for(lambda: len(logs) >= 1, 12), "unreachable logs a line")
time.sleep(0.5)
check(len(logs) == 1 and dead.message()["printers"][0]["state"] == "OFFLINE", f"unreachable: {logs}")
dead.stop()
poll.log.removeHandler(handler_)

# ---- probe ----------------------------------------------------------------------------
el.DISCOVERY_PORT = UDP_PORT
Fake.push_on_connect = False
r = el.probe({"host": "127.0.0.1", "port": PORT}, None)
check(r.ok and r.name == "Centauri" and r.model == "Centauri Carbon" and r.secret is None,
      f"probe via discovery: {r}")
el.DISCOVERY_PORT = DEAD_UDP
Fake.push_on_connect = True
r = el.probe({"host": "127.0.0.1", "port": PORT}, None)
check(r.ok and r.name == "Workshop CC" and r.model == "Centauri Carbon", f"probe via attributes: {r}")
r = el.probe({"host": "127.0.0.1", "port": 1}, None, timeout=1)
check(not r.ok and "No websocket" in r.message and "127.0.0.1:1" in r.message, f"probe unreachable: {r}")
el.DISCOVERY_PORT = UDP_PORT
r = el.probe({"host": "127.0.0.1", "port": 1}, None, timeout=1)
check(not r.ok and "answered discovery" in r.message and r.model == "Centauri Carbon",
      f"probe: discovery but no websocket: {r}")

check("printer" in enabled_pages({"printers": [entry]}), "printer page auto-added for elegoo")

# ---- the CLI --------------------------------------------------------------------------
tmp = pathlib.Path(tempfile.mkdtemp()) / "config.toml"
tmp.write_text('# my config\n[hub]\nhost = "x"\n', encoding="utf-8")
ADD = functools.partial(printers_cli.cmd_add_polled, spec=el.SPEC)


def run(cmd, answers, passwords):
    a, p = iter(answers), iter(passwords)
    builtins.input = lambda prompt="": next(a)
    getpass.getpass = lambda prompt="": next(p)
    cmd(tmp)


el.DEFAULT_PORT = PORT  # the CLI never asks for a port; point the probe at the fake
Fake.push_on_connect = False
run(ADD, ["127.0.0.1", "", ""], [])  # host, then accept the suggested name and model
cfg = tomllib.loads(tmp.read_text())
check(cfg["printers"] == [{"name": "Centauri", "type": "elegoo", "host": "127.0.0.1", "model": "Centauri Carbon"}],
      f"elegoo saved: {cfg.get('printers')}")
check(not store, f"no credential stored: {store}")
check("Elegoo 127.0.0.1:3030" in printers_cli.describe(cfg["printers"][0]), "describe")
run(ADD, ["127.0.0.1", "", ""], [])
check(len(tomllib.loads(tmp.read_text())["printers"]) == 1, "duplicate host refused")
el.SPEC.probe = lambda *a, **k: poll.ProbeResult(False, "No answer (stubbed)")
run(ADD, ["192.168.1.90", "y", "", ""], [])
cfg = tomllib.loads(tmp.read_text())
check(cfg["printers"][1] == {"name": "Elegoo", "type": "elegoo", "host": "192.168.1.90"},
      f"default model left out: {cfg['printers'][1]}")
check(not store, "still no credential")

srv.shutdown()
udp.close()
print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
