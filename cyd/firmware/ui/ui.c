// Bildschirm, Navigationsleiste, Seitenwechsel und gemeinsame Helfer.
#include <stdio.h>
#include <string.h>
#include <math.h>

#include "ui.h"
#include "ui_internal.h"

hub_event_t g_events[HUB_MAX_EVENTS];
int g_event_count, g_event_days = 7;
hub_claude_t g_claude;
hub_github_t g_github;
hub_net_t g_net;
hub_weather_t g_weather;
hub_homelab_t g_homelab;
time_t g_rx[P_COUNT];
bool g_had_data;

typedef struct {
    const char *name;
    const char *alias;   // Name im Original
    const char *icon;
    void (*create)(lv_obj_t *);
    void (*refresh)(void);
} page_def_t;

static const page_def_t PAGES[P_COUNT] = {
    [P_HOME] = {"home", NULL, ICON_HOME, home_create, home_refresh},
    [P_CLAUDE] = {"claude", "ai", ICON_AUTO_AWESOME, claude_create, claude_refresh},
    [P_CALENDAR] = {"calendar", NULL, ICON_EVENT, calendar_create, calendar_refresh},
    [P_WEATHER] = {"weather", NULL, ICON_WB_SUNNY, weather_create, weather_refresh},
    [P_TIMER] = {"timer", NULL, ICON_TIMER, timer_page_create, timer_page_refresh},
    [P_GITHUB] = {"github", NULL, ICON_COMMIT, github_create, github_refresh},
    [P_HOMELAB] = {"homelab", NULL, ICON_STORAGE, homelab_create, homelab_refresh},
    [P_NET] = {"net", "network", ICON_PUBLIC, net_create, net_refresh},
};

static lv_obj_t *s_page, *s_dock, *s_hdr_status;
static lv_obj_t *s_tab[P_COUNT], *s_tab_icon[P_COUNT], *s_tab_text[P_COUNT], *s_tab_line[P_COUNT];
static uint8_t s_order[P_COUNT];
static int s_order_n;
static int s_current = -1;
static bool s_was_online;
static uint32_t s_last_refresh_ms;
static bool s_refresh_sent;

// ---- Bausteine -------------------------------------------------------------

lv_obj_t *ui_box(lv_obj_t *parent, int x, int y, int w, int h)
{
    lv_obj_t *o = lv_obj_create(parent);
    lv_obj_remove_flag(o, LV_OBJ_FLAG_SCROLLABLE | LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_pos(o, x, y);
    lv_obj_set_size(o, w, h);
    return o;
}

lv_obj_t *ui_label(lv_obj_t *parent, const lv_font_t *font, uint32_t color, const char *text)
{
    lv_obj_t *l = lv_label_create(parent);
    lv_obj_set_style_text_font(l, font, 0);
    lv_obj_set_style_text_color(l, lv_color_hex(color), 0);
    lv_label_set_text(l, text ? text : "");
    return l;
}

lv_obj_t *ui_label_at(lv_obj_t *parent, const lv_font_t *font, uint32_t color, int x, int y, const char *text)
{
    lv_obj_t *l = ui_label(parent, font, color, text);
    lv_obj_set_pos(l, x, y);
    return l;
}

lv_obj_t *ui_label_w(lv_obj_t *parent, const lv_font_t *font, uint32_t color, int x, int y, int w, const char *text)
{
    lv_obj_t *l = ui_label_at(parent, font, color, x, y, text);
    lv_obj_set_size(l, w, lv_font_get_line_height(font));   // eine Zeile, sonst bricht DOT um
    lv_label_set_long_mode(l, LV_LABEL_LONG_DOT);
    return l;
}

void ui_set_text_if(lv_obj_t *l, const char *text)
{
    if (!l) return;
    if (strcmp(lv_label_get_text(l), text) != 0) lv_label_set_text(l, text);
}

lv_obj_t *ui_bar(lv_obj_t *parent, int x, int y, int w, int h, uint32_t color, uint32_t track)
{
    lv_obj_t *b = lv_bar_create(parent);
    lv_obj_set_pos(b, x, y);
    lv_obj_set_size(b, w, h);
    lv_bar_set_range(b, 0, 100);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(track), 0);
    lv_obj_set_style_radius(b, h / 2, 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, LV_PART_INDICATOR);
    lv_obj_set_style_bg_color(b, lv_color_hex(color), LV_PART_INDICATOR);
    lv_obj_set_style_radius(b, h / 2, LV_PART_INDICATOR);
    return b;
}

lv_obj_t *ui_button(lv_obj_t *parent, int x, int y, int w, int h, const char *text, bool primary,
                    lv_event_cb_t cb, void *user)
{
    lv_obj_t *b = lv_button_create(parent);
    lv_obj_set_pos(b, x, y);
    lv_obj_set_size(b, w, h);
    lv_obj_set_style_radius(b, 8, 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(primary ? COL_ACCENT : COL_CARD_HI), 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(primary ? COL_ACCENT_PRESSED : COL_PRESSED), LV_STATE_PRESSED);
    lv_obj_t *l = ui_label(b, F16, primary ? COL_ON_ACCENT : COL_TEXT, text);
    lv_obj_center(l);
    if (cb) lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, user);
    return b;
}

lv_obj_t *ui_header(lv_obj_t *parent, const char *title, uint32_t color)
{
    lv_obj_t *t = ui_label_w(parent, F16, color, PAD, 3, 200, title);
    (void)t;
    s_hdr_status = ui_label(parent, F12, COL_MUTED, "");
    lv_obj_align(s_hdr_status, LV_ALIGN_TOP_RIGHT, -PAD, 6);
    return s_hdr_status;
}

// ---- Zeit und Zahlen -------------------------------------------------------

static const char *WD_SHORT[] = {"So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"};
static const char *WD_LONG[] = {"Sonntag", "Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag"};
static const char *MON_LONG[] = {"Januar", "Februar", "März", "April", "Mai", "Juni",
                                 "Juli", "August", "September", "Oktober", "November", "Dezember"};

const char *ui_wday_short(int w) { return WD_SHORT[((w % 7) + 7) % 7]; }
const char *ui_wday_long(int w) { return WD_LONG[((w % 7) + 7) % 7]; }
const char *ui_month_long(int m) { return MON_LONG[((m % 12) + 12) % 12]; }

const char *ui_month_de(const char *en)
{
    static const char *map[][2] = {{"Mar", "Mär"}, {"May", "Mai"}, {"Oct", "Okt"}, {"Dec", "Dez"}};
    for (size_t i = 0; i < sizeof(map) / sizeof(map[0]); i++)
        if (!strcmp(en, map[i][0])) return map[i][1];
    return en;
}

bool ui_localtime(time_t t, struct tm *tm)
{
    return localtime_r(&t, tm) != NULL;
}

long ui_days_between(time_t a, time_t b)
{
    struct tm ta, tb;
    ui_localtime(a, &ta);
    ui_localtime(b, &tb);
    // Mittag nehmen, damit die Zeitumstellung nicht stoert.
    ta.tm_hour = tb.tm_hour = 12;
    ta.tm_min = tb.tm_min = ta.tm_sec = tb.tm_sec = 0;
    ta.tm_isdst = tb.tm_isdst = -1;
    return lround(difftime(mktime(&tb), mktime(&ta)) / 86400.0);
}

void ui_fmt_clock(char *buf, size_t n, time_t t)
{
    struct tm tm;
    ui_localtime(t, &tm);
    snprintf(buf, n, "%02d:%02d", tm.tm_hour, tm.tm_min);
}

void ui_fmt_when(char *buf, size_t n, time_t t)
{
    struct tm tm;
    char hm[8];
    ui_localtime(t, &tm);
    ui_fmt_clock(hm, sizeof(hm), t);
    long d = ui_days_between(t, plat_now());
    if (d == 0) snprintf(buf, n, "%s", hm);
    else if (d == 1) snprintf(buf, n, "gestern %s", hm);
    else if (d > 1 && d < 7) snprintf(buf, n, "%s %s", ui_wday_short(tm.tm_wday), hm);
    else snprintf(buf, n, "%d.%d.", tm.tm_mday, tm.tm_mon + 1);
}

void ui_fmt_since(char *buf, size_t n, time_t t)
{
    char w[24];
    ui_fmt_when(w, sizeof(w), t);
    snprintf(buf, n, "seit %s", w);
}

void ui_fmt_stand(char *buf, size_t n, time_t t)
{
    char w[24];
    ui_fmt_when(w, sizeof(w), t);
    snprintf(buf, n, "Stand %s", w);
}

void ui_fmt_countdown(char *buf, size_t n, time_t reset)
{
    long s = (long)(reset - plat_now());
    if (reset == 0) {
        buf[0] = 0;
    } else if (s <= 0) {
        snprintf(buf, n, "wird gerade erneuert");
    } else if (s >= 86400) {
        struct tm tm;
        char hm[8];
        ui_localtime(reset, &tm);
        ui_fmt_clock(hm, sizeof(hm), reset);
        snprintf(buf, n, "neu am %s %s", ui_wday_short(tm.tm_wday), hm);
    } else if (s >= 3600) {
        snprintf(buf, n, "neu in %ld h %02ld min", s / 3600, (s / 60) % 60);
    } else {
        snprintf(buf, n, "neu in %ld min", (s + 59) / 60);
    }
}

void ui_fmt_temp(char *buf, size_t n, float t)
{
    int v = (int)lroundf(t);
    if (v == 0) v = 0;   // kein "-0°"
    if (v < 0) snprintf(buf, n, "\xe2\x88\x92%d°", -v);   // echtes Minus (U+2212)
    else snprintf(buf, n, "%d°", v);
}

void ui_fmt_int(char *buf, size_t n, long v)
{
    char tmp[24];
    snprintf(tmp, sizeof(tmp), "%ld", v < 0 ? -v : v);
    int len = (int)strlen(tmp), o = 0;
    if (v < 0 && o < (int)n - 1) buf[o++] = '-';
    for (int i = 0; i < len && o < (int)n - 1; i++) {
        buf[o++] = tmp[i];
        int rest = len - i - 1;
        if (rest > 0 && rest % 3 == 0 && o < (int)n - 1) buf[o++] = '.';
    }
    buf[o] = 0;
}

void ui_fmt_day_title(char *buf, size_t n, time_t t)
{
    struct tm tm;
    ui_localtime(t, &tm);
    long d = ui_days_between(plat_now(), t);
    if (d == 0) snprintf(buf, n, "Heute, %d.%d.", tm.tm_mday, tm.tm_mon + 1);
    else if (d == 1) snprintf(buf, n, "Morgen, %d.%d.", tm.tm_mday, tm.tm_mon + 1);
    else snprintf(buf, n, "%s, %d.%d.", ui_wday_long(tm.tm_wday), tm.tm_mday, tm.tm_mon + 1);
}

uint32_t ui_level_color(float pct)
{
    return pct >= 80 ? COL_BAD : pct >= 50 ? COL_WARN : COL_GOOD;
}

// ---- Wetter (wie firmware/main/weather.c, Texte deutsch) --------------------

const char *weather_icon(int code, bool is_day)
{
    if (code == 0) return is_day ? ICON_WB_SUNNY : ICON_NIGHTS_STAY;
    if (code <= 2) return is_day ? ICON_WB_CLOUDY : ICON_NIGHTS_STAY;
    if (code == 3) return ICON_CLOUD;
    if (code == 45 || code == 48) return ICON_FOGGY;
    if (code >= 51 && code <= 57) return ICON_GRAIN;
    if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return ICON_UMBRELLA;
    if ((code >= 71 && code <= 77) || code == 85 || code == 86) return ICON_AC_UNIT;
    if (code >= 95) return ICON_THUNDERSTORM;
    return ICON_CLOUD;
}

uint32_t weather_color(int code, bool is_day)
{
    if (code <= 1) return is_day ? COL_ACCENT : 0xb49cff;
    if (code == 2) return is_day ? 0xffd27a : 0xb49cff;
    if ((code >= 51 && code <= 67) || (code >= 80 && code <= 82)) return COL_BLUE;
    if ((code >= 71 && code <= 77) || code == 85 || code == 86) return 0xdfe8ff;
    if (code >= 95) return 0xffd166;
    return COL_MUTED;
}

const char *weather_text(int code)
{
    switch (code) {
    case 0: return "Klar";
    case 1: return "Überwiegend klar";
    case 2: return "Teils bewölkt";
    case 3: return "Bedeckt";
    case 45: case 48: return "Nebel";
    case 51: case 53: case 55: return "Nieselregen";
    case 56: case 57: return "Gefrierender Niesel";
    case 61: return "Leichter Regen";
    case 63: return "Regen";
    case 65: return "Starker Regen";
    case 66: case 67: return "Eisregen";
    case 71: return "Leichter Schnee";
    case 73: return "Schnee";
    case 75: return "Starker Schnee";
    case 77: return "Schneegriesel";
    case 80: case 81: return "Schauer";
    case 82: return "Starke Schauer";
    case 85: case 86: return "Schneeschauer";
    case 95: return "Gewitter";
    case 96: case 99: return "Gewitter mit Hagel";
    default: return "Unbekannt";
    }
}

// ---- Veraltet / Warten -----------------------------------------------------

time_t ui_stale_at(int page)
{
    time_t now = plat_now();
    switch (page) {
    case P_CLAUDE:
        // Wie im Original: Limits, die vor mehr als 10 Minuten gemessen wurden, sind alt.
        if (!g_claude.valid) return 0;
        if (g_claude.limits_updated && now - g_claude.limits_updated > 10 * 60) return g_claude.limits_updated;
        break;
    case P_HOMELAB:
        if (!g_homelab.valid) return 0;
        if (!g_homelab.ok) return g_homelab.updated ? g_homelab.updated : g_rx[page];
        break;
    case P_WEATHER:
        if (!g_weather.valid) return 0;
        if (g_weather.updated && now - g_weather.updated > 3 * 3600) return g_weather.updated;
        break;
    case P_TIMER:
    case P_HOME:
        return 0;
    default:
        break;
    }
    if (g_rx[page] && now - g_rx[page] > STALE_S) return g_rx[page];
    return 0;
}

bool ui_waiting(void)
{
    return !g_had_data && !plat_companion_online();
}

// ---- Navigationsleiste -----------------------------------------------------

static void tab_cb(lv_event_t *e)
{
    ui_show_page((int)(intptr_t)lv_event_get_user_data(e));
}

static void build_dock(void)
{
    if (s_dock) lv_obj_delete(s_dock);
    memset(s_tab, 0, sizeof(s_tab));
    memset(s_tab_icon, 0, sizeof(s_tab_icon));
    memset(s_tab_text, 0, sizeof(s_tab_text));
    memset(s_tab_line, 0, sizeof(s_tab_line));
    s_dock = ui_box(lv_screen_active(), 0, PAGE_H, SCR_W, DOCK_H);
    lv_obj_set_style_bg_opa(s_dock, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(s_dock, lv_color_hex(COL_RAIL), 0);
    int n = s_order_n;
    for (int i = 0; i < n; i++) {
        int p = s_order[i];
        int x0 = i * SCR_W / n, x1 = (i + 1) * SCR_W / n;
        lv_obj_t *t = lv_obj_create(s_dock);
        lv_obj_remove_flag(t, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_set_pos(t, x0, 0);
        lv_obj_set_size(t, x1 - x0, DOCK_H);
        lv_obj_set_style_bg_color(t, lv_color_hex(COL_PRESSED), LV_STATE_PRESSED);
        lv_obj_set_style_bg_opa(t, LV_OPA_COVER, LV_STATE_PRESSED);
        lv_obj_add_event_cb(t, tab_cb, LV_EVENT_CLICKED, (void *)(intptr_t)p);
        s_tab[p] = t;
        s_tab_icon[p] = ui_label(t, &icons_20, COL_DIM, PAGES[p].icon);
        lv_obj_center(s_tab_icon[p]);
        s_tab_text[p] = ui_label(t, F12, COL_TEXT, "");
        lv_obj_center(s_tab_text[p]);
        lv_obj_add_flag(s_tab_text[p], LV_OBJ_FLAG_HIDDEN);
        s_tab_line[p] = ui_box(t, 6, 0, x1 - x0 - 12, 2);
        lv_obj_set_style_bg_opa(s_tab_line[p], LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(s_tab_line[p], lv_color_hex(p == P_CLAUDE ? COL_CLAUDE : COL_ACCENT), 0);
        lv_obj_add_flag(s_tab_line[p], LV_OBJ_FLAG_HIDDEN);
    }
}

static void mark_tabs(void)
{
    for (int p = 0; p < P_COUNT; p++) {
        if (!s_tab[p]) continue;
        bool on = p == s_current;
        uint32_t c = on ? (p == P_CLAUDE ? COL_CLAUDE : COL_ACCENT) : COL_DIM;
        lv_obj_set_style_text_color(s_tab_icon[p], lv_color_hex(c), 0);
        if (on) lv_obj_remove_flag(s_tab_line[p], LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(s_tab_line[p], LV_OBJ_FLAG_HIDDEN);
    }
}

void ui_dock_set_text(int page, const char *text)
{
    if (page < 0 || page >= P_COUNT || !s_tab[page]) return;
    if (text) {
        ui_set_text_if(s_tab_text[page], text);
        lv_obj_remove_flag(s_tab_text[page], LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_tab_icon[page], LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_tab_text[page], LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_tab_icon[page], LV_OBJ_FLAG_HIDDEN);
    }
}

// ---- Seiten ----------------------------------------------------------------

int ui_page_by_name(const char *name)
{
    for (int i = 0; i < P_COUNT; i++) {
        if (!strcmp(name, PAGES[i].name)) return i;
        if (PAGES[i].alias && !strcmp(name, PAGES[i].alias)) return i;
    }
    return -1;
}

const char *ui_page_name(int page)
{
    return page >= 0 && page < P_COUNT ? PAGES[page].name : "";
}

int ui_current_page(void) { return s_current; }

int ui_layout_get(uint8_t *out)
{
    memcpy(out, s_order, s_order_n);
    return s_order_n;
}

static void update_header_status(void)
{
    if (!s_hdr_status || s_current < 0) return;
    char buf[32];
    time_t st = ui_stale_at(s_current);
    if (st) {
        ui_fmt_stand(buf, sizeof(buf), st);
        lv_obj_set_style_text_color(s_hdr_status, lv_color_hex(COL_WARN), 0);
    } else if (plat_time_valid()) {
        ui_fmt_clock(buf, sizeof(buf), plat_now());
        lv_obj_set_style_text_color(s_hdr_status, lv_color_hex(COL_MUTED), 0);
    } else {
        buf[0] = 0;
    }
    ui_set_text_if(s_hdr_status, buf);
}

void ui_show_page(int page)
{
    if (page < 0 || page >= P_COUNT) return;
    bool changed = page != s_current;
    s_current = page;
    s_hdr_status = NULL;
    lv_obj_clean(s_page);
    PAGES[page].create(s_page);
    PAGES[page].refresh();
    update_header_status();
    mark_tabs();
    if (changed) {
        char msg[64];
        snprintf(msg, sizeof(msg), "{\"type\":\"page\",\"name\":\"%s\"}", PAGES[page].name);
        plat_send(msg);
    }
}

static void gesture_cb(lv_event_t *e)
{
    (void)e;
    lv_dir_t dir = lv_indev_get_gesture_dir(lv_indev_active());
    if (dir != LV_DIR_LEFT && dir != LV_DIR_RIGHT) return;
    int idx = 0;
    for (int i = 0; i < s_order_n; i++) if (s_order[i] == s_current) idx = i;
    idx += dir == LV_DIR_LEFT ? 1 : -1;
    if (idx < 0 || idx >= s_order_n) return;
    ui_show_page(s_order[idx]);
}

void ui_set_layout(const uint8_t *order, int n)
{
    uint8_t o[P_COUNT];
    int k = 0;
    o[k++] = P_HOME;   // Home ist immer dabei, vorn, wenn nicht anders genannt
    bool home_given = false;
    for (int i = 0; i < n; i++) if (order[i] == P_HOME) home_given = true;
    if (home_given) k = 0;
    for (int i = 0; i < n && k < P_COUNT; i++) o[k++] = order[i];
    if (k == s_order_n && !memcmp(o, s_order, k)) return;
    memcpy(s_order, o, k);
    s_order_n = k;
    build_dock();
    bool still = false;
    for (int i = 0; i < k; i++) if (s_order[i] == s_current) still = true;
    ui_show_page(still ? s_current : s_order[0]);
}

void ui_init(void)
{
    lv_obj_t *scr = lv_screen_active();
    lv_obj_set_style_bg_color(scr, lv_color_hex(COL_BG), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_set_style_text_color(scr, lv_color_hex(COL_TEXT), 0);
    lv_obj_set_style_text_font(scr, F14, 0);
    lv_obj_remove_flag(scr, LV_OBJ_FLAG_SCROLLABLE);
    s_page = ui_box(scr, 0, 0, SCR_W, PAGE_H);
    lv_obj_add_flag(s_page, LV_OBJ_FLAG_GESTURE_BUBBLE);
    lv_obj_add_event_cb(scr, gesture_cb, LV_EVENT_GESTURE, NULL);
    for (int i = 0; i < P_COUNT; i++) s_order[i] = (uint8_t)i;
    s_order_n = P_COUNT;
    build_dock();
    ui_show_page(P_HOME);
}

// ---- Daten -----------------------------------------------------------------

static void got(int page)
{
    g_rx[page] = plat_now();
    g_had_data = true;
    if (s_current == page) PAGES[page].refresh();
    else if (s_current == P_HOME) home_refresh();
    update_header_status();
}

void ui_set_events(const hub_event_t *ev, int n, int days)
{
    if (n > HUB_MAX_EVENTS) n = HUB_MAX_EVENTS;
    memcpy(g_events, ev, sizeof(hub_event_t) * n);
    g_event_count = n;
    g_event_days = days;
    got(P_CALENDAR);
}

void ui_set_claude(const hub_claude_t *c) { g_claude = *c; got(P_CLAUDE); }
void ui_set_github(const hub_github_t *g) { g_github = *g; got(P_GITHUB); }
void ui_set_net(const hub_net_t *n) { g_net = *n; got(P_NET); }
void ui_set_weather(const hub_weather_t *w) { g_weather = *w; got(P_WEATHER); }
void ui_set_homelab(const hub_homelab_t *h) { g_homelab = *h; got(P_HOMELAB); }

// ---- Takt ------------------------------------------------------------------

void ui_tick(void)
{
    static time_t last_sec;
    timer_global_tick();
    if (s_current == P_TIMER) timer_page_tick();

    bool online = plat_companion_online();
    if (online && !s_was_online) {
        // Nach dem Neustart oder einer neuen Verbindung: alles frisch anfordern.
        plat_send("{\"type\":\"refresh\"}");
        s_last_refresh_ms = plat_millis();
        s_refresh_sent = true;
    }
    if (online != s_was_online && s_current == P_HOME) home_refresh();
    s_was_online = online;

    time_t now = plat_now();
    if (now == last_sec) return;
    last_sec = now;
    if (s_current == P_HOME) home_tick();
    update_header_status();

    // Daten aelter als 15 Minuten: hoechstens alle 15 Minuten nachfragen.
    if (online && (!s_refresh_sent || plat_millis() - s_last_refresh_ms > STALE_S * 1000u)) {
        bool old = false;
        for (int i = 0; i < s_order_n; i++) {
            int p = s_order[i];
            if (g_rx[p] && now - g_rx[p] > STALE_S) old = true;
        }
        if (old) {
            plat_send("{\"type\":\"refresh\"}");
            s_last_refresh_ms = plat_millis();
            s_refresh_sent = true;
        }
    }
}
