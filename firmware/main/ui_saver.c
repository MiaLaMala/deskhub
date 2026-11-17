// Screensaver shown while the PC's display is asleep: a large, dim clock with the
// date under it on black. It moves to a new spot each minute, and a tap hides it.
#include <stdio.h>
#include <string.h>
#include "esp_random.h"
#include "ui.h"
#include "ui_internal.h"

static lv_obj_t *s_root, *s_box, *s_time, *s_sub;
static lv_timer_t *s_timer;
static int s_last_min = -1;

static void place(void)
{
    lv_obj_update_layout(s_box);
    int w = lv_obj_get_width(s_box), h = lv_obj_get_height(s_box);
    int room_x = 800 - 40 - w, room_y = 480 - 40 - h;
    int x = 20 + (room_x > 0 ? (int)(esp_random() % (uint32_t)room_x) : 0);
    int y = 20 + (room_y > 0 ? (int)(esp_random() % (uint32_t)room_y) : 0);
    lv_obj_set_pos(s_box, x, y);
}

static void update(lv_timer_t *t)
{
    time_t now = time(NULL);
    struct tm tm;
    localtime_r(&now, &tm);
    if (tm.tm_min == s_last_min) return;
    s_last_min = tm.tm_min;
    if (tm.tm_year < 120) {  // clock not set yet
        lv_label_set_text(s_time, "--:--");
        lv_label_set_text(s_sub, "");
    } else {
        char clock[16], sub[64], date[40];
        ui_fmt_clock(clock, sizeof(clock), now);
        // "3:05 PM": the digits go big, AM/PM joins the date line.
        char *sp = strchr(clock, ' ');
        const char *ampm = "";
        if (sp) { *sp = '\0'; ampm = sp + 1; }
        strftime(date, sizeof(date), "%A, %B ", &tm);
        snprintf(sub, sizeof(sub), "%s%d%s%s", date, tm.tm_mday, *ampm ? "  \xE2\x80\xA2  " : "", ampm);
        lv_label_set_text(s_time, clock);
        lv_label_set_text(s_sub, sub);
    }
    place();
}

static void tapped_cb(lv_event_t *e)
{
    ui_saver_show(false);
}

bool ui_saver_shown(void)
{
    return s_root && !lv_obj_has_flag(s_root, LV_OBJ_FLAG_HIDDEN);
}

void ui_saver_show(bool on)
{
    if (!s_root) {
        if (!on) return;
        s_root = lv_obj_create(lv_layer_top());
        lv_obj_remove_style_all(s_root);
        lv_obj_set_size(s_root, 800, 480);
        lv_obj_set_style_bg_color(s_root, lv_color_black(), 0);
        lv_obj_set_style_bg_opa(s_root, LV_OPA_COVER, 0);
        lv_obj_remove_flag(s_root, LV_OBJ_FLAG_SCROLLABLE);
        lv_obj_add_flag(s_root, LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_event_cb(s_root, tapped_cb, LV_EVENT_CLICKED, NULL);
        s_box = lv_obj_create(s_root);
        lv_obj_remove_style_all(s_box);
        lv_obj_set_size(s_box, LV_SIZE_CONTENT, LV_SIZE_CONTENT);
        lv_obj_set_flex_flow(s_box, LV_FLEX_FLOW_COLUMN);
        lv_obj_set_flex_align(s_box, LV_FLEX_ALIGN_START, LV_FLEX_ALIGN_CENTER, LV_FLEX_ALIGN_CENTER);
        lv_obj_remove_flag(s_box, LV_OBJ_FLAG_CLICKABLE | LV_OBJ_FLAG_SCROLLABLE);
        s_time = ui_label(s_box, g_font_clock, COL_MUTED, "");
        s_sub = ui_label(s_box, &lv_font_montserrat_24, COL_DIM, "");
        s_timer = lv_timer_create(update, 2000, NULL);
        lv_timer_pause(s_timer);
    }
    if (on == ui_saver_shown()) return;
    if (on) {
        lv_obj_remove_flag(s_root, LV_OBJ_FLAG_HIDDEN);
        lv_obj_move_foreground(s_root);
        s_last_min = -1;
        update(NULL);
        lv_timer_resume(s_timer);
    } else {
        lv_obj_add_flag(s_root, LV_OBJ_FLAG_HIDDEN);
        lv_timer_pause(s_timer);
    }
}
