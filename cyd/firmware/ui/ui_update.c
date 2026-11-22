// Firmware-Update: "Firmware-Update installieren?" mit Ablehnen / Installieren,
// danach ein Fortschrittsbalken. Liegt ueber allem (lv_layer_top).
#include <stdio.h>

#include "ui_internal.h"

static lv_obj_t *s_root, *s_title, *s_sub, *s_btns, *s_bar;

static void answer_cb(lv_event_t *e)
{
    bool allow = (bool)(intptr_t)lv_event_get_user_data(e);
    plat_ota_answer(allow);
    lv_obj_add_flag(s_btns, LV_OBJ_FLAG_HIDDEN);
    lv_label_set_text(s_sub, allow ? "Startet ..." : "Nicht installiert.");
}

static void build(void)
{
    s_root = ui_box(lv_layer_top(), 0, 0, SCR_W, SCR_H);
    lv_obj_add_flag(s_root, LV_OBJ_FLAG_CLICKABLE);   // nichts dahinter reagiert
    lv_obj_set_style_bg_opa(s_root, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(s_root, lv_color_hex(COL_BG), 0);
    lv_obj_t *i = ui_label(s_root, &icons_36, COL_ACCENT, ICON_SYSTEM_UPDATE);
    lv_obj_align(i, LV_ALIGN_TOP_MID, 0, 22);
    s_title = ui_label(s_root, F20, COL_TEXT, "");
    lv_obj_align(s_title, LV_ALIGN_TOP_MID, 0, 70);
    s_sub = ui_label(s_root, F14, COL_MUTED, "");
    lv_obj_set_width(s_sub, SCR_W - 4 * PAD);
    lv_obj_set_style_text_align(s_sub, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(s_sub, LV_ALIGN_TOP_MID, 0, 102);
    s_bar = ui_bar(s_root, 3 * PAD, 150, SCR_W - 6 * PAD, 10, COL_ACCENT, COL_CARD_HI);
    s_btns = ui_box(s_root, 0, 176, SCR_W, 48);
    const int bw = (SCR_W - 2 * 12 - 12) / 2;
    ui_button(s_btns, 12, 0, bw, 48, "Ablehnen", false, answer_cb, (void *)(intptr_t)0);
    ui_button(s_btns, 12 + bw + 12, 0, bw, 48, "Installieren", true, answer_cb, (void *)(intptr_t)1);
}

void ui_update_show(void)
{
    if (!s_root) build();
    lv_label_set_text(s_title, "Firmware-Update installieren?");
    lv_label_set_text(s_sub, "Der Begleiter hat eine neue\nVersion geschickt.");
    lv_obj_remove_flag(s_btns, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_bar, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_root);
}

void ui_update_progress(int pct)
{
    if (!s_root) return;
    char buf[40];
    snprintf(buf, sizeof(buf), "Installiere ... %d %%", pct);
    lv_label_set_text(s_title, "Update läuft");
    lv_label_set_text(s_sub, buf);
    lv_obj_add_flag(s_btns, LV_OBJ_FLAG_HIDDEN);
    lv_obj_remove_flag(s_bar, LV_OBJ_FLAG_HIDDEN);
    lv_bar_set_value(s_bar, pct, LV_ANIM_OFF);
}

void ui_update_message(const char *text)
{
    if (!s_root) return;
    lv_label_set_text(s_sub, text);
    lv_obj_add_flag(s_btns, LV_OBJ_FLAG_HIDDEN);
}

void ui_update_hide(void)
{
    if (s_root) lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}
