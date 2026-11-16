// AI agent usage (Claude Code or Codex, see g_claude.provider): plan limits
// plus token totals from local transcripts, sent by the companion.
#include <stdio.h>
#include <string.h>

#include "icons.h"
#include "ui_internal.h"

#define CARD_W ((CONTENT_W - 2 * 12) / 3)
#define TOP_H 200
#define CHART_W 400

hub_claude_t g_claude;

typedef struct {
    lv_obj_t *arc, *pct, *big, *sub, *reset;
} limit_card_t;

static limit_card_t s_5h, s_7d;
static lv_obj_t *s_today_val[4];
static lv_obj_t *s_chart, *s_day_lbl[HUB_CLAUDE_DAYS], *s_peak;
static lv_chart_series_t *s_ser;
static lv_obj_t *s_model_name[HUB_CLAUDE_MODELS], *s_model_bar[HUB_CLAUDE_MODELS], *s_model_val[HUB_CLAUDE_MODELS];
static lv_obj_t *s_offline;

void ui_fmt_tokens(char *buf, size_t n, double t)
{
    if (t >= 1e9) snprintf(buf, n, "%.1fB", t / 1e9);
    else if (t >= 1e6) snprintf(buf, n, "%.1fM", t / 1e6);
    else if (t >= 1e3) snprintf(buf, n, "%.0fK", t / 1e3);
    else snprintf(buf, n, "%d", (int)t);
}

void ui_fmt_countdown(char *buf, size_t n, time_t reset)
{
    long s = (long)(reset - time(NULL));
    if (s <= 0) {
        strlcpy(buf, "Resetting now", n);
    } else if (s >= 86400) {
        struct tm tm;
        char when[24], t[16];
        localtime_r(&reset, &tm);
        strftime(when, sizeof(when), "%a", &tm);
        ui_fmt_clock(t, sizeof(t), reset);
        snprintf(buf, n, "Resets %s %s", when, t);
    } else if (s >= 3600) {
        snprintf(buf, n, "Resets in %ldh %02ldm", s / 3600, (s / 60) % 60);
    } else {
        snprintf(buf, n, "Resets in %ldm", (s + 59) / 60);
    }
}

uint32_t ui_level_color(float pct)
{
    return pct >= 80 ? COL_BAD : pct >= 50 ? COL_WARN : COL_GOOD;
}

static void make_limit_card(lv_obj_t *page, limit_card_t *c, int x, const char *title)
{
    lv_obj_t *card = ui_card(page);
    lv_obj_set_size(card, CARD_W, TOP_H);
    lv_obj_set_pos(card, x, 0);
    lv_obj_t *t = ui_label(card, &lv_font_montserrat_14, COL_MUTED, title);
    lv_obj_align(t, LV_ALIGN_TOP_LEFT, 0, 0);

    c->arc = lv_arc_create(card);
    lv_obj_set_size(c->arc, 112, 112);
    lv_obj_align(c->arc, LV_ALIGN_TOP_MID, 0, 22);
    lv_arc_set_rotation(c->arc, 135);
    lv_arc_set_bg_angles(c->arc, 0, 270);
    lv_arc_set_range(c->arc, 0, 100);
    lv_obj_remove_style(c->arc, NULL, LV_PART_KNOB);
    lv_obj_remove_flag(c->arc, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_arc_width(c->arc, 11, LV_PART_MAIN);
    lv_obj_set_style_arc_width(c->arc, 11, LV_PART_INDICATOR);
    lv_obj_set_style_arc_rounded(c->arc, true, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(c->arc, lv_color_hex(COL_CARD_HI), LV_PART_MAIN);
    c->pct = ui_label(card, &lv_font_montserrat_32, COL_TEXT, "");
    lv_obj_set_width(c->pct, 112);
    lv_obj_set_style_text_align(c->pct, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align_to(c->pct, c->arc, LV_ALIGN_CENTER, 0, -2);

    // Shown instead of the arc when there is no limit data.
    c->big = ui_label(card, &lv_font_montserrat_32, COL_TEXT, "");
    lv_obj_align(c->big, LV_ALIGN_TOP_MID, 0, 50);

    c->sub = ui_label(card, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_set_width(c->sub, CARD_W - 32);
    lv_obj_set_style_text_align(c->sub, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(c->sub, LV_ALIGN_BOTTOM_MID, 0, -20);
    c->reset = ui_label(card, &lv_font_montserrat_16, COL_TEXT, "");
    lv_obj_set_width(c->reset, CARD_W - 32);
    lv_obj_set_style_text_align(c->reset, LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align(c->reset, LV_ALIGN_BOTTOM_MID, 0, 2);
}

static void show_arc(limit_card_t *c, bool on)
{
    if (on) {
        lv_obj_remove_flag(c->arc, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(c->pct, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(c->big, LV_OBJ_FLAG_HIDDEN);
    } else {
        lv_obj_add_flag(c->arc, LV_OBJ_FLAG_HIDDEN);
        lv_obj_add_flag(c->pct, LV_OBJ_FLAG_HIDDEN);
        lv_obj_remove_flag(c->big, LV_OBJ_FLAG_HIDDEN);
    }
}

static void set_limit(limit_card_t *c, float pct)
{
    char buf[12];
    show_arc(c, true);
    lv_arc_set_value(c->arc, (int)(pct + 0.5f));
    lv_obj_set_style_arc_color(c->arc, lv_color_hex(ui_level_color(pct)), LV_PART_INDICATOR);
    snprintf(buf, sizeof(buf), "%d%%", (int)(pct + 0.5f));
    lv_label_set_text(c->pct, buf);
}

void claude_create(lv_obj_t *page)
{
    make_limit_card(page, &s_5h, 0, "5-HOUR LIMIT");
    make_limit_card(page, &s_7d, CARD_W + 12, "WEEKLY LIMIT");

    lv_obj_t *today = ui_card(page);
    lv_obj_set_size(today, CARD_W, TOP_H);
    lv_obj_set_pos(today, 2 * (CARD_W + 12), 0);
    lv_obj_t *t = ui_caption(today, "TODAY");
    lv_obj_set_pos(t, 0, 0);
    static const char *names[4] = {"Tokens", "Output", "Messages", "Last hour"};
    for (int i = 0; i < 4; i++) {
        lv_obj_t *n = ui_label(today, &lv_font_montserrat_16, COL_MUTED, names[i]);
        lv_obj_set_pos(n, 0, 30 + i * 36);
        s_today_val[i] = ui_label(today, i == 0 ? &lv_font_montserrat_20 : &lv_font_montserrat_16, COL_TEXT, "--");
        lv_obj_set_width(s_today_val[i], 90);
        lv_obj_set_style_text_align(s_today_val[i], LV_TEXT_ALIGN_RIGHT, 0);
        lv_obj_set_pos(s_today_val[i], CARD_W - 32 - 90, 28 + i * 36);
    }

    lv_obj_t *hist = ui_card(page);
    lv_obj_set_size(hist, CONTENT_W, CONTENT_H - TOP_H - 12);
    lv_obj_set_pos(hist, 0, TOP_H + 12);
    lv_obj_t *h = ui_caption(hist, "LAST 7 DAYS");
    lv_obj_set_pos(h, 0, 0);
    s_peak = ui_label(hist, &lv_font_montserrat_14, COL_DIM, "");
    lv_obj_align(s_peak, LV_ALIGN_TOP_LEFT, CHART_W - 150, 0);
    lv_obj_set_width(s_peak, 150);
    lv_obj_set_style_text_align(s_peak, LV_TEXT_ALIGN_RIGHT, 0);

    s_chart = lv_chart_create(hist);
    lv_obj_set_size(s_chart, CHART_W, 140);
    lv_obj_set_pos(s_chart, 0, 24);
    lv_chart_set_type(s_chart, LV_CHART_TYPE_BAR);
    lv_chart_set_point_count(s_chart, HUB_CLAUDE_DAYS);
    lv_chart_set_div_line_count(s_chart, 0, 0);
    lv_obj_set_style_bg_opa(s_chart, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(s_chart, 0, 0);
    lv_obj_set_style_pad_all(s_chart, 0, 0);
    lv_obj_set_style_pad_column(s_chart, 14, 0);
    lv_obj_set_style_radius(s_chart, 6, LV_PART_ITEMS);
    lv_obj_set_style_bg_grad_color(s_chart, lv_color_lighten(lv_color_hex(ui_agent_color()), 110), LV_PART_ITEMS);
    lv_obj_set_style_bg_grad_dir(s_chart, LV_GRAD_DIR_VER, LV_PART_ITEMS);
    s_ser = lv_chart_add_series(s_chart, lv_color_hex(ui_agent_color()), LV_CHART_AXIS_PRIMARY_Y);
    for (int i = 0; i < HUB_CLAUDE_DAYS; i++) {
        s_day_lbl[i] = ui_label(hist, &lv_font_montserrat_14, COL_MUTED, "");
        lv_obj_set_width(s_day_lbl[i], CHART_W / HUB_CLAUDE_DAYS);
        lv_obj_set_style_text_align(s_day_lbl[i], LV_TEXT_ALIGN_CENTER, 0);
        lv_obj_set_pos(s_day_lbl[i], i * CHART_W / HUB_CLAUDE_DAYS, 170);
    }

    const int mx = CHART_W + 28, mw = CONTENT_W - 32 - mx;
    lv_obj_t *mt = ui_caption(hist, "MODELS TODAY");
    lv_obj_set_pos(mt, mx, 0);
    for (int i = 0; i < HUB_CLAUDE_MODELS; i++) {
        s_model_name[i] = ui_label(hist, &lv_font_montserrat_16, COL_TEXT, "");
        lv_obj_set_pos(s_model_name[i], mx, 28 + i * 44);
        s_model_val[i] = ui_label(hist, &lv_font_montserrat_14, COL_MUTED, "");
        lv_obj_set_width(s_model_val[i], 80);
        lv_obj_set_style_text_align(s_model_val[i], LV_TEXT_ALIGN_RIGHT, 0);
        lv_obj_set_pos(s_model_val[i], mx + mw - 80, 30 + i * 44);
        s_model_bar[i] = ui_bar(hist, ui_agent_color());
        lv_obj_set_size(s_model_bar[i], mw, 6);
        lv_obj_set_pos(s_model_bar[i], mx, 50 + i * 44);
    }

    s_offline = ui_label(page, &lv_font_montserrat_16, COL_DIM, "Start the companion app on your PC");
    lv_obj_align(s_offline, LV_ALIGN_BOTTOM_MID, 0, -6);

    claude_refresh();
}

// Claude Code only reports limits from an interactive session, so they can go
// stale. Show when they were measured once they are more than 5 minutes old.
static void set_asof(lv_obj_t *label, time_t updated)
{
    time_t now = time(NULL);
    char buf[32], t[16];
    if (updated <= 0 || now - updated < 5 * 60) {
        lv_label_set_text(label, "");
        return;
    }
    if (now - updated < 20 * 3600) {
        ui_fmt_clock(t, sizeof(t), updated);
        snprintf(buf, sizeof(buf), "as of %s", t);
    } else {
        struct tm tm;
        localtime_r(&updated, &tm);
        strftime(buf, sizeof(buf), "as of %a", &tm);
    }
    lv_label_set_text(label, buf);
}

static void refresh_limits(void)
{
    const hub_claude_t *c = &g_claude;
    char buf[48], tok[16];

    if (!c->has_5h && c->has_7d && strcmp(c->provider, "codex") == 0) {
        // Some Codex plans only have a weekly limit.
        show_arc(&s_5h, false);
        lv_label_set_text(s_5h.big, "--");
        lv_label_set_text(s_5h.sub, "This plan has no 5-hour limit");
        lv_label_set_text(s_5h.reset, "");
    } else if (c->has_5h) {
        set_limit(&s_5h, c->pct_5h);
        set_asof(s_5h.sub, c->limits_updated);
        ui_fmt_countdown(buf, sizeof(buf), c->reset_5h);
        lv_label_set_text(s_5h.reset, buf);
    } else if (c->has_7d) {
        // The 5-hour window expired; a new one starts at the next prompt.
        set_limit(&s_5h, 0);
        lv_label_set_text(s_5h.sub, "");
        lv_label_set_text(s_5h.reset, "Starts with next prompt");
    } else {
        // No plan data: show the local estimate of the current window.
        show_arc(&s_5h, false);
        if (c->block_active) {
            ui_fmt_tokens(tok, sizeof(tok), c->block_tokens);
            lv_label_set_text(s_5h.big, tok);
            snprintf(buf, sizeof(buf), "tokens in %d messages (estimate)", c->block_msgs);
            lv_label_set_text(s_5h.sub, buf);
            ui_fmt_countdown(buf, sizeof(buf), c->block_reset);
            lv_label_set_text(s_5h.reset, buf);
        } else {
            lv_label_set_text(s_5h.big, c->valid ? "Idle" : "--");
            lv_label_set_text(s_5h.sub, c->valid ? "No active window" : "");
            lv_label_set_text(s_5h.reset, "");
        }
    }

    if (c->has_7d) {
        set_limit(&s_7d, c->pct_7d);
        set_asof(s_7d.sub, c->limits_updated);
        ui_fmt_countdown(buf, sizeof(buf), c->reset_7d);
        lv_label_set_text(s_7d.reset, buf);
    } else {
        show_arc(&s_7d, false);
        lv_label_set_text(s_7d.big, "--");
        snprintf(buf, sizeof(buf), "No limit data yet. It appears after a\n%s reply.", ui_agent_name());
        lv_label_set_text(s_7d.sub, c->valid ? buf : "");
        lv_label_set_text(s_7d.reset, "");
    }
}

void claude_refresh(void)
{
    const hub_claude_t *c = &g_claude;
    // Brand colour of the current agent (it can switch at runtime).
    uint32_t col = ui_agent_color();
    lv_chart_set_series_color(s_chart, s_ser, lv_color_hex(col));
    lv_obj_set_style_bg_grad_color(s_chart, lv_color_lighten(lv_color_hex(col), 110), LV_PART_ITEMS);
    for (int i = 0; i < HUB_CLAUDE_MODELS; i++) ui_bar_set_color(s_model_bar[i], col);
    if (g_pc_online) lv_obj_add_flag(s_offline, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_remove_flag(s_offline, LV_OBJ_FLAG_HIDDEN);
    refresh_limits();

    char buf[32];
    double vals[4] = {c->today_tokens, c->today_output, c->today_msgs, c->last_hour};
    for (int i = 0; i < 4; i++) {
        if (!c->valid) strlcpy(buf, "--", sizeof(buf));
        else if (i == 2) snprintf(buf, sizeof(buf), "%d", c->today_msgs);
        else ui_fmt_tokens(buf, sizeof(buf), vals[i]);
        lv_label_set_text(s_today_val[i], buf);
    }

    double peak = 1;
    for (int i = 0; i < HUB_CLAUDE_DAYS; i++) if (c->days[i] > peak) peak = c->days[i];
    // Chart values are in thousandths of the peak so they fit int32.
    lv_chart_set_range(s_chart, LV_CHART_AXIS_PRIMARY_Y, 0, 1000);
    time_t now = time(NULL);
    for (int i = 0; i < HUB_CLAUDE_DAYS; i++) {
        lv_chart_set_value_by_id(s_chart, s_ser, i, (int32_t)(1000 * c->days[i] / peak));
        time_t d = now - (time_t)(HUB_CLAUDE_DAYS - 1 - i) * 86400;
        struct tm tm;
        localtime_r(&d, &tm);
        if (i == HUB_CLAUDE_DAYS - 1) strlcpy(buf, "Today", sizeof(buf));
        else strftime(buf, sizeof(buf), "%a", &tm);
        lv_label_set_text(s_day_lbl[i], buf);
    }
    lv_chart_refresh(s_chart);
    if (c->valid) {
        char tok[16];
        ui_fmt_tokens(tok, sizeof(tok), peak);
        snprintf(buf, sizeof(buf), "peak %s tokens", tok);
        lv_label_set_text(s_peak, buf);
    }

    double top = c->model_count ? c->model_tokens[0] : 1;
    for (int i = 0; i < HUB_CLAUDE_MODELS; i++) {
        bool on = i < c->model_count;
        if (on) {
            lv_obj_remove_flag(s_model_name[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(s_model_val[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_remove_flag(s_model_bar[i], LV_OBJ_FLAG_HIDDEN);
            lv_label_set_text(s_model_name[i], c->model_name[i]);
            ui_fmt_tokens(buf, sizeof(buf), c->model_tokens[i]);
            lv_label_set_text(s_model_val[i], buf);
            lv_bar_set_value(s_model_bar[i], top > 0 ? (int)(100 * c->model_tokens[i] / top) : 0, LV_ANIM_OFF);
        } else {
            lv_obj_add_flag(s_model_name[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(s_model_val[i], LV_OBJ_FLAG_HIDDEN);
            lv_obj_add_flag(s_model_bar[i], LV_OBJ_FLAG_HIDDEN);
        }
    }
}

void claude_tick(void)
{
    // Countdowns move every second; everything else waits for the companion.
    if (g_claude.valid) refresh_limits();
}
