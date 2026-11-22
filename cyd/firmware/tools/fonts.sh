#!/bin/sh
# Erzeugt die LVGL-Schriften fuer die CYD-Firmware aus den Schriften des Originals
# (firmware/main/fonts). Text als Latin-1 mit ein paar Zeichen dazu, Icons nur die
# benutzten Material Icons. Aufruf aus cyd/firmware: sh tools/fonts.sh
# Braucht node (npx lv_font_conv).
set -e
cd "$(dirname "$0")/.."
SRC=../../firmware/main/fonts
OUT=ui/fonts
mkdir -p "$OUT"
CONV="npx --yes lv_font_conv@1.5.3"

# Latin-1 plus Gedankenstrich, Auslassung, Pfeile, Minus.
LATIN="0x20-0x7E,0xA0-0xFF,0x2013,0x2026,0x2191,0x2193,0x2212"

text() { # name datei groesse bereich
  $CONV --no-compress --no-prefilter --bpp 4 --size "$3" --font "$SRC/$2" -r "$4" \
    --format lvgl --lv-include lvgl.h --lv-font-name "$1" -o "$OUT/$1.c"
}

text inter_12 Inter-Medium.ttf 12 "$LATIN"
text inter_14 Inter-Medium.ttf 14 "$LATIN"
text inter_16 Inter-SemiBold.ttf 16 "$LATIN"
text inter_20 Inter-SemiBold.ttf 20 "$LATIN"
# Grosse Zahlen: Ziffern und das, was neben Zahlen steht.
text inter_28 Inter-SemiBold.ttf 28 "0x20-0x7E,0xB0,0xC4,0xD6,0xDC,0xDF,0xE4,0xF6,0xFC,0x2013,0x2212"
text inter_48 Inter-SemiBold.ttf 48 "0x20,0x25,0x2B-0x3A,0xB0,0x2013,0x2212"

# Material Icons (Codepunkte wie in firmware/main/icons.h).
NAV="0xE88A,0xE65F,0xE878,0xE430,0xE425,0xEAF5,0xE1DB,0xE80B"
WX="0xE430,0xEA46,0xE42D,0xE2BD,0xE818,0xE3EA,0xF1AD,0xEB3B,0xEBDB"
MISC="0xE62A,0xE63E,0xE648,0xE000,0xE798,0xE5D5,0xE037,0xE034,0xE042,0xE5CD,0xEFD8"
icons() { # name groesse codepunkte
  $CONV --no-compress --no-prefilter --bpp 4 --size "$2" --font "$SRC/MaterialIcons-Regular.ttf" -r "$3" \
    --format lvgl --lv-include lvgl.h --lv-font-name "$1" -o "$OUT/$1.c"
}
icons icons_16 16 "$NAV,$WX,$MISC"
icons icons_20 20 "$NAV,$MISC"
icons icons_36 36 "$WX,0xE62A"
