# Desk Hub CYD: Protokoll zwischen Begleiter und Display

Gilt für die CYD-Variante (ESP32-2432S028R, 320 x 240, resistiver Touch). Der Begleiter läuft
auf einem Linux-Rechner im selben WLAN wie das Display (bei Mia ein Raspberry Pi 4, der auch
das WLAN aufspannt). Grundlage ist das Protokoll von Desk Hub: eine WebSocket-Verbindung
`ws://<display>/ws`, Nachrichten als JSON mit Feld `type`, Zeiten als Unix-Sekunden (UTC).

## Anmeldung

Begleiter sendet zuerst `{"type":"hello","token":"<HUB_TOKEN>"}`. Das Display antwortet
`{"type":"hello_ok","version":"<firmware-version>","board":"cyd"}`. Falsches Token: Verbindung
zu. Nachrichten vor dem `hello` werden ignoriert. Wie im Original gilt nur eine Verbindung.

## Übernommene Typen (Felder exakt wie im Original)

Maßgeblich sind die Parser in `firmware/main/hub_server.c` und die Erzeuger in
`companion/deskhub/`. Die CYD-Firmware nimmt dieselben Felder an und ignoriert unbekannte.

- `layout`: `{"type":"layout","pages":["home","claude","calendar","weather","timer","github","homelab","net"]}`
  Reihenfolge = Reihenfolge der Navigationsleiste. `home` ist immer dabei.
- `events`: wie Original (`events[]` mit `start`, `end`, `all_day`, `title`, `loc`, `cal`, `color`), dazu `days`.
- `ai`: wie Original, aber der Begleiter auf dem Pi hat keine lokalen Claude-Code-Dateien. Er
  sendet nur `provider:"claude"` und `limits` (`updated`, `five_hour{pct,reset}`,
  `seven_day{pct,reset}`). `block`, `today`, `days`, `models` fehlen dann. Das Display blendet
  die zugehörigen Teile aus, statt Nullen zu zeigen. Optional `history`: Liste
  `[[unix, pct_7d], ...]` (höchstens 48 Punkte), vom Begleiter selbst mitgeschrieben.
- `github`: wie Original.
- `net`: wie Original (Messwerte der Leitung des Pi). Kein Speedtest auf der CYD-Seite.

## Neue Typen

- `time`: `{"type":"time","unix":1795400000.25}`. Kommt nach `hello_ok` und alle 10 Minuten.
  Das Display stellt damit die Uhr, wenn SNTP noch nicht gegriffen hat oder blockiert ist.
  Zeitzone im Display fest: `CET-1CEST,M3.5.0,M10.5.0/3`.
- `weather`: Das Display holt kein Wetter selbst (kein TLS auf dem Gerät).
  ```json
  {"type":"weather","place":"Hamburg","updated":1795400000,
   "now":{"temp":7.2,"feels":4.1,"code":3,"is_day":true,"humidity":81,"wind":18},
   "hours":[{"t":1795402800,"temp":6.8,"code":3,"precip":40}],
   "days":[{"t":1795392000,"min":3.0,"max":8.0,"code":61,"precip":70}]}
  ```
  `code` = WMO-Wettercode wie bei Open-Meteo, `precip` = Regenwahrscheinlichkeit in Prozent,
  `wind` in km/h. Höchstens 12 Stunden und 6 Tage.
- `homelab`:
  ```json
  {"type":"homelab","ok":true,"updated":1795400000,"up":53,"total":54,
   "down":[{"name":"Nextcloud","since":1795390000}]}
  ```
  `ok:false` heißt: Quelle nicht erreichbar, dann zeigt das Display den letzten Stand mit Uhrzeit.
  Höchstens 8 Einträge in `down`.

## Vom Display zum Begleiter

- `{"type":"page","name":"weather"}` bei Seitenwechsel (der Begleiter darf dann sofort auffrischen).
- `{"type":"refresh"}` nach Neustart oder wenn Daten älter als 15 Minuten sind.

## Firmware über WLAN

`POST /firmware?token=<HUB_TOKEN>` mit dem App-Image als Body, wie im Original: Das Display
fragt auf dem Schirm (Installieren / Ablehnen, 60 s) und schreibt erst nach dem Tippen.
Zusätzlich eine Probezeit in Software, weil der vorinstallierte Arduino-Bootloader keinen
verlässlichen Rückfall hat: nach dem Umschalten merkt sich das Display im NVS die alte
Partition und zählt Starts. Kommt binnen 5 Minuten kein `hello` mit gültigem Token oder startet
es dreimal ohne Bestätigung, schaltet es auf die alte Partition zurück und startet neu.

## Hilfen zum Prüfen aus der Ferne (alle mit `?token=`)

- `GET /screenshot`: BMP 320 x 240, zeilenweise aus dem Panel gelesen (kein Vollbildpuffer).
- `GET /tap?x=..&y=..`: Berührung an Bildschirmkoordinaten auslösen.
- `GET /perf`: JSON mit `heap_free`, `heap_min`, `uptime_s`, `version`, `rssi`, `page`.
