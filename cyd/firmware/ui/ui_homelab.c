// Homelab: Dienste oben / gesamt und die Liste der ausgefallenen mit "seit".
// ok:false heisst: Quelle nicht erreichbar, dann bleibt der letzte Stand mit Uhrzeit.
#include <stdio.h>
#include <string.h>

#include "ui_internal.h"

static lv_obj_t *s_big, *s_sub, *s_state, *s_list, *s_none;

void homelab_create(lv_obj_t *p)
{
    ui_header(p, "Homelab", COL_TEXT);
    s_big = ui_label_at(p, F48, COL_TEXT, PAD, 24, "");
    s_sub = ui_label_at(p, F14, COL_MUTED, 170, 34, "Dienste oben");
    s_state = ui_label_w(p, F16, COL_GOOD, 170, 54, SCR_W - 170 - PAD, "");
    s_list = lv_obj_create(p);
    lv_obj_set_pos(s_list, 0, 84);
    lv_obj_set_size(s_list, SCR_W, PAGE_H - 84);
    lv_obj_set_scroll_dir(s_list, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(s_list, LV_SCROLLBAR_MODE_OFF);
    lv_obj_remove_flag(s_list, LV_OBJ_FLAG_SCROLL_ELASTIC | LV_OBJ_FLAG_SCROLL_MOMENTUM);
    lv_obj_add_flag(s_list, LV_OBJ_FLAG_GESTURE_BUBBLE);
    s_none = ui_label(p, F14, COL_MUTED, "Homelab kommt vom Begleiter");
    lv_obj_align(s_none, LV_ALIGN_CENTER, 0, 0);
}

void homelab_refresh(void)
{
    const hub_homelab_t *h = &g_homelab;
    char buf[48];
    lv_obj_clean(s_list);
    bool v = h->valid;
    lv_obj_t *o[] = {s_big, s_sub, s_state, s_list};
    for (int i = 0; i < 4; i++) { if (v) lv_obj_remove_flag(o[i], LV_OBJ_FLAG_HIDDEN); else lv_obj_add_flag(o[i], LV_OBJ_FLAG_HIDDEN); }
    if (v) lv_obj_add_flag(s_none, LV_OBJ_FLAG_HIDDEN);
    else { lv_obj_remove_flag(s_none, LV_OBJ_FLAG_HIDDEN); return; }

    snprintf(buf, sizeof(buf), "%d/%d", h->up, h->total);
    lv_label_set_text(s_big, buf);
    int down = h->total - h->up;
    if (down < h->down_count) down = h->down_count;
    bool bad = down > 0;
    lv_obj_set_style_text_color(s_big, lv_color_hex(!h->ok ? COL_MUTED : bad ? COL_BAD : COL_TEXT), 0);
    if (!h->ok) {
        lv_label_set_text(s_state, "Quelle offline");
        lv_obj_set_style_text_color(s_state, lv_color_hex(COL_WARN), 0);
    } else if (!bad) {
        lv_label_set_text(s_state, "Alles läuft");
        lv_obj_set_style_text_color(s_state, lv_color_hex(COL_GOOD), 0);
    } else {
        snprintf(buf, sizeof(buf), down == 1 ? "%d ausgefallen" : "%d ausgefallen", down);
        lv_label_set_text(s_state, buf);
        lv_obj_set_style_text_color(s_state, lv_color_hex(COL_BAD), 0);
    }
    lv_obj_t *sep = ui_box(s_list, PAD, 0, SCR_W - 2 * PAD, 1);
    lv_obj_set_style_bg_opa(sep, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(sep, lv_color_hex(COL_BORDER), 0);
    int y = 6;
    for (int i = 0; i < h->down_count; i++) {
        lv_obj_t *d = ui_box(s_list, PAD + 2, y + 6, 8, 8);
        lv_obj_set_style_radius(d, 4, 0);
        lv_obj_set_style_bg_opa(d, LV_OPA_COVER, 0);
        lv_obj_set_style_bg_color(d, lv_color_hex(h->ok ? COL_BAD : COL_DIM), 0);
        buf[0] = 0;
        if (h->down_since[i]) ui_fmt_since(buf, sizeof(buf), h->down_since[i]);
        lv_obj_t *s = ui_label(s_list, F12, COL_MUTED, buf);
        lv_obj_align(s, LV_ALIGN_TOP_RIGHT, -PAD, y + 3);
        int sw = lv_text_get_width(buf, strlen(buf), F12, 0);
        ui_label_w(s_list, F14, COL_TEXT, PAD + 18, y + 1, SCR_W - 2 * PAD - 18 - sw - 8, h->down_name[i]);
        y += 26;
    }
    if (h->down_count == 0 && h->ok && !bad)
        ui_label_at(s_list, F12, COL_DIM, PAD, y + 2, "Kein Dienst ausgefallen.");
}
