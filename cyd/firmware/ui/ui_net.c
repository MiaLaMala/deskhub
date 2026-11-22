// Netz: Latenz, Verlust, Verlauf der letzten Messungen (Leitung des Pi).
#include <stdio.h>
#include <string.h>

#include "ui_internal.h"

static lv_obj_t *s_lat, *s_unit, *s_state, *s_loss, *s_jit, *s_graph, *s_cap, *s_drop, *s_none;

static void graph_draw_cb(lv_event_t *e)
{
    lv_obj_t *o = lv_event_get_target(e);
    lv_layer_t *layer = lv_event_get_layer(e);
    const hub_net_t *n = &g_net;
    lv_area_t a;
    lv_obj_get_coords(o, &a);
    int w = lv_area_get_width(&a), h = lv_area_get_height(&a);
    int step = w / HUB_NET_HIST;   // 5 px
    int maxv = 20;
    for (int i = 0; i < n->hist_count; i++) if (n->hist[i] > maxv) maxv = n->hist[i];
    lv_draw_rect_dsc_t d;
    lv_draw_rect_dsc_init(&d);
    d.bg_opa = LV_OPA_COVER;
    d.bg_color = lv_color_hex(COL_BORDER);
    lv_area_t base = {a.x1, a.y2, a.x2, a.y2};
    lv_draw_rect(layer, &d, &base);
    int x0 = a.x2 + 1 - n->hist_count * step;
    for (int i = 0; i < n->hist_count; i++) {
        int v = n->hist[i];
        lv_area_t r;
        r.x1 = x0 + i * step;
        r.x2 = r.x1 + step - 2;
        if (v < 0) {   // verloren: rote Saeule ueber die ganze Hoehe
            r.y1 = a.y1;
            r.y2 = a.y2 - 1;
            d.bg_color = lv_color_hex(0x9a3c3c);
            lv_draw_rect(layer, &d, &r);
            continue;
        }
        int bh = v * (h - 2) / maxv;
        if (bh < 1) bh = 1;
        r.y1 = a.y2 - bh;
        r.y2 = a.y2 - 1;
        d.bg_color = lv_color_hex(v > 100 ? COL_WARN : COL_BLUE);
        lv_draw_rect(layer, &d, &r);
    }
}

void net_create(lv_obj_t *p)
{
    ui_header(p, "Netz", COL_TEXT);
    s_lat = ui_label_at(p, F48, COL_TEXT, PAD, 24, "");
    // "ms" auf derselben Grundlinie wie die grosse Zahl.
    s_unit = ui_label_at(p, F16, COL_MUTED, PAD,
                         24 + (F48->line_height - F48->base_line) - (F16->line_height - F16->base_line), "ms");
    s_state = ui_label_w(p, F16, COL_GOOD, 180, 26, SCR_W - 180 - PAD, "");
    s_loss = ui_label_w(p, F14, COL_TEXT, 180, 47, SCR_W - 180 - PAD, "");
    s_jit = ui_label_w(p, F12, COL_MUTED, 180, 66, SCR_W - 180 - PAD, "");
    s_cap = ui_label_at(p, F12, COL_MUTED, PAD, 88, "Latenz, letzte Messungen");
    s_graph = ui_box(p, PAD, 108, (SCR_W - 2 * PAD) / HUB_NET_HIST * HUB_NET_HIST, 58);
    lv_obj_add_event_cb(s_graph, graph_draw_cb, LV_EVENT_DRAW_MAIN, NULL);
    s_drop = ui_label_w(p, F12, COL_MUTED, PAD, 175, SCR_W - 2 * PAD, "");
    s_none = ui_label(p, F14, COL_MUTED, "Netzdaten kommen vom Begleiter");
    lv_obj_align(s_none, LV_ALIGN_CENTER, 0, 0);
}

void net_refresh(void)
{
    const hub_net_t *n = &g_net;
    char buf[80], w[24];
    lv_obj_t *o[] = {s_lat, s_unit, s_state, s_loss, s_jit, s_graph, s_cap, s_drop};
    for (size_t i = 0; i < sizeof(o) / sizeof(o[0]); i++) {
        if (n->valid) lv_obj_remove_flag(o[i], LV_OBJ_FLAG_HIDDEN);
        else lv_obj_add_flag(o[i], LV_OBJ_FLAG_HIDDEN);
    }
    if (n->valid) lv_obj_add_flag(s_none, LV_OBJ_FLAG_HIDDEN);
    else { lv_obj_remove_flag(s_none, LV_OBJ_FLAG_HIDDEN); return; }

    if (n->latency_ms >= 0 && n->online) snprintf(buf, sizeof(buf), "%d", (int)(n->latency_ms + 0.5f));
    else strlcpy(buf, "–", sizeof(buf));
    if (!(n->latency_ms >= 0 && n->online)) strlcpy(buf, "-", sizeof(buf));
    lv_label_set_text(s_lat, buf);
    int lw = lv_text_get_width(buf, strlen(buf), F48, 0);
    lv_obj_set_x(s_unit, PAD + lw + 6);
    lv_obj_set_style_text_color(s_lat, lv_color_hex(!n->online ? COL_BAD : n->latency_ms > 100 ? COL_WARN : COL_TEXT), 0);

    if (n->online) {
        if (n->up_since) { ui_fmt_since(w, sizeof(w), n->up_since); snprintf(buf, sizeof(buf), "Online %s", w); }
        else strlcpy(buf, "Online", sizeof(buf));
        lv_label_set_text(s_state, buf);
        lv_obj_set_style_text_color(s_state, lv_color_hex(COL_GOOD), 0);
    } else {
        lv_label_set_text(s_state, "Offline");
        lv_obj_set_style_text_color(s_state, lv_color_hex(COL_BAD), 0);
    }
    snprintf(buf, sizeof(buf), "Verlust %d %%", n->loss_pct);
    lv_label_set_text(s_loss, buf);
    lv_obj_set_style_text_color(s_loss, lv_color_hex(n->loss_pct > 0 ? COL_WARN : COL_TEXT), 0);
    snprintf(buf, sizeof(buf), "Jitter %d ms", (int)(n->jitter_ms + 0.5f));
    lv_label_set_text(s_jit, buf);
    lv_obj_invalidate(s_graph);

    if (n->drop_at) {
        ui_fmt_when(w, sizeof(w), n->drop_at);
        int s = n->drop_dur_s;
        if (s >= 3600) snprintf(buf, sizeof(buf), "Letzter Ausfall: %s, %d h %d min", w, s / 3600, (s / 60) % 60);
        else if (s >= 60) snprintf(buf, sizeof(buf), "Letzter Ausfall: %s, %d min", w, s / 60);
        else snprintf(buf, sizeof(buf), "Letzter Ausfall: %s, %d s", w, s);
    } else {
        strlcpy(buf, "Kein Ausfall gesehen", sizeof(buf));
    }
    lv_label_set_text(s_drop, buf);
}
