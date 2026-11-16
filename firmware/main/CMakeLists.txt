idf_component_register(
    SRCS "main.c" "board.c" "display.c" "net.c" "hub_server.c" "weather.c"
         "ui.c" "ui_home.c" "ui_stats.c" "ui_media.c" "ui_calendar.c" "ui_weather.c" "ui_shortcuts.c" "ui_claude.c" "ui_printer.c" "ui_alert.c" "ui_timer.c" "logos.c"
    INCLUDE_DIRS "."
    EMBED_FILES "fonts/MaterialIcons-Regular.ttf" "fonts/Montserrat-SemiBold.ttf"
    REQUIRES esp_lcd esp_driver_i2c esp_driver_gpio esp_wifi esp_netif esp_event nvs_flash
             esp_http_server esp_http_client esp-tls json esp_timer
)
