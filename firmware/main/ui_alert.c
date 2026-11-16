// Full-screen "an agent is waiting for you" alert, drawn on the top layer so it
// covers whatever page is showing. The companion sends {"type":"alert",...} when
// a Claude Code session needs a permission approval or a reply, and
// {"type":"alert","clear":true} once nothing is waiting.
#include <stdio.h>
#include <string.h>

#include "display.h"
#include "hub_server.h"
#include "icons.h"
#include "ui.h"
#include "ui_internal.h"

static lv_obj_t *s_root, *s_logo, *s_kind, *s_title, *s_detail, *s_project;
static char s_id[64];

static void send_action(const char *action)
{
    char buf[128];
    snprintf(buf, sizeof(buf), "{\"type\":\"alert_action\",\"id\":\"%s\",\"action\":\"%s\"}", s_id, action);
    hub_server_send(buf);
}

static void hide(void)
{
    if (s_root) lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    s_id[0] = 0;
}

static void on_focus(lv_event_t *e)
{
    (void)e;
    send_action("focus");
    hide();
}

static void on_dismiss(lv_event_t *e)
{
    (void)e;
    send_action("dismiss");
    hide();
}

static lv_obj_t *pill_button(lv_obj_t *parent, const char *text, uint32_t bg, uint32_t fg, lv_event_cb_t cb)
{
    lv_obj_t *b = lv_button_create(parent);
    lv_obj_remove_style_all(b);
    lv_obj_set_size(b, 236, 64);
    lv_obj_set_style_radius(b, 32, 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(bg), 0);
    lv_obj_set_style_bg_opa(b, LV_OPA_COVER, 0);
    lv_obj_set_style_border_color(b, lv_color_hex(COL_BORDER), 0);
    lv_obj_set_style_border_width(b, bg == COL_CARD_HI ? 1 : 0, 0);
    lv_obj_set_style_bg_color(b, lv_color_hex(COL_ACCENT2), LV_STATE_PRESSED);
    lv_obj_set_ext_click_area(b, 8);
    lv_obj_t *l = ui_label(b, &lv_font_montserrat_24, fg, text);
    lv_obj_center(l);
    lv_obj_add_event_cb(b, cb, LV_EVENT_CLICKED, NULL);
    return b;
}

static void build(void)
{
    // Opaque backdrop: cheaper to redraw than a translucent dim over the page.
    s_root = lv_obj_create(lv_layer_top());
    lv_obj_remove_style_all(s_root);
    lv_obj_set_size(s_root, 800, 480);
    lv_obj_set_style_bg_color(s_root, lv_color_hex(COL_BG), 0);
    lv_obj_set_style_bg_opa(s_root, LV_OPA_COVER, 0);
    lv_obj_add_flag(s_root, LV_OBJ_FLAG_CLICKABLE);   // swallow taps meant for the page below
    lv_obj_remove_flag(s_root, LV_OBJ_FLAG_SCROLLABLE);

    lv_obj_t *card = ui_card(s_root);
    lv_obj_set_size(card, 680, 400);
    lv_obj_center(card);
    lv_obj_set_style_border_color(card, lv_color_hex(COL_ACCENT), 0);
    lv_obj_set_style_border_width(card, 2, 0);
    lv_obj_set_style_pad_all(card, 32, 0);

    // Logo badge and a small "needs permission" / "waiting" caption.
    lv_obj_t *badge = lv_obj_create(card);
    lv_obj_remove_style_all(badge);
    lv_obj_set_size(badge, 64, 64);
    lv_obj_set_style_radius(badge, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_color(badge, lv_color_hex(COL_CARD_HI), 0);
    lv_obj_set_style_bg_opa(badge, LV_OPA_COVER, 0);
    lv_obj_align(badge, LV_ALIGN_TOP_LEFT, 0, 0);
    s_logo = lv_image_create(badge);
    lv_image_set_src(s_logo, ui_agent_logo(32));
    lv_obj_center(s_logo);

    s_kind = ui_caption(card, "");
    lv_obj_align_to(s_kind, badge, LV_ALIGN_OUT_RIGHT_TOP, 20, 4);
    s_project = ui_label(card, &lv_font_montserrat_20, COL_TEXT, "");
    lv_obj_set_width(s_project, 520);
    lv_label_set_long_mode(s_project, LV_LABEL_LONG_DOT);
    lv_obj_align_to(s_project, badge, LV_ALIGN_OUT_RIGHT_BOTTOM, 20, -4);

    s_title = ui_label(card, &lv_font_montserrat_32, COL_TEXT, "");
    lv_obj_set_width(s_title, 612);
    lv_label_set_long_mode(s_title, LV_LABEL_LONG_DOT);
    lv_obj_align(s_title, LV_ALIGN_TOP_LEFT, 0, 96);

    s_detail = ui_label(card, &lv_font_montserrat_24, COL_MUTED, "");
    lv_obj_set_width(s_detail, 612);
    lv_obj_set_height(s_detail, 64);
    lv_label_set_long_mode(s_detail, LV_LABEL_LONG_DOT);
    lv_obj_align(s_detail, LV_ALIGN_TOP_LEFT, 0, 148);

    lv_obj_t *show = pill_button(card, "Show on PC", COL_ACCENT, COL_BG, on_focus);
    lv_obj_align(show, LV_ALIGN_BOTTOM_RIGHT, 0, 0);
    lv_obj_t *later = pill_button(card, "Not now", COL_CARD_HI, COL_TEXT, on_dismiss);
    lv_obj_align(later, LV_ALIGN_BOTTOM_LEFT, 0, 0);
}

void ui_set_alert(const hub_alert_t *a)
{
    if (!a->active) {
        hide();
        return;
    }
    if (!s_root) build();
    bool is_new = strcmp(s_id, a->id) != 0 || lv_obj_has_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    strlcpy(s_id, a->id, sizeof(s_id));

    bool perm = strcmp(a->kind, "permission") == 0;
    lv_label_set_text(s_kind, perm ? "NEEDS PERMISSION" : "WAITING FOR YOU");
    lv_obj_set_style_text_color(s_kind, lv_color_hex(perm ? COL_WARN : COL_ACCENT), 0);
    lv_label_set_text(s_title, a->title[0] ? a->title : "Claude is waiting for you");
    lv_label_set_text(s_detail, a->detail);
    lv_label_set_text(s_project, a->project);
    lv_image_set_src(s_logo, ui_agent_logo(32));

    lv_obj_remove_flag(s_root, LV_OBJ_FLAG_HIDDEN);
    lv_obj_move_foreground(s_root);
    if (is_new) display_wake();
}
