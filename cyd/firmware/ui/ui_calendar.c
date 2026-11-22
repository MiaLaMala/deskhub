// Kalender: Termine nach Tag gruppiert, senkrecht verschiebbar.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ui_internal.h"

static lv_obj_t *s_list, *s_empty;

void calendar_create(lv_obj_t *p)
{
    ui_header(p, "Kalender", COL_TEXT);
    s_list = lv_obj_create(p);
    lv_obj_set_pos(s_list, 0, HDR_H + 2);
    lv_obj_set_size(s_list, SCR_W, PAGE_H - HDR_H - 2);
    lv_obj_set_scroll_dir(s_list, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(s_list, LV_SCROLLBAR_MODE_OFF);
    lv_obj_remove_flag(s_list, LV_OBJ_FLAG_SCROLL_ELASTIC | LV_OBJ_FLAG_SCROLL_MOMENTUM);
    lv_obj_add_flag(s_list, LV_OBJ_FLAG_GESTURE_BUBBLE);
    s_empty = ui_label(p, F14, COL_MUTED, "");
    lv_obj_align(s_empty, LV_ALIGN_CENTER, 0, 10);
}

static int cmp_ev(const void *a, const void *b)
{
    const hub_event_t *x = a, *y = b;
    if (x->start != y->start) return x->start < y->start ? -1 : 1;
    return (int)y->all_day - (int)x->all_day;
}

void calendar_refresh(void)
{
    lv_obj_clean(s_list);
    time_t now = plat_now();
    static hub_event_t ev[HUB_MAX_EVENTS];
    int n = 0;
    for (int i = 0; i < g_event_count; i++) {
        time_t end = g_events[i].end ? g_events[i].end : g_events[i].start;
        if (end > now) ev[n++] = g_events[i];
    }
    qsort(ev, n, sizeof(ev[0]), cmp_ev);
    if (!n) {
        lv_label_set_text(s_empty, g_rx[P_CALENDAR] ? "Keine Termine in nächster Zeit" : "Termine kommen vom Begleiter");
        lv_obj_remove_flag(s_empty, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_add_flag(s_empty, LV_OBJ_FLAG_HIDDEN);
    int y = 0;
    long last_day = -9999;
    char buf[96], hm[8], hm2[8];
    for (int i = 0; i < n; i++) {
        const hub_event_t *e = &ev[i];
        // Ganztägiges, das schon läuft, steht unter heute.
        time_t day_t = e->start < now ? now : e->start;
        long d = ui_days_between(now, day_t);
        if (d != last_day) {
            last_day = d;
            ui_fmt_day_title(buf, sizeof(buf), day_t);
            ui_label_at(s_list, F12, d == 0 ? COL_ACCENT : COL_MUTED, PAD, y + 4, buf);
            y += 22;
        }
        lv_obj_t *strip = ui_box(s_list, PAD, y + 2, 3, 32);
        lv_obj_set_style_bg_opa(strip, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(strip, lv_color_hex(e->color), 0);
        lv_obj_set_style_radius(strip, 1, 0);
        ui_label_w(s_list, F14, COL_TEXT, PAD + 10, y, SCR_W - 2 * PAD - 10, e->title);
        if (e->all_day) {
            strlcpy(buf, "ganztägig", sizeof(buf));
        } else {
            ui_fmt_clock(hm, sizeof(hm), e->start);
            ui_fmt_clock(hm2, sizeof(hm2), e->end);
            if (e->end > e->start) snprintf(buf, sizeof(buf), "%s–%s", hm, hm2);
            else snprintf(buf, sizeof(buf), "%s", hm);
        }
        if (e->location[0]) { strlcat(buf, " · ", sizeof(buf)); strlcat(buf, e->location, sizeof(buf)); }
        ui_label_w(s_list, F12, COL_MUTED, PAD + 10, y + 19, SCR_W - 2 * PAD - 10, buf);
        y += 40;
    }
    // Etwas Luft unter dem letzten Termin.
    ui_box(s_list, 0, y, 1, 4);
}
