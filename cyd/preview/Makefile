# Vorschau der CYD-Oberflaeche auf Linux: LVGL + UI-Code mit gcc, ohne SDL.
#   make            baut, rendert alle Seiten nach out/ und schreibt out/kontaktbogen.png
#   make test       Parser-Test mit den Beispielnachrichten aus samples/
# LVGL 9.2.2 und cJSON werden beim ersten Lauf nach build/ geholt (git).

CC      ?= gcc
BUILD   := build
UI      := ../firmware/ui
LVGL    := $(BUILD)/lvgl
CJSON   := $(BUILD)/cJSON
CFLAGS  := -O1 -g -std=gnu11 -Wall -Wno-unused-parameter -Wno-format-truncation -DCYD_PREVIEW -DLV_CONF_INCLUDE_SIMPLE \
           -I../firmware/include -I$(UI) -I$(LVGL) -I$(CJSON) -I.

UI_SRC  := $(wildcard $(UI)/*.c) $(wildcard $(UI)/fonts/*.c)
UI_OBJ  := $(patsubst $(UI)/%.c,$(BUILD)/ui/%.o,$(UI_SRC))
LV_SRC   = $(shell find $(LVGL)/src -name '*.c' 2>/dev/null)
LV_OBJ   = $(patsubst $(LVGL)/%.c,$(BUILD)/lv/%.o,$(LV_SRC))
ENV_OBJ := $(BUILD)/env.o $(BUILD)/cJSON.o

.PHONY: all render test clean
all: render

$(LVGL)/lvgl.h:
	mkdir -p $(BUILD)
	git clone --quiet --depth 1 --branch v9.2.2 https://github.com/lvgl/lvgl.git $(LVGL)

$(CJSON)/cJSON.c:
	mkdir -p $(BUILD)
	git clone --quiet --depth 1 --branch v1.7.18 https://github.com/DaveGamble/cJSON.git $(CJSON)

deps: $(LVGL)/lvgl.h $(CJSON)/cJSON.c

$(BUILD)/liblvgl.a: | deps
	$(MAKE) --no-print-directory lvgl-objs
	ar rcs $@ $(shell find $(BUILD)/lv -name '*.o')

lvgl-objs: $(LV_OBJ)

$(BUILD)/lv/%.o: $(LVGL)/%.c ../firmware/include/lv_conf.h
	@mkdir -p $(dir $@)
	@$(CC) $(CFLAGS) -w -c $< -o $@

$(BUILD)/ui/%.o: $(UI)/%.c $(wildcard $(UI)/*.h) ../firmware/include/lv_conf.h | deps
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/env.o: env.c env.h | deps
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD)/cJSON.o: | deps
	$(CC) $(CFLAGS) -w -c $(CJSON)/cJSON.c -o $@

$(BUILD)/preview: preview.c $(UI_OBJ) $(ENV_OBJ) $(BUILD)/liblvgl.a
	$(CC) $(CFLAGS) preview.c $(UI_OBJ) $(ENV_OBJ) $(BUILD)/liblvgl.a -lm -o $@

$(BUILD)/test_proto: test_proto.c $(UI_OBJ) $(ENV_OBJ) $(BUILD)/liblvgl.a
	$(CC) $(CFLAGS) test_proto.c $(UI_OBJ) $(ENV_OBJ) $(BUILD)/liblvgl.a -lm -o $@

render: $(BUILD)/preview
	./$(BUILD)/preview samples out

test: $(BUILD)/test_proto
	./$(BUILD)/test_proto samples

clean:
	rm -rf $(BUILD)/ui $(BUILD)/lv $(BUILD)/*.o $(BUILD)/*.a $(BUILD)/preview $(BUILD)/test_proto out
