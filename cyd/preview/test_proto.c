// Test der Parser: je eine Beispielnachricht jedes Typs aus cyd/PROTOKOLL.md,
// danach die Werte im Modell pruefen. Laeuft in der Vorschau-Umgebung (gleiche
// Parser und UI wie auf dem Geraet). Aufruf: make -C cyd/preview test
#include <math.h>
#include <stdio.h>
#include <string.h>

#include "env.h"
#include "lvgl.h"
#include "ui.h"
#include "ui_internal.h"

static int s_fail, s_ok;
static const char *S = "samples";

#define CHECK(cond) do { if (cond) s_ok++; else { s_fail++; printf("  FEHLER %s:%d: %s\n", __FILE__, __LINE__, #cond); } } while (0)
#define NEAR(a, b) (fabs((double)(a) - (double)(b)) < 0.01)

static bool feed(const char *name)
{
    char p[256];
    snprintf(p, sizeof(p), "%s/%s.json", S, name);
    return env_feed_file(p);
}

static cJSON *load(const char *name)
{
    char p[256];
    snprintf(p, sizeof(p), "%s/%s.json", S, name);
    return env_load_json(p);
}

static bool sent(const char *needle)
{
    for (int i = 0; i < g_sent_count; i++) if (strstr(g_sent[i], needle)) return true;
    return false;
}

int main(int argc, char **argv)
{
    if (argc > 1) S = argv[1];
    env_init();
    const double NOW = SAMPLE_NOW;

    printf("hello\n");
    {
        cJSON *h = load("hello");
        CHECK(h != NULL);
        CHECK(proto_is_hello(h));
        CHECK(proto_hello_ok(h, "beispiel-token"));
        CHECK(!proto_hello_ok(h, "falsch"));
        CHECK(!proto_hello_ok(h, ""));
        char reply[96];
        proto_hello_reply(reply, sizeof(reply), "0.1.0");
        cJSON *r = cJSON_Parse(reply);
        CHECK(r && !strcmp(cJSON_GetObjectItem(r, "type")->valuestring, "hello_ok"));
        CHECK(r && !strcmp(cJSON_GetObjectItem(r, "version")->valuestring, "0.1.0"));
        CHECK(r && !strcmp(cJSON_GetObjectItem(r, "board")->valuestring, "cyd"));
        cJSON_Delete(r);
        // hello geht nicht durch den Nachrichten-Parser (das macht der Server).
        CHECK(!proto_dispatch(h));
        cJSON_Delete(h);
    }

    printf("Display -> Begleiter: refresh, page\n");
    g_online = true;
    ui_tick();
    CHECK(sent("{\"type\":\"refresh\"}"));
    g_sent_count = 0;
    ui_show_page(P_WEATHER);
    CHECK(sent("{\"type\":\"page\",\"name\":\"weather\"}"));
    ui_show_page(P_HOME);

    printf("layout\n");
    {
        CHECK(proto_handle_text("{\"type\":\"layout\",\"pages\":[\"claude\",\"net\",\"weather\",\"bogus\"]}"));
        uint8_t o[P_COUNT];
        int n = ui_layout_get(o);
        CHECK(n == 4 && o[0] == P_HOME && o[1] == P_CLAUDE && o[2] == P_NET && o[3] == P_WEATHER);
        // Namen des Originals gehen auch.
        CHECK(proto_handle_text("{\"type\":\"layout\",\"pages\":[\"home\",\"ai\",\"network\"]}"));
        n = ui_layout_get(o);
        CHECK(n == 3 && o[1] == P_CLAUDE && o[2] == P_NET);
        CHECK(feed("layout"));
        n = ui_layout_get(o);
        CHECK(n == 8 && o[0] == P_HOME && o[1] == P_CLAUDE && o[2] == P_CALENDAR && o[3] == P_WEATHER &&
              o[4] == P_TIMER && o[5] == P_GITHUB && o[6] == P_HOMELAB && o[7] == P_NET);
    }

    printf("time\n");
    g_now = 1000;
    g_time_valid = false;
    CHECK(feed("time"));
    CHECK(g_time_valid);
    CHECK(plat_now() == (time_t)NOW);

    printf("events\n");
    CHECK(feed("events"));
    CHECK(g_event_count == 8);
    CHECK(g_event_days == 7);
    CHECK(g_events[0].all_day && !strcmp(g_events[0].title, "Müllabfuhr"));
    CHECK(g_events[1].start == 1795474800 + 10 * 3600 + 30 * 60);
    CHECK(g_events[1].end == 1795474800 + 11 * 3600 + 15 * 60);
    CHECK(!g_events[1].all_day);
    CHECK(!strcmp(g_events[1].location, "Raum 2"));
    CHECK(!strcmp(g_events[1].calendar, "Arbeit"));
    CHECK(g_events[1].color == 0x6cb4ff);
    CHECK(g_rx[P_CALENDAR] == (time_t)NOW);

    printf("ai\n");
    CHECK(feed("ai"));
    CHECK(g_claude.valid);
    CHECK(!strcmp(g_claude.provider, "claude"));
    CHECK(g_claude.has_5h && NEAR(g_claude.pct_5h, 42.4));
    CHECK(g_claude.reset_5h == (time_t)NOW + 2 * 3600 + 14 * 60);
    CHECK(g_claude.has_7d && NEAR(g_claude.pct_7d, 61.0));
    CHECK(g_claude.limits_updated == (time_t)NOW - 120);
    CHECK(!g_claude.has_block && !g_claude.has_today && g_claude.day_count == 0 && g_claude.model_count == 0);
    CHECK(g_claude.hist_count == 48);
    CHECK(NEAR(g_claude.hist_pct[47], 61.0));
    CHECK(g_claude.hist_t[0] < g_claude.hist_t[47]);
    // Mit den Teilen aus lokalen Dateien (Original-Begleiter) und ohne five_hour.
    CHECK(proto_handle_text("{\"type\":\"ai\",\"limits\":{\"seven_day\":{\"pct\":5,\"reset\":1}},"
                            "\"block\":{\"active\":true,\"tokens\":1200},\"today\":{\"tokens\":3400,\"messages\":7},"
                            "\"days\":[1,2,3],\"models\":[{\"name\":\"opus\",\"tokens\":9}]}"));
    CHECK(!g_claude.has_5h && g_claude.has_7d && g_claude.has_block && g_claude.block_active);
    CHECK(g_claude.has_today && g_claude.today_msgs == 7 && NEAR(g_claude.today_tokens, 3400));
    CHECK(g_claude.day_count == 3 && g_claude.model_count == 1 && !strcmp(g_claude.model_name[0], "opus"));
    CHECK(!strcmp(g_claude.provider, "claude"));
    CHECK(feed("ai"));

    printf("github\n");
    CHECK(feed("github"));
    CHECK(g_github.valid);
    CHECK(!strcmp(g_github.login, "beispiel"));
    CHECK(g_github.total == 1019 && g_github.streak == 12 && g_github.week == 10 && g_github.longest == 41);
    CHECK(g_github.day_count == 371);
    CHECK(g_github.start_wday == 3);
    CHECK(g_github.level[370] == 3);
    CHECK(g_github.month_count >= 12);
    CHECK(g_github.week_day_count == 3 && g_github.week_days[1] == 5);
    CHECK(g_github.commits == 812 && g_github.private_count == 90);
    CHECK(g_github.repo_count == 2 && !strcmp(g_github.repo_name[0], "deskhub"));

    printf("net\n");
    CHECK(feed("net"));
    CHECK(g_net.valid && g_net.online);
    CHECK(NEAR(g_net.latency_ms, 14.2) && NEAR(g_net.jitter_ms, 2.1) && g_net.loss_pct == 0);
    CHECK(g_net.hist_count == 60);
    CHECK(g_net.hist[17] == -1 && g_net.hist[18] == -1 && g_net.hist[44] == 142);
    CHECK(g_net.drop_at == 1795474800 - 86400 + 22 * 3600 + 14 * 60 && g_net.drop_dur_s == 184);
    CHECK(!g_net.has_speed);
    CHECK(!strcmp(g_net.ip, "192.0.2.1"));

    printf("weather\n");
    CHECK(feed("weather"));
    CHECK(g_weather.valid);
    CHECK(!strcmp(g_weather.place, "Hamburg"));
    CHECK(g_weather.updated == (time_t)NOW - 600);
    CHECK(NEAR(g_weather.temp, 7.2) && NEAR(g_weather.feels, 4.1));
    CHECK(g_weather.code == 3 && g_weather.is_day && g_weather.humidity == 81 && NEAR(g_weather.wind, 18));
    CHECK(g_weather.hour_count == 12 && g_weather.hour_code[2] == 61 && g_weather.hour_precip[4] == 80);
    CHECK(g_weather.day_count == 6 && NEAR(g_weather.day_lo[3], -3.0) && NEAR(g_weather.day_hi[5], 10.0));
    CHECK(g_weather.day_code[2] == 71 && g_weather.day_precip[0] == 70);

    printf("homelab\n");
    CHECK(feed("homelab"));
    CHECK(g_homelab.valid && g_homelab.ok);
    CHECK(g_homelab.up == 51 && g_homelab.total == 54);
    CHECK(g_homelab.down_count == 3 && !strcmp(g_homelab.down_name[0], "Nextcloud"));
    CHECK(g_homelab.down_since[0] == (time_t)NOW - 2 * 3600 - 5 * 60);
    CHECK(ui_stale_at(P_HOMELAB) == 0);
    CHECK(feed("homelab_alt"));
    CHECK(!g_homelab.ok && g_homelab.up == 53);
    CHECK(ui_stale_at(P_HOMELAB) == (time_t)NOW - 40 * 60);

    printf("unbekannt, kaputt, ping\n");
    CHECK(!proto_handle_text("{\"type\":\"stats\",\"cpu\":5}"));
    CHECK(!proto_handle_text("{kein json"));
    CHECK(proto_handle_text("{\"type\":\"ping\"}"));

    printf("Veraltet nach 15 Minuten\n");
    CHECK(ui_stale_at(P_CALENDAR) == 0);
    g_now += 16 * 60;
    CHECK(ui_stale_at(P_CALENDAR) == (time_t)NOW);
    CHECK(ui_stale_at(P_CLAUDE) == (time_t)NOW - 120);   // Limits aelter als 10 min

    printf("Alle Seiten bauen und zeichnen\n");
    for (int p = 0; p < P_COUNT; p++) { ui_show_page(p); env_render(); CHECK(ui_current_page() == p); }

    printf("\n%d Pruefungen, %d Fehler: %s\n", s_ok + s_fail, s_fail, s_fail ? "ROT" : "GRUEN");
    return s_fail ? 1 : 0;
}
