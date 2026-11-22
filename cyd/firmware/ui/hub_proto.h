// Parser fuer die Nachrichten des Begleiters (nach dem hello).
// Die uebernommenen Typen sind aus firmware/main/hub_server.c portiert.
#pragma once

#include <stdbool.h>
#include <stddef.h>
#include "cJSON.h"

#ifdef __cplusplus
extern "C" {
#endif

// Verarbeitet eine angemeldete Nachricht mit Feld "type". Gibt false zurueck,
// wenn der Typ unbekannt ist (wird ignoriert). Aufruf unter der LVGL-Sperre.
bool proto_dispatch(const cJSON *m);

// Anmeldung: {"type":"hello","token":"..."}. true, wenn Typ hello und Token stimmt.
bool proto_is_hello(const cJSON *m);
bool proto_hello_ok(const cJSON *m, const char *token);
// Antwort auf ein gueltiges hello: {"type":"hello_ok","version":"..","board":"cyd"}
void proto_hello_reply(char *buf, size_t n, const char *version);

// Bequem fuer Vorschau und Test: Text parsen und verarbeiten.
bool proto_handle_text(const char *json);

#ifdef __cplusplus
}
#endif
