#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <time.h>

#include "cJSON.h"
#include "hub_proto.h"
#include "platform.h"

#define SCR_W_ 320
#define SCR_H_ 240
#define SAMPLE_NOW 1795509660.0   // Di 24.11.2026 09:41 MEZ, wie make_samples.py

extern double g_now;
extern uint32_t g_ms;
extern bool g_online;
extern bool g_time_valid;
extern const char *g_ip;
extern char g_sent[16][128];
extern int g_sent_count;
extern int g_ota_answer;
extern uint16_t g_fb[SCR_W_ * SCR_H_];

void env_init(void);
void env_render(void);
bool env_feed_file(const char *path);
cJSON *env_load_json(const char *path);
bool png_write_rgb(const char *path, const uint8_t *rgb, int w, int h);
void fb_to_rgb(uint8_t *rgb);
