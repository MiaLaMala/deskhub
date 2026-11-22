// Start: Uhr gross, Datum, naechster Termin, Claude 5 h und Woche, Wetter jetzt,
// eine Homelab-Zeile. Ohne Begleiter: "Warte auf Begleiter" mit IP und Uhr.
#include <stdio.h>
#include <string.h>

#include "ui_internal.h"

static lv_obj_t *s_clock, *s_wday, *s_date, *s_link;
static lv_obj_t *s_wait;                 // Wartezustand
static lv_obj_t *s_body;                 // Datenzeilen
static lv_obj_t *s_ev_icon, *s_ev_title, *s_ev_sub;
static lv_obj_t *s_c5_val, *s_c5_bar, *s_c7_val, *s_c7_bar, *s_c_none, *s_c_cap5, *s_c_cap7;
static lv_obj_t *s_wx_icon, *s_wx_text;
static lv_obj_t *s_hl_dot, *s_hl_text;
static lv_obj_t *s_wait_ip, *s_wait_sub;

static lv_obj_t *dot(lv_obj_t *p, int x, int y, uint32_t c)
{
    lv_obj_t *d = ui_box(p, x, y, 8, 8);
    lv_obj_set_style_radius(d, 4, 0);
    lv_obj_set_style_bg_opa(d, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(d, lv_color_hex(c), 0);
    return d;
}

void home_create(lv_obj_t *p)
{
    s_clock = ui_label_at(p, F48, COL_TEXT, PAD, 4, "--:--");
    s_wday = ui_label_at(p, F16, COL_TEXT, 168, 9, "");
    s_date = ui_label_at(p, F14, COL_MUTED, 168, 30, "");
    s_link = ui_label_at(p, F12, COL_WARN, PAD + 22, 178, "");

    // Wartezustand
    s_wait = ui_box(p, 0, 62, SCR_W, PAGE_H - 62);
    lv_obj_t *t = ui_label(s_wait, F20, COL_TEXT, "Warte auf Begleiter");
    lv_obj_align(t, LV_ALIGN_TOP_MID, 0, 20);
    s_wait_ip = ui_label(s_wait, F14, COL_MUTED, "");
    lv_obj_align(s_wait_ip, LV_ALIGN_TOP_MID, 0, 56);
    s_wait_sub = ui_label(s_wait, F12, COL_DIM, "Der Timer geht auch ohne.");
    lv_obj_align(s_wait_sub, LV_ALIGN_TOP_MID, 0, 84);

    // Datenzeilen
    s_body = ui_box(p, 0, 58, SCR_W, PAGE_H - 58);
    lv_obj_t *sep = ui_box(s_body, PAD, 0, SCR_W - 2 * PAD, 1);
    lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(sep, lv_color_hex(COL_BORDER), 0);

    s_ev_icon = ui_label_at(s_body, &icons_16, COL_ACCENT, PAD, 8, ICON_EVENT);
    s_ev_title = ui_label_w(s_body, F16, COL_TEXT, PAD + 22, 6, SCR_W - 2 * PAD - 22, "");
    s_ev_sub = ui_label_w(s_body, F12, COL_MUTED, PAD + 22, 26, SCR_W - 2 * PAD - 22, "");

    // Claude: zwei Haelften, je Label und Wert direkt nebeneinander ("5 h 42 %"),
    // Balken darunter; zwischen den Paaren bleibt Luft. Labels wie auf der Claude-Seite.
    const int cy = 46, half = (SCR_W - 3 * PAD) / 2, x7 = 2 * PAD + half;
    s_c_cap5 = ui_label_at(s_body, F12, COL_CLAUDE, PAD, cy + 2, "5 h");
    s_c5_val = ui_label_at(s_body, F16, COL_TEXT, PAD + ui_text_w("5 h", F12) + 6, cy, "");
    s_c5_bar = ui_bar(s_body, PAD, cy + 20, half, 6, COL_CLAUDE, COL_CLAUDE_LO);
    s_c_cap7 = ui_label_at(s_body, F12, COL_CLAUDE, x7, cy + 2, "Woche");
    s_c7_val = ui_label_at(s_body, F16, COL_TEXT, x7 + ui_text_w("Woche", F12) + 6, cy, "");
    s_c7_bar = ui_bar(s_body, x7, cy + 20, half, 6, COL_CLAUDE, COL_CLAUDE_LO);
    s_c_none = ui_label_at(s_body, F12, COL_DIM, PAD + 70, cy + 2, "");

    s_wx_icon = ui_label_at(s_body, &icons_16, COL_MUTED, PAD, 79, ICON_CLOUD);
    s_wx_text = ui_label_w(s_body, F14, COL_TEXT, PAD + 22, 78, SCR_W - 2 * PAD - 22, "");

    s_hl_dot = dot(s_body, PAD + 4, 106, COL_DIM);
    s_hl_text = ui_label_w(s_body, F14, COL_TEXT, PAD + 22, 101, SCR_W - 2 * PAD - 22, "");
}

static const hub_event_t *next_event(void)
{
    time_t now = plat_now();
    const hub_event_t *best = NULL;
    for (int i = 0; i < g_event_count; i++) {
        const hub_event_t *e = &g_events[i];
        time_t end = e->end ? e->end : e->start;
        if (end <= now) continue;
        // Ganztägiges von heute zählt nur, wenn nichts mit Uhrzeit kommt.
        if (!best) { best = e; continue; }
        if (best->all_day && !e->all_day && ui_days_between(now, e->start) == 0) { best = e; continue; }
        if (!e->all_day && !best->all_day && e->start < best->start) best = e;
    }
    return best;
}

static void fill_event(void)
{
    char a[96], b[96];
    const hub_event_t *e = next_event();
    if (!e) {
        lv_label_set_text(s_ev_title, g_rx[P_CALENDAR] ? "Keine Termine mehr" : "Termine kommen vom Begleiter");
        lv_obj_set_style_text_color(s_ev_title, lv_color_hex(COL_MUTED), 0);
        lv_label_set_text(s_ev_sub, "");
        return;
    }
    lv_obj_set_style_text_color(s_ev_title, lv_color_hex(COL_TEXT), 0);
    lv_obj_set_style_text_color(s_ev_icon, lv_color_hex(e->color), 0);
    time_t now = plat_now();
    long d = ui_days_between(now, e->start);
    char hm[8], hm2[8];
    ui_fmt_clock(hm, sizeof(hm), e->start);
    ui_fmt_clock(hm2, sizeof(hm2), e->end);
    if (e->all_day) snprintf(a, sizeof(a), "%s", e->title);
    else snprintf(a, sizeof(a), "%s %s", hm, e->title);
    lv_label_set_text(s_ev_title, a);
    const char *day;
    char dbuf[24];
    struct tm tm;
    ui_localtime(e->start, &tm);
    if (d <= 0) day = e->start <= now && !e->all_day ? "läuft" : "heute";
    else if (d == 1) day = "morgen";
    else { snprintf(dbuf, sizeof(dbuf), "%s %d.%d.", ui_wday_short(tm.tm_wday), tm.tm_mday, tm.tm_mon + 1); day = dbuf; }
    if (e->all_day) snprintf(b, sizeof(b), "%s, ganztägig", day);
    else snprintf(b, sizeof(b), "%s, bis %s", day, hm2);
    if (e->location[0]) { strlcat(b, " · ", sizeof(b)); strlcat(b, e->location, sizeof(b)); }
    lv_label_set_text(s_ev_sub, b);
}

static void fill_claude(void)
{
    char buf[16];
    const hub_claude_t *c = &g_claude;
    bool any = c->valid && (c->has_5h || c->has_7d);
    lv_obj_t *a[] = {s_c5_val, s_c5_bar, s_c7_val, s_c7_bar, s_c_cap7};
    for (size_t i = 0; i < sizeof(a) / sizeof(a[0]); i++) {
        if (any) lv_obj_remove_flag(a[i], LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(a[i], LV_OBJ_FLAG_HIDDEN);
    }
    if (!any) {
        lv_label_set_text(s_c_cap5, "Claude");
        lv_label_set_text(s_c_none, "noch keine Limits");
        return;
    }
    lv_label_set_text(s_c_cap5, "5 h");
    lv_label_set_text(s_c_none, "");
    bool stale = ui_stale_at(P_CLAUDE) != 0;
    struct { bool has; float pct; lv_obj_t *val, *bar; } r[2] = {
        {c->has_5h, c->pct_5h, s_c5_val, s_c5_bar}, {c->has_7d, c->pct_7d, s_c7_val, s_c7_bar}};
    for (int i = 0; i < 2; i++) {
        if (!r[i].has) { lv_label_set_text(r[i].val, "–"); lv_bar_set_value(r[i].bar, 0, LV_ANIM_OFF); continue; }
        snprintf(buf, sizeof(buf), "%d %%", (int)(r[i].pct + 0.5f));
        lv_label_set_text(r[i].val, buf);
        lv_obj_set_style_text_color(r[i].val, lv_color_hex(stale ? COL_MUTED : r[i].pct >= 80 ? COL_BAD : COL_TEXT), 0);
        lv_bar_set_value(r[i].bar, (int)(r[i].pct + 0.5f), LV_ANIM_OFF);
    }
}

static void fill_weather(void)
{
    char buf[96], t[8], f[8];
    const hub_weather_t *w = &g_weather;
    if (!w->valid) {
        lv_label_set_text(s_wx_text, "Wetter kommt vom Begleiter");
        lv_obj_set_style_text_color(s_wx_text, lv_color_hex(COL_MUTED), 0);
        return;
    }
    lv_label_set_text(s_wx_icon, weather_icon(w->code, w->is_day));
    lv_obj_set_style_text_color(s_wx_icon, lv_color_hex(weather_color(w->code, w->is_day)), 0);
    ui_fmt_temp(t, sizeof(t), w->temp);
    snprintf(buf, sizeof(buf), "%s  %s", t, weather_text(w->code));
    if (w->feels == w->feels) {   // nicht NAN
        ui_fmt_temp(f, sizeof(f), w->feels);
        if (strcmp(f, t)) { strlcat(buf, ", gefühlt ", sizeof(buf)); strlcat(buf, f, sizeof(buf)); }
    }
    time_t st = ui_stale_at(P_WEATHER);
    if (st) {
        char s[24];
        ui_fmt_clock(s, sizeof(s), st);
        strlcat(buf, " (", sizeof(buf));
        strlcat(buf, s, sizeof(buf));
        strlcat(buf, ")", sizeof(buf));
    }
    lv_label_set_text(s_wx_text, buf);
    lv_obj_set_style_text_color(s_wx_text, lv_color_hex(st ? COL_MUTED : COL_TEXT), 0);
}

static void fill_homelab(void)
{
    char buf[96];
    const hub_homelab_t *h = &g_homelab;
    if (!h->valid) {
        lv_label_set_text(s_hl_text, "Homelab kommt vom Begleiter");
        lv_obj_set_style_text_color(s_hl_text, lv_color_hex(COL_MUTED), 0);
        lv_obj_set_style_bg_color(s_hl_dot, lv_color_hex(COL_DIM), 0);
        return;
    }
    uint32_t col = h->down_count || h->up < h->total ? COL_BAD : COL_GOOD;
    if (h->down_count == 0 && h->up >= h->total) snprintf(buf, sizeof(buf), "Homelab: alle %d oben", h->total);
    else if (h->down_count == 1) snprintf(buf, sizeof(buf), "Homelab %d/%d: %s aus", h->up, h->total, h->down_name[0]);
    else snprintf(buf, sizeof(buf), "Homelab %d/%d: %d ausgefallen", h->up, h->total, h->total - h->up);
    time_t st = ui_stale_at(P_HOMELAB);
    if (st) {   // kurz, damit die Uhrzeit nicht abgeschnitten wird
        char s[32];
        ui_fmt_stand(s, sizeof(s), st);
        snprintf(buf, sizeof(buf), "Homelab %d/%d · %s", h->up, h->total, s);
        col = COL_WARN;
    }
    lv_label_set_text(s_hl_text, buf);
    lv_obj_set_style_text_color(s_hl_text, lv_color_hex(st ? COL_WARN : COL_TEXT), 0);
    lv_obj_set_style_bg_color(s_hl_dot, lv_color_hex(col), 0);
}

void home_tick(void)
{
    char buf[40];
    if (plat_time_valid()) {
        time_t now = plat_now();
        struct tm tm;
        ui_localtime(now, &tm);
        ui_fmt_clock(buf, sizeof(buf), now);
        ui_set_text_if(s_clock, buf);
        ui_set_text_if(s_wday, ui_wday_long(tm.tm_wday));
        snprintf(buf, sizeof(buf), "%d. %s", tm.tm_mday, ui_month_long(tm.tm_mon));
        ui_set_text_if(s_date, buf);
    } else {
        ui_set_text_if(s_clock, "--:--");
        ui_set_text_if(s_wday, "Uhr nicht gestellt");
        ui_set_text_if(s_date, "");
    }
    if (ui_waiting()) {
        const char *ip = plat_ip();
        if (ip[0]) snprintf(buf, sizeof(buf), "IP %s · deskhub.local", ip);
        else snprintf(buf, sizeof(buf), "kein WLAN");
        ui_set_text_if(s_wait_ip, buf);
    }
    ui_set_text_if(s_link, g_had_data && !plat_companion_online() ? "Begleiter getrennt" : "");
}

void home_refresh(void)
{
    bool wait = ui_waiting();
    if (wait) {
        lv_obj_remove_flag(s_wait, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_body, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_wait, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_body, LV_OBJ_FLAG_HIDDEN);
        fill_event();
        fill_claude();
        fill_weather();
        fill_homelab();
    }
    home_tick();
}
