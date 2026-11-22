// WebSocket-Server ws://<display>/ws fuer den Begleiter plus die Hilfen zum
// Pruefen aus der Ferne (/screenshot, /tap, /perf) und Firmware ueber WLAN
// (/firmware). Aufbau wie firmware/main/hub_server.c und ota.c des Originals,
// angepasst an Arduino-ESP32 2.x (ESP-IDF 4.4, ohne PSRAM).
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <unistd.h>

#include "cJSON.h"
#include "config.h"
#include "esp_heap_caps.h"
#include "esp_http_server.h"
#include "esp_log.h"
#include "esp_ota_ops.h"
#include "esp_system.h"
#include "esp_timer.h"
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "hub_proto.h"
#include "ui.h"

static const char *TAG = "server";

#define MAX_FRAME (24 * 1024)    // groesste Nachricht (events mit 16 Terminen ~4 KB)
#define PREAUTH_MAX 256
#define W 320
#define H 240

static httpd_handle_t s_server;
static volatile int s_client = -1;

// ---- Nachrichten -----------------------------------------------------------

static void on_text(int fd, const char *text)
{
    cJSON *m = cJSON_Parse(text);
    if (!m) {
        ESP_LOGW(TAG, "kaputtes JSON");
        return;
    }
    if (proto_is_hello(m)) {
        if (proto_hello_ok(m, HUB_TOKEN)) {
            // Wie im Original gilt nur eine Verbindung: die alte geht zu.
            if (s_client >= 0 && s_client != fd) httpd_sess_trigger_close(s_server, s_client);
            s_client = fd;
            ESP_LOGI(TAG, "Begleiter angemeldet (fd %d)", fd);
            char reply[96];
            proto_hello_reply(reply, sizeof(reply), FW_VERSION);
            hub_server_send(reply);
            ota_probation_confirm();
        } else {
            ESP_LOGW(TAG, "falsches Token von fd %d", fd);
            httpd_sess_trigger_close(s_server, fd);
        }
    } else if (fd == s_client) {
        display_lock();
        proto_dispatch(m);
        display_unlock();
    }
    // Alles vor dem hello wird ignoriert.
    cJSON_Delete(m);
}

static esp_err_t ws_handler(httpd_req_t *req)
{
    if (req->method == HTTP_GET) return ESP_OK;   // Handshake
    httpd_ws_frame_t frame = {0};
    esp_err_t err = httpd_ws_recv_frame(req, &frame, 0);
    if (err != ESP_OK) return err;
    if (frame.len == 0 || frame.len > MAX_FRAME) return frame.len ? ESP_FAIL : ESP_OK;
    int fd = httpd_req_to_sockfd(req);
    if (fd != s_client && frame.len > PREAUTH_MAX) return ESP_FAIL;
    uint8_t *buf = malloc(frame.len + 1);
    if (!buf) return ESP_ERR_NO_MEM;
    frame.payload = buf;
    err = httpd_ws_recv_frame(req, &frame, frame.len);
    if (err == ESP_OK && frame.type == HTTPD_WS_TYPE_TEXT) {
        buf[frame.len] = 0;
        on_text(fd, (const char *)buf);
    }
    free(buf);
    return err;
}

static void on_close(httpd_handle_t hd, int fd)
{
    (void)hd;
    if (fd == s_client) {
        s_client = -1;
        ESP_LOGI(TAG, "Begleiter getrennt");
    }
    close(fd);
}

typedef struct {
    int fd;
    size_t len;
    char data[];
} send_job_t;

static void send_work(void *arg)
{
    send_job_t *job = arg;
    if (job->fd == s_client && job->fd >= 0) {
        httpd_ws_frame_t f = {
            .final = true,
            .type = HTTPD_WS_TYPE_TEXT,
            .payload = (uint8_t *)job->data,
            .len = job->len,
        };
        httpd_ws_send_frame_async(s_server, job->fd, &f);
    }
    free(job);
}

void hub_server_send(const char *json)
{
    int fd = s_client;
    if (!s_server || fd < 0) return;
    size_t len = strlen(json);
    send_job_t *job = malloc(sizeof(send_job_t) + len + 1);
    if (!job) return;
    job->fd = fd;
    job->len = len;
    memcpy(job->data, json, len + 1);
    if (httpd_queue_work(s_server, send_work, job) != ESP_OK) free(job);
}

bool hub_server_online(void)
{
    return s_client >= 0;
}

// ---- Hilfen: /screenshot, /tap, /perf (alle mit ?token=) ---------------------

static bool token_ok(httpd_req_t *req, char *query, size_t qlen)
{
    char token[64];
    if (httpd_req_get_url_query_str(req, query, qlen) != ESP_OK ||
        httpd_query_key_value(query, "token", token, sizeof(token)) != ESP_OK || strcmp(token, HUB_TOKEN) != 0) {
        httpd_resp_send_err(req, HTTPD_403_FORBIDDEN, "bad token");
        return false;
    }
    return true;
}

static void put32(uint8_t *p, uint32_t v)
{
    p[0] = v; p[1] = v >> 8; p[2] = v >> 16; p[3] = v >> 24;
}

// BMP 320 x 240, 24 Bit. Kein Vollbildpuffer: je 8 Zeilen aus dem Panel lesen
// (unter der LVGL-Sperre) und sofort senden. BMP-Zeilen laufen von unten nach oben.
static esp_err_t screenshot_handler(httpd_req_t *req)
{
    char query[128];
    if (!token_ok(req, query, sizeof(query))) return ESP_OK;
    enum { ROWS = 8 };
    uint16_t *px = malloc(W * ROWS * 2);
    uint8_t *out = malloc(W * 3 * ROWS);
    if (!px || !out) {
        free(px);
        free(out);
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "no memory");
    }
    uint8_t hdr[54] = {'B', 'M'};
    uint32_t row = W * 3, img = row * H;
    put32(hdr + 2, 54 + img);
    put32(hdr + 10, 54);
    put32(hdr + 14, 40);
    put32(hdr + 18, W);
    put32(hdr + 22, H);
    hdr[26] = 1;
    hdr[28] = 24;
    put32(hdr + 34, img);
    httpd_resp_set_type(req, "image/bmp");
    esp_err_t err = httpd_resp_send_chunk(req, (const char *)hdr, sizeof(hdr));
    for (int top = H - ROWS; top >= 0 && err == ESP_OK; top -= ROWS) {
        display_lock();
        panel_read_rows(top, ROWS, px);
        display_unlock();
        for (int r = 0; r < ROWS; r++) {
            const uint16_t *src = px + (ROWS - 1 - r) * W;   // unterste Zeile zuerst
            uint8_t *dst = out + r * row;
            for (int x = 0; x < W; x++) {
                uint16_t p = (uint16_t)((src[x] << 8) | (src[x] >> 8));   // Panel liefert Big Endian
                dst[3 * x + 0] = (p & 0x1f) << 3;
                dst[3 * x + 1] = ((p >> 5) & 0x3f) << 2;
                dst[3 * x + 2] = (p >> 11) << 3;
            }
        }
        err = httpd_resp_send_chunk(req, (const char *)out, row * ROWS);
    }
    free(px);
    free(out);
    if (err == ESP_OK) httpd_resp_send_chunk(req, NULL, 0);
    return err;
}

static esp_err_t tap_handler(httpd_req_t *req)
{
    char query[128], v[8];
    if (!token_ok(req, query, sizeof(query))) return ESP_OK;
    int x = -1, y = -1;
    if (httpd_query_key_value(query, "x", v, sizeof(v)) == ESP_OK) x = atoi(v);
    if (httpd_query_key_value(query, "y", v, sizeof(v)) == ESP_OK) y = atoi(v);
    if (x < 0 || y < 0 || x >= W || y >= H) return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "x/y out of range");
    touch_inject(x, y);
    return httpd_resp_sendstr(req, "ok\n");
}

static esp_err_t perf_handler(httpd_req_t *req)
{
    char query[128], buf[200];
    if (!token_ok(req, query, sizeof(query))) return ESP_OK;
    display_lock();
    const char *page = ui_page_name(ui_current_page());
    display_unlock();
    snprintf(buf, sizeof(buf),
             "{\"heap_free\":%u,\"heap_min\":%u,\"uptime_s\":%lu,\"version\":\"%s\",\"rssi\":%d,\"page\":\"%s\"}\n",
             (unsigned)esp_get_free_heap_size(), (unsigned)esp_get_minimum_free_heap_size(),
             (unsigned long)(esp_timer_get_time() / 1000000), FW_VERSION, wifi_rssi(), page);
    httpd_resp_set_type(req, "application/json");
    return httpd_resp_sendstr(req, buf);
}

static esp_err_t root_handler(httpd_req_t *req)
{
    httpd_resp_set_type(req, "text/plain");
    return httpd_resp_sendstr(req, hub_server_online() ? "Desk Hub CYD: Begleiter verbunden\n"
                                                       : "Desk Hub CYD: warte auf Begleiter\n");
}

// ---- Firmware ueber WLAN ---------------------------------------------------
//
// Wie im Original: erst fragen (Installieren / Ablehnen, 60 s), dann schreiben.
// Arduino-ESP32 2.x (IDF 4.4) kennt httpd_req_async_handler_begin noch nicht, also
// wartet der Handler selbst. Solange steht der HTTP-Server (auch der WebSocket);
// die Oberflaeche laeuft in loop() weiter und nimmt die Antwort an.

#define ANSWER_TIMEOUT_MS 60000
#define CHUNK 4096
enum { ANSWER_NONE, ANSWER_ALLOW, ANSWER_DENY };
static volatile int s_answer;

void plat_ota_answer(bool allow)
{
    s_answer = allow ? ANSWER_ALLOW : ANSWER_DENY;
}

static void ui_msg(const char *text)
{
    display_lock();
    ui_update_message(text);
    display_unlock();
}

static void ui_hide_later(void)
{
    vTaskDelay(pdMS_TO_TICKS(3000));
    display_lock();
    ui_update_hide();
    display_unlock();
}

static esp_err_t firmware_handler(httpd_req_t *req)
{
    char query[128];
    if (!token_ok(req, query, sizeof(query))) return ESP_OK;
    const esp_partition_t *part = esp_ota_get_next_update_partition(NULL);
    if (!part) return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "no OTA slot");
    if (req->content_len < 64 * 1024 || req->content_len > part->size)
        return httpd_resp_send_err(req, HTTPD_400_BAD_REQUEST, "image size looks wrong");

    s_answer = ANSWER_NONE;
    display_wake();
    display_lock();
    ui_update_show();
    display_unlock();
    int waited = 0;
    while (s_answer == ANSWER_NONE && waited < ANSWER_TIMEOUT_MS) {
        vTaskDelay(pdMS_TO_TICKS(100));
        waited += 100;
    }
    if (s_answer != ANSWER_ALLOW) {
        bool denied = s_answer == ANSWER_DENY;
        ESP_LOGW(TAG, "Update %s", denied ? "abgelehnt" : "nicht beantwortet");
        display_lock();
        ui_update_hide();
        display_unlock();
        httpd_resp_set_status(req, denied ? "403 Forbidden" : "408 Request Timeout");
        return httpd_resp_sendstr(req, denied ? "denied on the board" : "nobody answered on the board");
    }

    esp_ota_handle_t h = 0;
    char *buf = malloc(CHUNK);
    if (!buf || esp_ota_begin(part, OTA_SIZE_UNKNOWN, &h) != ESP_OK) {
        free(buf);
        ui_msg("Update fehlgeschlagen: kein Platz");
        ui_hide_later();
        return httpd_resp_send_err(req, HTTPD_500_INTERNAL_SERVER_ERROR, "can't start the update");
    }
    ESP_LOGI(TAG, "schreibe %d Bytes nach %s", req->content_len, part->label);
    size_t left = req->content_len, total = req->content_len;
    int last_pct = -1, timeouts = 0;
    esp_err_t err = ESP_OK;
    while (left > 0) {
        int n = httpd_req_recv(req, buf, left < CHUNK ? left : CHUNK);
        if (n == HTTPD_SOCK_ERR_TIMEOUT && ++timeouts < 5) continue;
        if (n <= 0) { err = ESP_FAIL; break; }
        timeouts = 0;
        if ((err = esp_ota_write(h, buf, n)) != ESP_OK) break;
        left -= n;
        int pct = (int)((total - left) * 100 / total);
        if (pct / 5 != last_pct / 5) {
            last_pct = pct;
            display_lock();
            ui_update_progress(pct);
            display_unlock();
        }
    }
    free(buf);
    if (err == ESP_OK) err = esp_ota_end(h);   // prueft das Image
    else esp_ota_abort(h);
    if (err == ESP_OK) {
        // Probezeit vormerken, bevor umgeschaltet wird.
        ota_probation_arm(esp_ota_get_running_partition()->label);
        err = esp_ota_set_boot_partition(part);
    }
    if (err != ESP_OK) {
        ESP_LOGE(TAG, "Update fehlgeschlagen: %s", esp_err_to_name(err));
        // Nichts umgeschaltet: der Merker zeigt auf die laufende Partition und
        // wird beim naechsten Start verworfen.
        ui_msg(err == ESP_ERR_OTA_VALIDATE_FAILED ? "Update fehlgeschlagen: kein gültiges Image" : "Update fehlgeschlagen");
        ui_hide_later();
        httpd_resp_set_status(req, err == ESP_ERR_OTA_VALIDATE_FAILED ? "400 Bad Request" : "500 Internal Server Error");
        return httpd_resp_sendstr(req, esp_err_to_name(err));
    }
    ui_msg("Neustart mit der neuen Firmware");
    httpd_resp_sendstr(req, "installed; restarting");
    vTaskDelay(pdMS_TO_TICKS(1500));
    esp_restart();
    return ESP_OK;
}

void hub_server_start(void)
{
    httpd_config_t cfg = HTTPD_DEFAULT_CONFIG();
    cfg.stack_size = 8192;
    cfg.close_fn = on_close;
    cfg.lru_purge_enable = true;
    cfg.max_open_sockets = 4;
    cfg.max_uri_handlers = 8;
    if (httpd_start(&s_server, &cfg) != ESP_OK) {
        ESP_LOGE(TAG, "HTTP-Server startet nicht");
        return;
    }
    static const httpd_uri_t uris[] = {
        {.uri = "/ws", .method = HTTP_GET, .handler = ws_handler, .is_websocket = true},
        {.uri = "/", .method = HTTP_GET, .handler = root_handler},
        {.uri = "/screenshot", .method = HTTP_GET, .handler = screenshot_handler},
        {.uri = "/tap", .method = HTTP_GET, .handler = tap_handler},
        {.uri = "/perf", .method = HTTP_GET, .handler = perf_handler},
        {.uri = "/firmware", .method = HTTP_POST, .handler = firmware_handler},
    };
    for (size_t i = 0; i < sizeof(uris) / sizeof(uris[0]); i++) httpd_register_uri_handler(s_server, &uris[i]);
    ESP_LOGI(TAG, "lauscht auf :80");
}
