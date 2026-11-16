"""Opt-in: current Claude plan limits straight from Anthropic.

Off unless `[claude] live_limits = true` in config.toml. When on, the companion
reads the access token that Claude Code saved in ~/.claude/.credentials.json and
asks https://api.anthropic.com/api/oauth/usage for the 5-hour and weekly
percentages, the same lookup Claude's own apps use to draw their usage bars.

- No messages are sent to Claude, so this uses no tokens and no API credits.
- The token stays in memory. It is never logged, saved elsewhere, or sent to the hub.
- The token is never refreshed here (refreshing could sign Claude Code out).
  When it expires, live limits pause until Claude Code renews it on its next use.
- The endpoint is undocumented and may change; failures fall back quietly to the
  status line readings.
"""
import datetime as dt
import json
import logging
import pathlib
import time

import httpx

log = logging.getLogger(__name__)

URL = "https://api.anthropic.com/api/oauth/usage"
CREDENTIALS = pathlib.Path.home() / ".claude" / ".credentials.json"


def _epoch(iso: str | None) -> int | None:
    if not iso:
        return None
    try:
        return int(dt.datetime.fromisoformat(iso).timestamp())
    except ValueError:
        return None


class LiveLimits:
    def __init__(self, path: pathlib.Path = CREDENTIALS):
        self.path = path
        self._next = 0.0
        self._last: dict = {}
        self._bad_mtime = None   # credentials file state that got a 401
        self._state = ""         # last logged problem, so each is logged once

    def _note(self, state: str, msg: str):
        if state != self._state:
            self._state = state
            if msg:
                log.info("live Claude limits: %s", msg)

    def _token(self) -> str | None:
        try:
            st = self.path.stat()
            if self._bad_mtime == st.st_mtime:
                return None  # same token that was rejected; wait for Claude Code to renew it
            oauth = json.loads(self.path.read_text(encoding="utf-8")).get("claudeAiOauth") or {}
        except (OSError, ValueError):
            self._note("nofile", "no Claude Code sign-in found; run `claude` once to sign in")
            return None
        token = oauth.get("accessToken")
        expires = (oauth.get("expiresAt") or 0) / 1000
        if not token:
            self._note("notoken", "no access token in the Claude Code sign-in")
            return None
        if expires and expires < time.time() + 30:
            self._note("expired", "sign-in expired; paused until Claude Code renews it (use `claude` once)")
            return None
        return token

    def get(self, active: bool) -> dict:
        """Latest limits as {five_hour: {pct, reset}, seven_day: {...}, updated}, or {}.
        Polls every minute while Claude Code is in use, every 5 minutes otherwise."""
        now = time.time()
        if now < self._next:
            return self._last
        self._next = now + (60 if active else 300)
        token = self._token()
        if not token:
            return self._last if self._fresh() else {}
        try:
            r = httpx.get(URL, timeout=15, headers={
                "Authorization": f"Bearer {token}",
                "anthropic-beta": "oauth-2025-04-20",
                "User-Agent": "deskhub",
            })
        except httpx.HTTPError as e:
            self._note("neterr", f"request failed ({type(e).__name__})")
            return self._last if self._fresh() else {}
        if r.status_code == 401:
            try:
                self._bad_mtime = self.path.stat().st_mtime
            except OSError:
                pass
            self._note("401", "sign-in was rejected; paused until Claude Code renews it")
            return {}
        if r.status_code == 429:
            self._next = now + 600
            self._note("429", "rate limited; trying again in 10 minutes")
            return self._last if self._fresh() else {}
        if r.status_code != 200:
            self._note(f"http{r.status_code}", f"HTTP {r.status_code}")
            return self._last if self._fresh() else {}
        try:
            data = r.json()
        except ValueError:
            self._note("badjson", "unexpected response")
            return {}
        out = {}
        for name in ("five_hour", "seven_day"):
            w = data.get(name) or {}
            pct, reset = w.get("utilization"), _epoch(w.get("resets_at"))
            if isinstance(pct, (int, float)) and reset and reset > now:
                out[name] = {"pct": round(float(pct), 1), "reset": reset}
        if out:
            out["updated"] = int(now)
            self._note("ok", "receiving live limits")
        self._last = out
        return out

    def _fresh(self) -> bool:
        return bool(self._last) and time.time() - self._last.get("updated", 0) < 15 * 60
