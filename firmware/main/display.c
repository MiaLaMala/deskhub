#include "display.h"

#include "board.h"
#include "esp_heap_caps.h"
#include "esp_lcd_panel_ops.h"
#include "esp_log.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/semphr.h"
#include "freertos/task.h"
#include "lvgl.h"
#include "sdkconfig.h"

static const char *TAG = "display";

#define DRAW_LINES 24

static SemaphoreHandle_t s_lock;
static int64_t s_last_activity_us;
static bool s_screen_on = true;
static bool s_swallow_touch;
static volatile int64_t s_inject_until_us;
static volatile uint16_t s_inject_x, s_inject_y, s_inject_x2;
static volatile int64_t s_inject_start_us;

static uint32_t tick_ms(void)
{
    return (uint32_t)(esp_timer_get_time() / 1000);
}

// ---- render timing (reported by /perf) -------------------------------------
static int64_t s_render_start_us;
static uint32_t s_frames, s_render_us_total, s_render_us_max, s_pixels;
static int64_t s_window_start_us;
static display_perf_t s_perf;

static void render_start_cb(lv_event_t *e)
{
    s_render_start_us = esp_timer_get_time();
}

static void render_ready_cb(lv_event_t *e)
{
    int64_t now = esp_timer_get_time();
    uint32_t dt = (uint32_t)(now - s_render_start_us);
    s_frames++;
    s_render_us_total += dt;
    if (dt > s_render_us_max) s_render_us_max = dt;
    if (now - s_window_start_us >= 1000000) {
        // Publish the last one-second window.
        s_perf.fps = s_frames;
        s_perf.avg_ms = s_frames ? s_render_us_total / s_frames / 1000.0f : 0;
        s_perf.max_ms = s_render_us_max / 1000.0f;
        s_perf.px_per_s = s_pixels;
        s_frames = s_render_us_total = s_render_us_max = s_pixels = 0;
        s_window_start_us = now;
    }
}

display_perf_t display_perf(void)
{
    return s_perf;
}

int64_t display_time_full_redraw(void)
{
    // Caller holds the display lock. Redraw the whole screen and time it.
    int64_t t0 = esp_timer_get_time();
    lv_obj_invalidate(lv_screen_active());
    lv_refr_now(NULL);
    return esp_timer_get_time() - t0;
}

static void flush_cb(lv_display_t *disp, const lv_area_t *a, uint8_t *px)
{
    s_pixels += lv_area_get_size(a);
    // The RGB driver copies into its PSRAM frame buffer; this returns when done.
    esp_lcd_panel_draw_bitmap(board_panel(), a->x1, a->y1, a->x2 + 1, a->y2 + 1, px);
    lv_display_flush_ready(disp);
}

static void touch_cb(lv_indev_t *indev, lv_indev_data_t *data)
{
    uint16_t x = 0, y = 0;
    bool down = board_touch_read(&x, &y);
    if (esp_timer_get_time() < s_inject_until_us) {
        // A tap requested over the network (/tap) overrides the panel.
        down = true;
        // A drag moves linearly from x to x2 over the press.
        int64_t span = s_inject_until_us - s_inject_start_us;
        int64_t t = esp_timer_get_time() - s_inject_start_us;
        x = s_inject_x + (int)((s_inject_x2 - s_inject_x) * t / (span ? span : 1));
        y = s_inject_y;
    } else if (s_inject_until_us) {
        // Release at the end point so LVGL sees the click or swipe there.
        x = s_inject_x2;
        y = s_inject_y;
        if (!down) s_inject_until_us = 0;
    }
    data->point.x = x;
    data->point.y = y;

    if (down) {
        s_last_activity_us = esp_timer_get_time();
        if (!s_screen_on) {
            // First touch on a dark screen just turns it on.
            board_backlight(true);
            s_screen_on = true;
            s_swallow_touch = true;
        }
    } else {
        s_swallow_touch = false;
    }
    data->state = (down && !s_swallow_touch) ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
}

static void idle_check(void)
{
#if CONFIG_HUB_SCREEN_OFF_MIN > 0
    int64_t idle = esp_timer_get_time() - s_last_activity_us;
    if (s_screen_on && idle > (int64_t)CONFIG_HUB_SCREEN_OFF_MIN * 60 * 1000000) {
        board_backlight(false);
        s_screen_on = false;
    }
#endif
}

static void lvgl_task(void *arg)
{
    while (true) {
        display_lock();
        uint32_t wait = lv_timer_handler();
        idle_check();
        display_unlock();
        if (wait < 5) wait = 5;
        if (wait > 30) wait = 30;
        vTaskDelay(pdMS_TO_TICKS(wait));
    }
}

void display_lock(void)
{
    xSemaphoreTakeRecursive(s_lock, portMAX_DELAY);
}

void display_unlock(void)
{
    xSemaphoreGiveRecursive(s_lock);
}

void display_inject_tap(uint16_t x, uint16_t y)
{
    display_inject_drag(x, y, x, 120);
}

void display_inject_drag(uint16_t x, uint16_t y, uint16_t x2, int ms)
{
    display_lock();
    s_inject_x = x;
    s_inject_y = y;
    s_inject_x2 = x2;
    s_inject_start_us = esp_timer_get_time();
    s_inject_until_us = s_inject_start_us + (int64_t)ms * 1000;
    display_unlock();
    display_wake();
}

void display_wake(void)
{
    s_last_activity_us = esp_timer_get_time();
    if (!s_screen_on) {
        board_backlight(true);
        s_screen_on = true;
    }
}

esp_err_t display_start(void)
{
    s_lock = xSemaphoreCreateRecursiveMutex();
    s_last_activity_us = esp_timer_get_time();

    lv_init();
    lv_tick_set_cb(tick_ms);

    lv_display_t *disp = lv_display_create(BOARD_WIDTH, BOARD_HEIGHT);
    lv_display_set_color_format(disp, LV_COLOR_FORMAT_RGB565);
    size_t buf_bytes = BOARD_WIDTH * DRAW_LINES * 2;
    // Rendering into internal RAM is much faster than into PSRAM.
    void *buf = heap_caps_malloc(buf_bytes, MALLOC_CAP_INTERNAL | MALLOC_CAP_8BIT);
    if (!buf) {
        ESP_LOGW(TAG, "draw buffer falls back to PSRAM");
        buf = heap_caps_malloc(buf_bytes, MALLOC_CAP_SPIRAM);
    }
    if (!buf) {
        return ESP_ERR_NO_MEM;
    }
    lv_display_set_buffers(disp, buf, NULL, buf_bytes, LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(disp, flush_cb);
    lv_display_add_event_cb(disp, render_start_cb, LV_EVENT_RENDER_START, NULL);
    lv_display_add_event_cb(disp, render_ready_cb, LV_EVENT_RENDER_READY, NULL);

    lv_indev_t *indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, touch_cb);

    BaseType_t ok = xTaskCreatePinnedToCore(lvgl_task, "lvgl", 16 * 1024, NULL, 4, NULL, 1);
    return ok == pdPASS ? ESP_OK : ESP_ERR_NO_MEM;
}
