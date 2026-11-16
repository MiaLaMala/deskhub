#pragma once

#include <stdbool.h>
#include <stdint.h>
#include "esp_err.h"

// Starts LVGL, the display driver, touch input and the LVGL task.
esp_err_t display_start(void);

// Every LVGL call from outside the LVGL task must hold this lock.
void display_lock(void);
void display_unlock(void);

// Screen power. A touch while the screen is off only wakes it.
void display_wake(void);

// Simulate a short tap at (x, y), for remote testing.
void display_inject_tap(uint16_t x, uint16_t y);
// Simulate a horizontal drag from x to x2 at height y, lasting ms.
void display_inject_drag(uint16_t x, uint16_t y, uint16_t x2, int ms);

// Rendering performance over the last second (frames that actually redrew something).
typedef struct {
    uint32_t fps;       // frames rendered in the last second
    float avg_ms;       // average render+flush time per frame
    float max_ms;
    uint32_t px_per_s;  // pixels redrawn in the last second
} display_perf_t;
display_perf_t display_perf(void);
// Force a full-screen redraw now and return how long it took, in microseconds.
// Call with display_lock() held.
int64_t display_time_full_redraw(void);
