// Waveshare ESP32-S3-Touch-LCD-4.3B: 800x480 RGB panel, GT911 touch,
// CH422G I/O expander for touch reset, LCD reset and backlight.
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"
#include "esp_lcd_types.h"

#define BOARD_WIDTH  800
#define BOARD_HEIGHT 480

esp_err_t board_init(void);
esp_lcd_panel_handle_t board_panel(void);
void board_backlight(bool on);
// Returns true while a finger is down; x/y get the first touch point.
bool board_touch_read(uint16_t *x, uint16_t *y);
