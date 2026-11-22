// Kalender: Termine nach Tag gruppiert. Nur ganze Zeilen; passt nicht alles,
// steht unten "+N weitere" (resistiver Touch: kein Scrollen noetig).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ui_internal.h"

static lv_obj_t *s_list, *s_empty;

#define LIST_Y (HDR_H + 2)
#define LIST_H (PAGE_H - LIST_Y - 10)   // 10 px Luft zur Navigationsleiste
#define DAY_H 22                         // Tageszeile
#define ROW_H 40                         // Termin (Titel + Zeit/Ort)
#define ROW_VIS 35                       // davon sichtbar belegt
#define MORE_H 16                        // "+N weitere"

void calendar_create(lv_obj_t *p)
{
    ui_header(p, "Kalender", COL_TEXT);
    s_list = ui_box(p, 0, LIST_Y, SCR_W, LIST_H);
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
    int shown = 0;
    for (int i = 0; i < n; i++) {
        const hub_event_t *e = &ev[i];
        // Ganztägiges, das schon läuft, steht unter heute.
        time_t day_t = e->start < now ? now : e->start;
        long d = ui_days_between(now, day_t);
        // Passt der Termin (mit Tageszeile) noch ganz? Fuer die letzten Termine
        // braucht es keinen Platz fuer den Hinweis.
        int need = (d != last_day ? DAY_H : 0) + ROW_VIS;
        int room = LIST_H - (i == n - 1 ? 0 : MORE_H);
        if (y + need > room) break;
        shown++;
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
        y += ROW_H;
    }
    if (shown < n) {
        snprintf(buf, sizeof(buf), "+%d weitere", n - shown);
        lv_obj_t *m = ui_label(s_list, F12, COL_MUTED, buf);
        lv_obj_align(m, LV_ALIGN_BOTTOM_RIGHT, -PAD, 0);
    }
}
