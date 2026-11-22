// Umgebung der Vorschau: Plattform-Funktionen ohne Geraet, LVGL-Anzeige in einen
// Puffer, PNG schreiben. Genutzt von preview.c und test_proto.c.
#include "env.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "lvgl.h"
#include "ui.h"

double g_now = SAMPLE_NOW;
uint32_t g_ms = 1000;
bool g_online;
bool g_time_valid = true;
const char *g_ip = "192.0.2.23";   // Dokumentationsadresse, kein echtes Netz
char g_sent[16][128];
int g_sent_count;
int g_ota_answer = -1;
uint16_t g_fb[SCR_W_ * SCR_H_];

time_t plat_now(void) { return (time_t)g_now; }
bool plat_time_valid(void) { return g_time_valid; }
void plat_set_time(double t) { g_now = t; g_time_valid = true; }
uint32_t plat_millis(void) { return g_ms; }
bool plat_companion_online(void) { return g_online; }
const char *plat_ip(void) { return g_ip; }
void plat_ota_answer(bool allow) { g_ota_answer = allow; }
void plat_set_night(int s, int e, int style) { (void)s; (void)e; (void)style; }

void plat_send(const char *json)
{
    if (!g_online) return;
    if (g_sent_count < 16) strncpy(g_sent[g_sent_count++], json, 127);
}

static uint32_t tick_cb(void) { return g_ms; }

static void flush_cb(lv_display_t *d, const lv_area_t *a, uint8_t *px)
{
    const uint16_t *src = (const uint16_t *)px;
    int w = a->x2 - a->x1 + 1;
    for (int y = a->y1; y <= a->y2; y++)
        memcpy(&g_fb[y * SCR_W_ + a->x1], src + (y - a->y1) * w, w * 2);
    lv_display_flush_ready(d);
}

static lv_display_t *s_disp;

void env_init(void)
{
    setenv("TZ", "CET-1CEST,M3.5.0,M10.5.0/3", 1);
    tzset();
    lv_init();
    lv_tick_set_cb(tick_cb);
    s_disp = lv_display_create(SCR_W_, SCR_H_);
    // Wie auf dem Geraet: Teilpuffer mit 24 Zeilen.
    static uint8_t buf[SCR_W_ * 24 * 2];
    lv_display_set_buffers(s_disp, buf, NULL, sizeof(buf), LV_DISPLAY_RENDER_MODE_PARTIAL);
    lv_display_set_flush_cb(s_disp, flush_cb);
    ui_init();
}

void env_render(void)
{
    // Ein paar Takte, damit Timer und Neuzeichnen durchlaufen.
    for (int i = 0; i < 3; i++) {
        g_ms += 5;
        ui_tick();
        lv_timer_handler();
    }
    lv_obj_invalidate(lv_screen_active());
    lv_obj_invalidate(lv_layer_top());
    lv_refr_now(s_disp);
}

bool env_feed_file(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "fehlt: %s\n", path); return false; }
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc(n + 1);
    if (fread(buf, 1, n, f) != (size_t)n) { fclose(f); free(buf); return false; }
    buf[n] = 0;
    fclose(f);
    bool ok = proto_handle_text(buf);
    free(buf);
    return ok;
}

cJSON *env_load_json(const char *path)
{
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    fseek(f, 0, SEEK_END);
    long n = ftell(f);
    fseek(f, 0, SEEK_SET);
    char *buf = malloc(n + 1);
    size_t r = fread(buf, 1, n, f);
    buf[r] = 0;
    fclose(f);
    cJSON *j = cJSON_Parse(buf);
    free(buf);
    return j;
}

// ---- PNG ohne zlib: unkomprimierte Deflate-Bloecke ----------------------------

static uint32_t crc_table[256];

static uint32_t crc(const uint8_t *p, size_t n, uint32_t c)
{
    if (!crc_table[1])
        for (uint32_t i = 0; i < 256; i++) {
            uint32_t k = i;
            for (int j = 0; j < 8; j++) k = k & 1 ? 0xedb88320u ^ (k >> 1) : k >> 1;
            crc_table[i] = k;
        }
    c ^= 0xffffffffu;
    while (n--) c = crc_table[(c ^ *p++) & 0xff] ^ (c >> 8);
    return c ^ 0xffffffffu;
}

static void be32(uint8_t *p, uint32_t v) { p[0] = v >> 24; p[1] = v >> 16; p[2] = v >> 8; p[3] = v; }

static void chunk(FILE *f, const char *type, const uint8_t *data, size_t n)
{
    uint8_t h[8];
    be32(h, (uint32_t)n);
    memcpy(h + 4, type, 4);
    fwrite(h, 1, 8, f);
    if (n) fwrite(data, 1, n, f);
    uint32_t c = crc((const uint8_t *)type, 4, 0);
    c = crc(data, n, c);
    be32(h, c);
    fwrite(h, 1, 4, f);
}

bool png_write_rgb(const char *path, const uint8_t *rgb, int w, int h)
{
    FILE *f = fopen(path, "wb");
    if (!f) return false;
    static const uint8_t sig[8] = {0x89, 'P', 'N', 'G', '\r', '\n', 0x1a, '\n'};
    fwrite(sig, 1, 8, f);
    uint8_t ihdr[13];
    be32(ihdr, w);
    be32(ihdr + 4, h);
    ihdr[8] = 8; ihdr[9] = 2; ihdr[10] = 0; ihdr[11] = 0; ihdr[12] = 0;
    chunk(f, "IHDR", ihdr, 13);
    size_t raw_n = (size_t)(w * 3 + 1) * h;
    uint8_t *raw = malloc(raw_n);
    for (int y = 0; y < h; y++) {
        raw[y * (w * 3 + 1)] = 0;
        memcpy(raw + y * (w * 3 + 1) + 1, rgb + (size_t)y * w * 3, w * 3);
    }
    size_t blocks = (raw_n + 65534) / 65535;
    size_t z_n = 2 + raw_n + blocks * 5 + 4;
    uint8_t *z = malloc(z_n), *p = z;
    *p++ = 0x78; *p++ = 0x01;
    uint32_t a = 1, b = 0;
    for (size_t i = 0; i < raw_n; i++) { a = (a + raw[i]) % 65521; b = (b + a) % 65521; }
    for (size_t off = 0; off < raw_n; off += 65535) {
        size_t len = raw_n - off < 65535 ? raw_n - off : 65535;
        *p++ = off + len >= raw_n ? 1 : 0;
        *p++ = len & 0xff; *p++ = len >> 8;
        *p++ = ~len & 0xff; *p++ = (~len >> 8) & 0xff;
        memcpy(p, raw + off, len);
        p += len;
    }
    be32(p, (b << 16) | a);
    p += 4;
    chunk(f, "IDAT", z, p - z);
    chunk(f, "IEND", NULL, 0);
    free(raw);
    free(z);
    fclose(f);
    return true;
}

void fb_to_rgb(uint8_t *rgb)
{
    for (int i = 0; i < SCR_W_ * SCR_H_; i++) {
        uint16_t c = g_fb[i];
        rgb[3 * i + 0] = (uint8_t)(((c >> 11) & 0x1f) * 255 / 31);
        rgb[3 * i + 1] = (uint8_t)(((c >> 5) & 0x3f) * 255 / 63);
        rgb[3 * i + 2] = (uint8_t)((c & 0x1f) * 255 / 31);
    }
}
