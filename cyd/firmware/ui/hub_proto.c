// Parser fuer die Nachrichten des Begleiters. Die uebernommenen Typen (layout,
// events, ai, github, net) sind aus firmware/main/hub_server.c portiert; time,
// weather und homelab sind neu (cyd/PROTOKOLL.md).
#include "hub_proto.h"

#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "hub_model.h"
#include "platform.h"
#include "ui.h"

// ---- Helfer (wie im Original) ----------------------------------------------

static void copy_str(char *dst, size_t n, const cJSON *obj, const char *key)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (cJSON_IsString(v) && v->valuestring) {
        strlcpy(dst, v->valuestring, n);
    } else {
        dst[0] = 0;
    }
}

static double get_num(const cJSON *obj, const char *key, double fallback)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(obj, key);
    return cJSON_IsNumber(v) ? v->valuedouble : fallback;
}

static bool get_bool(const cJSON *obj, const char *key)
{
    return cJSON_IsTrue(cJSON_GetObjectItemCaseSensitive(obj, key));
}

static uint32_t get_color(const cJSON *obj, const char *key, uint32_t fallback)
{
    const cJSON *v = cJSON_GetObjectItemCaseSensitive(obj, key);
    if (cJSON_IsString(v) && v->valuestring && v->valuestring[0] == '#') {
        return (uint32_t)strtoul(v->valuestring + 1, NULL, 16);
    }
    return fallback;
}

// ---- uebernommene Typen ----------------------------------------------------

// {"type":"layout","pages":["home","claude",...]}: Reihenfolge = Navigationsleiste.
// Anders als im Original gilt die Reihenfolge immer (PROTOKOLL.md), nicht erst mit
// "ordered":true. Die Namen des Originals ("ai", "network") gehen auch.
static void on_layout(const cJSON *m)
{
    uint8_t order[P_COUNT];
    int n = 0;
    uint32_t seen = 0;
    const cJSON *it;
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "pages")) {
        if (!cJSON_IsString(it)) continue;
        int p = ui_page_by_name(it->valuestring);
        if (p < 0 || (seen & (1u << p)) || n >= P_COUNT) continue;
        seen |= 1u << p;
        order[n++] = (uint8_t)p;
    }
    if (cJSON_IsArray(cJSON_GetObjectItemCaseSensitive(m, "pages"))) ui_set_layout(order, n);
    // Nachtmodus wie im Original: nur wenn der Begleiter ihn kennt.
    if (cJSON_GetObjectItemCaseSensitive(m, "night_start")) {
        char style[8];
        copy_str(style, sizeof(style), m, "night_style");
        plat_set_night((int)get_num(m, "night_start", -1), (int)get_num(m, "night_end", -1),
                       strcmp(style, "clock") == 0 ? 1 : 0);
    }
}

static void on_events(const cJSON *m)
{
    static hub_event_t ev[HUB_MAX_EVENTS];
    int n = 0;
    const cJSON *it;
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "events")) {
        if (n >= HUB_MAX_EVENTS) break;
        hub_event_t *e = &ev[n++];
        memset(e, 0, sizeof(*e));
        e->start = (time_t)get_num(it, "start", 0);
        e->end = (time_t)get_num(it, "end", 0);
        e->all_day = get_bool(it, "all_day");
        e->color = get_color(it, "color", 0x7c9cff);
        copy_str(e->title, sizeof(e->title), it, "title");
        copy_str(e->location, sizeof(e->location), it, "loc");
        copy_str(e->calendar, sizeof(e->calendar), it, "cal");
    }
    ui_set_events(ev, n, (int)get_num(m, "days", 7));
}

static void on_claude(const cJSON *m)
{
    static hub_claude_t c;
    memset(&c, 0, sizeof(c));
    c.valid = true;
    copy_str(c.provider, sizeof(c.provider), m, "provider");
    if (!c.provider[0]) strlcpy(c.provider, "claude", sizeof(c.provider));

    const cJSON *limits = cJSON_GetObjectItemCaseSensitive(m, "limits");
    const cJSON *w5 = cJSON_GetObjectItemCaseSensitive(limits, "five_hour");
    const cJSON *w7 = cJSON_GetObjectItemCaseSensitive(limits, "seven_day");
    c.limits_updated = (time_t)get_num(limits, "updated", 0);
    if (cJSON_IsObject(w5)) {
        c.has_5h = true;
        c.pct_5h = get_num(w5, "pct", 0);
        c.reset_5h = (time_t)get_num(w5, "reset", 0);
    }
    if (cJSON_IsObject(w7)) {
        c.has_7d = true;
        c.pct_7d = get_num(w7, "pct", 0);
        c.reset_7d = (time_t)get_num(w7, "reset", 0);
    }

    // Die Teile aus lokalen Claude-Code-Dateien fehlen beim Begleiter auf dem Pi:
    // dann bleiben has_block / has_today falsch und die Seite blendet sie aus.
    const cJSON *block = cJSON_GetObjectItemCaseSensitive(m, "block");
    c.has_block = cJSON_IsObject(block);
    c.block_active = get_bool(block, "active");
    c.block_reset = (time_t)get_num(block, "reset", 0);
    c.block_tokens = get_num(block, "tokens", 0);
    c.block_msgs = (int)get_num(block, "messages", 0);

    const cJSON *today = cJSON_GetObjectItemCaseSensitive(m, "today");
    c.has_today = cJSON_IsObject(today);
    c.today_tokens = get_num(today, "tokens", 0);
    c.today_output = get_num(today, "output", 0);
    c.today_msgs = (int)get_num(today, "messages", 0);
    c.last_hour = get_num(m, "last_hour", 0);

    const cJSON *it;
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "days")) {
        if (c.day_count >= HUB_CLAUDE_DAYS) break;
        c.days[c.day_count++] = cJSON_IsNumber(it) ? it->valuedouble : 0;
    }
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "models")) {
        if (c.model_count >= HUB_CLAUDE_MODELS) break;
        copy_str(c.model_name[c.model_count], sizeof(c.model_name[0]), it, "name");
        c.model_tokens[c.model_count] = get_num(it, "tokens", 0);
        c.model_count++;
    }
    // Neu: "history": [[unix, pct_7d], ...], hoechstens 48 Punkte; bei mehr die neuesten.
    const cJSON *hist = cJSON_GetObjectItemCaseSensitive(m, "history");
    int total = cJSON_GetArraySize(hist), skip = total > HUB_CLAUDE_HIST ? total - HUB_CLAUDE_HIST : 0, i = 0;
    cJSON_ArrayForEach(it, hist) {
        if (i++ < skip) continue;
        const cJSON *t = cJSON_GetArrayItem(it, 0), *p = cJSON_GetArrayItem(it, 1);
        if (!cJSON_IsNumber(t) || !cJSON_IsNumber(p)) continue;
        c.hist_t[c.hist_count] = (time_t)t->valuedouble;
        c.hist_pct[c.hist_count] = (float)p->valuedouble;
        c.hist_count++;
    }
    ui_set_claude(&c);
}

static void on_net(const cJSON *m)
{
    static hub_net_t n;
    memset(&n, 0, sizeof(n));
    n.valid = true;
    n.online = get_bool(m, "online");
    n.latency_ms = (float)get_num(m, "latency_ms", -1);
    n.jitter_ms = (float)get_num(m, "jitter_ms", 0);
    n.loss_pct = (int)get_num(m, "loss_pct", 0);
    const cJSON *it;
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "hist")) {
        if (n.hist_count >= HUB_NET_HIST) break;
        n.hist[n.hist_count++] = cJSON_IsNumber(it) ? (int16_t)it->valueint : -1;
    }
    n.up_since = (time_t)get_num(m, "up_since", 0);
    const cJSON *drop = cJSON_GetObjectItemCaseSensitive(m, "last_drop");
    n.drop_at = (time_t)get_num(drop, "at", 0);
    n.drop_dur_s = (int)get_num(drop, "dur_s", 0);
    n.today_bytes = get_num(m, "today_bytes", 0);
    n.month_bytes = get_num(m, "month_bytes", 0);
    const cJSON *sp = cJSON_GetObjectItemCaseSensitive(m, "speed");
    n.has_speed = cJSON_IsObject(sp);
    n.down_mbps = (float)get_num(sp, "down_mbps", 0);
    n.up_mbps = (float)get_num(sp, "up_mbps", 0);
    n.speed_ping_ms = (float)get_num(sp, "ping_ms", 0);
    n.speed_at = (time_t)get_num(sp, "at", 0);
    n.testing = get_bool(m, "testing");
    copy_str(n.ip, sizeof(n.ip), m, "ip");
    ui_set_net(&n);
}

static void on_github(const cJSON *m)
{
    static hub_github_t g;
    memset(&g, 0, sizeof(g));
    g.valid = true;
    g.accent = get_bool(m, "accent");
    g.total = (int)get_num(m, "total", 0);
    g.today = (int)get_num(m, "today", 0);
    g.week = (int)get_num(m, "week", 0);
    g.last_week = (int)get_num(m, "last_week", 0);
    g.streak = (int)get_num(m, "streak", 0);
    g.best = (int)get_num(m, "best", 0);
    g.start_wday = (int)get_num(m, "start_wday", 0) % 7;
    int shift = 0;
    const cJSON *lv = cJSON_GetObjectItemCaseSensitive(m, "levels");
    if (cJSON_IsString(lv) && lv->valuestring) {
        const char *s = lv->valuestring;
        size_t n = strlen(s);
        if (n > HUB_GH_DAYS) {
            int drop = (int)(n - HUB_GH_DAYS);
            s += drop;
            shift = (g.start_wday + drop) / 7;
            g.start_wday = (g.start_wday + drop) % 7;
            n = HUB_GH_DAYS;
        }
        for (size_t i = 0; i < n; i++) g.level[i] = s[i] >= '0' && s[i] <= '4' ? s[i] - '0' : 0;
        g.day_count = (int)n;
    }
    const cJSON *it;
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "months")) {
        if (g.month_count >= HUB_GH_MONTHS) break;
        const cJSON *col = cJSON_GetArrayItem(it, 0), *name = cJSON_GetArrayItem(it, 1);
        if (!cJSON_IsNumber(col) || !cJSON_IsString(name)) continue;
        if (col->valueint - shift < 0) continue;
        g.month_col[g.month_count] = (int16_t)(col->valueint - shift);
        strlcpy(g.month_name[g.month_count], name->valuestring, sizeof(g.month_name[0]));
        g.month_count++;
    }
    copy_str(g.login, sizeof(g.login), m, "login");
    g.longest = (int)get_num(m, "longest", 0);
    copy_str(g.best_date, sizeof(g.best_date), m, "best_date");
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "week_days")) {
        if (g.week_day_count >= 7) break;
        g.week_days[g.week_day_count++] = cJSON_IsNumber(it) ? it->valueint : 0;
    }
    int lw = 0;
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "last_week_days")) {
        if (lw >= 7) break;
        g.last_week_days[lw++] = cJSON_IsNumber(it) ? it->valueint : 0;
    }
    const cJSON *kinds = cJSON_GetObjectItemCaseSensitive(m, "kinds");
    g.commits = (int)get_num(kinds, "commits", 0);
    g.prs = (int)get_num(kinds, "prs", 0);
    g.reviews = (int)get_num(kinds, "reviews", 0);
    g.issues = (int)get_num(kinds, "issues", 0);
    g.private_count = (int)get_num(kinds, "private", 0);
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "repos")) {
        if (g.repo_count >= HUB_GH_REPOS) break;
        copy_str(g.repo_name[g.repo_count], sizeof(g.repo_name[0]), it, "name");
        g.repo_commits[g.repo_count] = (int)get_num(it, "count", 0);
        g.repo_count++;
    }
    ui_set_github(&g);
}

// ---- neue Typen ------------------------------------------------------------

// {"type":"time","unix":1795400000.25}
static void on_time(const cJSON *m)
{
    double t = get_num(m, "unix", 0);
    if (t > 1600000000.0) plat_set_time(t);
}

static void on_weather(const cJSON *m)
{
    static hub_weather_t w;
    memset(&w, 0, sizeof(w));
    copy_str(w.place, sizeof(w.place), m, "place");
    w.updated = (time_t)get_num(m, "updated", 0);
    const cJSON *now = cJSON_GetObjectItemCaseSensitive(m, "now");
    w.valid = cJSON_IsObject(now);
    w.temp = (float)get_num(now, "temp", 0);
    w.feels = (float)get_num(now, "feels", NAN);
    w.code = (int)get_num(now, "code", 3);
    w.is_day = cJSON_GetObjectItemCaseSensitive(now, "is_day") ? get_bool(now, "is_day") : true;
    w.humidity = (int)get_num(now, "humidity", -1);
    w.wind = (float)get_num(now, "wind", -1);
    const cJSON *it;
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "hours")) {
        if (w.hour_count >= HUB_HOURS) break;
        int i = w.hour_count++;
        w.hour_t[i] = (time_t)get_num(it, "t", 0);
        w.hour_temp[i] = (float)get_num(it, "temp", 0);
        w.hour_code[i] = (int)get_num(it, "code", 3);
        w.hour_precip[i] = (int)get_num(it, "precip", -1);
    }
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "days")) {
        if (w.day_count >= HUB_DAYS) break;
        int i = w.day_count++;
        w.day_t[i] = (time_t)get_num(it, "t", 0);
        w.day_lo[i] = (float)get_num(it, "min", 0);
        w.day_hi[i] = (float)get_num(it, "max", 0);
        w.day_code[i] = (int)get_num(it, "code", 3);
        w.day_precip[i] = (int)get_num(it, "precip", -1);
    }
    ui_set_weather(&w);
}

static void on_homelab(const cJSON *m)
{
    static hub_homelab_t h;
    memset(&h, 0, sizeof(h));
    h.valid = true;
    h.ok = get_bool(m, "ok");
    h.updated = (time_t)get_num(m, "updated", 0);
    h.up = (int)get_num(m, "up", 0);
    h.total = (int)get_num(m, "total", 0);
    const cJSON *it;
    cJSON_ArrayForEach(it, cJSON_GetObjectItemCaseSensitive(m, "down")) {
        if (h.down_count >= HUB_HL_DOWN) break;
        copy_str(h.down_name[h.down_count], sizeof(h.down_name[0]), it, "name");
        h.down_since[h.down_count] = (time_t)get_num(it, "since", 0);
        h.down_count++;
    }
    ui_set_homelab(&h);
}

bool proto_is_hello(const cJSON *m)
{
    char type[8];
    copy_str(type, sizeof(type), m, "type");
    return strcmp(type, "hello") == 0;
}

bool proto_hello_ok(const cJSON *m, const char *token)
{
    char got[64];
    if (!proto_is_hello(m)) return false;
    copy_str(got, sizeof(got), m, "token");
    return token && token[0] && strcmp(got, token) == 0;
}

void proto_hello_reply(char *buf, size_t n, const char *version)
{
    snprintf(buf, n, "{\"type\":\"hello_ok\",\"version\":\"%s\",\"board\":\"cyd\"}", version);
}

bool proto_dispatch(const cJSON *m)
{
    char type[24];
    copy_str(type, sizeof(type), m, "type");
    if (!strcmp(type, "layout")) on_layout(m);
    else if (!strcmp(type, "events")) on_events(m);
    else if (!strcmp(type, "ai") || !strcmp(type, "claude")) on_claude(m);
    else if (!strcmp(type, "github")) on_github(m);
    else if (!strcmp(type, "net")) on_net(m);
    else if (!strcmp(type, "time")) on_time(m);
    else if (!strcmp(type, "weather")) on_weather(m);
    else if (!strcmp(type, "homelab")) on_homelab(m);
    else if (!strcmp(type, "ping")) { /* haelt die Verbindung wach */ }
    else return false;
    return true;
}

bool proto_handle_text(const char *json)
{
    cJSON *m = cJSON_Parse(json);
    if (!m) return false;
    bool ok = proto_dispatch(m);
    cJSON_Delete(m);
    return ok;
}
