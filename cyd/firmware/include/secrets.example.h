// Vorlage: nach include/secrets.h kopieren und ausfuellen. secrets.h steht in
// .gitignore und kommt nie ins Repo.
#pragma once

// WLAN. Leer lassen, dann nimmt das Display die zuletzt im NVS gespeicherten Daten.
#define WIFI_SSID ""
#define WIFI_PASS ""

// Gemeinsames Geheimnis mit dem Begleiter (hello, /firmware, /screenshot, /tap, /perf).
#define HUB_TOKEN "bitte-aendern"
