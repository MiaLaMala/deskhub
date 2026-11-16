"""Popular games that aren't (only) on Steam, recognised without any setup.

They work like `[[games]]` entries in config.toml (see custom_games.py): the board
shows one while its program runs, it joins the recent games once played, and a tap
opens `launch`. Your own `[[games]]` entry with the same name replaces a preset.
Turn them off with `[game_presets] enabled = false`, or skip some with
`disabled = ["Roblox", ...]`.

`steam_appid` borrows the cover from Steam's CDN for games that are also sold there.
League of Legends and Teamfight Tactics run as the same program, so the League
client's local API (on this PC only) tells them apart.
"""
import json
import logging
import os
import pathlib

log = logging.getLogger(__name__)

RIOT_INSTALLS = pathlib.Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "Riot Games" / "RiotClientInstalls.json"
STEAM_HEADER = "https://cdn.cloudflare.steamstatic.com/steam/apps/{}/header.jpg"

_RIOT_LOL = "{riot} --launch-product=league_of_legends --launch-patchline=live"

PRESETS = [
    # Riot
    {"name": "League of Legends", "process": ["league of legends.exe"], "launch": _RIOT_LOL, "mode": "lol"},
    {"name": "Teamfight Tactics", "process": ["league of legends.exe"], "launch": _RIOT_LOL, "mode": "tft"},
    {"name": "VALORANT", "process": ["valorant-win64-shipping.exe"],
     "launch": "{riot} --launch-product=valorant --launch-patchline=live"},
    # Epic
    {"name": "Fortnite", "process": ["fortniteclient-win64-shipping.exe"],
     "launch": "com.epicgames.launcher://apps/Fortnite?action=launch&silent=true"},
    {"name": "Rocket League", "process": ["rocketleague.exe"], "steam_appid": 252950,
     "launch": "com.epicgames.launcher://apps/Sugar?action=launch&silent=true"},
    # Minecraft
    {"name": "Minecraft", "process": ["javaw.exe", "java.exe"], "match": "minecraft",
     "launch": "C:/XboxGames/Minecraft Launcher/Content/Minecraft.exe"},
    {"name": "Minecraft Bedrock", "process": ["minecraft.windows.exe"], "launch": "minecraft://"},
    {"name": "Roblox", "process": ["robloxplayerbeta.exe"]},
    # Battle.net
    {"name": "Overwatch 2", "process": ["overwatch.exe"], "steam_appid": 2357570, "launch": "battlenet://Pro"},
    {"name": "World of Warcraft", "process": ["wow.exe", "wowclassic.exe"], "launch": "battlenet://WoW"},
    {"name": "Diablo IV", "process": ["diablo iv.exe"], "steam_appid": 2344520, "launch": "battlenet://Fen"},
    {"name": "Hearthstone", "process": ["hearthstone.exe"], "launch": "battlenet://WTCG"},
    {"name": "StarCraft II", "process": ["sc2_x64.exe", "sc2.exe"], "launch": "battlenet://S2"},
    {"name": "Call of Duty", "process": ["cod.exe"]},
    # HoYoverse
    {"name": "Genshin Impact", "process": ["genshinimpact.exe", "yuanshen.exe"]},
    {"name": "Honkai: Star Rail", "process": ["starrail.exe"]},
    {"name": "Zenless Zone Zero", "process": ["zenlesszonezero.exe"]},
    # Others
    {"name": "Grand Theft Auto V", "process": ["gta5.exe", "gta5_enhanced.exe"], "steam_appid": 271590},
    {"name": "Apex Legends", "process": ["r5apex.exe", "r5apex_dx12.exe"], "steam_appid": 1172470},
    {"name": "EA SPORTS FC", "process": ["fc25.exe", "fc26.exe"]},
    {"name": "The Sims 4", "process": ["ts4_x64.exe"], "steam_appid": 1222670},
    {"name": "Halo Infinite", "process": ["haloinfinite.exe"], "steam_appid": 1240440},
    {"name": "Escape from Tarkov", "process": ["escapefromtarkov.exe"]},
    {"name": "osu!", "process": ["osu!.exe"]},
]


def riot_client() -> str:
    """Path of RiotClientServices.exe, from Riot's own install record, or ""."""
    try:
        data = json.loads(RIOT_INSTALLS.read_text(encoding="utf-8"))
        path = data.get("rc_default") or data.get("rc_live") or ""
        return path if path and os.path.isfile(path) else ""
    except (OSError, ValueError, AttributeError):
        return ""


def _launch(template: str) -> str:
    if "{riot}" in template:
        rc = riot_client()
        return template.replace("{riot}", f'"{rc}"') if rc else ""
    if "://" not in template and not os.path.exists(template):
        return ""  # e.g. the Minecraft Launcher isn't installed
    return template


def preset_entries(cfg: dict, taken: set[str]) -> list[dict]:
    """Presets as raw [[games]]-style dicts, minus those turned off or overridden."""
    opts = cfg.get("game_presets", {}) or {}
    if not opts.get("enabled", True):
        return []
    disabled = {str(n).strip().lower() for n in opts.get("disabled", []) or []}
    out = []
    for p in PRESETS:
        key = p["name"].lower()
        if key in disabled or key in taken:
            continue
        entry = {"name": p["name"], "process": list(p["process"])}
        if p.get("match"):
            entry["match"] = p["match"]
        if p.get("launch"):
            launch = _launch(p["launch"])
            if launch:
                entry["launch"] = launch
        if p.get("steam_appid"):
            entry["image"] = STEAM_HEADER.format(p["steam_appid"])
        if p.get("mode"):
            entry["mode"] = p["mode"]
        out.append(entry)
    return out


def league_mode(processes=None, get=None) -> str:
    """"tft" when the League client says the current game is Teamfight Tactics, else
    "lol". Asks the client's local API (127.0.0.1) with the port and token it puts on
    its own command line; nothing leaves this PC."""
    import psutil

    try:
        port = token = ""
        for p in (processes or psutil.process_iter)(["name"]):
            if (p.info.get("name") or "").lower() == "leagueclientux.exe":
                for arg in p.cmdline():
                    if arg.startswith("--app-port="):
                        port = arg.split("=", 1)[1]
                    elif arg.startswith("--remoting-auth-token="):
                        token = arg.split("=", 1)[1]
                break
        if not port or not token:
            return "lol"
        if get is None:
            import httpx

            def get(url, auth):
                return httpx.get(url, auth=auth, verify=False, timeout=2).json()
        s = get(f"https://127.0.0.1:{port}/lol-gameflow/v1/session", ("riot", token)) or {}
        mode = ((s.get("gameData") or {}).get("queue") or {}).get("gameMode") or (s.get("map") or {}).get("gameMode")
        return "tft" if str(mode).upper() == "TFT" else "lol"
    except Exception as e:  # client closed, API changed
        log.debug("league mode: %s", e)
        return "lol"
