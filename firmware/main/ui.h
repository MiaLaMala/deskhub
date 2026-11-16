// Public UI API. Every function must be called with display_lock() held.
#pragma once

#include <stdint.h>
#include "hub_model.h"

void ui_init(void);

void ui_set_stats(const hub_stats_t *s);
void ui_set_media(const hub_media_t *m);
void ui_set_art(uint32_t id, uint16_t w, uint16_t h, const uint8_t *rgb565);
void ui_set_events(const hub_event_t *ev, int n);
void ui_set_tiles(const hub_tile_t *tiles, int n);
void ui_set_weather(const hub_weather_t *w);
void ui_set_claude(const hub_claude_t *c);
void ui_set_printers(const hub_printer_t *p, int n);
// Bit i set = page i shown (see the PAGE_* order in ui_internal.h). Saved to NVS.
void ui_set_layout(uint32_t pages_mask);
// Home widgets per column, e.g. "clock,claude,events|weather,media,stats". Saved to NVS.
void ui_set_home(const char *spec);
// Full-screen "agent waiting" alert; a->active false hides it.
void ui_set_alert(const hub_alert_t *a);
// Shortcut tiles that are "on" (bit i = tile i), e.g. mic or speaker muted.
void ui_set_tile_state(uint32_t on_mask);
