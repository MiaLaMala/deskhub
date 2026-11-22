// Claude: beide Limits mit Rueckstellzeit, darunter der Wochenverlauf aus
// "history". Fehlende Teile (Token-Zahlen auf dem Pi) werden ausgeblendet.
#include <stdio.h>
#include <string.h>

#include "ui_internal.h"

typedef struct { lv_obj_t *cap, *pct, *bar, *reset; } limit_t;
static limit_t s_l[2];
static lv_obj_t *s_none, *s_hist_cap, *s_hist, *s_today;

static void make_limit(lv_obj_t *p, limit_t *l, int y, const char *title)
{
    l->cap = ui_label_at(p, F14, COL_MUTED, PAD, y + 8, title);
    l->pct = ui_label(p, F28, COL_TEXT, "");
    lv_obj_align(l->pct, LV_ALIGN_TOP_RIGHT, -PAD, y);
    l->bar = ui_bar(p, PAD, y + 36, SCR_W - 2 * PAD, 10, COL_CLAUDE, COL_CLAUDE_LO);
    l->reset = ui_label_w(p, F12, COL_MUTED, PAD, y + 50, SCR_W - 2 * PAD, "");
}

static void hist_draw_cb(lv_event_t *e)
{
    lv_obj_t *o = lv_event_get_target(e);
    lv_layer_t *layer = lv_event_get_layer(e);
    lv_area_t a;
    lv_obj_get_coords(o, &a);
    int n = g_claude.hist_count;
    if (n <= 0) return;
    int w = lv_area_get_width(&a), h = lv_area_get_height(&a);
    int step = w / HUB_CLAUDE_HIST;            // 6 px je Punkt
    int bw = step > 2 ? step - 1 : step;
    int x0 = a.x2 + 1 - n * step;               // neueste rechts
    lv_draw_rect_dsc_t d;
    lv_draw_rect_dsc_init(&d);
    d.bg_opa = LV_OPA_COVER;
    d.radius = 0;
    // Grundlinie
    d.bg_color = lv_color_hex(COL_CLAUDE_LO);
    lv_area_t base = {a.x1, a.y2, a.x2, a.y2};
    lv_draw_rect(layer, &d, &base);
    for (int i = 0; i < n; i++) {
        float pct = g_claude.hist_pct[i];
        if (pct < 0) pct = 0;
        if (pct > 100) pct = 100;
        int bh = (int)(pct * (h - 1) / 100.0f + 0.5f);
        if (bh < 1) bh = 1;
        lv_area_t r = {x0 + i * step, a.y2 - bh, x0 + i * step + bw - 1, a.y2 - 1};
        d.bg_color = lv_color_hex(i == n - 1 ? COL_CLAUDE : 0x8a4e3b);
        lv_draw_rect(layer, &d, &r);
    }
}

void claude_create(lv_obj_t *p)
{
    ui_header(p, "Claude", COL_CLAUDE);
    make_limit(p, &s_l[0], 26, "5-Stunden-Fenster");
    make_limit(p, &s_l[1], 92, "Woche");
    s_hist_cap = ui_label_at(p, F12, COL_MUTED, PAD, 158, "Woche, Verlauf");
    s_hist = ui_box(p, 0, 175, (SCR_W - 2 * PAD) / HUB_CLAUDE_HIST * HUB_CLAUDE_HIST, 26);
    lv_obj_align(s_hist, LV_ALIGN_TOP_RIGHT, -PAD, 175);
    lv_obj_add_event_cb(s_hist, hist_draw_cb, LV_EVENT_DRAW_MAIN, NULL);
    s_today = ui_label_w(p, F14, COL_TEXT, PAD, 170, SCR_W - 2 * PAD, "");
    s_none = ui_label(p, F14, COL_MUTED, "Noch keine Daten von Claude");
    lv_obj_align(s_none, LV_ALIGN_CENTER, 0, 0);
}

static void show(lv_obj_t *o, bool on)
{
    if (on) lv_obj_remove_flag(o, LV_OBJ_FLAG_HIDDEN);
    else lv_obj_add_flag(o, LV_OBJ_FLAG_HIDDEN);
}

static void fmt_tokens(char *buf, size_t n, double t)
{
    if (t >= 1e6) snprintf(buf, n, "%.1f Mio.", t / 1e6);
    else if (t >= 1e3) snprintf(buf, n, "%.0f Tsd.", t / 1e3);
    else snprintf(buf, n, "%.0f", t);
    for (char *c = buf; *c; c++) if (*c == '.' && c[1] >= '0' && c[1] <= '9') *c = ',';
}

void claude_refresh(void)
{
    const hub_claude_t *c = &g_claude;
    bool valid = c->valid;
    show(s_none, !valid);
    for (int i = 0; i < 2; i++) {
        show(s_l[i].cap, valid);
        show(s_l[i].pct, valid);
        show(s_l[i].bar, valid);
        show(s_l[i].reset, valid);
    }
    if (!valid) {
        show(s_hist_cap, false);
        show(s_hist, false);
        show(s_today, false);
        return;
    }
    bool stale = ui_stale_at(P_CLAUDE) != 0;
    struct { bool has; float pct; time_t reset; } r[2] = {
        {c->has_5h, c->pct_5h, c->reset_5h}, {c->has_7d, c->pct_7d, c->reset_7d}};
    char buf[48];
    for (int i = 0; i < 2; i++) {
        limit_t *l = &s_l[i];
        if (!r[i].has) {
            lv_label_set_text(l->pct, "–");
            lv_obj_set_style_text_color(l->pct, lv_color_hex(COL_DIM), 0);
            lv_bar_set_value(l->bar, 0, LV_ANIM_OFF);
            lv_label_set_text(l->reset, "keine Angabe");
            continue;
        }
        int pct = (int)(r[i].pct + 0.5f);
        snprintf(buf, sizeof(buf), "%d %%", pct);
        lv_label_set_text(l->pct, buf);
        uint32_t col = stale ? COL_MUTED : pct >= 80 ? COL_BAD : COL_TEXT;
        lv_obj_set_style_text_color(l->pct, lv_color_hex(col), 0);
        lv_obj_align(l->pct, LV_ALIGN_TOP_RIGHT, -PAD, i == 0 ? 26 : 92);
        lv_bar_set_value(l->bar, pct > 100 ? 100 : pct, LV_ANIM_ON);
        ui_fmt_countdown(buf, sizeof(buf), r[i].reset);
        if (!buf[0]) strlcpy(buf, "Rückstellzeit unbekannt", sizeof(buf));
        lv_label_set_text(l->reset, buf);
    }
    bool hist = c->hist_count >= 2;
    show(s_hist_cap, hist);
    show(s_hist, hist);
    if (hist) lv_obj_invalidate(s_hist);
    // Token-Zahlen nur, wenn der Begleiter sie hat (nie als Nullen).
    bool today = !hist && c->has_today && c->today_tokens > 0;
    show(s_today, today);
    if (today) {
        char t[24];
        fmt_tokens(t, sizeof(t), c->today_tokens);
        if (c->today_msgs > 0) snprintf(buf, sizeof(buf), "Heute %s Tokens, %d Nachrichten", t, c->today_msgs);
        else snprintf(buf, sizeof(buf), "Heute %s Tokens", t);
        lv_label_set_text(s_today, buf);
    }
}
