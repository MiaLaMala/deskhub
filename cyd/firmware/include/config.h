// Einstellungen und Verbindung zwischen main.cpp (Arduino/C++) und hub_server.c.
#pragma once

#include <stdbool.h>
#include <stdint.h>

#if __has_include("secrets.h")
#include "secrets.h"
#else
#warning "include/secrets.h fehlt: es gelten die Platzhalter aus secrets.example.h"
#include "secrets.example.h"
#endif

#define FW_VERSION "0.1.0"
#define HOSTNAME "deskhub"
#define TZ_INFO "CET-1CEST,M3.5.0,M10.5.0/3"

#ifdef __cplusplus
extern "C" {
#endif

// LVGL-Sperre (rekursiv). Alles, was LVGL oder das Panel anfasst, darunter.
void display_lock(void);
void display_unlock(void);
void display_wake(void);                       // Hintergrundlicht an (z. B. fuer den Update-Dialog)

// Fuer /screenshot: n Zeilen ab y aus dem Panel lesen (RGB565, Byte-Reihenfolge des Panels).
void panel_read_rows(int y, int n, uint16_t *buf);
// Fuer /tap: eine Beruehrung an (x, y) ausloesen.
void touch_inject(int x, int y);
int wifi_rssi(void);

// Software-Probezeit nach einem Update (siehe PROTOKOLL.md).
void ota_probation_arm(const char *prev_label);
void ota_probation_confirm(void);

void hub_server_start(void);
bool hub_server_online(void);
void hub_server_send(const char *json);

#ifdef __cplusplus
}
#endif
