# Desk Hub auf dem CYD (ESP32-2432S028R)

Eine kleine Variante von Desk Hub für das „Cheap Yellow Display“: ESP32 ohne PSRAM,
ILI9341 mit 320 × 240 und resistivem Touch (XPT2046). Seiten: Start, Claude, Kalender,
Wetter, Timer, GitHub, Homelab, Netz. Das Protokoll zum Begleiter steht in
[PROTOKOLL.md](PROTOKOLL.md).

- `firmware/` – PlatformIO-Projekt (Arduino-ESP32, LVGL 9.2, TFT_eSPI)
- `firmware/ui/` – Oberfläche und Parser, ohne Gerätebezug (baut auch auf Linux)
- `preview/` – Vorschau: rendert jede Seite mit Beispieldaten als PNG, dazu der Parser-Test

## Bauen

```sh
cp firmware/include/secrets.example.h firmware/include/secrets.h   # ausfüllen
pio run -e cyd -d firmware
```

`secrets.h` (steht in `.gitignore`):

- `WIFI_SSID`, `WIFI_PASS` – WLAN. Leer gelassen, nimmt das Display die zuletzt im NVS
  gespeicherten Zugangsdaten.
- `HUB_TOKEN` – dasselbe Geheimnis wie beim Begleiter.

Plattform `espressif32@6.5.0`, Board `esp32dev` und die Partitionstabelle `min_spiffs.csv`
bleiben bitte so: Nur mit genau diesem Layout lässt sich die Firmware über WLAN auf ein
Gerät spielen, das schon eine Firmware aus diesem Stand trägt.

Schriften neu erzeugen (nur nach Änderungen an den Zeichensätzen): `sh firmware/tools/fonts.sh`
(braucht node/npx).

## Flashen per Kabel

PlatformIO: `pio run -e cyd -d firmware -t upload`. Oder mit esptool (Adressen für
`min_spiffs.csv`):

```sh
B=firmware/.pio/build/cyd
esptool.py --chip esp32 --port /dev/ttyUSB0 --baud 921600 write_flash \
  0x1000 $B/bootloader.bin 0x8000 $B/partitions.bin \
  0xe000 ~/.platformio/packages/framework-arduinoespressif32/tools/partitions/boot_app0.bin \
  0x10000 $B/firmware.bin
```

Nur die App tauschen: `esptool.py --chip esp32 write_flash 0x10000 $B/firmware.bin`.

## Flashen per WLAN

```sh
curl --data-binary @firmware/.pio/build/cyd/firmware.bin \
  "http://deskhub.local/firmware?token=$HUB_TOKEN"
```

Auf dem Display erscheint „Firmware-Update installieren?“; erst nach *Installieren* wird
geschrieben (keine Antwort binnen 60 s = abgelehnt). Danach läuft eine Probezeit: Meldet
sich binnen 5 Minuten kein Begleiter mit gültigem Token, oder startet die neue Fassung
dreimal ohne Bestätigung neu, schaltet das Display auf die alte Partition zurück.

## Vorschau und Test

```sh
make -C preview          # out/<seite>.png und out/kontaktbogen.png, prüft Layout
make -C preview test     # Parser-Test mit samples/*.json
```

Beim ersten Lauf holt das Makefile LVGL 9.2.2 und cJSON nach `preview/build/`.
Beispieldaten neu erzeugen: `python3 preview/make_samples.py` (alles erfunden).

## Begleiter auf dem Pi

`deskhub-pi` ist der Linux-Begleiter (`companion/deskhub/pi/`). Er läuft auf einem Raspberry Pi,
holt die Daten und schickt sie nach PROTOKOLL.md an das Display: Claude-Kontingent, Termine und
Homelab aus Mia OS, GitHub-Beiträge, Wetter und Leitungswerte. Das Windows-Programm im Rest von
`companion/` bleibt unverändert; der Pi-Einstieg lädt nichts davon (pywin32, winsdk und pystray
werden nirgends gebraucht).

**Einrichten** (als normaler Benutzer, ohne root):

```sh
git clone <dieses-repo> ~/deskhub-cyd && cd ~/deskhub-cyd      # Zweig mit cyd/ und companion/
python3 -m venv ~/.venvs/deskhub
~/.venvs/deskhub/bin/pip install -r cyd/companion-requirements.txt
mkdir -p ~/.config/deskhub ~/.deskhub
cp cyd/companion.example.toml ~/.config/deskhub/companion.toml
chmod 600 ~/.config/deskhub/companion.toml     # Platzhalter ersetzen, vor allem hub.token
```

Den Schlüssel für das Kontingent nicht in die Config, sondern in eine Datei nur für dich
(`key_file` in `[claude]`, `chmod 600`) oder in die Umgebungsvariable `KONTINGENT_KEY`. Einen
GitHub-Token braucht es nicht: ohne Token wird die öffentliche Beitragsseite des Nutzers gelesen
(`[github] user`). Nur wenn `token_file` oder `DESKHUB_GITHUB_TOKEN` gesetzt ist, fragt der
Begleiter GraphQL und zählt Privates mit.

**Starten von Hand:**

```sh
cd ~/deskhub-cyd/companion
PYTHONPATH=. ~/.venvs/deskhub/bin/python -m deskhub.pi --config ~/.config/deskhub/companion.toml -v
```

Abstände: Kontingent 60 s, Termine und Homelab 2 min, Wetter 15 min, GitHub 1 h, Uhrzeit 10 min,
Leitung 5 s (alle in `[intervals]` änderbar). Wechselt das Display die Seite oder schickt es
`refresh`, geht der letzte Stand sofort raus und die Quelle wird neu gefragt (höchstens alle
15 s). Fällt eine Quelle aus, bleibt der letzte Stand stehen; nur das Homelab meldet dann
`ok:false`. Ohne Verbindung zum Display versucht der Begleiter es mit Wartezeit (1 s bis 60 s) neu.

**Als Dienst** (systemd-Benutzereinheit, `cyd/deskhub-pi.service`; Pfade in der Datei prüfen):

```sh
mkdir -p ~/.config/systemd/user
cp cyd/deskhub-pi.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now deskhub-pi
loginctl enable-linger "$USER"          # damit er ohne Anmeldung nach dem Start läuft
journalctl --user -u deskhub-pi -f      # Protokoll
```

**Firmware einspielen** (App-Image = `firmware.bin` aus PlatformIO):

```sh
cd ~/deskhub-cyd/companion
export PYTHONPATH=.; PY=~/.venvs/deskhub/bin/python
# per WLAN: Host und Token aus der Config, das Display fragt auf dem Schirm (60 s)
$PY -m deskhub.pi flash --ota firmware.bin --config ~/.config/deskhub/companion.toml
# per Kabel (esptool): schreibt bei 0x10000 (app0 in min_spiffs.csv), danach otadata löschen
$PY -m deskhub.pi flash --serial /dev/ttyUSB0 firmware.bin
# Sicherung des ganzen 4-MB-Flashs (read_flash 0x0 0x400000), überschreibt keine Datei
$PY -m deskhub.pi backup --serial /dev/ttyUSB0 sicherung.bin
```

Über Kabel nötigenfalls BOOT gedrückt halten, während das Kabel eingesteckt wird. Zurückspielen
einer Sicherung: `python -m esptool --chip esp32 --port /dev/ttyUSB0 write_flash 0x0 sicherung.bin`.
Der Begleiter nimmt nur App-Images an (erstes Byte `0xE9`, höchstens 1.966.080 Bytes), keine
ganze Sicherung.

**Prüfen ohne Hardware:** `cd companion && python3 tests/run_all.py`. Die Pi-Tests
(`test_pi_*.py`) laufen gegen `tests/fake_cyd_hub.py`, das Anmeldung und jedes Feld gegen
PROTOKOLL.md prüft. Einige ältere Tests sind Windows-Tests (Startmenü-Verknüpfung, Pfade mit
Laufwerksbuchstaben) und schlagen unter Linux fehl.
