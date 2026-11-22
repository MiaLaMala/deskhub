// GitHub: Jahres-Heatmap (53 Wochen x 7 Tage, 5 px plus 1 px Abstand = 318 px),
// Serie, Woche, Jahr, darunter die Tage dieser Woche.
#include <stdio.h>
#include <string.h>

#include "ui_internal.h"

#define GH_WEEKS 53
#define GH_PITCH 6
#define GH_SQ 5
#define GH_X 1
#define GH_Y 28

static lv_obj_t *s_title, *s_chart, *s_none, *s_body;
static lv_obj_t *s_month[HUB_GH_MONTHS];
static lv_obj_t *s_val[3], *s_unit[3];
static lv_obj_t *s_week, *s_week_cap;

static const uint32_t GREENS[5] = {0x1d2128, 0x0e4429, 0x006d32, 0x26a641, 0x39d353};
static const uint32_t AMBERS[5] = {0x1d2128, 0x4d3a12, 0x8a6514, 0xc98f1b, COL_ACCENT};

static int total_weeks(void)
{
    const hub_github_t *g = &g_github;
    if (g->day_count <= 0) return 0;
    return (g->start_wday + g->day_count - 1) / 7 + 1;
}

static void chart_draw_cb(lv_event_t *e)
{
    lv_obj_t *o = lv_event_get_target(e);
    lv_layer_t *layer = lv_event_get_layer(e);
    const hub_github_t *g = &g_github;
    lv_area_t a;
    lv_obj_get_coords(o, &a);
    const lv_area_t *clip = &layer->_clip_area;
    int weeks = total_weeks();
    int first = weeks > GH_WEEKS ? weeks - GH_WEEKS : 0;
    const uint32_t *pal = g->accent ? AMBERS : GREENS;
    lv_draw_rect_dsc_t d;
    lv_draw_rect_dsc_init(&d);
    d.bg_opa = LV_OPA_COVER;
    d.radius = 1;
    for (int i = 0; i < g->day_count; i++) {
        int k = g->start_wday + i;
        int col = k / 7 - first, row = k % 7;
        if (col < 0) continue;
        lv_area_t r;
        r.x1 = a.x1 + col * GH_PITCH;
        r.y1 = a.y1 + row * GH_PITCH;
        r.x2 = r.x1 + GH_SQ - 1;
        r.y2 = r.y1 + GH_SQ - 1;
        if (r.y2 < clip->y1 || r.y1 > clip->y2 || r.x2 < clip->x1 || r.x1 > clip->x2) continue;
        d.bg_color = lv_color_hex(pal[g->level[i] > 4 ? 4 : g->level[i]]);
        if (i == g->day_count - 1) {   // heute mit Rand
            d.border_width = 1;
            d.border_color = lv_color_hex(COL_TEXT);
            d.border_opa = LV_OPA_COVER;
        } else {
            d.border_width = 0;
        }
        lv_draw_rect(layer, &d, &r);
    }
}

static void week_draw_cb(lv_event_t *e)
{
    lv_obj_t *o = lv_event_get_target(e);
    lv_layer_t *layer = lv_event_get_layer(e);
    const hub_github_t *g = &g_github;
    lv_area_t a;
    lv_obj_get_coords(o, &a);
    int maxv = 1;
    for (int i = 0; i < g->week_day_count; i++) if (g->week_days[i] > maxv) maxv = g->week_days[i];
    int colw = lv_area_get_width(&a) / 7, h = lv_area_get_height(&a) - 16;
    lv_draw_rect_dsc_t d;
    lv_draw_rect_dsc_init(&d);
    d.bg_opa = LV_OPA_COVER;
    d.radius = 2;
    lv_draw_label_dsc_t t;
    lv_draw_label_dsc_init(&t);
    t.font = F12;
    t.align = LV_TEXT_ALIGN_CENTER;
    for (int i = 0; i < 7; i++) {
        int x = a.x1 + i * colw;
        bool has = i < g->week_day_count;
        int v = has ? g->week_days[i] : 0;
        int bh = has ? (v * h + maxv - 1) / maxv : 0;
        if (has && bh < 2) bh = 2;
        lv_area_t r = {x + colw / 2 - 9, a.y1 + h - bh, x + colw / 2 + 8, a.y1 + h - 1};
        if (!has) { r.y1 = a.y1 + h - 2; }
        d.bg_color = lv_color_hex(!has ? COL_CARD_HI : i == g->week_day_count - 1 ? (g->accent ? COL_ACCENT : 0x39d353)
                                                                                   : (g->accent ? 0x8a6514 : 0x26a641));
        lv_draw_rect(layer, &d, &r);
        lv_area_t ta = {x, a.y1 + h + 2, x + colw - 1, a.y2};
        t.color = lv_color_hex(i == g->week_day_count - 1 ? COL_TEXT : COL_MUTED);
        t.text = ui_wday_short(i);
        lv_draw_label(layer, &t, &ta);
    }
}

void github_create(lv_obj_t *p)
{
    ui_header(p, "GitHub", COL_TEXT);
    s_title = lv_obj_get_child(p, 0);
    s_chart = ui_box(p, GH_X, GH_Y, GH_WEEKS * GH_PITCH - 1, 7 * GH_PITCH - 1);
    lv_obj_add_event_cb(s_chart, chart_draw_cb, LV_EVENT_DRAW_MAIN, NULL);
    for (int i = 0; i < HUB_GH_MONTHS; i++) {
        s_month[i] = ui_label_at(p, F12, COL_MUTED, 0, GH_Y + 7 * GH_PITCH + 1, "");
        lv_obj_add_flag(s_month[i], LV_OBJ_FLAG_HIDDEN);
    }
    s_body = ui_box(p, 0, 90, SCR_W, PAGE_H - 90);
    static const char *caps[3] = {"Serie", "Diese Woche", "Im Jahr"};
    const int cw = (SCR_W - 2 * PAD) / 3;
    for (int i = 0; i < 3; i++) {
        ui_label_at(s_body, F12, COL_MUTED, PAD + i * cw, 0, caps[i]);
        s_val[i] = ui_label_at(s_body, F20, COL_TEXT, PAD + i * cw, 16, "");
        s_unit[i] = ui_label_at(s_body, F12, COL_MUTED, PAD + i * cw, 24, "");
    }
    s_week_cap = ui_label_at(s_body, F12, COL_MUTED, PAD, 48, "");
    s_week = ui_box(s_body, 110, 46, SCR_W - 110 - PAD, 66);
    lv_obj_add_event_cb(s_week, week_draw_cb, LV_EVENT_DRAW_MAIN, NULL);
    s_none = ui_label(p, F14, COL_MUTED, "GitHub kommt vom Begleiter");
    lv_obj_align(s_none, LV_ALIGN_CENTER, 0, 0);
}

void github_refresh(void)
{
    const hub_github_t *g = &g_github;
    char buf[48];
    if (!g->valid) {
        lv_obj_add_flag(s_body, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_chart, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_none, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_add_flag(s_none, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(s_body, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(s_chart, LV_OBJ_FLAG_HIDDEN);
    if (g->login[0]) snprintf(buf, sizeof(buf), "GitHub · %s", g->login);
    else strlcpy(buf, "GitHub", sizeof(buf));
    lv_label_set_text(s_title, buf);
    lv_obj_invalidate(s_chart);
    lv_obj_invalidate(s_week);

    // Monatsnamen unter die Spalten; was sich ueberlappen wuerde, entfaellt.
    int weeks = total_weeks(), first = weeks > GH_WEEKS ? weeks - GH_WEEKS : 0;
    int last_right = -100;
    for (int i = 0; i < HUB_GH_MONTHS; i++) {
        lv_obj_t *l = s_month[i];
        lv_obj_add_flag(l, LV_OBJ_FLAG_HIDDEN);
        if (i >= g->month_count) continue;
        int col = g->month_col[i] - first;
        if (col < 0) continue;
        const char *name = ui_month_de(g->month_name[i]);
        int w = lv_text_get_width(name, strlen(name), F12, 0);
        int x = GH_X + col * GH_PITCH;
        // Jeder zweite Monat (der neueste immer): ein Monat sind nur gut 26 px.
        if ((g->month_count - 1 - i) % 2) continue;
        if (x < last_right + 4 || x + w > SCR_W - 1) continue;
        lv_label_set_text(l, name);
        lv_obj_set_x(l, x);
        lv_obj_remove_flag(l, LV_OBJ_FLAG_HIDDEN);
        last_right = x + w;
    }

    int v[3] = {g->streak, g->week, g->total};
    for (int i = 0; i < 3; i++) {
        ui_fmt_int(buf, sizeof(buf), v[i]);
        lv_label_set_text(s_val[i], buf);
        int w = lv_text_get_width(buf, strlen(buf), F20, 0);
        lv_obj_set_x(s_unit[i], PAD + i * ((SCR_W - 2 * PAD) / 3) + w + 4);
    }
    lv_label_set_text(s_unit[0], g->streak == 1 ? "Tag" : "Tage");
    lv_label_set_text(s_unit[1], "");
    lv_label_set_text(s_unit[2], "");
    if (g->longest > 0) snprintf(buf, sizeof(buf), "Längste\nSerie %d", g->longest);
    else buf[0] = 0;
    lv_label_set_text(s_week_cap, buf);
}
