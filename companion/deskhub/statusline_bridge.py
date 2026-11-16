"""Claude Code status line bridge for the desk hub. Standard library only.

Claude Code runs the status line command with a JSON description of the session
on stdin. On Pro/Max plans that JSON includes `rate_limits` (five-hour and
seven-day usage percentages with reset times). This script saves those numbers
to ~/.deskhub/claude_status.json for the companion, then runs your previous
status line command (if any) with the same stdin and prints its output, so your
status line looks exactly as before.

    python statusline_bridge.py [--wrap "<previous status line command>"]
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

OUT = pathlib.Path.home() / ".deskhub" / "claude_status.json"


def save(data: dict):
    limits = data.get("rate_limits")
    if not isinstance(limits, dict):
        return
    record = {
        "updated": int(time.time()),
        "rate_limits": {
            k: {"used_percentage": v.get("used_percentage"), "resets_at": v.get("resets_at")}
            for k, v in limits.items()
            if isinstance(v, dict) and k in ("five_hour", "seven_day")
        },
        "model": (data.get("model") or {}).get("display_name", ""),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=OUT.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(record, f)
    os.replace(tmp, OUT)


def main():
    raw = sys.stdin.buffer.read()
    try:
        save(json.loads(raw))
    except Exception:
        pass  # never break the user's status line over this

    wrapped = None
    if len(sys.argv) >= 3 and sys.argv[1] == "--wrap":
        wrapped = sys.argv[2]
    if wrapped:
        try:
            r = subprocess.run(wrapped, shell=True, input=raw, capture_output=True, timeout=10)
            sys.stdout.buffer.write(r.stdout)
        except Exception:
            pass
    else:
        try:
            print((json.loads(raw).get("model") or {}).get("display_name", ""))
        except Exception:
            pass


if __name__ == "__main__":
    main()
