// 3D printer (Bambu Lab): progress, temperatures and filament for the current print.
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "icons.h"
#include "ui_internal.h"

#define LEFT_W 300
#define RIGHT_X (LEFT_W + 12)
#define RIGHT_W (CONTENT_W - RIGHT_X)
#define SWATCH 30
// Card heights on the right; tighter above the bottom dock.
#define JOB_H (UI_COMPACT ? 96 : 112)
#define TEMPS_H (UI_COMPACT ? 104 : 120)
#define TEMPS_Y (56 + JOB_H + 12)
#define AMS_Y (TEMPS_Y + TEMPS_H + 12)

static lv_obj_t *s_body, *s_empty, *s_empty_sub;
static lv_obj_t *s_name, *s_chip, *s_chip_lbl, *s_count;
static lv_obj_t *s_arc, *s_pct, *s_remain, *s_eta, *s_layer, *s_error;
static lv_obj_t *s_file_cap, *s_file, *s_speed;
static lv_obj_t *s_temp_val[3], *s_temp_tgt[3];
static lv_obj_t *s_ams_card, *s_ams_dot[HUB_MAX_AMS], *s_ams_lbl[HUB_MAX_AMS], *s_ams_none;
static int s_user_sel = -1;  // printer picked by tapping the name; -1 = automatic

static const char *state_text(const char *s)
{
    if (!strcmp(s, "RUNNING")) return "Printing";
    if (!strcmp(s, "PREPARE")) return "Preparing";
    if (!strcmp(s, "SLICING")) return "Slicing";
    if (!strcmp(s, "PAUSE")) return "Paused";
    if (!strcmp(s, "FINISH")) return "Finished";
    if (!strcmp(s, "FAILED")) return "Failed";
    if (!strcmp(s, "IDLE")) return "Idle";
    if (!strcmp(s, "OFFLINE")) return "Offline";
    return s[0] ? s : "Unknown";
}

static uint32_t state_color(const char *s)
{
    if (!strcmp(s, "RUNNING") || !strcmp(s, "PREPARE") || !strcmp(s, "SLICING")) return COL_ACCENT;
    if (!strcmp(s, "PAUSE")) return COL_WARN;
    if (!strcmp(s, "FINISH")) return COL_GOOD;
    if (!strcmp(s, "FAILED")) return COL_BAD;
    return COL_DIM;
}

static bool is_active(const hub_printer_t *p)
{
    return !strcmp(p->state, "RUNNING") || !strcmp(p->state, "PAUSE") || !strcmp(p->state, "PREPARE");
}

static void next_cb(lv_event_t *e)
{
    if (g_printer_count < 2) return;
    int cur = s_user_sel >= 0 ? s_user_sel : 0;
    s_user_sel = (cur + 1) % g_printer_count;
    printer_refresh();
}

static void fmt_temp(char *buf, size_t n, float t)
{
    if (isnan(t)) snprintf(buf, n, "--");
    else snprintf(buf, n, "%d\xC2\xB0", (int)lroundf(t));
}

static void fmt_minutes(char *buf, size_t n, int m)
{
    if (m >= 60) snprintf(buf, n, "%dh %02dm left", m / 60, m % 60);
    else snprintf(buf, n, "%dm left", m);
}

void printer_create(lv_obj_t *page)
{
    s_body = lv_obj_create(page);
    lv_obj_remove_style_all(s_body);
    lv_obj_set_size(s_body, LV_PCT(100), LV_PCT(100));
    lv_obj_remove_flag(s_body, LV_OBJ_FLAG_SCROLLABLE);

    // Header: printer name (tap to switch printers), state chip, "1/2".
    s_name = ui_label(s_body, g_font_32, COL_TEXT, "");
    lv_obj_set_pos(s_name, 0, 0);
    lv_obj_add_flag(s_name, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_ext_click_area(s_name, 12);
    lv_obj_add_event_cb(s_name, next_cb, LV_EVENT_CLICKED, NULL);
    s_chip = lv_obj_create(s_body);
    lv_obj_remove_style_all(s_chip);
    lv_obj_set_size(s_chip, LV_SIZE_CONTENT, 28);
    lv_obj_set_style_radius(s_chip, LV_RADIUS_CIRCLE, 0);
    lv_obj_set_style_bg_opa(s_chip, LV_OPA_30, 0);
    lv_obj_set_style_pad_hor(s_chip, 12, 0);
    s_chip_lbl = ui_label(s_chip, g_font_16, COL_TEXT, "");
    lv_obj_center(s_chip_lbl);
    s_count = ui_label(s_body, g_font_16, COL_MUTED, "");
    lv_obj_align(s_count, LV_ALIGN_TOP_RIGHT, 0, 10);

    // Left: progress ring.
    lv_obj_t *left = ui_card(s_body);
    lv_obj_set_size(left, LEFT_W, CONTENT_H - 56);
    lv_obj_set_pos(left, 0, 56);
    s_arc = lv_arc_create(left);
    lv_obj_set_size(s_arc, UI_COMPACT ? 180 : 220, UI_COMPACT ? 180 : 220);
    lv_obj_align(s_arc, LV_ALIGN_TOP_MID, 0, 6);
    lv_arc_set_rotation(s_arc, 135);
    lv_arc_set_bg_angles(s_arc, 0, 270);
    lv_arc_set_range(s_arc, 0, 100);
    lv_obj_remove_style(s_arc, NULL, LV_PART_KNOB);
    lv_obj_remove_flag(s_arc, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_arc_width(s_arc, 16, LV_PART_MAIN);
    lv_obj_set_style_arc_width(s_arc, 16, LV_PART_INDICATOR);
    lv_obj_set_style_arc_rounded(s_arc, true, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(s_arc, lv_color_hex(COL_CARD_HI), LV_PART_MAIN);
    s_pct = ui_label(left, g_font_48, COL_TEXT, "");
    lv_obj_set_width(s_pct, 200);
    lv_obj_set_style_text_align(s_pct, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align_to(s_pct, s_arc, LV_ALIGN_CENTER, 0, -10);
    s_remain = ui_label(left, g_font_16, COL_MUTED, "");
    lv_obj_set_width(s_remain, 200);
    lv_obj_set_style_text_align(s_remain, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align_to(s_remain, s_arc, LV_ALIGN_CENTER, 0, 32);
    s_eta = ui_label(left, g_font_20, COL_TEXT, "");
    lv_obj_set_width(s_eta, LEFT_W - 32);
    lv_obj_set_style_text_align(s_eta, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(s_eta, LV_ALIGN_BOTTOM_MID, 0, -64);
    s_layer = ui_label(left, g_font_16, COL_MUTED, "");
    lv_obj_set_width(s_layer, LEFT_W - 32);
    lv_obj_set_style_text_align(s_layer, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(s_layer, LV_ALIGN_BOTTOM_MID, 0, -40);
    s_error = ui_label(left, g_font_14, COL_BAD, "");
    ui_marquee(s_error);
    lv_obj_set_width(s_error, LEFT_W - 32);
    lv_obj_set_style_text_align(s_error, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(s_error, LV_ALIGN_BOTTOM_MID, 0, 0);

    // Right top: the file being printed.
    lv_obj_t *job = ui_card(s_body);
    lv_obj_set_size(job, RIGHT_W, JOB_H);
    lv_obj_set_pos(job, RIGHT_X, 56);
    s_file_cap = ui_caption(job, "PRINTING");
    lv_obj_set_pos(s_file_cap, 0, 0);
    s_file = ui_label(job, g_font_24, COL_TEXT, "");
    ui_marquee(s_file);
    lv_obj_set_width(s_file, RIGHT_W - 32);
    lv_obj_set_pos(s_file, 0, UI_COMPACT ? 20 : 22);
    s_speed = ui_label(job, g_font_14, COL_MUTED, "");
    lv_obj_set_pos(s_speed, 0, UI_COMPACT ? 48 : 58);

    // Right middle: temperatures.
    lv_obj_t *temps = ui_card(s_body);
    lv_obj_set_size(temps, RIGHT_W, TEMPS_H);
    lv_obj_set_pos(temps, RIGHT_X, TEMPS_Y);
    static const char *names[3] = {"Nozzle", "Bed", "Chamber"};
    static const char *glyphs[3] = {ICON_LOCAL_FIRE, ICON_LAYERS, ICON_DEVICE_THERMOSTAT};
    static const uint32_t tints[3] = {COL_WARN, COL_ACCENT2, COL_CYAN};
    const int col = (RIGHT_W - 32) / 3;
    for (int i = 0; i < 3; i++) {
        lv_obj_t *ic = ui_label(temps, g_icon_24, tints[i], glyphs[i]);
        lv_obj_set_pos(ic, i * col, 0);
        lv_obj_t *nm = ui_label(temps, g_font_14, COL_MUTED, names[i]);
        lv_obj_set_pos(nm, i * col + 30, 4);
        s_temp_val[i] = ui_label(temps, g_font_32, COL_TEXT, "--");
        lv_obj_set_pos(s_temp_val[i], i * col, UI_COMPACT ? 24 : 32);
        s_temp_tgt[i] = ui_label(temps, g_font_14, COL_MUTED, "");
        lv_obj_set_pos(s_temp_tgt[i], i * col, UI_COMPACT ? 58 : 70);
    }

    // Right bottom: AMS filament slots.
    s_ams_card = ui_card(s_body);
    lv_obj_set_size(s_ams_card, RIGHT_W, CONTENT_H - AMS_Y);
    lv_obj_set_pos(s_ams_card, RIGHT_X, AMS_Y);
    lv_obj_t *cap = ui_caption(s_ams_card, "FILAMENT");
    lv_obj_set_pos(cap, 0, 0);
    const int step = (RIGHT_W - 32) / HUB_MAX_AMS;
    for (int i = 0; i < HUB_MAX_AMS; i++) {
        lv_obj_t *d = lv_obj_create(s_ams_card);
        lv_obj_remove_style_all(d);
        lv_obj_set_size(d, SWATCH, SWATCH);
        lv_obj_set_style_radius(d, LV_RADIUS_CIRCLE, 0);
        lv_obj_set_style_bg_opa(d, LV_OPA_COVER, 0);
        lv_obj_set_style_border_color(d, lv_color_hex(COL_TEXT), 0);
        lv_obj_set_style_outline_color(d, lv_color_hex(COL_ACCENT), 0);
        lv_obj_set_style_outline_pad(d, 3, 0);
        lv_obj_set_pos(d, i * step + (step - SWATCH) / 2, UI_COMPACT ? 22 : 26);
        s_ams_dot[i] = d;
        s_ams_lbl[i] = ui_label(s_ams_card, g_font_14, COL_MUTED, "");
        lv_label_set_long_mode(s_ams_lbl[i], LV_LABEL_LONG_CLIP);
        lv_obj_set_width(s_ams_lbl[i], step);
        lv_obj_set_style_text_align(s_ams_lbl[i], LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_pos(s_ams_lbl[i], i * step, 62);
            if (UI_COMPACT) lv_obj_add_flag(s_ams_lbl[i], LV_OBJ_FLAG_HIDDEN);   // no room for labels
    }
    s_ams_none = ui_label(s_ams_card, g_font_16, COL_DIM, "No AMS data");
    lv_obj_set_pos(s_ams_none, 0, 32);

    // Empty state.
    s_empty = lv_obj_create(page);
    lv_obj_remove_style_all(s_empty);
    lv_obj_set_size(s_empty, LV_PCT(100), LV_PCT(100));
    lv_obj_t *icon = ui_label(s_empty, g_icon_80, COL_DIM, ICON_VIEW_IN_AR);
    lv_obj_align(icon, LV_ALIGN_CENTER, 0, -40);
    lv_obj_t *msg = ui_label(s_empty, g_font_24, COL_MUTED, "No printer connected");
    lv_obj_align(msg, LV_ALIGN_CENTER, 0, 24);
    s_empty_sub = ui_label(s_empty, g_font_16, COL_DIM, "");
    lv_obj_align(s_empty_sub, LV_ALIGN_CENTER, 0, 56);

    printer_refresh();
}

void printer_refresh(void)
{
    if (!s_body) return;
    if (g_printer_count == 0) {
        lv_obj_add_flag(s_body, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_empty, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(s_empty_sub, g_pc_online ? "Add one with deskhub-printers on your PC"
                                                   : "Start the companion app on your PC");
        return;
    }
    lv_obj_remove_flag(s_body, LV_OBJ_FLAG_HIDDEN);
    lv_obj_add_flag(s_empty, LV_OBJ_FLAG_HIDDEN);

    // Show the printer the user picked, else the first one that is printing.
    int sel = 0;
    if (s_user_sel >= 0 && s_user_sel < g_printer_count) {
        sel = s_user_sel;
    } else {
        for (int i = 0; i < g_printer_count; i++) {
            if (is_active(&g_printers[i])) { sel = i; break; }
        }
    }
    const hub_printer_t *p = &g_printers[sel];
    char buf[64];

    lv_label_set_text(s_name, p->name[0] ? p->name : p->model);
    uint32_t sc = state_color(p->state);
    lv_label_set_text(s_chip_lbl, state_text(p->state));
    lv_obj_set_style_bg_color(s_chip, lv_color_hex(sc), 0);
    lv_obj_set_style_text_color(s_chip_lbl, lv_color_lighten(lv_color_hex(sc), 120), 0);
    lv_obj_update_layout(s_name);
    lv_obj_align_to(s_chip, s_name, LV_ALIGN_OUT_RIGHT_MID, 14, 0);
    if (g_printer_count > 1) {
        snprintf(buf, sizeof(buf), "%d of %d  " "›", sel + 1, g_printer_count);
        lv_label_set_text(s_count, buf);
    } else {
        lv_label_set_text(s_count, p->model);
    }

    bool active = is_active(p);
    bool finished = !strcmp(p->state, "FINISH");
    int pct = finished ? 100 : p->pct;
    lv_arc_set_value(s_arc, active || finished ? pct : 0);
    lv_obj_set_style_arc_color(s_arc, lv_color_hex(sc), LV_PART_INDICATOR);
    if (active || finished) {
        snprintf(buf, sizeof(buf), "%d%%", pct);
        lv_label_set_text(s_pct, buf);
    } else {
        lv_label_set_text(s_pct, state_text(p->state));
    }

    if (active && p->remaining_min > 0) {
        fmt_minutes(buf, sizeof(buf), p->remaining_min);
        lv_label_set_text(s_remain, buf);
        char t[16];
        time_t done = time(NULL) + (time_t)p->remaining_min * 60;
        ui_fmt_clock(t, sizeof(t), done);
        if (p->remaining_min >= 18 * 60) {
            struct tm tm;
            char day[8];
            localtime_r(&done, &tm);
            strftime(day, sizeof(day), "%a", &tm);
            snprintf(buf, sizeof(buf), "Done %s %s", day, t);
        } else {
            snprintf(buf, sizeof(buf), "Done at %s", t);
        }
        lv_label_set_text(s_eta, buf);
    } else {
        lv_label_set_text(s_remain, "");
        lv_label_set_text(s_eta, finished ? "Ready to remove" : "");
    }
    if (p->layers > 0 && (active || finished)) {
        snprintf(buf, sizeof(buf), "Layer %d of %d", p->layer, p->layers);
        lv_label_set_text(s_layer, buf);
    } else {
        lv_label_set_text(s_layer, "");
    }
    lv_label_set_text(s_error, p->error);

    lv_label_set_text(s_file_cap, active ? "PRINTING" : (finished ? "LAST PRINT" : "LAST FILE"));
    lv_label_set_text(s_file, p->file[0] ? p->file : "--");
    if (p->speed[0] && active) {
        snprintf(buf, sizeof(buf), "%s speed", p->speed);
        lv_label_set_text(s_speed, buf);
    } else {
        lv_label_set_text(s_speed, "");
    }

    float cur[3] = {p->nozzle, p->bed, p->chamber};
    float tgt[3] = {p->nozzle_target, p->bed_target, NAN};
    for (int i = 0; i < 3; i++) {
        fmt_temp(buf, sizeof(buf), cur[i]);
        lv_label_set_text(s_temp_val[i], buf);
        if (!isnan(tgt[i]) && tgt[i] > 0) {
            char t[12];
            fmt_temp(t, sizeof(t), tgt[i]);
            snprintf(buf, sizeof(buf), "target %s", t);
            lv_label_set_text(s_temp_tgt[i], buf);
        } else {
            lv_label_set_text(s_temp_tgt[i], "");
        }
    }

    // Spread the slots over the card: 4 slots get wide labels, 8 get narrow ones.
    int slots = p->ams_count > 4 ? p->ams_count : 4;
    int step = (RIGHT_W - 32) / slots;
    for (int i = 0; i < HUB_MAX_AMS; i++) {
        bool on = i < p->ams_count;
        if (on) {
            lv_obj_set_pos(s_ams_dot[i], i * step + (step - SWATCH) / 2, UI_COMPACT ? 22 : 26);
            lv_obj_set_width(s_ams_lbl[i], step);
            lv_obj_set_pos(s_ams_lbl[i], i * step, 62);
            if (UI_COMPACT) lv_obj_add_flag(s_ams_lbl[i], LV_OBJ_FLAG_HIDDEN);   // no room for labels
            lv_obj_remove_flag(s_ams_dot[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_set_style_bg_color(s_ams_dot[i], lv_color_hex(p->ams_color[i]), 0);
            lv_obj_set_style_outline_width(s_ams_dot[i], p->ams_active[i] ? 2 : 0, 0);
            lv_obj_set_style_border_width(s_ams_dot[i], p->ams_color[i] < 0x202020 ? 1 : 0, 0);
            lv_label_set_text(s_ams_lbl[i], p->ams_type[i]);
            lv_obj_set_style_text_color(s_ams_lbl[i], lv_color_hex(p->ams_active[i] ? COL_TEXT : COL_MUTED), 0);
        } else {
            lv_obj_add_flag(s_ams_dot[i], LV_OBJ_FLAG_HIDDEN);
            lv_label_set_text(s_ams_lbl[i], "");
        }
    }
    if (p->ams_count) lv_obj_add_flag(s_ams_none, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_remove_flag(s_ams_none, LV_OBJ_FLAG_HIDDEN);
}
