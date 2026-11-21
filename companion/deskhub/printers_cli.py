"""Connect 3D printers: Bambu Lab (cloud account or LAN) and Klipper printers (Moonraker).

    uv run deskhub-printers [--config path/to/config.toml] [list|add-cloud|add-local|add-moonraker|remove]
"""
import argparse
import getpass
import pathlib
import re

import tomlkit

from . import bambu_cloud as cloud
from . import moonraker as mr
from .__main__ import find_config
from .calendar_feed import _safe_error
from .calendars_cli import ask, load, write
from .printer import MAX_PRINTERS, MODELS, lan_key, probe_local

_IP = re.compile(r"[\w.\-:]+")


def printers_of(doc) -> tomlkit.items.AoT:
    if "printers" not in doc:
        doc["printers"] = tomlkit.aot()
    return doc["printers"]


def _keyring():
    import keyring
    return keyring


def _ensure_page(doc):
    """With an explicit [pages] list, the printer page must be in it to show up."""
    pages = doc.get("pages")
    enabled = pages.get("enabled") if pages is not None else None
    if enabled is not None and "printer" not in enabled:
        enabled.append("printer")
        print("Added \"printer\" to [pages] enabled so the page shows.")


def _same(a, b) -> bool:
    if a.get("type") == "moonraker" or b.get("type") == "moonraker":
        return (a.get("type"), a.get("host"), a.get("port", mr.DEFAULT_PORT)) == \
               (b.get("type"), b.get("host"), b.get("port", mr.DEFAULT_PORT))
    return a.get("serial") == b.get("serial")


def _add(path, doc, entry: dict) -> bool:
    printers = printers_of(doc)
    if any(_same(p, entry) for p in printers):
        print(f"{entry.get('serial') or entry.get('host')} is already configured.")
        return False
    if len(printers) >= MAX_PRINTERS:
        print(f"The board shows at most {MAX_PRINTERS} printers. Remove one first.")
        return False
    row = tomlkit.table()
    for k, v in entry.items():
        row[k] = v
    printers.append(row)
    _ensure_page(doc)
    write(path, doc)
    return True


def describe(p) -> str:
    if p.get("type") == "moonraker":
        return (f"{p.get('name', '')}  [{p.get('model') or 'Klipper'}, Moonraker "
                f"{p.get('host', '')}:{p.get('port', mr.DEFAULT_PORT)}]")
    model = p.get("model") or MODELS.get(str(p.get("serial", ""))[:3], "")
    where = f"LAN {p.get('host', '')}" if p.get("type") == "local" else f"cloud {p.get('account', '')}"
    return f"{p.get('name', '')}  [{model + ', ' if model else ''}{where}, serial {p.get('serial', '')}]"


def cmd_list(path):
    printers = printers_of(load(path))
    if not printers:
        print("No printers configured yet.")
    for i, p in enumerate(printers, 1):
        print(f"  {i}. {describe(p)}")


def sign_in(http, region: str, email: str) -> str | None:
    """Password, then an emailed code if Bambu asks for one. -> access token or None."""
    password = getpass.getpass("Bambu password (hidden): ")
    if not password:
        return None
    try:
        res = cloud.login(http, region, email, password)
        if res["status"] == "code":
            cloud.send_code(http, region, email)
            print(f"Bambu emailed a verification code to {email}.")
            code = ask("Code (empty to cancel)")
            if not code:
                return None
            return cloud.login_with_code(http, region, email, code)
        return res["token"]
    except cloud.BambuError as e:
        print(f"Sign-in failed: {_safe_error(e, password)}")
        return None


def cmd_add_cloud(path):
    print("""
Bambu cloud
  Sign in with your Bambu Lab account to read your printers' status through Bambu's servers.
  This works from anywhere, and OrcaSlicer and Bambu Handy keep working as usual.
  The access token (valid about 3 months) goes into your OS credential store; your password
  is not saved.
""")
    email = ask("Bambu account email (empty to cancel)")
    if not email:
        return
    region = ask("Region, us or cn (cn only for China accounts)", "us").lower()
    region = "cn" if region == "cn" else "us"
    with cloud.make_client() as http:
        token = sign_in(http, region, email)
        if not token:
            return
        try:
            found = cloud.list_printers(http, region, token)
        except cloud.BambuError as e:
            print(f"Could not list your printers: {_safe_error(e, token)}")
            return
    if not found:
        print("Signed in, but no printers are bound to this account.")
        return
    print("Printers on this account:")
    for i, d in enumerate(found, 1):
        print(f"  {i}. {d['name']}  ({d['model'] or 'unknown model'}, {'online' if d['online'] else 'offline'})")
    pick = ask("Numbers to add, comma separated, or 'all'", "all")
    try:
        chosen = found if pick.lower() == "all" else \
            [found[int(n) - 1] for n in pick.replace(" ", "").split(",") if n]
    except (ValueError, IndexError):
        print("Didn't understand that selection.")
        return
    _keyring().set_password(cloud.SERVICE, email, token)
    doc = load(path)
    added = 0
    for d in chosen:
        entry = {"name": d["name"], "type": "cloud", "serial": d["serial"],
                 "account": email, "region": region}
        if d["model"]:
            entry["model"] = d["model"]
        added += _add(path, doc, entry)
    print(f"Token saved to the credential store, {added} printer(s) saved to {path}.")
    print("Restart the companion to pick it up.")


def cmd_add_local(path):
    print("""
Local (LAN) printer
  Needs, from the printer's screen: the IP address and the 8-character access code
  (Settings > WLAN/Network, or Settings > LAN Only Mode); the serial number is under
  Settings > Device (or on the printer's label).
  Newer firmware only allows third-party tools when LAN Only Mode or Developer Mode is on.
""")
    host = ask("Printer IP address (empty to cancel)")
    if not host:
        return
    if not _IP.fullmatch(host):
        print("That doesn't look like an IP address.")
        return
    serial = ask("Serial number").upper()
    if not serial:
        return
    code = getpass.getpass("Access code (hidden): ").strip()
    if not code:
        return
    name = ask("Name for this printer", MODELS.get(serial[:3], "Printer"))
    print("Testing the connection (up to 10 s)...")
    try:
        ok, msg = probe_local(host, serial, code)
    except Exception as e:
        ok, msg = False, f"Connection test failed: {_safe_error(e, code)}"
    print(msg)
    if not ok and ask("Save it anyway? (y/n)", "n").lower() != "y":
        return
    _keyring().set_password(cloud.SERVICE, lan_key(serial), code)
    if _add(path, load(path), {"name": name, "type": "local", "serial": serial, "host": host}):
        print(f"Access code saved to the credential store, printer saved to {path}.")
        print("Restart the companion to pick it up.")


def cmd_add_moonraker(path):
    print("""
Klipper printer (Moonraker)
  For printers running Klipper with Moonraker: Voron and other self-built printers, Sovol SV08,
  Qidi, Elegoo Neptune 4, Snapmaker U1, and Creality K1/K2 with Moonraker enabled. If you open
  Mainsail or Fluidd in a browser to control the printer, this is the one.
  Moonraker listens on port 7125; use 80 if you only reach it through Mainsail/Fluidd.
  Most setups let devices on the home network in without a key (trusted_clients in
  moonraker.conf); otherwise enter an API key from Mainsail/Fluidd's settings.
""")
    host = ask("Printer IP address or hostname (empty to cancel)")
    if not host:
        return
    if not _IP.fullmatch(host):
        print("That doesn't look like an IP address or hostname.")
        return
    port_s = ask("Port", str(mr.DEFAULT_PORT))
    if not port_s.isdigit() or not 0 < int(port_s) < 65536:
        print("The port is a number from 1 to 65535.")
        return
    port = int(port_s)
    api_key = getpass.getpass("API key (hidden, empty if none): ").strip()
    print("Testing the connection...")
    try:
        ok, msg, hostname = mr.probe(host, port, api_key or None)
    except Exception as e:
        ok, msg, hostname = False, f"Connection test failed: {_safe_error(e, api_key)}", ""
    print(msg)
    if not ok and ask("Save it anyway? (y/n)", "n").lower() != "y":
        return
    name = ask("Name for this printer", hostname or "Klipper")
    model = ask("Model, shown on the board (for example Voron 2.4, SV08)", "Klipper")
    entry = {"name": name, "type": "moonraker", "host": host}
    if port != mr.DEFAULT_PORT:
        entry["port"] = port
    if model and model != "Klipper":
        entry["model"] = model
    if _add(path, load(path), entry):
        if api_key:
            _keyring().set_password(mr.SERVICE, mr.api_key_name(host, port), api_key)
            print("API key saved to the credential store.")
        print(f"Printer saved to {path}. Restart the companion to pick it up.")


def cmd_remove(path):
    doc = load(path)
    printers = printers_of(doc)
    if not printers:
        print("Nothing to remove.")
        return
    cmd_list(path)
    n = ask("Number to remove (empty to cancel)")
    if not n.isdigit() or not 1 <= int(n) <= len(printers):
        return
    gone = printers[int(n) - 1]
    del printers[int(n) - 1]
    write(path, doc)
    print("Removed.")
    if gone.get("type") == "moonraker":
        host, port = str(gone.get("host", "")), int(gone.get("port", mr.DEFAULT_PORT))
        service, key = mr.SERVICE, mr.api_key_name(host, port)
        try:
            if _keyring().get_password(service, key) is None:
                return
        except Exception:
            return
    elif gone.get("type") == "local":
        service, key = cloud.SERVICE, lan_key(str(gone.get("serial", "")))
    elif not any(p.get("account") == gone.get("account") for p in printers):
        service, key = cloud.SERVICE, str(gone.get("account", ""))
    else:
        return
    if ask("Also delete the stored credential? (y/n)", "y").lower() == "y":
        kr = _keyring()
        try:
            kr.delete_password(service, key)
        except kr.errors.PasswordDeleteError:
            pass


COMMANDS = {"list": cmd_list, "add-cloud": cmd_add_cloud, "add-local": cmd_add_local,
            "add-moonraker": cmd_add_moonraker, "remove": cmd_remove}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config")
    ap.add_argument("command", nargs="?", choices=list(COMMANDS))
    args = ap.parse_args()
    path = find_config(args.config)
    if args.command:
        COMMANDS[args.command](path)
        return
    menu(path)


def menu(path: pathlib.Path):
    """Interactive printer menu; also used by `deskhub-setup`."""
    names = list(COMMANDS)
    labels = ["List printers", "Add Bambu Lab printers from a Bambu cloud account",
              "Add a Bambu Lab printer on the local network (LAN)",
              "Add a Klipper printer (Moonraker: Voron, Sovol, Qidi, Creality K1/K2...)",
              "Remove a printer"]
    while True:
        print(f"\nPrinters in {path}")
        for i, label in enumerate(labels, 1):
            print(f"  {i}. {label}")
        choice = ask(f"Choose 1-{len(labels)}, or empty to quit")
        if not choice:
            return
        if choice.isdigit() and 1 <= int(choice) <= len(names):
            COMMANDS[names[int(choice) - 1]](path)


if __name__ == "__main__":
    main()
