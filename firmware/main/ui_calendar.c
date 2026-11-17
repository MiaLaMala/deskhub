// Calendar: upcoming events from the companion's ICS feeds, grouped by day.
#include <stdio.h>
#include <string.h>

#include "icons.h"
#include "ui_internal.h"

static lv_obj_t *s_list, *s_empty, *s_empty_sub;

void calendar_create(lv_obj_t *page)
{
    lv_obj_t *title = ui_label(page, g_font_32, COL_TEXT, "Upcoming");
    lv_obj_set_pos(title, 0, 0);

    s_list = lv_obj_create(page);
    lv_obj_remove_style_all(s_list);
    lv_obj_set_size(s_list, CONTENT_W, CONTENT_H - 56);
    lv_obj_set_pos(s_list, 0, 56);
    lv_obj_set_flex_flow(s_list, LV_FLEX_FLOW_COLUMN);
    lv_obj_set_style_pad_row(s_list, 10, 0);
    lv_obj_set_scroll_dir(s_list, LV_DIR_VER);
    lv_obj_set_scrollbar_mode(s_list, LV_SCROLLBAR_MODE_ACTIVE);

    s_empty = ui_label(page, g_font_24, COL_MUTED, "No upcoming events");
    lv_obj_align(s_empty, LV_ALIGN_CENTER, 0, 0);
    s_empty_sub = ui_label(page, g_font_16, COL_DIM, "");
    lv_obj_align(s_empty_sub, LV_ALIGN_CENTER, 0, 34);

    calendar_refresh(true);
}

static void add_day_header(time_t t, time_t now)
{
    struct tm st, nt;
    localtime_r(&t, &st);
    localtime_r(&now, &nt);
    char date[32], buf[64];
    strftime(date, sizeof(date), "%A, %B %e", &st);
    time_t tomorrow = now + 86400;
    struct tm tt;
    localtime_r(&tomorrow, &tt);
    if (st.tm_yday == nt.tm_yday && st.tm_year == nt.tm_year) {
        snprintf(buf, sizeof(buf), "TODAY  \xE2\x80\xA2  %s", date);
    } else if (st.tm_yday == tt.tm_yday && st.tm_year == tt.tm_year) {
        snprintf(buf, sizeof(buf), "TOMORROW  \xE2\x80\xA2  %s", date);
    } else {
        strlcpy(buf, date, sizeof(buf));
    }
    lv_obj_t *l = ui_label(s_list, g_font_16, COL_ACCENT, buf);
    lv_obj_set_style_pad_top(l, 6, 0);
}

static void add_event(const hub_event_t *e, time_t now)
{
    lv_obj_t *row = ui_card(s_list);
    lv_obj_set_size(row, LV_PCT(100), LV_SIZE_CONTENT);
    lv_obj_set_style_pad_all(row, 12, 0);
    lv_obj_set_style_pad_left(row, 20, 0);
    bool live = !e->all_day && e->start <= now && e->end > now;
    if (live) {
        lv_obj_set_style_border_color(row, lv_color_hex(e->color), 0);
        lv_obj_set_style_border_width(row, 2, 0);
    }

    lv_obj_t *bar = lv_obj_create(row);
    lv_obj_remove_style_all(bar);
    lv_obj_set_size(bar, 4, 40);
    lv_obj_set_style_radius(bar, 2, 0);
    lv_obj_set_style_bg_color(bar, lv_color_hex(e->color), 0);
    lv_obj_set_style_bg_opa(bar, LV_OPA_COVER, 0);
    lv_obj_align(bar, LV_ALIGN_LEFT_MID, -8, 0);

    char t1[16], t2[16], when[40];
    if (e->all_day) {
        strlcpy(when, "All day", sizeof(when));
    } else {
        ui_fmt_clock(t1, sizeof(t1), e->start);
        ui_fmt_clock(t2, sizeof(t2), e->end);
        snprintf(when, sizeof(when), "%s\n%s", t1, t2);
    }
    lv_obj_t *tl = ui_label(row, g_font_16, live ? COL_TEXT : COL_MUTED, when);
    lv_obj_set_width(tl, 100);
    lv_obj_set_pos(tl, 4, 0);

    lv_obj_t *title = ui_label(row, g_font_20, COL_TEXT, e->title);
    lv_label_set_long_mode(title, LV_LABEL_LONG_DOT);
    lv_obj_set_width(title, CONTENT_W - 160);
    lv_obj_set_pos(title, 116, 0);

    char sub[sizeof(e->location) + sizeof(e->calendar) + 8];
    if (e->location[0] && e->calendar[0]) snprintf(sub, sizeof(sub), "%s  \xE2\x80\xA2  %s", e->location, e->calendar);
    else snprintf(sub, sizeof(sub), "%s%s", e->location, e->calendar);
    if (sub[0]) {
        lv_obj_t *s = ui_label(row, g_font_14, COL_MUTED, sub);
        lv_label_set_long_mode(s, LV_LABEL_LONG_DOT);
        lv_obj_set_width(s, CONTENT_W - 160);
        lv_obj_set_pos(s, 116, 26);
    } else {
        lv_obj_set_height(row, 64);
    }
}

void calendar_refresh(bool force)
{
    static int s_last_visible = -1, s_last_live = -1, s_last_yday = -1;
    static bool s_last_online;
    time_t now = time(NULL);

    // Rebuilding resets scroll and any press, so only do it when the list would change:
    // an event ended or started, the day rolled over, or the PC went on/offline.
    int visible = 0, live = 0;
    for (int i = 0; i < g_event_count; i++) {
        if (g_events[i].end > now) visible++;
        if (g_events[i].start <= now && g_events[i].end > now) live++;
    }
    struct tm today;
    localtime_r(&now, &today);
    if (!force && visible == s_last_visible && live == s_last_live &&
        today.tm_yday == s_last_yday && g_pc_online == s_last_online) {
        return;
    }
    s_last_visible = visible;
    s_last_live = live;
    s_last_yday = today.tm_yday;
    s_last_online = g_pc_online;

    lv_obj_clean(s_list);
    int shown = 0, last_yday = -1, last_year = -1;
    for (int i = 0; i < g_event_count; i++) {
        const hub_event_t *e = &g_events[i];
        if (e->end <= now) continue;
        // Events already in progress are listed under today.
        time_t day_t = e->start < now ? now : e->start;
        struct tm tm;
        localtime_r(&day_t, &tm);
        if (tm.tm_yday != last_yday || tm.tm_year != last_year) {
            add_day_header(day_t, now);
            last_yday = tm.tm_yday;
            last_year = tm.tm_year;
        }
        add_event(e, now);
        shown++;
    }
    if (shown) {
        lv_obj_add_flag(s_empty, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(s_empty_sub, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_remove_flag(s_empty, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(s_empty_sub, LV_OBJ_FLAG_HIDDEN);
        lv_label_set_text(s_empty_sub, g_pc_online ? "Add one with deskhub-calendars on your PC"
                                                   : "Start the companion app on your PC");
    }
}
