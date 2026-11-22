// Vorschau: baut LVGL und die UI der CYD-Firmware fuer Linux, speist die
// Beispielnachrichten aus samples/ durch dieselben Parser und schreibt fuer jede
// Seite und jeden Zustand out/<name>.png (320 x 240) plus out/kontaktbogen.png.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>

#include "env.h"
#include "lvgl.h"
#include "ui.h"

#define MAX_SHOTS 24
static char s_name[MAX_SHOTS][32];
static uint8_t *s_rgb[MAX_SHOTS];
static int s_n;
static const char *s_dir = "out";
static const char *s_samples = "samples";

// ---- Layout-Pruefung: abgeschnittene, umgebrochene, ueberlappende Texte ------

#define MAX_LABELS 160
static lv_obj_t *s_labels[MAX_LABELS];
static int s_label_n, s_problems, s_shortened;

static bool really_visible(lv_obj_t *o)
{
    for (lv_obj_t *p = o; p; p = lv_obj_get_parent(p))
        if (lv_obj_has_flag(p, LV_OBJ_FLAG_HIDDEN) || lv_obj_get_style_opa(p, 0) == LV_OPA_TRANSP) return false;
    return true;
}

static void collect(lv_obj_t *o)
{
    if (lv_obj_has_flag(o, LV_OBJ_FLAG_HIDDEN) || lv_obj_get_style_opa(o, 0) == LV_OPA_TRANSP) return;
    if (lv_obj_check_type(o, &lv_label_class) && lv_label_get_text(o)[0] && s_label_n < MAX_LABELS)
        s_labels[s_label_n++] = o;
    for (uint32_t i = 0; i < lv_obj_get_child_count(o); i++) collect(lv_obj_get_child(o, i));
}

// Scrollbarer Vorfahr (Liste): dort ist Abschneiden unten gewollt.
static lv_obj_t *scroll_parent(lv_obj_t *o)
{
    for (lv_obj_t *p = lv_obj_get_parent(o); p; p = lv_obj_get_parent(p))
        if (lv_obj_has_flag(p, LV_OBJ_FLAG_SCROLLABLE) && lv_obj_get_scroll_bottom(p) > 0) return p;
    return NULL;
}

static void problem(const char *scene, const char *what, lv_obj_t *l, lv_obj_t *other)
{
    lv_area_t a;
    lv_obj_get_coords(l, &a);
    printf("    ! %s: %s \"%s\" bei (%d,%d)-(%d,%d)", scene, what, lv_label_get_text(l), (int)a.x1, (int)a.y1,
           (int)a.x2, (int)a.y2);
    if (other) printf(" mit \"%s\"", lv_label_get_text(other));
    printf("\n");
    s_problems++;
}

static void check_layer(const char *scene, lv_obj_t *root)
{
    s_label_n = 0;
    collect(root);
    for (int i = 0; i < s_label_n; i++) {
        lv_obj_t *l = s_labels[i];
        lv_area_t a;
        lv_obj_get_coords(l, &a);
        const lv_font_t *f = lv_obj_get_style_text_font(l, 0);
        const char *txt = lv_label_get_text(l);
        int lh = lv_font_get_line_height(f);
        // Umgebrochen, obwohl einzeilig gedacht (ohne \n im Text).
        if (!strchr(txt, '\n') && lv_area_get_height(&a) > lh + lh / 2) problem(scene, "umgebrochen", l, NULL);
        // Mit "..." gekuerzt: nur melden, das ist bei langen Titeln gewollt.
        if (lv_label_get_long_mode(l) == LV_LABEL_LONG_DOT) {
            size_t tl = strlen(txt);
            if (tl > 3 && !strcmp(txt + tl - 3, "...")) {
                printf("    · %s: gekürzt \"%s\"\n", scene, txt);
                s_shortened++;
            }
        }
        // Ausserhalb des Bildschirms oder eines Vorfahren.
        lv_obj_t *sp = scroll_parent(l);
        for (lv_obj_t *p = lv_obj_get_parent(l); p; p = lv_obj_get_parent(p)) {
            lv_area_t pa;
            lv_obj_get_coords(p, &pa);
            bool vert_ok = sp != NULL;
            if (a.x1 < pa.x1 || a.x2 > pa.x2 || (!vert_ok && (a.y1 < pa.y1 || a.y2 > pa.y2))) {
                problem(scene, "abgeschnitten", l, NULL);
                break;
            }
        }
        if (!sp && (a.x1 < 0 || a.y1 < 0 || a.x2 >= SCR_W_ || a.y2 >= SCR_H_)) problem(scene, "über den Rand", l, NULL);
        // Seite: nichts darf in die Navigationsleiste reichen.
        if (root == lv_screen_active() && a.y1 < 204 && a.y2 >= 204 && !sp) problem(scene, "in der Leiste", l, NULL);
        for (int j = i + 1; j < s_label_n; j++) {
            lv_area_t b;
            // In einer Liste: nur innerhalb derselben Liste vergleichen (sie schneidet ab).
            if (scroll_parent(s_labels[j]) != sp) continue;
            lv_obj_get_coords(s_labels[j], &b);
            if (a.x1 <= b.x2 && b.x1 <= a.x2 && a.y1 <= b.y2 && b.y1 <= a.y2) {
                problem(scene, "überlappt", l, s_labels[j]);
            }
        }
    }
}

// Luft zur Navigationsleiste (y = 204): Tippziele 12 px, alles andere 10 px.
#define DOCK_Y 204
static void check_gap(const char *scene, lv_obj_t *o, bool in_page)
{
    if (lv_obj_has_flag(o, LV_OBJ_FLAG_HIDDEN) || lv_obj_get_style_opa(o, 0) == LV_OPA_TRANSP) return;
    lv_area_t a;
    lv_obj_get_coords(o, &a);
    bool is_page = lv_obj_get_parent(o) == lv_screen_active() && lv_obj_get_height(o) >= 200;
    if (in_page && a.y1 < DOCK_Y) {
        bool label = lv_obj_check_type(o, &lv_label_class);
        bool tap = lv_obj_has_flag(o, LV_OBJ_FLAG_CLICKABLE) && lv_obj_check_type(o, &lv_button_class);
        bool drawn = lv_obj_get_event_count(o) > 0 && !lv_obj_has_flag(o, LV_OBJ_FLAG_CLICKABLE) &&
                     lv_obj_get_height(o) < 120;
        bool bar = lv_obj_check_type(o, &lv_bar_class);
        int need = tap ? 12 : 10;
        int gap = DOCK_Y - (a.y2 + 1);
        // Labels: die Schrift reicht nicht bis zur Unterkante der Zeile (Unterlaenge).
        if ((label && lv_label_get_text(o)[0]) || tap || drawn || bar) {
            if (gap < need) {
                printf("    ! %s: nur %d px über der Leiste (%s, %d,%d-%d,%d)%s%s\n", scene, gap,
                       tap ? "Tippziel" : label ? "Text" : bar ? "Balken" : "Grafik", (int)a.x1, (int)a.y1,
                       (int)a.x2, (int)a.y2, label ? " " : "", label ? lv_label_get_text(o) : "");
                s_problems++;
            }
        }
        if (label || tap) return;
    }
    for (uint32_t i = 0; i < lv_obj_get_child_count(o); i++)
        check_gap(scene, lv_obj_get_child(o, i), in_page || is_page);
}

static void check_layout(const char *scene)
{
    bool overlay = lv_obj_get_child_count(lv_layer_top()) > 0;
    bool overlay_vis = false;
    for (uint32_t i = 0; i < lv_obj_get_child_count(lv_layer_top()); i++)
        if (really_visible(lv_obj_get_child(lv_layer_top(), i))) overlay_vis = true;
    if (overlay && overlay_vis) check_layer(scene, lv_layer_top());
    else {
        check_layer(scene, lv_screen_active());
        check_gap(scene, lv_screen_active(), false);
    }
}

static void shot(const char *name)
{
    env_render();
    check_layout(name);
    uint8_t *rgb = malloc(SCR_W_ * SCR_H_ * 3);
    fb_to_rgb(rgb);
    char path[256];
    snprintf(path, sizeof(path), "%s/%s.png", s_dir, name);
    png_write_rgb(path, rgb, SCR_W_, SCR_H_);
    lv_mem_monitor_t m;
    lv_mem_monitor(&m);
    printf("  %-22s LVGL-Speicher belegt %5u B, Spitze %5u B von %u B\n", name,
           (unsigned)(m.total_size - m.free_size), (unsigned)m.max_used, (unsigned)m.total_size);
    if (s_n < MAX_SHOTS) {
        strncpy(s_name[s_n], name, 31);
        s_rgb[s_n++] = rgb;
    } else {
        free(rgb);
    }
}

static void feed(const char *name)
{
    char path[256];
    snprintf(path, sizeof(path), "%s/%s.json", s_samples, name);
    if (!env_feed_file(path)) { fprintf(stderr, "Beispiel %s nicht verarbeitet\n", name); exit(1); }
}

static void page(int p) { ui_show_page(p); }

// Kontaktbogen: 4 Spalten, ueber jedem Bild der Name (von LVGL gesetzt).
static void contact_sheet(void)
{
    const int cols = 4, gap = 10, cap = 22;
    int rows = (s_n + cols - 1) / cols;
    int W = cols * SCR_W_ + (cols + 1) * gap, H = rows * (SCR_H_ + cap) + (rows + 1) * gap;
    uint8_t *sheet = malloc((size_t)W * H * 3);
    for (int i = 0; i < W * H; i++) { sheet[3 * i] = 0x30; sheet[3 * i + 1] = 0x33; sheet[3 * i + 2] = 0x3a; }
    // Bildunterschriften: eigener Bildschirm mit einem Label, oberste Zeilen kopieren.
    lv_obj_t *old = lv_screen_active();
    lv_obj_t *scr = lv_obj_create(NULL);
    lv_obj_set_style_bg_color(scr, lv_color_hex(0x30333a), 0);
    lv_obj_set_style_bg_opa(scr, LV_OPA_COVER, 0);
    lv_obj_t *l = lv_label_create(scr);
    lv_obj_set_style_text_color(l, lv_color_hex(0xffffff), 0);
    lv_obj_set_pos(l, 0, 3);
    lv_screen_load(scr);
    uint8_t *caprgb = malloc(SCR_W_ * SCR_H_ * 3);
    for (int i = 0; i < s_n; i++) {
        int cx = gap + (i % cols) * (SCR_W_ + gap), cy = gap + (i / cols) * (SCR_H_ + cap + gap);
        lv_label_set_text(l, s_name[i]);
        lv_obj_invalidate(scr);
        lv_refr_now(NULL);
        fb_to_rgb(caprgb);
        for (int y = 0; y < cap; y++)
            memcpy(sheet + ((size_t)(cy + y) * W + cx) * 3, caprgb + (size_t)y * SCR_W_ * 3, SCR_W_ * 3);
        for (int y = 0; y < SCR_H_; y++)
            memcpy(sheet + ((size_t)(cy + cap + y) * W + cx) * 3, s_rgb[i] + (size_t)y * SCR_W_ * 3, SCR_W_ * 3);
    }
    lv_screen_load(old);
    char path[256];
    snprintf(path, sizeof(path), "%s/kontaktbogen.png", s_dir);
    png_write_rgb(path, sheet, W, H);
    printf("Kontaktbogen: %s (%d x %d, %d Bilder)\n", path, W, H, s_n);
    free(caprgb);
    free(sheet);
}

int main(int argc, char **argv)
{
    if (argc > 1) s_samples = argv[1];
    if (argc > 2) s_dir = argv[2];
    mkdir(s_dir, 0755);
    env_init();
    printf("Vorschau nach %s/\n", s_dir);

    // Alle Szenen relativ zur time-Nachricht der Beispieldaten (auch bei echten
    // Daten liegt dann nichts in der Zukunft).
    double t0 = SAMPLE_NOW;
    {
        char path[256];
        snprintf(path, sizeof(path), "%s/time.json", s_samples);
        cJSON *j = env_load_json(path);
        cJSON *u = j ? cJSON_GetObjectItem(j, "unix") : NULL;
        if (cJSON_IsNumber(u)) t0 = u->valuedouble;
        cJSON_Delete(j);
    }
    // 1. Ohne Begleiter: Warte-Zustand mit IP und Uhr (Uhr per SNTP, also t0).
    g_now = t0;
    g_ms = 0;
    g_online = false;
    page(P_HOME);
    shot("warten");

    // 2. Begleiter da, alle Daten.
    g_online = true;
    feed("layout");
    feed("time");
    feed("events");
    feed("ai");
    feed("weather");
    feed("homelab");
    feed("github");
    feed("net");
    page(P_HOME);     shot("home");
    page(P_CLAUDE);   shot("claude");
    page(P_CALENDAR); shot("calendar");
    ui_calendar_debug_scroll(3);
    shot("calendar_gescrollt");
    page(P_WEATHER);  shot("weather");
    {   // Frost: die laengsten Werte fuer die Detailzeilen.
        char path[256];
        snprintf(path, sizeof(path), "%s/weather.json", s_samples);
        cJSON *j = env_load_json(path);
        cJSON *now = cJSON_GetObjectItem(j, "now");
        cJSON_ReplaceItemInObject(now, "temp", cJSON_CreateNumber(-12.4));
        cJSON_ReplaceItemInObject(now, "feels", cJSON_CreateNumber(-18.6));
        cJSON_ReplaceItemInObject(now, "humidity", cJSON_CreateNumber(100));
        cJSON_ReplaceItemInObject(now, "wind", cJSON_CreateNumber(112));
        cJSON_ReplaceItemInObject(now, "code", cJSON_CreateNumber(75));
        // Stunden und Tage passend: Frost um -12 Grad, Schnee.
        static const int hcode[] = {75, 75, 73, 73, 71, 71, 71, 73, 73, 75, 75, 71};
        int k = 0;
        cJSON *it;
        cJSON_ArrayForEach(it, cJSON_GetObjectItem(j, "hours")) {
            cJSON_ReplaceItemInObject(it, "temp", cJSON_CreateNumber(-12 - k / 3));
            cJSON_ReplaceItemInObject(it, "code", cJSON_CreateNumber(hcode[k % 12]));
            cJSON_ReplaceItemInObject(it, "precip", cJSON_CreateNumber(90 - 5 * k));
            k++;
        }
        k = 0;
        cJSON_ArrayForEach(it, cJSON_GetObjectItem(j, "days")) {
            cJSON_ReplaceItemInObject(it, "min", cJSON_CreateNumber(-17 + k));
            cJSON_ReplaceItemInObject(it, "max", cJSON_CreateNumber(-9 + k));
            static const int dcode[] = {75, 73, 71, 71, 73, 3};
            cJSON_ReplaceItemInObject(it, "code", cJSON_CreateNumber(dcode[k % 6]));
            k++;
        }
        proto_dispatch(j);
        cJSON_Delete(j);
        shot("weather_frost");
        feed("weather");
    }
    ui_timer_debug(25 * 60, 17 * 60 + 42, true, false);
    page(P_TIMER);    shot("timer");
    page(P_GITHUB);   shot("github");
    page(P_HOMELAB);  shot("homelab");
    page(P_NET);      shot("net");

    // 3. Update-Dialog.
    page(P_HOME);
    ui_update_show();
    shot("update");
    ui_update_progress(45);
    shot("update_fortschritt");
    ui_update_hide();

    // 4. Timer abgelaufen: Vollbild "Zeit um".
    ui_timer_debug(5 * 60, 0, false, true);
    page(P_TIMER);
    shot("timer_zeit_um");
    ui_timer_debug(5 * 60, 5 * 60, false, false);

    // 5. Claude ohne Verlauf und ohne Token-Daten (Begleiter auf dem Pi, erste Minuten).
    {
        char path[256];
        snprintf(path, sizeof(path), "%s/ai.json", s_samples);
        cJSON *j = env_load_json(path);
        cJSON_DeleteItemFromObject(j, "history");
        cJSON_DeleteItemFromObject(cJSON_GetObjectItem(j, "limits"), "five_hour");
        proto_dispatch(j);
        cJSON_Delete(j);
        page(P_CLAUDE);
        shot("claude_ohne_verlauf");
        feed("ai");
    }

    // 6. Veraltet: Homelab-Quelle faellt zur time-Nachricht aus (letzter Stand t0 - 2 min),
    // dann 40 Minuten spaeter ohne Begleiter.
    g_online = true;
    {
        char path[256];
        snprintf(path, sizeof(path), "%s/homelab_alt.json", s_samples);
        cJSON *j = env_load_json(path);
        // Alle Zeitpunkte gleich weit verschieben: letzter Stand t0 - 2 min,
        // "seit" bleibt relativ dazu (nichts liegt in der Zukunft).
        cJSON *up = cJSON_GetObjectItem(j, "updated");
        double shift = cJSON_IsNumber(up) ? (t0 - 120) - up->valuedouble : 0;
        cJSON_ReplaceItemInObject(j, "updated", cJSON_CreateNumber(t0 - 120));
        cJSON *d;
        cJSON_ArrayForEach(d, cJSON_GetObjectItem(j, "down")) {
            cJSON *since = cJSON_GetObjectItem(d, "since");
            if (cJSON_IsNumber(since)) cJSON_SetNumberValue(since, since->valuedouble + shift);
        }
        proto_dispatch(j);
        cJSON_Delete(j);
    }
    g_now = t0 + 40 * 60;
    g_ms += 40 * 60 * 1000;
    g_online = false;
    page(P_HOME);     shot("veraltet");
    page(P_CALENDAR); shot("veraltet_kalender");
    page(P_HOMELAB);  shot("veraltet_homelab");

    printf("Layout-Prüfung: %d Probleme, %d gewollt gekürzte Texte\n", s_problems, s_shortened);
    contact_sheet();
    for (int i = 0; i < s_n; i++) free(s_rgb[i]);
    return 0;
}
