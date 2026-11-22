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
