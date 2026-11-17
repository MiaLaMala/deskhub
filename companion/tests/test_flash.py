"""deskhub-flash: how the board's answers to a Wi-Fi install are read."""
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import httpx

from deskhub import flash_cli as f

problems = []


def check(ok, what):
    print(("ok  " if ok else "BAD ") + what)
    if not ok:
        problems.append(what)


img = pathlib.Path(tempfile.mkdtemp()) / "deskhub.bin"
img.write_bytes(b"\xe9" + b"\0" * 200_000)
sent = {}


def fake(status, text=""):
    def post(url, params, content, headers, timeout):
        sent.update(url=url, params=params, size=len(content))
        return httpx.Response(status, text=text)
    return post


def down(*a, **k):
    raise httpx.ConnectError("no route")


check(f.send_over_wifi(img, "hub.local", "tok", post=fake(200, "installed")) == f.OK, "200 installs")
check(sent == {"url": "http://hub.local/firmware", "params": {"token": "tok"}, "size": 200_001}, f"request: {sent}")
check(f.send_over_wifi(img, "h", "t", post=fake(403, "denied on the board")) == f.DENIED, "Deny tapped")
check(f.send_over_wifi(img, "h", "t", post=fake(403, "bad token")) == f.BAD_TOKEN, "wrong token")
check(f.send_over_wifi(img, "h", "t", post=fake(408)) == f.NO_ANSWER, "nobody answered")
check(f.send_over_wifi(img, "h", "t", post=fake(404)) == f.NO_OTA, "old firmware without /firmware")
check(f.send_over_wifi(img, "h", "t", post=fake(500)) == f.FAILED, "install failed")
check(f.send_over_wifi(img, "h", "t", post=down) == f.UNREACHABLE, "board unreachable")

conf = img.parent / "config.toml"
conf.write_text('[hub]\nhost = "10.0.0.5"\ntoken = "abc"\n')
check(f.hub_settings(conf) == ("10.0.0.5", "abc"), "host and token from config.toml")
check(f.hub_settings(img.parent / "missing.toml") == ("deskhub.local", ""), "defaults without a config")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
