// Kalender: Termine nach Tag gruppiert. Es werden nur die Zeilen gebaut, die ganz
// ins Fenster passen (nie eine halbe Zeile); senkrechtes Wischen blaettert und rastet
// dabei auf ganze Zeilen ein: nach oben wischen = die erste nicht mehr sichtbare Zeile
// kommt nach oben. "+N weitere" zaehlt die Termine darunter.
// Warum kein LVGL-Scrollen: mit 16 Terminen als Objekten reicht der LVGL-Speicher
// (44 KB, ohne PSRAM) nicht sicher; so stehen hoechstens ~5 Zeilen im Speicher.
// Waagrechtes Wischen bleibt beim Bildschirm (Seitenwechsel, siehe ui.c gesture_cb).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ui_internal.h"

static lv_obj_t *s_list, *s_empty, *s_more, *s_above;
static hub_event_t s_ev[HUB_MAX_EVENTS];
static int s_n, s_off;

#define LIST_Y (HDR_H + 2)
#define MORE_H 16                                    // Zeile fuer "+N weitere"
#define VIEW_H (PAGE_H - LIST_Y - 10 - MORE_H)       // 10 px Luft zur Navigationsleiste
#define DAY_H 22                                     // Tageszeile
#define ROW_H 40                                     // Termin (Titel + Zeit/Ort)
#define ROW_VIS 35                                   // davon sichtbar belegt

static long day_of(const hub_event_t *e, time_t now)
{
    time_t t = e->start < now ? now : e->start;   // Ganztaegiges, das schon laeuft: heute
    return ui_days_between(now, t);
}

// Wie viele Zeilen ab start passen ganz ins Fenster? Die erste Zeile traegt immer
// ihre Tageszeile (sonst fehlt beim Blaettern der Bezug).
static int fit_from(int start, time_t now)
{
    int y = 0, k = 0;
    long last = -9999;
    for (int i = start; i < s_n; i++) {
        long d = day_of(&s_ev[i], now);
        int need = (d != last ? DAY_H : 0) + ROW_VIS;
        if (y + need > VIEW_H) break;
        y += need - ROW_VIS + ROW_H;
        last = d;
        k++;
    }
    return k > 0 ? k : (start < s_n ? 1 : 0);
}

void calendar_create(lv_obj_t *p)
{
    ui_header(p, "Kalender", COL_TEXT);
    s_off = 0;   // beim Oeffnen der Seite oben anfangen
    s_list = ui_box(p, 0, LIST_Y, SCR_W, VIEW_H);
    lv_obj_add_flag(s_list, LV_OBJ_FLAG_GESTURE_BUBBLE);
    s_above = ui_label(p, F12, COL_MUTED, "");
    lv_obj_align(s_above, LV_ALIGN_TOP_LEFT, PAD, LIST_Y + VIEW_H);
    s_more = ui_label(p, F12, COL_MUTED, "");
    lv_obj_align(s_more, LV_ALIGN_TOP_RIGHT, -PAD, LIST_Y + VIEW_H);
    s_empty = ui_label(p, F14, COL_MUTED, "");
    lv_obj_align(s_empty, LV_ALIGN_CENTER, 0, 10);
}

static void build(void)
{
    lv_obj_clean(s_list);
    time_t now = plat_now();
    if (s_off > s_n - 1) s_off = s_n > 0 ? s_n - 1 : 0;
    int k = fit_from(s_off, now), y = 0;
    long last_day = -9999;
    char buf[96], hm[8], hm2[8];
    for (int i = s_off; i < s_off + k; i++) {
        const hub_event_t *e = &s_ev[i];
        long d = day_of(e, now);
        if (d != last_day) {
            last_day = d;
            ui_fmt_day_title(buf, sizeof(buf), e->start < now ? now : e->start);
            ui_label_at(s_list, F12, d == 0 ? COL_ACCENT : COL_MUTED, PAD, y + 4, buf);
            y += DAY_H;
        }
        lv_obj_t *strip = ui_box(s_list, PAD, y + 2, 3, 32);
        lv_obj_set_style_bg_opa(strip, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(strip, lv_color_hex(e->color), 0);
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
    int below = s_n - (s_off + k);
    if (below > 0) {
        snprintf(buf, sizeof(buf), "+%d weitere", below);
        lv_label_set_text(s_more, buf);
        lv_obj_remove_flag(s_more, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_more, LV_OBJ_FLAG_HIDDEN);
    }
    if (s_off > 0) {
        snprintf(buf, sizeof(buf), "%d davor", s_off);
        lv_label_set_text(s_above, buf);
        lv_obj_remove_flag(s_above, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(s_above, LV_OBJ_FLAG_HIDDEN);
    }
}

// Senkrechtes Wischen (aus ui.c): dir > 0 = weiter (nach oben gewischt), < 0 = zurueck.
void calendar_page(int dir)
{
    time_t now = plat_now();
    if (dir > 0) {
        int k = fit_from(s_off, now);
        if (s_off + k >= s_n) return;
        s_off += k;
    } else {
        if (s_off == 0) return;
        // Frueheste Startzeile, von der aus alles bis vor s_off passt.
        int start = s_off - 1;
        while (start > 0 && start - 1 + fit_from(start - 1, now) >= s_off) start--;
        s_off = start;
    }
    build();
}

void ui_calendar_debug_scroll(int rows)
{
    s_off = rows < 0 ? 0 : rows;
    build();
}

static int cmp_ev(const void *a, const void *b)
{
    const hub_event_t *x = a, *y = b;
    if (x->start != y->start) return x->start < y->start ? -1 : 1;
    return (int)y->all_day - (int)x->all_day;
}

void calendar_refresh(void)
{
    time_t now = plat_now();
    s_n = 0;
    for (int i = 0; i < g_event_count; i++) {
        time_t end = g_events[i].end ? g_events[i].end : g_events[i].start;
        if (end > now) s_ev[s_n++] = g_events[i];
    }
    qsort(s_ev, s_n, sizeof(s_ev[0]), cmp_ev);
    if (!s_n) {
        lv_obj_clean(s_list);
        lv_obj_add_flag(s_more, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_above, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(s_empty, g_rx[P_CALENDAR] ? "Keine Termine in nächster Zeit" : "Termine kommen vom Begleiter");
        lv_obj_remove_flag(s_empty, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_add_flag(s_empty, LV_OBJ_FLAG_HIDDEN);
    build();
}
