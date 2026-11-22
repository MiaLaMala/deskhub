// Gemeinsames der Seiten. 320 x 240, unten die Navigationsleiste (36 px),
// darueber 204 px fuer die Seite. Farben wie im Original (Graphite).
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <time.h>
#include "hub_model.h"
#include "lvgl.h"
#include "platform.h"
#include "ui.h"

#define COL_BG       0x0d0e11
#define COL_RAIL     0x111216
#define COL_CARD     0x16181d
#define COL_CARD_HI  0x262a32
#define COL_BORDER   0x262a32
#define COL_PRESSED  0x30343d
#define COL_TEXT     0xf3f4f6
#define COL_MUTED    0x9aa0aa
#define COL_DIM      0x6b717c
#define COL_ACCENT   0xffb224
#define COL_ON_ACCENT 0x16181d
#define COL_ACCENT_PRESSED 0xd9931a
#define COL_BLUE     0x6cb4ff
#define COL_CYAN     0x5ed3c6
#define COL_GOOD     0x3dd68c
#define COL_WARN     0xffb224
#define COL_BAD      0xff6b6b
#define COL_CLAUDE   0xd97757
#define COL_CLAUDE_LO 0x3a2620   // leere Spur auf der Claude-Seite

#define SCR_W 320
#define SCR_H 240
#define DOCK_H 36
#define PAGE_H (SCR_H - DOCK_H)   // 204
#define PAD 8
#define HDR_H 24                   // Kopfzeile der Seiten
#define STALE_S (15 * 60)

LV_FONT_DECLARE(inter_12)
LV_FONT_DECLARE(inter_14)
LV_FONT_DECLARE(inter_16)
LV_FONT_DECLARE(inter_20)
LV_FONT_DECLARE(inter_28)
LV_FONT_DECLARE(inter_48)
LV_FONT_DECLARE(icons_16)
LV_FONT_DECLARE(icons_20)
LV_FONT_DECLARE(icons_36)

#define F12 (&inter_12)
#define F14 (&inter_14)
#define F16 (&inter_16)
#define F20 (&inter_20)
#define F28 (&inter_28)
#define F48 (&inter_48)

// Material Icons (Codepunkte wie in firmware/main/icons.h)
#define ICON_HOME          "\xEE\xA2\x8A"
#define ICON_AUTO_AWESOME  "\xEE\x99\x9F"
#define ICON_EVENT         "\xEE\xA1\xB8"
#define ICON_WB_SUNNY      "\xEE\x90\xB0"
#define ICON_TIMER         "\xEE\x90\xA5"
#define ICON_COMMIT        "\xEE\xAB\xB5"
#define ICON_STORAGE       "\xEE\x87\x9B"
#define ICON_PUBLIC        "\xEE\xA0\x8B"
#define ICON_NIGHTS_STAY   "\xEE\xA9\x86"
#define ICON_WB_CLOUDY     "\xEE\x90\xAD"
#define ICON_CLOUD         "\xEE\x8A\xBD"
#define ICON_FOGGY         "\xEE\xA0\x98"
#define ICON_GRAIN         "\xEE\x8F\xAA"
#define ICON_UMBRELLA      "\xEF\x86\xAD"
#define ICON_AC_UNIT       "\xEE\xAC\xBB"
#define ICON_THUNDERSTORM  "\xEE\xAF\x9B"
#define ICON_SYSTEM_UPDATE "\xEE\x98\xAA"
#define ICON_WIFI          "\xEE\x98\xBE"
#define ICON_WIFI_OFF      "\xEE\x99\x88"
#define ICON_ERROR         "\xEE\x80\x80"
#define ICON_WATER_DROP    "\xEE\x9E\x98"
#define ICON_REFRESH       "\xEE\x97\x95"
#define ICON_PLAY_ARROW    "\xEE\x80\xB7"
#define ICON_PAUSE         "\xEE\x80\xB4"
#define ICON_REPLAY        "\xEE\x81\x82"
#define ICON_CLOSE         "\xEE\x97\x8D"
#define ICON_AIR           "\xEE\xBF\x98"

// Letzter Stand der Daten.
extern hub_event_t g_events[HUB_MAX_EVENTS];
extern int g_event_count, g_event_days;
extern hub_claude_t g_claude;
extern hub_github_t g_github;
extern hub_net_t g_net;
extern hub_weather_t g_weather;
extern hub_homelab_t g_homelab;
extern time_t g_rx[P_COUNT];      // wann die Daten einer Seite kamen (0 = nie)
extern bool g_had_data;           // seit dem Start schon Daten vom Begleiter

// Bausteine
lv_obj_t *ui_box(lv_obj_t *parent, int x, int y, int w, int h);   // leerer Behaelter
lv_obj_t *ui_label(lv_obj_t *parent, const lv_font_t *font, uint32_t color, const char *text);
lv_obj_t *ui_label_at(lv_obj_t *parent, const lv_font_t *font, uint32_t color, int x, int y, const char *text);
// Feste Breite, zu langer Text endet mit "..."
lv_obj_t *ui_label_w(lv_obj_t *parent, const lv_font_t *font, uint32_t color, int x, int y, int w, const char *text);
lv_obj_t *ui_bar(lv_obj_t *parent, int x, int y, int w, int h, uint32_t color, uint32_t track);
lv_obj_t *ui_button(lv_obj_t *parent, int x, int y, int w, int h, const char *text, bool primary,
                    lv_event_cb_t cb, void *user);
// Kopfzeile: Titel links, rechts Uhr oder "Stand 14:05" (siehe ui_tick).
lv_obj_t *ui_header(lv_obj_t *parent, const char *title, uint32_t color);
void ui_set_text_if(lv_obj_t *l, const char *text);   // nur bei Aenderung (spart Neuzeichnen)

// Zeit und Zahlen, deutsch
bool ui_localtime(time_t t, struct tm *tm);
void ui_fmt_clock(char *buf, size_t n, time_t t);        // "14:05"
void ui_fmt_when(char *buf, size_t n, time_t t);         // "14:05", "gestern 14:05", "Mo 14:05", "12.11."
void ui_fmt_since(char *buf, size_t n, time_t t);        // "seit 14:05" ...
void ui_fmt_stand(char *buf, size_t n, time_t t);        // "Stand 14:05"
void ui_fmt_countdown(char *buf, size_t n, time_t reset); // "zurück in 2 h 14 min"
void ui_fmt_temp(char *buf, size_t n, float t);          // "7°"
void ui_fmt_int(char *buf, size_t n, long v);            // "1.019"
void ui_fmt_day_title(char *buf, size_t n, time_t t);    // "Heute", "Morgen", "Dienstag, 24.11."
const char *ui_wday_short(int wday);                     // "So".."Sa"
const char *ui_wday_long(int wday);
const char *ui_month_long(int mon);
const char *ui_month_de(const char *en);                 // "Dec" -> "Dez"
long ui_days_between(time_t a, time_t b);                // Kalendertage von a bis b

const char *weather_icon(int code, bool is_day);
uint32_t weather_color(int code, bool is_day);
const char *weather_text(int code);
uint32_t ui_level_color(float pct);
// Zeitpunkt, ab dem die Daten einer Seite alt sind; 0 = frisch oder keine.
time_t ui_stale_at(int page);
bool ui_waiting(void);   // kein Begleiter und noch nie Daten

// Seiten: create baut in den 320 x 204 grossen Behaelter, refresh fuellt ein.
void home_create(lv_obj_t *p);       void home_refresh(void);     void home_tick(void);
void claude_create(lv_obj_t *p);     void claude_refresh(void);
void calendar_create(lv_obj_t *p);   void calendar_refresh(void);
void weather_create(lv_obj_t *p);    void weather_refresh(void);
void timer_page_create(lv_obj_t *p);      void timer_page_refresh(void);    void timer_page_tick(void);
void github_create(lv_obj_t *p);     void github_refresh(void);
void homelab_create(lv_obj_t *p);    void homelab_refresh(void);
void net_create(lv_obj_t *p);        void net_refresh(void);

// Timer laeuft unabhaengig von der Seite.
bool timer_running(void);
int timer_left_s(void);
void timer_global_tick(void);
void ui_dock_set_text(int page, const char *text);   // Text statt Icon, NULL = Icon
