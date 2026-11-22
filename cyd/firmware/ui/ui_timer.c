// Timer: laeuft ohne Begleiter, Voreinstellungen, Vollbild "Zeit um".
// Die einzige Seite mit Bewegung: die Restzeit zaehlt, "Zeit um" blinkt.
#include <stdio.h>
#include <string.h>

#include "ui_internal.h"

static int s_total = 5 * 60;          // Sekunden
static int s_left_ms = 5 * 60 * 1000; // bei Pause
static uint32_t s_end_ms;             // wenn er laeuft
static bool s_running, s_done;

static lv_obj_t *s_time, *s_bar, *s_start_l, *s_reset;
static lv_obj_t *s_alarm, *s_alarm_t;
static lv_timer_t *s_blink;
static int s_blinks;

static const int PRESETS[] = {60, 5 * 60, 15 * 60, 25 * 60};
static const char *PRESET_TXT[] = {"+1 min", "5 min", "15 min", "25 min"};

bool timer_running(void) { return s_running; }

int timer_left_s(void)
{
    int ms = s_running ? (int)(s_end_ms - plat_millis()) : s_left_ms;
    if (ms < 0) ms = 0;
    return (ms + 999) / 1000;
}

static void fmt(char *buf, size_t n, int s)
{
    if (s >= 3600) snprintf(buf, n, "%d:%02d:%02d", s / 3600, (s / 60) % 60, s % 60);
    else snprintf(buf, n, "%02d:%02d", s / 60, s % 60);
}

static void alarm_close_cb(lv_event_t *e)
{
    (void)e;
    if (s_blink) { lv_timer_delete(s_blink); s_blink = NULL; }
    if (s_alarm) { lv_obj_delete(s_alarm); s_alarm = NULL; }
    s_done = false;
}

static void blink_cb(lv_timer_t *t)
{
    (void)t;
    if (!s_alarm) return;
    bool on = (++s_blinks & 1) == 0;
    lv_obj_set_style_bg_color(s_alarm, lv_color_hex(on ? COL_ACCENT : COL_BG), 0);
    lv_obj_set_style_text_color(s_alarm_t, lv_color_hex(on ? COL_ON_ACCENT : COL_ACCENT), 0);
    if (s_blinks >= 60) {   // 30 s blinken, dann ruhig stehen lassen
        lv_obj_set_style_bg_color(s_alarm, lv_color_hex(COL_ACCENT), 0);
        lv_obj_set_style_text_color(s_alarm_t, lv_color_hex(COL_ON_ACCENT), 0);
        lv_timer_delete(s_blink);
        s_blink = NULL;
    }
}

static void show_alarm(bool blink)
{
    if (s_alarm) return;
    s_alarm = ui_box(lv_layer_top(), 0, 0, SCR_W, SCR_H);
    lv_obj_add_flag(s_alarm, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_bg_opa(s_alarm, LV_OPA_COVER, 0);
    lv_obj_set_style_bg_color(s_alarm, lv_color_hex(COL_ACCENT), 0);
    lv_obj_add_event_cb(s_alarm, alarm_close_cb, LV_EVENT_CLICKED, NULL);
    s_alarm_t = ui_label(s_alarm, F28, COL_ON_ACCENT, "Zeit um");
    lv_obj_align(s_alarm_t, LV_ALIGN_CENTER, 0, -26);
    char buf[40], t[12];
    fmt(t, sizeof(t), s_total);
    snprintf(buf, sizeof(buf), "%s sind vorbei", t);
    lv_obj_t *l = ui_label(s_alarm, F16, COL_ON_ACCENT, buf);
    lv_obj_align(l, LV_ALIGN_CENTER, 0, 14);
    l = ui_label(s_alarm, F14, COL_ON_ACCENT, "Tippen zum Schließen");
    lv_obj_align(l, LV_ALIGN_BOTTOM_MID, 0, -20);
    s_blinks = 0;
    if (blink) s_blink = lv_timer_create(blink_cb, 500, NULL);
}

void timer_global_tick(void)
{
    if (s_running && (int32_t)(s_end_ms - plat_millis()) <= 0) {
        s_running = false;
        s_left_ms = 0;
        s_done = true;
        show_alarm(true);
        if (ui_current_page() == P_TIMER) timer_page_refresh();
    }
    if (ui_current_page() != P_TIMER && s_running) {
        char buf[12];
        int s = timer_left_s();
        if (s >= 3600) snprintf(buf, sizeof(buf), "%dh%02d", s / 3600, (s / 60) % 60);
        else snprintf(buf, sizeof(buf), "%d:%02d", s / 60, s % 60);
        ui_dock_set_text(P_TIMER, buf);
    } else {
        ui_dock_set_text(P_TIMER, NULL);
    }
}

static void start(void)
{
    if (s_left_ms <= 0) s_left_ms = s_total * 1000;
    s_end_ms = plat_millis() + (uint32_t)s_left_ms;
    s_running = true;
}

static void pause_(void)
{
    s_left_ms = (int)(s_end_ms - plat_millis());
    if (s_left_ms < 0) s_left_ms = 0;
    s_running = false;
}

static void preset_cb(lv_event_t *e)
{
    int i = (int)(intptr_t)lv_event_get_user_data(e);
    if (i == 0) {   // +1 min
        s_total += 60;
        if (s_running) s_end_ms += 60000;
        else s_left_ms += 60000;
    } else {
        s_total = PRESETS[i];
        s_left_ms = s_total * 1000;
        start();
    }
    timer_page_refresh();
}

static void start_cb(lv_event_t *e)
{
    (void)e;
    if (s_running) pause_();
    else start();
    timer_page_refresh();
}

static void reset_cb(lv_event_t *e)
{
    (void)e;
    s_running = false;
    s_left_ms = s_total * 1000;
    timer_page_refresh();
}

void timer_page_create(lv_obj_t *p)
{
    ui_header(p, "Timer", COL_TEXT);
    s_time = ui_label(p, F48, COL_TEXT, "");
    lv_obj_align(s_time, LV_ALIGN_TOP_MID, 0, 23);
    s_bar = ui_bar(p, PAD, 84, SCR_W - 2 * PAD, 6, COL_ACCENT, COL_CARD_HI);
    const int bw = (SCR_W - 2 * PAD - 3 * 6) / 4;
    for (int i = 0; i < 4; i++)
        ui_button(p, PAD + i * (bw + 6), 98, bw, 40, PRESET_TXT[i], false, preset_cb, (void *)(intptr_t)i);
    const int cw = (SCR_W - 2 * PAD - 8) / 2;
    lv_obj_t *b = ui_button(p, PAD, 146, cw, 44, "Start", true, start_cb, NULL);
    s_start_l = lv_obj_get_child(b, 0);
    s_reset = ui_button(p, PAD + cw + 8, 146, cw, 44, "Zurücksetzen", false, reset_cb, NULL);
}

void timer_page_refresh(void)
{
    char buf[16];
    int left = timer_left_s();
    fmt(buf, sizeof(buf), left);
    ui_set_text_if(s_time, buf);
    lv_obj_set_style_text_color(s_time, lv_color_hex(s_running ? COL_ACCENT : COL_TEXT), 0);
    int pct = s_total > 0 ? (int)((long)left * 100 / s_total) : 0;
    lv_bar_set_value(s_bar, pct, LV_ANIM_OFF);
    lv_label_set_text(s_start_l, s_running ? "Pause" : (left < s_total && left > 0) ? "Weiter" : "Start");
}

void timer_page_tick(void)
{
    timer_page_refresh();
}

void ui_timer_debug(int total_s, int left_s, bool running, bool done)
{
    s_total = total_s;
    s_left_ms = left_s * 1000;
    s_running = false;
    if (running) start();
    if (done) { s_running = false; s_left_ms = 0; s_done = true; show_alarm(false); }
    else alarm_close_cb(NULL);
    if (ui_current_page() == P_TIMER) timer_page_refresh();
}
