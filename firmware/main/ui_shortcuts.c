// Shortcut deck: tiles defined in the companion's config.toml. The hub only
// knows how a tile looks; tapping one sends its index back to the PC.
#include <stdio.h>
#include <string.h>

#include "hub_server.h"
#include "icons.h"
#include "ui_internal.h"

#define GAP 14

static lv_obj_t *s_grid, *s_empty;
static int s_count;
static uint32_t s_lit;                       // tiles that are on (bit per tile)
static lv_obj_t *s_btn[HUB_MAX_TILES], *s_icon[HUB_MAX_TILES];
static lv_color_t s_tint[HUB_MAX_TILES];

// A lit tile is filled with its colour and gets a bright edge and a white icon.
static void apply_lit(void)
{
    for (int i = 0; i < s_count; i++) {
        bool on = s_lit & (1u << i);
        if (on) lv_obj_add_state(s_btn[i], LV_STATE_CHECKED);
        else lv_obj_remove_state(s_btn[i], LV_STATE_CHECKED);
        lv_obj_set_style_text_color(s_icon[i], on ? lv_color_white() : lv_color_lighten(s_tint[i], 140), 0);
    }
}

void shortcuts_set_lit(uint32_t mask)
{
    if (mask == s_lit) return;
    s_lit = mask;
    apply_lit();
}

static void tile_cb(lv_event_t *e)
{
    int id = (int)(intptr_t)lv_event_get_user_data(e);
    char buf[48];
    snprintf(buf, sizeof(buf), "{\"type\":\"shortcut\",\"id\":%d}", id);
    hub_server_send(buf);
}

void shortcuts_create(lv_obj_t *page)
{
    s_grid = lv_obj_create(page);
    lv_obj_remove_style_all(s_grid);
    lv_obj_set_size(s_grid, LV_PCT(100), LV_PCT(100));
    lv_obj_remove_flag(s_grid, LV_OBJ_FLAG_SCROLLABLE);

    s_empty = lv_obj_create(page);
    lv_obj_remove_style_all(s_empty);
    lv_obj_set_size(s_empty, LV_PCT(100), LV_PCT(100));
    lv_obj_t *icon = ui_label(s_empty, g_icon_80, COL_DIM, ICON_GRID_VIEW);
    lv_obj_align(icon, LV_ALIGN_CENTER, 0, -40);
    lv_obj_t *msg = ui_label(s_empty, g_font_24, COL_MUTED, "No shortcuts yet");
    lv_obj_align(msg, LV_ALIGN_CENTER, 0, 24);
    lv_obj_t *sub = ui_label(s_empty, g_font_16, COL_DIM, "Start the companion app on your PC");
    lv_obj_align(sub, LV_ALIGN_CENTER, 0, 56);
}

void shortcuts_refresh(const hub_tile_t *tiles, int n)
{
    lv_obj_clean(s_grid);
    s_count = n;
    if (n == 0) {
        lv_obj_remove_flag(s_empty, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_add_flag(s_empty, LV_OBJ_FLAG_HIDDEN);

    int cols = n <= 4 ? 2 : n <= 6 ? 3 : 4;
    int rows = (n + cols - 1) / cols;
    const int W = CONTENT_W, H = CONTENT_H;
    int tw = (W - (cols - 1) * GAP) / cols;
    int th = (H - (rows - 1) * GAP) / rows;
    const lv_font_t *icon_font = th >= 140 ? g_icon_80 : g_icon_48;
    const lv_font_t *label_font = th >= 120 ? g_font_20 : g_font_16;

    for (int i = 0; i < n; i++) {
        const hub_tile_t *t = &tiles[i];
        lv_obj_t *b = lv_button_create(s_grid);
        lv_obj_remove_style_all(b);
        lv_obj_set_size(b, tw, th);
        lv_obj_set_pos(b, (i % cols) * (tw + GAP), (i / cols) * (th + GAP));
        lv_obj_set_style_radius(b, 16, 0);
        // Graphite tile: a plain card with the icon in the tile's colour. Pressing
        // tints it; a tile that is "on" (e.g. mic muted) fills with its colour.
        lv_color_t tint = lv_color_hex(t->color);
        lv_obj_set_style_bg_color(b, lv_color_hex(COL_CARD), 0);
        lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(b, lv_color_hex(COL_BORDER), 0);
        lv_obj_set_style_border_width(b, 1, 0);
        lv_obj_set_style_bg_color(b, lv_color_mix(tint, lv_color_hex(COL_CARD), 90), LV_STATE_PRESSED);
        lv_obj_set_style_bg_color(b, lv_color_darken(tint, 40), LV_STATE_CHECKED);
        lv_obj_set_style_border_color(b, lv_color_lighten(tint, 120), LV_STATE_CHECKED);
        lv_obj_set_style_border_width(b, 2, LV_STATE_CHECKED);
        lv_obj_set_style_border_opa(b, LV_OPA_COVER, LV_STATE_CHECKED);
        lv_obj_set_style_opa(b, LV_OPA_40, LV_STATE_DISABLED);
        lv_obj_set_style_transform_scale(b, 240, LV_STATE_PRESSED);
        lv_obj_set_style_transform_pivot_x(b, tw / 2, 0);
        lv_obj_set_style_transform_pivot_y(b, th / 2, 0);
        lv_obj_add_event_cb(b, tile_cb, LV_EVENT_CLICKED, (void *)(intptr_t)i);

        char glyph[5];
        lv_obj_t *ic = ui_label(b, icon_font, COL_TEXT, ui_icon_by_name(t->icon, glyph));
        lv_obj_set_style_text_color(ic, lv_color_lighten(tint, 140), 0);
        lv_obj_align(ic, LV_ALIGN_CENTER, 0, -16);
        lv_obj_t *lb = ui_label(b, label_font, COL_TEXT, t->label);
        lv_label_set_long_mode(lb, LV_LABEL_LONG_DOT);
        lv_obj_set_width(lb, tw - 16);
        lv_obj_set_style_text_align(lb, LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_align(lb, LV_ALIGN_BOTTOM_MID, 0, -14);
        if (!g_pc_online) lv_obj_add_state(b, LV_STATE_DISABLED);
        s_btn[i] = b;
        s_icon[i] = ic;
        s_tint[i] = tint;
    }
    apply_lit();
}

void shortcuts_set_online(bool online)
{
    uint32_t n = lv_obj_get_child_count(s_grid);
    for (uint32_t i = 0; i < n; i++) {
        lv_obj_t *b = lv_obj_get_child(s_grid, i);
        if (online) lv_obj_remove_state(b, LV_STATE_DISABLED);
        else lv_obj_add_state(b, LV_STATE_DISABLED);
    }
}
