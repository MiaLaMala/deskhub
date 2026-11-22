// Desk Hub CYD: Firmware fuer das ESP32-2432S028R ("Cheap Yellow Display").
//
// ILI9341 320 x 240 an HSPI (TFT_eSPI, per build_flags eingestellt), XPT2046 an
// einem eigenen Bus, LVGL 9.2 mit einem Zeilenpuffer (320 x 24). Der Begleiter
// verbindet sich per WebSocket (src/hub_server.c, Protokoll in cyd/PROTOKOLL.md).
#include <Arduino.h>
#include <ESPmDNS.h>
#include <Preferences.h>
#include <SPI.h>
#include <TFT_eSPI.h>
#include <WiFi.h>
#include <XPT2046_Touchscreen.h>
#include <sys/time.h>

#include "config.h"
#include "esp_ota_ops.h"
#include "esp_partition.h"
#include "lvgl.h"
#include "platform.h"
#include "ui.h"

// ---- Anschluesse -----------------------------------------------------------
// Der Touch haengt am zweiten SPI-Bus (VSPI) auf eigenen Pins; das Panel an HSPI.
#define TOUCH_CS 33
#define TOUCH_IRQ 36
#define TOUCH_MOSI 32
#define TOUCH_MISO 39
#define TOUCH_CLK 25
#define BL_CHANNEL 0

static const int BREIT = 320, HOCH = 240;
// Rohwerte des XPT2046 (0..4095) auf Pixel, wie in Jana Desktop.
static const int ROH_MIN = 300, ROH_MAX = 3800;
static int rohNachX(int roh) { return constrain((int)map(roh, ROH_MIN, ROH_MAX, 0, BREIT), 0, BREIT - 1); }
static int rohNachY(int roh) { return constrain((int)map(roh, ROH_MIN, ROH_MAX, 0, HOCH), 0, HOCH - 1); }

static TFT_eSPI tft;
static SPIClass touchSPI(VSPI);
static XPT2046_Touchscreen touch(TOUCH_CS, TOUCH_IRQ);
static SemaphoreHandle_t s_lock;
static Preferences s_prefs;

// ---- Sperre, Licht ---------------------------------------------------------

extern "C" void display_lock(void) { xSemaphoreTakeRecursive(s_lock, portMAX_DELAY); }
extern "C" void display_unlock(void) { xSemaphoreGiveRecursive(s_lock); }

static uint8_t s_bl = 255;
static volatile uint32_t s_wake_until;   // Beruehrung weckt fuer eine Minute
static int s_night_start = -1, s_night_end = -1, s_night_style = 0;

static void backlight(uint8_t v)
{
    if (v == s_bl) return;
    s_bl = v;
    ledcWrite(BL_CHANNEL, v);
}

extern "C" void display_wake(void)
{
    s_wake_until = millis() + 60000;
    backlight(255);
}

// ---- Panel -----------------------------------------------------------------

static void flush_cb(lv_display_t *d, const lv_area_t *a, uint8_t *px)
{
    uint32_t w = a->x2 - a->x1 + 1, h = a->y2 - a->y1 + 1;
    tft.startWrite();
    tft.setAddrWindow(a->x1, a->y1, w, h);
    tft.pushPixels((uint16_t *)px, w * h);
    tft.endWrite();
    lv_display_flush_ready(d);
}

extern "C" void panel_read_rows(int y, int n, uint16_t *buf)
{
    tft.readRect(0, y, BREIT, n, buf);
}

// ---- Touch -----------------------------------------------------------------

static volatile int s_inj_x, s_inj_y;
static volatile uint32_t s_inj_until;
static volatile bool s_inj_pending;

extern "C" void touch_inject(int x, int y)
{
    s_inj_x = x;
    s_inj_y = y;
    s_inj_until = millis() + 120;
    s_inj_pending = true;
}

static void touch_read(lv_indev_t *indev, lv_indev_data_t *data)
{
    static int last_x, last_y;
    static bool swallow;   // erste Beruehrung bei dunklem Schirm weckt nur
    if (s_inj_pending) {
        last_x = s_inj_x;
        last_y = s_inj_y;
        bool on = (int32_t)(s_inj_until - millis()) > 0;
        if (!on) s_inj_pending = false;
        data->point.x = last_x;
        data->point.y = last_y;
        data->state = on ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
        return;
    }
    bool an = touch.tirqTouched() && touch.touched();
    if (an) {
        TS_Point roh = touch.getPoint();
        // Zu schwacher Druck ist Rauschen: Zustand und Lage behalten.
        if (roh.z >= 300) {
            if (s_bl < 255) swallow = true;
            display_wake();
            // Die letzte gueltige Lage mitschreiben, solange der Finger liegt; beim
            // Loslassen meldet LVGL diese Lage (nicht das Rauschen ohne Druck).
            last_x = rohNachX(roh.x);
            last_y = rohNachY(roh.y);
            data->point.x = last_x;
            data->point.y = last_y;
            data->state = swallow ? LV_INDEV_STATE_RELEASED : LV_INDEV_STATE_PRESSED;
            return;
        }
        data->point.x = last_x;
        data->point.y = last_y;
        data->state = lv_indev_get_state(indev);
        return;
    }
    swallow = false;
    data->point.x = last_x;
    data->point.y = last_y;
    data->state = LV_INDEV_STATE_RELEASED;
}

// ---- Plattform fuer die UI -------------------------------------------------

static char s_ip[16];

extern "C" time_t plat_now(void) { return time(NULL); }
extern "C" bool plat_time_valid(void) { return time(NULL) > 1700000000; }
extern "C" uint32_t plat_millis(void) { return millis(); }
extern "C" void plat_send(const char *json) { hub_server_send(json); }
extern "C" bool plat_companion_online(void) { return hub_server_online(); }
extern "C" const char *plat_ip(void) { return s_ip; }
extern "C" int wifi_rssi(void) { return WiFi.status() == WL_CONNECTED ? WiFi.RSSI() : 0; }

extern "C" void plat_set_time(double t)
{
    // Rueckfall fuer SNTP: nur stellen, wenn die Uhr fehlt oder mehr als 2 s daneben liegt.
    struct timeval now;
    gettimeofday(&now, NULL);
    double cur = now.tv_sec + now.tv_usec / 1e6;
    if (plat_time_valid() && fabs(cur - t) < 2.0) return;
    struct timeval tv = {(time_t)t, (suseconds_t)((t - (time_t)t) * 1e6)};
    settimeofday(&tv, NULL);
}

extern "C" void plat_set_night(int start_min, int end_min, int style)
{
    s_night_start = start_min;
    s_night_end = end_min;
    s_night_style = style;
}

static bool in_night(void)
{
    if (s_night_start < 0 || s_night_end < 0 || s_night_start == s_night_end || !plat_time_valid()) return false;
    time_t t = time(NULL);
    struct tm tm;
    localtime_r(&t, &tm);
    int m = tm.tm_hour * 60 + tm.tm_min;
    return s_night_start < s_night_end ? (m >= s_night_start && m < s_night_end)
                                       : (m >= s_night_start || m < s_night_end);
}

// ---- Software-Probezeit nach einem Update ----------------------------------
// Der vorinstallierte Arduino-Bootloader faellt nicht verlaesslich zurueck. Darum:
// vor dem Umschalten die alte Partition im NVS merken; danach Starts zaehlen. Kommt
// binnen 5 Minuten kein gueltiges hello oder startet es dreimal unbestaetigt, geht
// es auf die alte Partition zurueck.

static bool s_probation;
static volatile bool s_confirm_req;

extern "C" void ota_probation_arm(const char *prev_label)
{
    Preferences p;
    p.begin("otaprob", false);
    p.putString("prev", prev_label);
    p.putInt("boots", 0);
    p.putBool("trial", true);
    p.end();
}

extern "C" void ota_probation_confirm(void) { s_confirm_req = true; }

static void probation_clear(void)
{
    Preferences p;
    p.begin("otaprob", false);
    p.clear();
    p.end();
}

static void rollback(const String &label)
{
    const esp_partition_t *part =
        esp_partition_find_first(ESP_PARTITION_TYPE_APP, ESP_PARTITION_SUBTYPE_ANY, label.c_str());
    probation_clear();
    if (part && esp_ota_set_boot_partition(part) == ESP_OK) {
        Serial.printf("[ota] Probezeit nicht bestanden, zurueck auf %s\n", label.c_str());
        delay(200);
        esp_restart();
    }
    Serial.println("[ota] Rueckfall nicht moeglich, bleibe auf dieser Fassung");
}

static void probation_boot(void)
{
    Preferences p;
    p.begin("otaprob", false);
    bool trial = p.getBool("trial", false);
    String prev = p.getString("prev", "");
    int boots = p.getInt("boots", 0);
    p.end();
    if (!trial) return;
    const esp_partition_t *run = esp_ota_get_running_partition();
    if (prev.length() == 0 || prev == run->label) {   // nie umgeschaltet oder schon zurueck
        probation_clear();
        return;
    }
    boots++;
    Serial.printf("[ota] Probezeit, Start %d von 3 ohne Bestaetigung\n", boots);
    if (boots >= 3) rollback(prev);
    p.begin("otaprob", false);
    p.putInt("boots", boots);
    p.end();
    s_probation = true;
}

static void probation_loop(void)
{
    if (!s_probation) return;
    if (s_confirm_req) {
        s_probation = false;
        probation_clear();
        esp_ota_mark_app_valid_cancel_rollback();
        Serial.println("[ota] neue Firmware bestaetigt");
        return;
    }
    if (millis() > 5UL * 60 * 1000) {
        Preferences p;
        p.begin("otaprob", true);
        String prev = p.getString("prev", "");
        p.end();
        rollback(prev);
        s_probation = false;
    }
}

// ---- Start und Schleife ----------------------------------------------------

static uint32_t lv_tick(void) { return millis(); }

void setup()
{
    Serial.begin(115200);
    Serial.printf("\nDesk Hub CYD %s\n", FW_VERSION);
    s_lock = xSemaphoreCreateRecursiveMutex();
    probation_boot();

    ledcSetup(BL_CHANNEL, 5000, 8);
    ledcAttachPin(TFT_BL, BL_CHANNEL);
    ledcWrite(BL_CHANNEL, 255);
    tft.init();
    tft.setRotation(3);
    tft.setSwapBytes(true);
    tft.fillScreen(TFT_BLACK);

    touchSPI.begin(TOUCH_CLK, TOUCH_MISO, TOUCH_MOSI, TOUCH_CS);
    touch.begin(touchSPI);
    touch.setRotation(3);

    lv_init();
    lv_tick_set_cb(lv_tick);
    lv_display_t *disp = lv_display_create(BREIT, HOCH);
    static uint8_t buf[BREIT * 24 * 2];   // 15 KB Zeilenpuffer, kein Vollbild
    lv_display_set_buffers(disp, buf, NULL, sizeof(buf), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(disp, flush_cb);
    lv_indev_t *indev = lv_indev_create();
    lv_indev_set_type(indev, LV_INDEV_TYPE_POINTER);
    lv_indev_set_read_cb(indev, touch_read);

    configTzTime(TZ_INFO, "pool.ntp.org");
    display_lock();
    ui_init();
    display_unlock();

    // WLAN: zuerst die Daten aus secrets.h, sonst die im NVS gespeicherten.
    WiFi.mode(WIFI_STA);
    WiFi.setHostname(HOSTNAME);
    WiFi.setAutoReconnect(true);
    if (strlen(WIFI_SSID) > 0) WiFi.begin(WIFI_SSID, WIFI_PASS);
    else WiFi.begin();
    hub_server_start();
    Serial.printf("[heap] frei %u nach dem Start\n", (unsigned)ESP.getFreeHeap());
}

void loop()
{
    static uint32_t last_tick, last_sec;
    static bool mdns_up, night_shown;
    uint32_t now = millis();

    display_lock();
    lv_timer_handler();
    if (now - last_tick >= 250) {
        last_tick = now;
        ui_tick();
    }
    display_unlock();

    if (now - last_sec >= 1000) {
        last_sec = now;
        probation_loop();
        if (WiFi.status() == WL_CONNECTED) {
            strlcpy(s_ip, WiFi.localIP().toString().c_str(), sizeof(s_ip));
            if (!mdns_up && MDNS.begin(HOSTNAME)) {
                MDNS.addService("http", "tcp", 80);
                mdns_up = true;
            }
        } else {
            s_ip[0] = 0;
        }
        // Nachtmodus aus der layout-Nachricht: aus oder gedimmte Uhr, Beruehrung weckt.
        bool woke = (int32_t)(s_wake_until - now) > 0;
        if (in_night() && !woke) {
            if (s_night_style == 1) {
                backlight(12);
                if (!night_shown) {
                    display_lock();
                    ui_show_page(P_HOME);
                    display_unlock();
                    night_shown = true;
                }
            } else {
                backlight(0);
            }
        } else {
            night_shown = false;
            backlight(255);
        }
    }
    delay(5);
}
