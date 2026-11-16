// Data shown on the hub. The PC companion fills stats, media, events and
// tiles; the hub fetches weather itself.
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <time.h>

typedef struct {
    float cpu;          // %
    float cpu_temp;     // °C, < 0 when unknown
    float ram_used;     // GB
    float ram_total;
    bool has_gpu;
    float gpu;          // %
    float gpu_temp;     // °C, < 0 when unknown
    float vram_used;    // GB
    float vram_total;
    float net_down;     // KB/s
    float net_up;
    float disk;         // % used of the system drive
    char cpu_name[48];
    char gpu_name[48];
} hub_stats_t;

typedef struct {
    bool active;
    bool playing;
    bool can_seek;
    int pos;            // seconds
    int dur;
    uint32_t art_id;    // 0 = no cover
    char title[128];
    char artist[96];
    char album[96];
    char source[32];
} hub_media_t;

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

#define HUB_MAX_TILES 16
typedef struct {
    uint32_t color;
    char label[32];
    char icon[32];
} hub_tile_t;

#define HUB_CLAUDE_DAYS 7
#define HUB_CLAUDE_MODELS 4
typedef struct {
    bool valid;
    char provider[12];   // "claude" or "codex"
    // Plan limits, from Claude Code's status line (Pro/Max only).
    bool has_5h, has_7d;
    float pct_5h, pct_7d;
    time_t reset_5h, reset_7d;
    time_t limits_updated;          // when Claude Code last reported them
    // Local estimate of the current five-hour window, from transcripts.
    bool block_active;
    time_t block_reset;
    double block_tokens;
    int block_msgs;
    double today_tokens, today_output, last_hour;
    int today_msgs;
    double days[HUB_CLAUDE_DAYS];   // oldest first, last entry is today
    int model_count;
    char model_name[HUB_CLAUDE_MODELS][16];
    double model_tokens[HUB_CLAUDE_MODELS];
} hub_claude_t;

#define HUB_MAX_PRINTERS 4
#define HUB_MAX_AMS 8
typedef struct {
    bool online;
    char name[32];
    char model[16];
    char state[12];       // IDLE, PREPARE, RUNNING, PAUSE, FINISH, FAILED, OFFLINE...
    char file[64];
    char speed[12];
    char error[48];
    int pct;              // 0-100
    int remaining_min;
    int layer, layers;
    float nozzle, nozzle_target, bed, bed_target, chamber;  // NAN when unknown
    int ams_count;
    uint32_t ams_color[HUB_MAX_AMS];   // 0xRRGGBB
    char ams_type[HUB_MAX_AMS][8];
    bool ams_active[HUB_MAX_AMS];
} hub_printer_t;

#define HUB_HOURS 24
#define HUB_DAYS 6
typedef struct {
    bool valid;
    time_t fetched;
    float temp;
    float feels;
    float wind;
    int humidity;
    int code;           // WMO weather code
    bool is_day;
    time_t hour_t[HUB_HOURS];
    float hour_temp[HUB_HOURS];
    int hour_code[HUB_HOURS];
    int hour_precip[HUB_HOURS];
    time_t day_t[HUB_DAYS];
    float day_hi[HUB_DAYS];
    float day_lo[HUB_DAYS];
    int day_code[HUB_DAYS];
    int day_precip[HUB_DAYS];
} hub_weather_t;

// An agent session waiting for the user (full-screen alert).
typedef struct {
    bool active;
    char id[64];        // session id, echoed back in alert_action
    char kind[16];      // "permission" or "input"
    char agent[16];     // "claude"
    char title[64];
    char detail[128];
    char project[48];
} hub_alert_t;
