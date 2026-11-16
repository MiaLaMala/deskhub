"""Steam extras that need the Steam Web API: which friends are in a game, and total
playtime for every game you own (Steam's local files only have it for some).

Opt-in: it needs your own Web API key from https://steamcommunity.com/dev/apikey,
kept in the Windows credential store (service "deskhub-steam"), never in
config.toml. Requests go only to api.steampowered.com, with your key and Steam ID.
"""
import logging
import time

from .text import ascii_fold

log = logging.getLogger(__name__)

API = "https://api.steampowered.com"
KEYRING_SERVICE = "deskhub-steam"
KEYRING_USER = "web_api_key"
STEAMID64_BASE = 76561197960265728
FRIENDS_EVERY_S = 60
PLAYTIME_EVERY_S = 30 * 60
BACKOFF_S = 10 * 60
MAX_FRIENDS = 5


def steamid64(account_id: int) -> int:
    """The 64-bit Steam ID for a userdata/<account id> folder."""
    return STEAMID64_BASE + int(account_id)


def get_key() -> str:
    try:
        import keyring

        return keyring.get_password(KEYRING_SERVICE, KEYRING_USER) or ""
    except Exception as e:  # no keyring backend
        log.debug("steam key: %s", e)
        return ""


def set_key(key: str | None):
    import keyring

    if key:
        keyring.set_password(KEYRING_SERVICE, KEYRING_USER, key)
    else:
        try:
            keyring.delete_password(KEYRING_SERVICE, KEYRING_USER)
        except keyring.errors.PasswordDeleteError:
            pass


def _http_get(url: str, params: dict) -> dict:
    import httpx

    r = httpx.get(url, params=params, timeout=10)
    r.raise_for_status()
    return r.json()


class SteamWeb:
    def __init__(self, key: str, get=_http_get, clock=time.time):
        self.key = key
        self._get = get
        self._clock = clock
        self._friends: list[dict] = []
        self._friends_at = -1e9
        self._playtime: dict[int, int] = {}
        self._playtime_at = -1e9
        self._fail_until: dict[str, float] = {}   # per API method

    def _call(self, path: str, **params):
        method = path.split("/")[1]
        if self._clock() < self._fail_until.get(method, 0):
            return None
        try:
            return self._get(f"{API}/{path}", {"key": self.key, **params})
        except Exception as e:  # bad key (403), private data (401), network
            status = getattr(getattr(e, "response", None), "status_code", None)
            if status == 401 and method == "GetFriendList":
                log.warning("Steam won't share your friends list: set Friends List to Public in "
                            "Steam > Profile > Edit Profile > Privacy Settings. Trying again in 30 minutes")
                self._fail_until[method] = self._clock() + 3 * BACKOFF_S
            else:
                log.warning("Steam Web API %s failed: %s; trying again in 10 minutes", method, status or e)
                self._fail_until[method] = self._clock() + BACKOFF_S
            return None

    def friends_in_game(self, sid: int) -> list[dict]:
        """Friends playing something now: [{"name", "game"}], at most 5."""
        now = self._clock()
        if now - self._friends_at < FRIENDS_EVERY_S:
            return self._friends
        data = self._call("ISteamUser/GetFriendList/v1/", steamid=sid, relationship="friend")
        if data is None:
            return self._friends
        self._friends_at = now
        ids = [f["steamid"] for f in (data.get("friendslist") or {}).get("friends", [])]
        playing = []
        for i in range(0, len(ids), 100):  # the API takes 100 ids at a time
            s = self._call("ISteamUser/GetPlayerSummaries/v2/", steamids=",".join(ids[i:i + 100]))
            for p in ((s or {}).get("response") or {}).get("players", []):
                if p.get("gameextrainfo"):
                    playing.append({"name": ascii_fold(p.get("personaname", ""), 24),
                                    "game": ascii_fold(p["gameextrainfo"], 32)})
        self._friends = sorted(playing, key=lambda f: f["name"].lower())[:MAX_FRIENDS]
        return self._friends

    def playtimes(self, sid: int) -> dict[int, int]:
        """Total minutes played per appid, for every game you own."""
        now = self._clock()
        if now - self._playtime_at < PLAYTIME_EVERY_S:
            return self._playtime
        data = self._call("IPlayerService/GetOwnedGames/v1/", steamid=sid, include_played_free_games=1)
        if data is not None:
            self._playtime_at = now
            self._playtime = {int(g["appid"]): int(g.get("playtime_forever", 0))
                              for g in (data.get("response") or {}).get("games", [])}
        return self._playtime
