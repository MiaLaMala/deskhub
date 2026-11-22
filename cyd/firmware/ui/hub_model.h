// Daten, die das CYD zeigt. Felder wie im Original (firmware/main/hub_model.h),
// gekuerzt auf die Seiten der CYD-Variante, dazu Wetter und Homelab vom Begleiter.
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <time.h>

#define HUB_MAX_EVENTS 16
typedef struct {
    time_t start;
    time_t end;
    bool all_day;
    uint32_t color;     // 0xRRGGBB
    char title[80];
    char location[64];
    char calendar[32];
} hub_event_t;

#define HUB_CLAUDE_DAYS 7
#define HUB_CLAUDE_MODELS 4
#define HUB_CLAUDE_HIST 48
typedef struct {
    bool valid;
    char provider[12];
    bool has_5h, has_7d;
    float pct_5h, pct_7d;
    time_t reset_5h, reset_7d;
    time_t limits_updated;
    // Nur wenn der Begleiter lokale Claude-Code-Dateien hat (auf dem Pi nicht).
    bool has_block, has_today;
    bool block_active;
    time_t block_reset;
    double block_tokens;
    int block_msgs;
    double today_tokens, today_output, last_hour;
    int today_msgs;
    int day_count;
    double days[HUB_CLAUDE_DAYS];
    int model_count;
    char model_name[HUB_CLAUDE_MODELS][16];
    double model_tokens[HUB_CLAUDE_MODELS];
    // Wochenverlauf vom Begleiter: [[unix, pct_7d], ...], aelteste zuerst.
    int hist_count;
    time_t hist_t[HUB_CLAUDE_HIST];
    float hist_pct[HUB_CLAUDE_HIST];
} hub_claude_t;

#define HUB_HOURS 12
#define HUB_DAYS 6
typedef struct {
    bool valid;
    char place[32];
    time_t updated;
    float temp, feels, wind;
    int humidity;
    int code;           // WMO-Wettercode
    bool is_day;
    int hour_count;
    time_t hour_t[HUB_HOURS];
    float hour_temp[HUB_HOURS];
    int hour_code[HUB_HOURS];
    int hour_precip[HUB_HOURS];
    int day_count;
    time_t day_t[HUB_DAYS];
    float day_hi[HUB_DAYS];
    float day_lo[HUB_DAYS];
    int day_code[HUB_DAYS];
    int day_precip[HUB_DAYS];
} hub_weather_t;

#define HUB_GH_DAYS 378
#define HUB_GH_MONTHS 14
#define HUB_GH_REPOS 4
typedef struct {
    bool valid;
    bool accent;
    int total;
    int today, week, last_week, streak, best;
    int start_wday;         // Wochentag des ersten Tages, 0 = Sonntag
    int day_count;
    uint8_t level[HUB_GH_DAYS];
    int month_count;
    int16_t month_col[HUB_GH_MONTHS];
    char month_name[HUB_GH_MONTHS][4];
    char login[40];
    int longest;
    char best_date[8];
    int week_days[7];       // diese Woche, Sonntag bis heute
    int week_day_count;
    int last_week_days[7];
    int commits, prs, reviews, issues;
    int private_count;
    int repo_count;
    char repo_name[HUB_GH_REPOS][32];
    int repo_commits[HUB_GH_REPOS];
} hub_github_t;

#define HUB_NET_HIST 60
typedef struct {
    bool valid;
    bool online;
    float latency_ms;        // < 0: unbekannt
    float jitter_ms;
    int loss_pct;
    int16_t hist[HUB_NET_HIST];   // aelteste zuerst, -1 = verloren
    int hist_count;
    time_t up_since;
    time_t drop_at;
    int drop_dur_s;
    double today_bytes, month_bytes;
    bool has_speed, testing;
    float down_mbps, up_mbps, speed_ping_ms;
    time_t speed_at;
    char ip[48];
} hub_net_t;

#define HUB_HL_DOWN 8
typedef struct {
    bool valid;
    bool ok;                 // false: Quelle nicht erreichbar, letzter Stand
    time_t updated;
    int up, total;
    int down_count;
    char down_name[HUB_HL_DOWN][32];
    time_t down_since[HUB_HL_DOWN];
} hub_homelab_t;
