// Shared between the UI pages.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include <time.h>
#include "hub_model.h"
#include "lvgl.h"

// Midnight theme: deep navy background, glassy indigo cards, soft violet accents.
#define COL_BG       0x060914   // bottom of the screen gradient
#define COL_BG_TOP   0x111842   // top of the screen gradient
#define COL_RAIL     0x080c22
#define COL_CARD     0x141c40   // card gradient top
#define COL_CARD_LO  0x0e1430   // card gradient bottom
#define COL_CARD_HI  0x1f2a5c   // pressed card, empty bar track
#define COL_BORDER   0x26315f
#define COL_TEXT     0xeef1ff
#define COL_MUTED    0x8e97c6
#define COL_DIM      0x4e578a
#define COL_ACCENT   0x8c9eff   // periwinkle
#define COL_ACCENT2  0xc08cff   // violet
#define COL_CYAN     0x67e8f9
#define COL_GOOD     0x4ade9c
#define COL_WARN     0xfbbf5a
#define COL_BAD      0xff6b8a

// Layout: navigation rail on the left, pages to its right.
#define RAIL_W 88
#define PAGE_W (800 - RAIL_W)          // 712
#define PAGE_H 480
#define PAD 20
#define CONTENT_W (PAGE_W - 2 * PAD)   // 672
#define CONTENT_H (PAGE_H - 2 * PAD)   // 440

// Material Icons and the large clock font, rendered at runtime by Tiny TTF.
extern lv_font_t *g_icon_24, *g_icon_32, *g_icon_48, *g_icon_80, *g_font_clock;

// Latest data, for pages that show it.
extern hub_stats_t g_stats;
extern hub_media_t g_media;
extern hub_weather_t g_weather;
extern hub_event_t g_events[HUB_MAX_EVENTS];
extern int g_event_count;
extern lv_image_dsc_t g_art;     // valid when g_art_id != 0
extern uint32_t g_art_id;
extern bool g_pc_online;

lv_obj_t *ui_card(lv_obj_t *parent);
lv_obj_t *ui_label(lv_obj_t *parent, const lv_font_t *font, uint32_t color, const char *text);
lv_obj_t *ui_bar(lv_obj_t *parent, uint32_t color);
void ui_bar_set_color(lv_obj_t *bar, uint32_t color);
lv_obj_t *ui_caption(lv_obj_t *parent, const char *text);   // small spaced-out section title
lv_obj_t *ui_round_button(lv_obj_t *parent, int size, uint32_t bg, const lv_font_t *icon_font,
                          const char *glyph, lv_event_cb_t cb, void *user);
void ui_fmt_clock(char *buf, size_t n, time_t t);   // "3:05 PM" / "15:05"
void ui_fmt_hour(char *buf, size_t n, time_t t);    // "3 PM" / "15:00"
void ui_fmt_temp(char *buf, size_t n, float t);     // "72°"
void ui_fmt_duration(char *buf, size_t n, int s);   // "3:07"
void ui_utf8_glyph(char out[5], uint32_t cp);
const char *ui_icon_by_name(const char *name, char out[5]);
bool ui_media_has_art(void);
void ui_show_page(int page);

enum { PAGE_HOME, PAGE_STATS, PAGE_CLAUDE, PAGE_CALENDAR, PAGE_WEATHER, PAGE_MEDIA, PAGE_PRINTER, PAGE_SHORTCUTS, PAGE_TIMER,
       PAGE_COUNT };

// Pages shown in the rail (bit per PAGE_*). Home is always on.
extern uint32_t g_pages_mask;
extern hub_printer_t g_printers[HUB_MAX_PRINTERS];
extern int g_printer_count;
void printer_create(lv_obj_t *page);
void printer_refresh(void);
void home_apply_layout(void);
void home_set_layout(const char *spec);   // "clock,claude,events|weather,media,stats"
void home_refresh_printer(void);
lv_font_t *ui_clock_font(int px, lv_font_t **old);
lv_font_t *ui_date_font(int px, lv_font_t **old);   // NULL if the font could not be made
lv_font_t *ui_header_font(void);
const lv_image_dsc_t *ui_agent_logo(int size);  // 24 or 32 px, for the agent in g_claude
const char *ui_agent_name(void);                // "Claude Code" / "Codex"
uint32_t ui_agent_color(void);                  // brand accent for charts and badges

extern hub_claude_t g_claude;
void claude_create(lv_obj_t *page);
void claude_refresh(void);
void claude_tick(void);
void home_refresh_claude(void);
void ui_fmt_tokens(char *buf, size_t n, double t);      // "1.2M"
void ui_fmt_countdown(char *buf, size_t n, time_t reset); // "Resets in 2h 14m"
uint32_t ui_level_color(float pct);

void home_create(lv_obj_t *page);
void home_tick(void);
void home_refresh_weather(void);
void home_refresh_media(void);
void home_refresh_stats(void);
void home_refresh_events(void);

void stats_create(lv_obj_t *page);
void stats_refresh(void);

void media_create(lv_obj_t *page);
void media_refresh(void);
void media_refresh_art(void);
void media_tick(void);

void calendar_create(lv_obj_t *page);
// force = rebuild even if the visible events look unchanged.
void calendar_refresh(bool force);

void weather_page_create(lv_obj_t *page);
void weather_page_refresh(void);

void shortcuts_create(lv_obj_t *page);
void shortcuts_refresh(const hub_tile_t *tiles, int n);
void shortcuts_set_online(bool online);

// Send a media command ("toggle", "next", "prev", "seek") to the PC.
void ui_send_media(const char *cmd, int value);

void timer_page_create(lv_obj_t *page);
lv_font_t *ui_timer_font(void);
// Show text (e.g. a countdown) on a rail tab instead of its icon; NULL restores the icon.
void ui_rail_set_text(int page, const char *text);
