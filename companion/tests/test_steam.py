"""Steam module against a fake Steam tree: VDF parsing, snapshot, frames, launch.

    uv run python tests/test_steam.py
"""
import io
import os
import pathlib
import struct
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from PIL import Image  # noqa: E402

from deskhub import steam as st  # noqa: E402

problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


# ---- VDF parser ---------------------------------------------------------------
v = st.parse_vdf('''﻿// comment
"Root" { "a" "1" // trailing
  "Nested" { "b" "two words" "esc" "q\\"x\\\\y" }
  bare value
  "empty" {}
  "dup" "1" "dup" "2"
}
''')
check(v["Root"]["a"] == "1", "vdf value")
check(v["Root"]["Nested"]["b"] == "two words", "vdf spaces")
check(v["Root"]["Nested"]["esc"] == 'q"x\\y', f"vdf escapes {v['Root']['Nested']['esc']!r}")
check(v["Root"]["bare"] == "value", "vdf bare tokens")
check(v["Root"]["empty"] == {} and v["Root"]["dup"] == "2", "vdf empty block / dup key")
check(st.parse_vdf('"a" { "b" "1"') == {"a": {"b": "1"}}, "vdf unterminated block")
check(st.parse_vdf("") == {}, "vdf empty")
check(st._get({"Software": {"Valve": {"x": "1"}}}, "software", "VALVE") == {"x": "1"}, "case-insensitive get")

# ---- fake Steam tree -----------------------------------------------------------
tmp = pathlib.Path(tempfile.mkdtemp())
root = tmp / "Steam"
lib2 = tmp / "Lib2"
for lib in (root, lib2):
    (lib / "steamapps").mkdir(parents=True)
(root / "steamapps" / "libraryfolders.vdf").write_text(
    '"libraryfolders" { "0" { "path" "%s" } "1" { "path" "%s" } "2" { "path" "%s" } }' % (
        str(root).replace("\\", "\\\\"), str(lib2).replace("\\", "\\\\"),
        str(tmp / "Missing").replace("\\", "\\\\")), encoding="utf-8")


def manifest(lib, appid, name):
    (lib / "steamapps" / f"appmanifest_{appid}.acf").write_text(
        '"AppState" { "appid" "%d" "name" "%s" }' % (appid, name), encoding="utf-8")


manifest(root, 10, "Alpha")
manifest(root, 228980, "Steamworks Common Redistributables")
manifest(root, 1493710, "Proton Experimental")
manifest(lib2, 20, "Beta Game")
manifest(lib2, 30, "Gamma")

APPS = {10: (1000, 120), 20: (3000, 45), 30: (2000, 9), 228980: (9999, 1), 1493710: (9998, 1),
        40: (4000, 600), 50: (0, 0), 60: (500, 3), 70: (400, 2)}


def localconfig(path, apps):
    body = "".join('"%d" { "LastPlayed" "%d" "Playtime" "%d" "Other" "x" }\n' % (i, lp, pt)
                   for i, (lp, pt) in apps.items())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('"UserLocalConfigStore" { "Software" { "Valve" { "Steam" { "apps" { %s } } } } }' % body, encoding="utf-8")


old_cfg = root / "userdata" / "111" / "config" / "localconfig.vdf"
new_cfg = root / "userdata" / "222" / "config" / "localconfig.vdf"
localconfig(old_cfg, {10: (1, 1)})  # stale account: must be ignored
localconfig(new_cfg, APPS)
os.utime(old_cfg, (1_000_000, 1_000_000))
os.utime(new_cfg, (2_000_000, 2_000_000))

# Store names and art never touch the network in tests.
st.NAMES_FILE = tmp / "names.json"
st.ART_DIR = tmp / "art"
st.httpx.get = lambda *a, **k: (_ for _ in ()).throw(st.httpx.ConnectError("offline"))

now = [10_000.0]
reg = [str(root), 0]
st.read_registry = lambda: (reg[0], reg[1])
s = st.Steam(clock=lambda: now[0])

snap = s.snapshot()
check(snap["found"] and snap["playing"] is None, f"nothing playing: {snap}")
ids = [g["appid"] for g in snap["recent"]]
check(ids == [40, 20, 30, 10, 60], f"recent order/exclusions: {ids}")
check(snap["recent"][0]["name"] == "App 40" and snap["recent"][0]["total_min"] == 600, "uninstalled name fallback")
check(snap["recent"][1]["name"] == "Beta Game" and snap["recent"][1]["last"] == 3000, "installed game fields")

# Playing: excluded from recent, session_s counts from when the change was seen.
reg[1] = 20
now[0] += 5
snap = s.snapshot()
check(snap["playing"] and snap["playing"]["appid"] == 20 and snap["playing"]["name"] == "Beta Game", f"playing {snap['playing']}")
check(snap["playing"]["session_s"] == 0 and snap["playing"]["total_min"] == 45, "session starts at 0")
check(20 not in [g["appid"] for g in snap["recent"]], "playing game not in recent")
now[0] += 30
check(s.snapshot()["playing"]["session_s"] == 30, "session counts seconds")
reg[1] = 0
check(s.snapshot()["playing"] is None, "stopped")
reg[1] = 228980
check(s.snapshot()["playing"] is None, "redistributable is not a game")
reg[1] = 0

# Long names are folded and cut.
manifest(root, 80, "Café " + "x" * 80)
localconfig(new_cfg, {**APPS, 80: (5000, 1)})
now[0] += 61  # past the cache window
snap = s.snapshot()
check(snap["recent"][0]["appid"] == 80 and snap["recent"][0]["name"].startswith("Cafe x") and len(snap["recent"][0]["name"]) == 40,
      f"name folded: {snap['recent'][0]['name']!r}")

# Not installed.
st.read_registry = lambda: (None, 0)
check(st.Steam().snapshot()["found"] is False, "steam not found")
st.read_registry = lambda: (reg[0], reg[1])

# ---- frames ----------------------------------------------------------------------


def jpeg(w, h, color):
    b = io.BytesIO()
    Image.new("RGB", (w, h), color).save(b, "JPEG")
    return b.getvalue()


fetched = []


def fake_art(self, appid, portrait):
    fetched.append((appid, portrait))
    if portrait and appid == 30:
        return None  # no portrait: falls back to a crop of the header
    return jpeg(600, 900, (255, 0, 0)) if portrait else jpeg(460, 215, (0, 255, 0))


st.Steam._fetch_art = fake_art
s = st.Steam(clock=lambda: now[0])
s.snapshot()  # nothing playing: thumb of the most recent game + 5 portraits
frames = s.frames()
hdr = lambda f: struct.unpack("<4sIHHHH", f[:16])  # noqa: E731
kinds = sorted((hdr(f)[1], hdr(f)[4]) for f in frames)
recent_ids = [g["appid"] for g in s._snap["recent"]]
check(kinds == sorted([(recent_ids[0], 1)] + [(i, 2) for i in recent_ids]), f"idle frames: {kinds}")
for f in frames:
    magic, appid, w, h, kind, zero = hdr(f)
    check(magic == b"STM1" and zero == 0, "frame magic")
    check((w, h) == st.KIND_SIZES[kind] and len(f) == 16 + w * h * 2, f"frame size kind {kind}")
check(st.KIND_SIZES == {0: (340, 159), 1: (64, 96), 2: (96, 144)}, "kind sizes")
p30 = next(f for f in frames if hdr(f)[1] == 30 and hdr(f)[4] == 2)
px = struct.unpack("<H", p30[16:18])[0]
check(px >> 11 == 0 and (px >> 5) & 0x3F > 50, "portrait fallback is a crop of the green header")
p40 = next(f for f in frames if hdr(f)[1] == 40 and hdr(f)[4] == 2)
check(struct.unpack("<H", p40[16:18])[0] >> 11 == 31, "portrait uses the red portrait art (RGB565 LE)")
check(s.frames() == [], "no changed frames the second time")
check(len(s.all_frames()) == len(frames), "all_frames resends everything")

reg[1] = 20
s.snapshot()
frames = s.frames()
k = sorted((hdr(f)[1], hdr(f)[4]) for f in frames)
check(k == [(20, 0), (20, 1), (60, 2)], f"playing frames (header, thumb, newly listed portrait): {k}")
check(any(hdr(f)[4] == 0 and (hdr(f)[2], hdr(f)[3]) == (340, 159) for f in frames), "header 340x159")
reg[1] = 0

# ---- launch ----------------------------------------------------------------------
started = []
os.startfile = lambda uri: started.append(uri)
s.snapshot()
check(s.launch(999999) is False and not started, "unknown appid refused")
check(s.launch(recent_ids[0]) is True and started == [f"steam://rungameid/{recent_ids[0]}"], f"launch ok: {started}")
check(s.launch(228980) is False, "redistributable refused")

import shutil  # noqa: E402
shutil.rmtree(tmp, ignore_errors=True)

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
