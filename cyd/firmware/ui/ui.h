// Oeffentliche Schnittstelle der UI. Alle Aufrufe unter der LVGL-Sperre.
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "hub_model.h"

#ifdef __cplusplus
extern "C" {
#endif

enum { P_HOME, P_CLAUDE, P_CALENDAR, P_WEATHER, P_TIMER, P_GITHUB, P_HOMELAB, P_NET, P_COUNT };

void ui_init(void);
// Etwa viermal pro Sekunde: Uhr, Timer, Veraltet-Hinweise, Wartezustand.
void ui_tick(void);

// Reihenfolge der Navigationsleiste (P_*). Home ist immer dabei.
void ui_set_layout(const uint8_t *order, int n);
int ui_page_by_name(const char *name);      // -1 wenn unbekannt
const char *ui_page_name(int page);
int ui_layout_get(uint8_t *out);           // aktuelle Reihenfolge, gibt die Anzahl zurueck
int ui_current_page(void);
void ui_show_page(int page);

void ui_set_events(const hub_event_t *ev, int n, int days);
void ui_set_claude(const hub_claude_t *c);
void ui_set_github(const hub_github_t *g);
void ui_set_net(const hub_net_t *n);
void ui_set_weather(const hub_weather_t *w);
void ui_set_homelab(const hub_homelab_t *h);

// Firmware-Update: Frage (Installieren / Ablehnen), Fortschritt, Meldung.
void ui_update_show(void);
void ui_update_progress(int pct);
void ui_update_message(const char *text);
void ui_update_hide(void);

// Fuer Vorschau und Tests: Timer setzen (Sekunden), "Zeit um" zeigen.
void ui_timer_debug(int total_s, int left_s, bool running, bool done);

#ifdef __cplusplus
}
#endif
