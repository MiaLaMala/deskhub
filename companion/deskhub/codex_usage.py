"""OpenAI Codex token usage, read from the local session logs.

Codex (CLI and app) writes one JSONL file per session under
~/.codex/sessions/YYYY/MM/DD/ (and ~/.codex/archived_sessions/). Only token
counts, rate limit readings, model names and timestamps are read; message text
is never looked at or sent. $CODEX_HOME overrides ~/.codex.

The log format is not a documented API, so this may need updating if Codex
changes it.
"""
import datetime as dt
import json
import logging
import os
import pathlib
import time

log = logging.getLogger(__name__)

HISTORY_DAYS = 7


def codex_home() -> pathlib.Path:
    env = os.environ.get("CODEX_HOME")
    return pathlib.Path(env) if env else pathlib.Path.home() / ".codex"


def _model_name(model: str) -> str:
    """Short display name, e.g. "gpt-6.1-sol" -> "GPT-6.1 Sol" (15 characters at most)."""
    parts = [p for p in (model or "").split("-") if p]
    if not parts:
        return "Other"
    if parts[0].lower() == "gpt" and len(parts) > 1:
        name = "GPT-" + parts[1]
        rest = parts[2:]
    else:
        name = parts[0].upper() if len(parts[0]) <= 3 else parts[0].title()
        rest = parts[1:]
    if rest:
        name += " " + " ".join(p.title() for p in rest)
    return name[:15]


def _limits_from(rate_limits: dict, ts: float) -> dict:
    """Map Codex's windows onto five_hour / seven_day by their length.
    Windows whose reset time has passed are dropped."""
    now = time.time()
    out = {}
    for w in (rate_limits.get("primary"), rate_limits.get("secondary")):
        if not isinstance(w, dict):
            continue
        pct, reset, mins = w.get("used_percent"), w.get("resets_at"), w.get("window_minutes")
        if not all(isinstance(v, (int, float)) for v in (pct, reset, mins)) or reset <= now:
            continue
        name = "five_hour" if mins <= 360 else "seven_day" if mins >= 1440 else None
        if name:
            out[name] = {"pct": round(float(pct), 1), "reset": int(reset)}
    if out:
        out["updated"] = int(ts)
    return out


class CodexUsage:
    def __init__(self, home: pathlib.Path | None = None):
        self.home = home or codex_home()
        self._offsets: dict[pathlib.Path, int] = {}
        self._models: dict[pathlib.Path, str] = {}
        self._seen: set[tuple[str, str]] = set()
        # (timestamp, model name, total tokens, output tokens)
        self._entries: list[tuple[dt.datetime, str, int, int]] = []
        self._limit_ts = 0.0
        self._rate_limits: dict | None = None

    def _files(self):
        for sub in ("sessions", "archived_sessions"):
            root = self.home / sub
            if root.is_dir():
                yield from root.glob("**/*.jsonl")

    def _scan(self):
        cutoff = time.time() - (HISTORY_DAYS + 1) * 86400
        for path in self._files():
            try:
                st = path.stat()
            except OSError:
                continue
            if st.st_mtime < cutoff:
                continue
            start = self._offsets.get(path, 0)
            if st.st_size < start:  # file was rewritten
                start = 0
            if st.st_size == start:
                continue
            try:
                with open(path, "rb") as f:
                    f.seek(start)
                    data = f.read()
            except OSError:
                continue
            # Only consume complete lines; a partial last line is re-read next time.
            end = data.rfind(b"\n") + 1
            self._offsets[path] = start + end
            for line in data[:end].splitlines():
                self._ingest(path, line)

    def _ingest(self, path: pathlib.Path, line: bytes):
        is_ctx = b'"turn_context"' in line
        if not is_ctx and b'"token_count"' not in line:
            return
        try:
            d = json.loads(line)
        except ValueError:
            return
        payload = d.get("payload")
        if not isinstance(payload, dict):
            return
        if is_ctx and d.get("type") == "turn_context":
            if isinstance(payload.get("model"), str):
                self._models[path] = payload["model"]
            return
        if d.get("type") != "event_msg" or payload.get("type") != "token_count":
            return
        stamp = d.get("timestamp")
        try:
            ts = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            return
        rl = payload.get("rate_limits")
        if isinstance(rl, dict) and ts.timestamp() >= self._limit_ts:
            self._limit_ts, self._rate_limits = ts.timestamp(), rl
        info = payload.get("info")
        last = info.get("last_token_usage") if isinstance(info, dict) else None
        if not isinstance(last, dict):
            return
        key = (str(path), stamp)
        if key in self._seen:
            return
        self._seen.add(key)
        out = int(last.get("output_tokens") or 0)
        total = last.get("total_tokens")
        total = int(total) if isinstance(total, (int, float)) else int(last.get("input_tokens") or 0) + out
        self._entries.append((ts, _model_name(self._models.get(path, "")), total, out))

    def snapshot(self) -> dict:
        self._scan()
        now = dt.datetime.now(dt.timezone.utc)
        horizon = now - dt.timedelta(days=HISTORY_DAYS)
        self._entries = sorted(e for e in self._entries if e[0] >= horizon)

        local_today = dt.datetime.now().astimezone().date()
        days = [local_today - dt.timedelta(days=i) for i in range(HISTORY_DAYS - 1, -1, -1)]
        per_day = {d: 0 for d in days}
        today = {"tokens": 0, "output": 0, "messages": 0}
        models: dict[str, int] = {}
        last_hour = 0
        for ts, name, total, out in self._entries:
            day = ts.astimezone().date()
            if day in per_day:
                per_day[day] += total
            if day == local_today:
                today["tokens"] += total
                today["output"] += out
                today["messages"] += 1
                models[name] = models.get(name, 0) + total
            if now - ts <= dt.timedelta(hours=1):
                last_hour += total

        last = self._entries[-1][0] if self._entries else None
        return {
            "limits": _limits_from(self._rate_limits, self._limit_ts) if self._rate_limits else {},
            "type": "codex",
            "today": today,
            "block": {"active": False},
            "last_hour": last_hour,
            "days": [per_day[d] for d in days],
            "models": [{"name": k, "tokens": v}
                       for k, v in sorted(models.items(), key=lambda kv: -kv[1]) if v > 0][:4],
            "last_active": int(last.timestamp()) if last else 0,
        }
