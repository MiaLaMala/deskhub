"""PrusaLink printer support without a printer: message mapping from sample status, the worker
and probe against a tiny local HTTP server that does real Digest authentication, and the CLI.

    uv run python tests/test_prusalink.py
Prints OK or the problems found. Never touches the OS credential store.
"""
import builtins
import functools
import getpass
import hashlib
import json
import pathlib
import re
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

from deskhub import printer as pr  # noqa: E402
from deskhub import printer_poll as poll  # noqa: E402
from deskhub import printers_cli  # noqa: E402
from deskhub import prusalink as pl  # noqa: E402

# ---- message mapping -------------------------------------------------------------
JOB = {"id": 7, "state": "PRINTING", "progress": 42.0, "time_remaining": 5400, "time_printing": 600,
       "file": {"name": "BRACKET~1.BGC", "display_name": "Bracket v2.bgcode", "path": "/usb/BRACKET~1.BGC"}}


def status(state="PRINTING", job=True, **printer):
    s = {"printer": {"state": state, "temp_nozzle": 214.96, "target_nozzle": 215, "temp_bed": 59.8,
                     "target_bed": 60, "axis_z": 3.2, "flow": 100, "speed": 110, "fan_hotend": 5000,
                     "fan_print": 4000}}
    s["printer"].update(printer)
    if job:
        s["job"] = {"id": 7, "progress": 42.0, "time_remaining": 5400, "time_printing": 600}
    return s


m = pl.build_message("MK4", "MK4S", status(), JOB)
check(m == {"name": "MK4", "model": "MK4S", "online": True, "state": "RUNNING", "pct": 42,
            "remaining_min": 90, "layer": 0, "layers": 0, "file": "Bracket v2", "nozzle": 215,
            "nozzle_target": 215, "bed": 59.8, "bed_target": 60, "chamber": None, "speed": "110%",
            "error": "", "ams": []}, f"printing: {m}")
json.dumps(m)
m = pl.build_message("M", "K", status("PAUSED"), JOB)
check(m["state"] == "PAUSE" and m["pct"] == 42 and m["speed"] == "110%", f"paused: {m}")
m = pl.build_message("M", "K", status("BUSY", job=False), {})
check(m["state"] == "PREPARE" and m["file"] == "" and m["pct"] == 0, f"busy: {m}")
m = pl.build_message("M", "K", status("FINISHED", job=False), {**JOB, "state": "FINISHED"})
check(m["state"] == "FINISH" and m["pct"] == 100 and m["file"] == "Bracket v2" and m["remaining_min"] == 0
      and m["speed"] == "", f"finished: {m}")
for raw in ("IDLE", "READY", "STOPPED"):
    m = pl.build_message("M", "K", status(raw, job=False), {})
    check(m["state"] == "IDLE" and m["pct"] == 0 and m["file"] == "" and m["nozzle"] == 215,
          f"{raw} -> IDLE: {m}")
m = pl.build_message("M", "K", status("ATTENTION"), JOB)
check(m["state"] == "PAUSE" and m["error"] == "Needs attention on the printer" and m["pct"] == 42
      and m["remaining_min"] == 90 and m["file"] == "Bracket v2", f"attention mid-print: {m}")
m = pl.build_message("M", "K", status("ATTENTION", job=False), {})
check(m["state"] == "FAILED" and m["error"] == "Needs attention on the printer", f"attention, no job: {m}")
m = pl.build_message("M", "K", status("ERROR", job=False, status_printer={"ok": False, "message": "Thermal runaway\nmore"}), {})
check(m["state"] == "FAILED" and m["error"] == "Thermal runaway", f"error: {m}")
m = pl.build_message("M", "K", status("ERROR", job=False), {})
check(m["state"] == "FAILED" and m["error"] == "Printer error", f"error without message: {m}")
m = pl.build_message("M", "K", {"printer": {"state": "SOMETHING_NEW"}}, {})
check(m["state"] == "IDLE" and m["nozzle"] is None, f"unknown state: {m}")
m = pl.build_message("M", "K", status(job=False), {})
check(m["state"] == "RUNNING" and m["pct"] == 0 and m["file"] == "", f"printing without job data: {m}")
m = pl.build_message("M", "K", status(), {**JOB, "file": {"name": "a.gcode"}})
check(m["file"] == "a", f"name fallback: {m['file']}")


# ---- a tiny PrusaLink with Digest auth -------------------------------------------
class Fake:
    user = "maker"
    password = "s3cret"
    realm = "Printer API"
    nonce = "abc123nonce"
    status = status()
    job = JOB
    info = {"hostname": "prusa-mk4", "mmu": False, "nozzle_diameter": 0.4}
    auth_required = True
    hits = {"job": 0}


def md5(s):
    return hashlib.md5(s.encode()).hexdigest()


def digest_ok(header, method):
    if not header or not header.startswith("Digest "):
        return False
    f = {k: quoted or bare for k, quoted, bare in re.findall(r'(\w+)=(?:"([^"]*)"|([^,\s]*))', header)}
    if f.get("username") != Fake.user or f.get("nonce") != Fake.nonce:
        return False
    ha1 = md5(f"{Fake.user}:{Fake.realm}:{Fake.password}")
    ha2 = md5(f"{method}:{f['uri']}")
    if f.get("qop"):
        want = md5(f"{ha1}:{f['nonce']}:{f['nc']}:{f['cnonce']}:{f['qop']}:{ha2}")
    else:
        want = md5(f"{ha1}:{f['nonce']}:{ha2}")
    return f.get("response") == want


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, body=None, headers=None):
        data = json.dumps(body).encode() if body is not None else b""
        self.send_response(code)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        if body is not None:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if Fake.auth_required:
            if not digest_ok(self.headers.get("Authorization"), "GET"):
                return self._send(401, {"message": "Unauthorized"}, {
                    "WWW-Authenticate": f'Digest realm="{Fake.realm}", nonce="{Fake.nonce}", qop="auth", '
                                        'algorithm=MD5'})
        if self.path == "/api/v1/status":
            return self._send(200, Fake.status)
        if self.path == "/api/v1/job":
            Fake.hits["job"] += 1
            return self._send(200, Fake.job) if Fake.job else self._send(204)
        if self.path == "/api/v1/info":
            return self._send(200, Fake.info)
        self._send(404, {"message": "not found"})


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


# Sanity check on the fake: a wrong password must fail.
c = pl.PrusaLinkClient("127.0.0.1", PORT, "maker", "wrong")
try:
    c.status()
    check(False, "fake digest accepted a wrong password")
except Exception as e:
    check(getattr(getattr(e, "response", None), "status_code", None) == 401, f"wrong password: {e}")
c.close()
c = pl.PrusaLinkClient("127.0.0.1", PORT, "maker", "s3cret")
check(c.status()["printer"]["state"] == "PRINTING", "right password works")
c.close()

pl.PrusaLinkWorker.POLL_S = 0.1
entry = {"name": "MK4", "type": "prusalink", "host": "127.0.0.1", "port": PORT, "user": "maker", "model": "MK4S"}
key = poll.secret_key("prusalink", "127.0.0.1", PORT)
store[(poll.SERVICE, key)] = "s3cret"
svc = pr.PrinterService([entry, {"name": "x", "type": "prusalink"}],
                        secret_getter=lambda s, k: store.get((s, k)))
check(len(svc.workers) == 1 and type(svc.workers[0]).__name__ == "PrusaLinkWorker", "worker built, no-host skipped")
svc.start()
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "RUNNING"), "prusalink: state arrives")
p = svc.message()["printers"][0]
check(p["pct"] == 42 and p["file"] == "Bracket v2" and p["model"] == "MK4S" and p["bed_target"] == 60,
      f"service message: {p}")
Fake.status = status("FINISHED", job=False)
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "IDLE" or
               svc.message()["printers"][0]["state"] == "FINISH"), "prusalink: update arrives")
Fake.status = status()
check(wait_for(lambda: svc.message()["printers"][0]["state"] == "RUNNING"), "prusalink: next job")
check(Fake.hits["job"] == 2, f"job fetched once per job: {Fake.hits}")
w = svc.workers[0]
check(w.message(now=time.monotonic() + pr.STALE_S + 1)["state"] == "OFFLINE", "stale -> OFFLINE")
svc.stop()

# Unreachable: offline, one log line, no crash.
logs = []
handler = type("H", (poll.logging.Handler,), {"emit": lambda self, rec: logs.append(rec.getMessage())})()
poll.log.addHandler(handler)
dead = pr.PrinterService([{"name": "Gone", "type": "prusalink", "host": "127.0.0.1", "port": 1}],
                         secret_getter=lambda s, k: None)
pl.PrusaLinkWorker.RETRY_S = 0.1
dead.start()
check(wait_for(lambda: len(logs) >= 1), "unreachable logs a line")
time.sleep(0.5)
check(len(logs) == 1 and dead.message()["printers"][0]["state"] == "OFFLINE", f"unreachable: {logs}")
dead.stop()

# Wrong password: clear hint, password never logged.
logs.clear()
store[(poll.SERVICE, key)] = "wrongpass"
bad = pr.PrinterService([entry], secret_getter=lambda s, k: store.get((s, k)))
bad.start()
check(wait_for(lambda: any("PrusaLink password on the printer" in line for line in logs)), f"401 hint: {logs}")
check(not any("wrongpass" in line for line in logs), "password not logged")
check(bad.message()["printers"][0]["state"] == "OFFLINE", "wrong password stays offline")
bad.stop()
poll.log.removeHandler(handler)

# ---- probe ---------------------------------------------------------------------
r = pl.probe({"host": "127.0.0.1", "port": PORT, "user": "maker"}, "s3cret")
check(r.ok and r.name == "prusa-mk4", f"probe ok: {r}")
r = pl.probe({"host": "127.0.0.1", "port": PORT, "user": "maker"}, "nope")
check(not r.ok and "password on the printer" in r.message and "nope" not in r.message, f"probe 401: {r}")
r = pl.probe({"host": "127.0.0.1", "port": PORT, "user": "maker"}, None)
check(not r.ok and "password" in r.message, f"probe no password: {r}")
r = pl.probe({"host": "127.0.0.1", "port": 1}, "s3cret", timeout=1)
check(not r.ok and "No answer" in r.message, f"probe unreachable: {r}")
Fake.auth_required = False
r = pl.probe({"host": "127.0.0.1", "port": PORT}, None)
check(r.ok, f"probe open server: {r}")
Fake.auth_required = True

# ---- the CLI -------------------------------------------------------------------
tmp = pathlib.Path(tempfile.mkdtemp()) / "config.toml"
tmp.write_text('# my config\n[hub]\nhost = "x"\n', encoding="utf-8")
ADD = functools.partial(printers_cli.cmd_add_polled, spec=pl.SPEC)


def run(cmd, answers, passwords):
    a, p = iter(answers), iter(passwords)
    builtins.input = lambda prompt="": next(a)
    getpass.getpass = lambda prompt="": next(p)
    cmd(tmp)


store.clear()
run(ADD, ["127.0.0.1", str(PORT), "", "", ""], ["s3cret"])
cfg = tomllib.loads(tmp.read_text())
check(cfg["printers"] == [{"name": "prusa-mk4", "type": "prusalink", "host": "127.0.0.1", "port": PORT,
                           "user": "maker"}], f"prusalink saved: {cfg.get('printers')}")
check(store.get((poll.SERVICE, key)) == "s3cret" and "s3cret" not in tmp.read_text(),
      "password in credential store only")
run(ADD, ["127.0.0.1", str(PORT), "", "", ""], ["s3cret"])
check(len(tomllib.loads(tmp.read_text())["printers"]) == 1, "duplicate host refused")
run(ADD, ["192.168.1.90", "", "admin", "", "", ""], [""])  # no password: cancelled
check(len(tomllib.loads(tmp.read_text())["printers"]) == 1, "password is required")
pl.SPEC.probe = lambda *a, **k: poll.ProbeResult(False, "No answer (stubbed)")
run(ADD, ["192.168.1.90", "", "bob", "y", "", "XL"], ["pw123"])
cfg = tomllib.loads(tmp.read_text())
check(cfg["printers"][1] == {"name": "Prusa", "type": "prusalink", "host": "192.168.1.90", "user": "bob",
                             "model": "XL"}, f"second printer: {cfg['printers'][1]}")
check(store.get((poll.SERVICE, "prusalink:192.168.1.90:80")) == "pw123" and "pw123" not in tmp.read_text(),
      "second password in credential store only")
check("PrusaLink 192.168.1.90:80" in printers_cli.describe(cfg["printers"][1]), "describe")

srv.shutdown()
print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
