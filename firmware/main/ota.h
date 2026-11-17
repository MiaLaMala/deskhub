#pragma once

#include <stdbool.h>
#include "esp_http_server.h"

// POST /firmware?token=... : asks on screen, then installs the image and restarts.
void ota_register(httpd_handle_t server);
// The on-screen prompt's answer.
void ota_answer(bool allow);
// Call once the firmware has started properly, so the bootloader keeps it.
void ota_mark_valid(void);
