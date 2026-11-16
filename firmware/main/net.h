#pragma once

#include <stdbool.h>

// Connects to Wi-Fi, starts SNTP and advertises <hostname>.local over mDNS.
void net_start(void);
bool net_connected(void);
bool net_time_valid(void);
const char *net_ip(void);
