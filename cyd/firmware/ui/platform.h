// Was die UI von der Umgebung braucht. Die Firmware (src/main.cpp) und die
// Vorschau (cyd/preview) setzen das jeweils um.
#pragma once

#include <stdbool.h>
#include <stdint.h>
#include <time.h>

#ifdef __cplusplus
extern "C" {
#endif

time_t plat_now(void);              // Unix-Sekunden
bool plat_time_valid(void);         // Uhr gestellt (SNTP oder time-Nachricht)
void plat_set_time(double unix_s);    // aus der time-Nachricht
uint32_t plat_millis(void);
void plat_send(const char *json);   // Text an den Begleiter, falls verbunden
bool plat_companion_online(void);   // Begleiter angemeldet
const char *plat_ip(void);          // eigene Adresse, "" ohne WLAN
void plat_ota_answer(bool allow);   // Antwort im Update-Dialog
// Nachtmodus aus der layout-Nachricht: Minuten nach Mitternacht, -1 = aus;
// style 0 = Bildschirm aus, 1 = gedimmte Uhr.
void plat_set_night(int start_min, int end_min, int style);

#ifdef __cplusplus
}
#endif
