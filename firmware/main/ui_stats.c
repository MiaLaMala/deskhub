// PC stats: four gauges and a one-minute CPU/GPU history.
#include <stdio.h>

#include "icons.h"
#include "ui_internal.h"

#define GAUGES 4
#define GAUGE_W ((CONTENT_W - 3 * 12) / 4)
#define HISTORY 60

static lv_obj_t *s_arc[GAUGES], *s_val[GAUGES], *s_sub[GAUGES];
static lv_obj_t *s_chart, *s_net, *s_disk, *s_offline, *s_names;
static lv_chart_series_t *s_cpu_ser, *s_gpu_ser;

static const char *NAMES[GAUGES] = {"CPU", "GPU", "RAM", "VRAM"};
static const uint32_t COLORS[GAUGES] = {COL_ACCENT, COL_CYAN, COL_ACCENT2, 0xf0abfc};

static void make_gauge(lv_obj_t *page, int i)
{
    lv_obj_t *c = ui_card(page);
    lv_obj_set_size(c, GAUGE_W, 196);
    lv_obj_set_pos(c, i * (GAUGE_W + 12), 0);

    lv_obj_t *arc = lv_arc_create(c);
    lv_obj_set_size(arc, 124, 124);
    lv_obj_align(arc, LV_ALIGN_TOP_MID, 0, 0);
    lv_arc_set_rotation(arc, 135);
    lv_arc_set_bg_angles(arc, 0, 270);
    lv_arc_set_range(arc, 0, 100);
    lv_arc_set_value(arc, 0);
    lv_obj_remove_style(arc, NULL, LV_PART_KNOB);
    lv_obj_remove_flag(arc, LV_OBJ_FLAG_CLICKABLE);
    lv_obj_set_style_arc_width(arc, 12, LV_PART_MAIN);
    lv_obj_set_style_arc_width(arc, 12, LV_PART_INDICATOR);
    lv_obj_set_style_arc_rounded(arc, true, LV_PART_INDICATOR);
    lv_obj_set_style_arc_color(arc, lv_color_hex(COL_CARD_HI), LV_PART_MAIN);
    lv_obj_set_style_arc_color(arc, lv_color_hex(COLORS[i]), LV_PART_INDICATOR);
    s_arc[i] = arc;

    s_val[i] = ui_label(c, &lv_font_montserrat_32, COL_TEXT, "--");
    lv_obj_set_width(s_val[i], 124);
    lv_obj_set_style_text_align(s_val[i], LV_TEXT_ALIGN_CENTER, 0);
    lv_obj_align_to(s_val[i], arc, LV_ALIGN_CENTER, 0, -4);
    lv_obj_t *name = ui_label(c, &lv_font_montserrat_20, COL_TEXT, NAMES[i]);
    lv_obj_align(name, LV_ALIGN_BOTTOM_MID, 0, -22);
    s_sub[i] = ui_label(c, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_align(s_sub[i], LV_ALIGN_BOTTOM_MID, 0, 0);
}

void stats_create(lv_obj_t *page)
{
    for (int i = 0; i < GAUGES; i++) make_gauge(page, i);

    lv_obj_t *c = ui_card(page);
    lv_obj_set_size(c, CONTENT_W, CONTENT_H - 208);
    lv_obj_set_pos(c, 0, 208);

    lv_obj_t *t = ui_caption(c, "LAST MINUTE");
    lv_obj_set_pos(t, 0, 0);
    lv_obj_t *cpu_key = ui_label(c, &lv_font_montserrat_14, COL_ACCENT, "\xE2\x80\xA2 CPU");
    lv_obj_set_pos(cpu_key, 150, 0);
    lv_obj_t *gpu_key = ui_label(c, &lv_font_montserrat_14, COL_CYAN, "\xE2\x80\xA2 GPU");
    lv_obj_set_pos(gpu_key, 210, 0);

    s_net = ui_label(c, &lv_font_montserrat_16, COL_TEXT, "");
    lv_obj_align(s_net, LV_ALIGN_TOP_RIGHT, 0, -2);
    s_disk = ui_label(c, &lv_font_montserrat_14, COL_MUTED, "");
    lv_obj_align(s_disk, LV_ALIGN_BOTTOM_RIGHT, 0, 4);
    s_names = ui_label(c, &lv_font_montserrat_14, COL_DIM, "");
    lv_obj_align(s_names, LV_ALIGN_BOTTOM_LEFT, 0, 4);

    s_chart = lv_chart_create(c);
    lv_obj_set_size(s_chart, CONTENT_W - 32, 150);
    lv_obj_set_pos(s_chart, 0, 28);
    lv_chart_set_type(s_chart, LV_CHART_TYPE_LINE);
    lv_chart_set_point_count(s_chart, HISTORY);
    lv_chart_set_range(s_chart, LV_CHART_AXIS_PRIMARY_Y, 0, 100);
    lv_chart_set_div_line_count(s_chart, 4, 0);
    lv_chart_set_update_mode(s_chart, LV_CHART_UPDATE_MODE_SHIFT);
    lv_obj_set_style_bg_opa(s_chart, LV_OPA_TRANSP, 0);
    lv_obj_set_style_border_width(s_chart, 0, 0);
    lv_obj_set_style_pad_all(s_chart, 0, 0);
    lv_obj_set_style_line_color(s_chart, lv_color_hex(COL_CARD_HI), LV_PART_MAIN);
    lv_obj_set_style_size(s_chart, 0, 0, LV_PART_INDICATOR);
    lv_obj_set_style_line_width(s_chart, 3, LV_PART_ITEMS);
    s_cpu_ser = lv_chart_add_series(s_chart, lv_color_hex(COL_ACCENT), LV_CHART_AXIS_PRIMARY_Y);
    s_gpu_ser = lv_chart_add_series(s_chart, lv_color_hex(COL_CYAN), LV_CHART_AXIS_PRIMARY_Y);
    lv_chart_set_all_value(s_chart, s_cpu_ser, LV_CHART_POINT_NONE);
    lv_chart_set_all_value(s_chart, s_gpu_ser, LV_CHART_POINT_NONE);

    s_offline = ui_label(c, &lv_font_montserrat_20, COL_DIM, "Start the companion app on your PC");
    lv_obj_center(s_offline);
}

static void fmt_rate(char *buf, size_t n, float kbps)
{
    if (kbps >= 1024) snprintf(buf, n, "%.1f MB/s", kbps / 1024);
    else snprintf(buf, n, "%d KB/s", (int)kbps);
}

static void set_gauge(int i, float pct, const char *sub)
{
    char buf[12];
    lv_arc_set_value(s_arc[i], (int)pct);
    snprintf(buf, sizeof(buf), "%d%%", (int)(pct + 0.5f));
    lv_label_set_text(s_val[i], buf);
    lv_label_set_text(s_sub[i], sub);
}

static void clear_gauge(int i, const char *sub)
{
    lv_arc_set_value(s_arc[i], 0);
    lv_label_set_text(s_val[i], "--");
    lv_label_set_text(s_sub[i], sub);
}

void stats_refresh(void)
{
    if (!g_pc_online) {
        for (int i = 0; i < GAUGES; i++) clear_gauge(i, "");
        lv_label_set_text(s_net, "");
        lv_label_set_text(s_disk, "");
        lv_label_set_text(s_names, "");
        lv_obj_remove_flag(s_offline, LV_OBJ_FLAG_HIDDEN);
        return;
    }
    lv_obj_add_flag(s_offline, LV_OBJ_FLAG_HIDDEN);
    const hub_stats_t *s = &g_stats;
    char sub[32];

    if (s->cpu_temp >= 0) snprintf(sub, sizeof(sub), "%d\xC2\xB0" "C", (int)s->cpu_temp);
    else sub[0] = 0;
    set_gauge(0, s->cpu, sub);

    if (s->has_gpu) {
        if (s->gpu_temp >= 0) snprintf(sub, sizeof(sub), "%d\xC2\xB0" "C", (int)s->gpu_temp);
        else sub[0] = 0;
        set_gauge(1, s->gpu, sub);
        if (s->vram_total > 0) {
            snprintf(sub, sizeof(sub), "%.1f / %.0f GB", s->vram_used, s->vram_total);
            set_gauge(3, 100.0f * s->vram_used / s->vram_total, sub);
        } else {
            clear_gauge(3, "");
        }
    } else {
        clear_gauge(1, "No GPU data");
        clear_gauge(3, "");
    }

    if (s->ram_total > 0) {
        snprintf(sub, sizeof(sub), "%.1f / %.0f GB", s->ram_used, s->ram_total);
        set_gauge(2, 100.0f * s->ram_used / s->ram_total, sub);
    }

    char down[20], up[20], buf[160];
    fmt_rate(down, sizeof(down), s->net_down);
    fmt_rate(up, sizeof(up), s->net_up);
    snprintf(buf, sizeof(buf), LV_SYMBOL_DOWNLOAD " %s    " LV_SYMBOL_UPLOAD " %s", down, up);
    lv_label_set_text(s_net, buf);
    snprintf(buf, sizeof(buf), "Disk %d%% used", (int)s->disk);
    lv_label_set_text(s_disk, buf);
    snprintf(buf, sizeof(buf), "%s%s%s", s->cpu_name, s->gpu_name[0] ? "  /  " : "", s->gpu_name);
    lv_label_set_text(s_names, buf);

    lv_chart_set_next_value(s_chart, s_cpu_ser, (int32_t)s->cpu);
    lv_chart_set_next_value(s_chart, s_gpu_ser, s->has_gpu ? (int32_t)s->gpu : LV_CHART_POINT_NONE);
}
