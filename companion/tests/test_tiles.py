"""Shortcut tiles that light up: which Windows state each tile shows, and the
message the board gets. Reads (never changes) the real mute states on Windows.

    uv run python tests/test_tiles.py
"""
import os
import sys

from deskhub import audio_state
from deskhub.shortcuts import lit_message, load_tiles, tile_state

problems = []


def check(cond, msg):
    if not cond:
        problems.append(msg)


check(tile_state({"action": "volume", "target": "mute"}) == "speaker_mute", "system mute tile -> speaker")
check(tile_state({"action": "volume", "target": "up"}) == "", "volume up has no state")
check(tile_state({"action": "mic"}) == "mic_mute", "mic action -> mic")
check(tile_state({"action": "keys", "target": "ctrl+shift+m", "icon": "mic_off"}) == "mic_mute", "mic icon -> mic")
check(tile_state({"action": "keys", "icon": "mic_off", "state": ""}) == "", "state = '' turns it off")
check(tile_state({"action": "run", "state": "speaker_mute"}) == "speaker_mute", "explicit state")
check(tile_state({"action": "run", "state": "bogus"}) == "", "unknown state ignored")

tiles = load_tiles({"tiles": [
    {"label": "Mic", "action": "mic", "icon": "mic_off"},
    {"label": "Mute", "action": "volume", "target": "mute"},
    {"label": "Vol +", "action": "volume", "target": "up"},
]})
check([t["state"] for t in tiles] == ["mic_mute", "speaker_mute", ""], f"states loaded: {tiles}")
check(lit_message(tiles, {"mic_mute": True, "speaker_mute": False}) == {"type": "tile_state", "on": [0]}, "mic lit")
check(lit_message(tiles, {"mic_mute": True, "speaker_mute": True})["on"] == [0, 1], "both lit")
check(lit_message(tiles, {})["on"] == [], "no devices -> nothing lit")

if sys.platform == "win32":
    audio_state.com_thread()
    st = audio_state.read_states()
    if st or not os.environ.get("CI"):
        check(isinstance(st.get("speaker_mute"), bool), f"speaker mute readable: {st}")
    else:
        print("skip speaker mute: no audio device (CI runner)")

print("\nPROBLEMS:" if problems else "\nOK", problems if problems else "")
sys.exit(1 if problems else 0)
