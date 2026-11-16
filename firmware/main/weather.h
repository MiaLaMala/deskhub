#pragma once

#include <stdbool.h>
#include <stdint.h>

// Fetches Open-Meteo every 15 minutes (on its own task) and pushes it to the UI.
void weather_start(void);

// Material icon glyph and a short description for a WMO weather code.
const char *weather_icon(int code, bool is_day);
const char *weather_text(int code);
// Tint for the weather icon: amber sun, violet night, cyan rain, and so on.
uint32_t weather_color(int code, bool is_day);
