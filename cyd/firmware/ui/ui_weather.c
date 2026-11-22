// Wetter: jetzt, die naechsten Stunden, die naechsten Tage. Daten vom Begleiter.
#include <stdio.h>
#include <string.h>

#include "ui_internal.h"

#define NH 6   // Stunden-Spalten
#define ND 6   // Tages-Spalten

static lv_obj_t *s_title, *s_icon, *s_temp, *s_cond, *s_det1, *s_det2, *s_det3, *s_none, *s_grid;
static lv_obj_t *s_h_t[NH], *s_h_i[NH], *s_h_v[NH], *s_h_p[NH];
static lv_obj_t *s_d_t[ND], *s_d_i[ND], *s_d_v[ND];

static lv_obj_t *centered(lv_obj_t *p, const lv_font_t *f, uint32_t c, int cx, int y)
{
    lv_obj_t *l = ui_label(p, f, c, "");
    lv_obj_set_width(l, 50);
    lv_obj_set_pos(l, cx - 25, y);
    lv_obj_set_style_text_align(l, LV_TEXT_ALIGN_CENTER, 0);
    return l;
}

void weather_create(lv_obj_t *p)
{
    lv_obj_t *st = ui_header(p, "Wetter", COL_TEXT);
    (void)st;
    s_title = lv_obj_get_child(p, 0);
    s_icon = ui_label_at(p, &icons_36, COL_MUTED, PAD, 32, ICON_CLOUD);
    s_temp = ui_label_at(p, F48, COL_TEXT, PAD + 44, 24, "");
    // Je eine kurze Zeile: passt auch bei "gefühlt −19°", 100 % und 112 km/h.
    s_cond = ui_label_w(p, F16, COL_TEXT, 170, 23, SCR_W - 170 - PAD, "");
    s_det1 = ui_label_w(p, F12, COL_MUTED, 170, 43, SCR_W - 170 - PAD, "");
    s_det2 = ui_label_w(p, F12, COL_MUTED, 170, 59, SCR_W - 170 - PAD, "");
    s_det3 = ui_label_w(p, F12, COL_MUTED, 170, 75, SCR_W - 170 - PAD, "");

    s_grid = ui_box(p, 0, 91, SCR_W, PAGE_H - 91);
    lv_obj_t *sep = ui_box(s_grid, PAD, 0, SCR_W - 2 * PAD, 1);
    lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(sep, lv_color_hex(COL_BORDER), 0);
    const int colw = (SCR_W - 2 * PAD) / NH;
    for (int i = 0; i < NH; i++) {
        int cx = PAD + colw * i + colw / 2;
        s_h_t[i] = centered(s_grid, F12, COL_MUTED, cx, 0);
        s_h_i[i] = centered(s_grid, &icons_16, COL_MUTED, cx, 16);
        s_h_v[i] = centered(s_grid, F14, COL_TEXT, cx, 33);
        s_h_p[i] = centered(s_grid, F12, COL_BLUE, cx, 51);
    }
    sep = ui_box(s_grid, PAD, 67, SCR_W - 2 * PAD, 1);
    lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(sep, lv_color_hex(COL_BORDER), 0);
    const int dw = (SCR_W - 2 * PAD) / ND;
    for (int i = 0; i < ND; i++) {
        int cx = PAD + dw * i + dw / 2;
        // Tag und Symbol nebeneinander ("Mi ☁"), heute in der Akzentfarbe: spart eine Zeile.
        s_d_t[i] = ui_label(s_grid, F12, COL_MUTED, "");
        lv_obj_set_width(s_d_t[i], 22);
        lv_obj_set_pos(s_d_t[i], cx - 22, 70);
        lv_obj_set_style_text_align(s_d_t[i], LV_TEXT_ALIGN_RIGHT, 0);
        s_d_i[i] = ui_label_at(s_grid, &icons_16, COL_MUTED, cx + 2, 69, "");
        s_d_v[i] = centered(s_grid, F12, COL_TEXT, cx, 87);
    }
    s_none = ui_label(p, F14, COL_MUTED, "Wetter kommt vom Begleiter");
    lv_obj_align(s_none, LV_ALIGN_CENTER, 0, 0);
}

void weather_refresh(void)
{
    const hub_weather_t *w = &g_weather;
    char buf[64], a[8], b[8];
    if (!w->valid) {
        lv_obj_add_flag(s_grid, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_icon, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_none, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_add_flag(s_none, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(s_grid, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(s_icon, LV_OBJ_FLAG_HIDDEN);
    if (w->place[0]) snprintf(buf, sizeof(buf), "Wetter · %s", w->place);
    else strlcpy(buf, "Wetter", sizeof(buf));
    lv_label_set_text(s_title, buf);
    lv_label_set_text(s_icon, weather_icon(w->code, w->is_day));
    lv_obj_set_style_text_color(s_icon, lv_color_hex(weather_color(w->code, w->is_day)), 0);
    ui_fmt_temp(a, sizeof(a), w->temp);
    lv_label_set_text(s_temp, a);
    lv_label_set_text(s_cond, weather_text(w->code));
    // Drei kurze Zeilen; fehlende Werte ruecken nach oben (keine Luecken, keine Nullen).
    lv_obj_t *det[3] = {s_det1, s_det2, s_det3};
    int nd = 0;
    if (w->feels == w->feels) { ui_fmt_temp(b, sizeof(b), w->feels); snprintf(buf, sizeof(buf), "gefühlt %s", b); lv_label_set_text(det[nd++], buf); }
    if (w->humidity >= 0) { snprintf(buf, sizeof(buf), "Feuchte %d %%", w->humidity); lv_label_set_text(det[nd++], buf); }
    if (w->wind >= 0) { snprintf(buf, sizeof(buf), "Wind %d km/h", (int)(w->wind + 0.5f)); lv_label_set_text(det[nd++], buf); }
    while (nd < 3) lv_label_set_text(det[nd++], "");

    // Stunden: die naechsten, die noch kommen (jede zweite, wenn genug da sind).
    time_t now = plat_now();
    int first = 0;
    while (first < w->hour_count && w->hour_t[first] + 3600 <= now) first++;
    int avail = w->hour_count - first;
    int step = avail >= 2 * NH ? 2 : 1;
    for (int i = 0; i < NH; i++) {
        int k = first + i * step;
        bool on = k < w->hour_count;
        lv_obj_t *o[] = {s_h_t[i], s_h_i[i], s_h_v[i], s_h_p[i]};
        for (int j = 0; j < 4; j++) { if (on) lv_obj_remove_flag(o[j], LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(o[j], LV_OBJ_FLAG_HIDDEN); }
        if (!on) continue;
        struct tm tm;
        ui_localtime(w->hour_t[k], &tm);
        snprintf(buf, sizeof(buf), "%02d Uhr", tm.tm_hour);
        lv_label_set_text(s_h_t[i], buf);
        bool day = tm.tm_hour >= 7 && tm.tm_hour < 19;
        lv_label_set_text(s_h_i[i], weather_icon(w->hour_code[k], day));
        lv_obj_set_style_text_color(s_h_i[i], lv_color_hex(weather_color(w->hour_code[k], day)), 0);
        ui_fmt_temp(a, sizeof(a), w->hour_temp[k]);
        lv_label_set_text(s_h_v[i], a);
        if (w->hour_precip[k] >= 10) snprintf(buf, sizeof(buf), "%d %%", w->hour_precip[k]);
        else buf[0] = 0;
        lv_label_set_text(s_h_p[i], buf);
    }
    for (int i = 0; i < ND; i++) {
        bool on = i < w->day_count;
        lv_obj_t *o[] = {s_d_t[i], s_d_i[i], s_d_v[i]};
        for (int j = 0; j < 3; j++) { if (on) lv_obj_remove_flag(o[j], LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(o[j], LV_OBJ_FLAG_HIDDEN); }
        if (!on) continue;
        struct tm tm;
        // Tage kommen als Mitternacht UTC oder lokal: Mittag nehmen, dann stimmt der Wochentag.
        ui_localtime(w->day_t[i] + 12 * 3600, &tm);
        long d = ui_days_between(now, w->day_t[i] + 12 * 3600);
        lv_label_set_text(s_d_t[i], ui_wday_short(tm.tm_wday));
        lv_obj_set_style_text_color(s_d_t[i], lv_color_hex(d == 0 ? COL_ACCENT : COL_MUTED), 0);
        lv_label_set_text(s_d_i[i], weather_icon(w->day_code[i], true));
        lv_obj_set_style_text_color(s_d_i[i], lv_color_hex(weather_color(w->day_code[i], true)), 0);
        ui_fmt_temp(a, sizeof(a), w->day_hi[i]);
        ui_fmt_temp(b, sizeof(b), w->day_lo[i]);
        snprintf(buf, sizeof(buf), "%s/%s", a, b);
        lv_label_set_text(s_d_v[i], buf);
    }
}
