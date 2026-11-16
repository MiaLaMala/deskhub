# Roadmap

Ideas for Desk Hub, roughly in order of value. Each item notes how it would work.

## Integrations

- [ ] **Phone notifications and text messages.**
  - **Approach:** read phone notifications through Windows rather than talking to the phone directly. Windows' Phone Link already mirrors texts and app notifications from Android phones and iPhones into Windows notifications. The companion reads them with the `UserNotificationListener` API (Windows asks the user for permission once), and could show other PC notifications too, such as Discord or Teams.
  - **On the board:** a Messages page plus a small Home widget with the latest few texts (sender, a preview and the time), and a brief pop-up when a new one arrives.
  - **Privacy:** off by default. Options to show the sender only, to hide previews, and to pick which apps count. Message text only goes to the paired board over the LAN and isn't stored.
  - **Limits:** replying from the board isn't possible with this approach. Phone Link has no supported way for other apps to send messages, so replies stay on the phone or in Phone Link. iPhone support in Phone Link is more limited than Android.
  - **Alternative for Android:** the open KDE Connect protocol could give the companion texts, battery level and "find my phone" directly, without Phone Link. It's more work and Android-only.

## Design

- [ ] **A new, modern design language.** A deliberate visual system to replace today's midnight theme, which grew one screen at a time.
  - **Define the foundations first:**
    - colour tokens, with a dark theme and possibly a light one;
    - a type scale (one family at fixed sizes via Tiny TTF);
    - spacing and radius scales, and how surfaces get depth.
  - **Build a small set of shared components on top:** card, chip, gauge, progress bar, list row, button, empty state.
  - **Prototype in HTML first.** Mock up the screens at 800 × 480 on a PC so ideas can be compared quickly, then port the winner to LVGL.
  - **Design for the hardware.** Full-screen redraws are limited by PSRAM bandwidth (about 150 ms), so flat surfaces and few overlapping layers are cheaper than gradients and transparency. Text must stay readable from arm's length, and colours need enough contrast on this panel.
  - **Apply it everywhere:** every page, the Home widgets, the sidebar, alerts and empty states. Then refresh the README screenshots.

## Day-to-day polish

- [ ] **Calendar dot on the sidebar.** When the calendar widget isn't on Home, a small dot on the sidebar's Calendar tab shows that there's an event coming up, like the dot the AI tab gets for waiting alerts.
  - **When:** an event today that hasn't ended yet (all-day events included). The dot goes away once the day's events are over.
  - **Colour:** the colour of that event's calendar. With more than one, use the first upcoming event (the one the Calendar page lists first).
  - **Only when Home doesn't show it:** if the Up next widget is on Home, no dot. Toggling the widget in the Home layout turns the dot on or off.
  - **Implementation:** board-only. `ui_rail_set_badge(PAGE_CALENDAR, color)`, recomputed when events arrive, when the Home layout changes, and each minute (when events end).

- [ ] **Readable scrolling for any text that doesn't fit.** Today long song and video titles scroll endlessly: they slide left, jump straight back to the start and never rest. Other long text is cut off with "…": event titles, file names, calendar locations, reset times, the printer's file name, shortcut labels.
  - **One shared behaviour** for every label that overflows its space:
    - rest on the start of the text for a few seconds;
    - slide slowly left (easing in and out) until the end is fully visible;
    - rest at the end;
    - slide slowly back to the start, and repeat.
  - **Text that fits doesn't move at all.** When the text changes (a new song, a new event), the motion restarts from the beginning.
  - **Speed** depends on how far the text has to move, so long and short overflows both feel calm and stay readable.
  - **Implementation:** a small helper, `ui_marquee()`. It's an LVGL animation on the label's position inside a clipping container, using `lv_anim` with start and playback delays and an ease path. Use it everywhere text can overflow, in place of `LV_LABEL_LONG_SCROLL_CIRCULAR` and `LV_LABEL_LONG_DOT`.
  - **Redraw cost:** only the moving label's small area redraws, so it's cheap. Several moving at once on Home should still be measured with `/perf`.

- [ ] **Night mode.** The screen goes dark on a schedule, for example 11 PM to 7 AM, and a touch wakes it for a minute.
  - The 4.3B backlight is on/off only, so options are: backlight off, or a black overlay with a tiny clock.
  - Set in `config.toml`. The board keeps the schedule in NVS, so it works without the PC.

- [ ] **Start with Windows.** A `deskhub-install` command that sets the companion to start at login, hidden (`pythonw`).
  - It creates the Startup-folder shortcut, and `--remove` undoes it.
  - Setup offers it as its last step.

- [ ] **Configurator UI on the PC.** A settings window instead of editing `config.toml` and answering setup questions in a terminal.
  - **Sections:** Wi-Fi and city, pages (toggles and order), a drag-and-drop Home layout with a live preview at 800 × 480, calendars, printers, shortcut tiles (icon picker, colour, action), custom games (pick from open windows), Claude/Codex options, internet, and Steam key.
  - **How:** a small local web app served by the companion on `127.0.0.1` (no new install; opens in the default browser), editing `config.toml` with tomlkit so comments survive. Secrets still go to the Windows credential store.
  - **Apply live:** saving pushes layout, Home and tile changes to the board at once; settings that need firmware (Wi-Fi, city, units) offer **Build and flash**.
  - Opened from the tray icon's **Edit config** and by `uv run deskhub-config`.

- [ ] **Tray icon for the companion.** Show the companion running in the Windows taskbar's notification area instead of a terminal window, so it can run hidden and still be easy to control.
  - The icon shows whether the board is connected (for example, coloured when connected and grey when it isn't), with a tooltip naming the board and its IP.
  - Right-click menu: **Edit config** (opens `config.toml` in the default editor), **Run setup**, **Restart** (reloads config.toml and reconnects), **Open log**, and **Quit**.
  - Built with `pystray` (plus Pillow for the icon) on its own thread next to the asyncio loop. Restart re-reads the config in place, without a new process.
  - Pairs with **Start with Windows**: the login shortcut starts the tray version hidden (`pythonw -m deskhub --tray`).

- [ ] **Firmware updates over Wi-Fi.** Flash new builds without the USB cable.
  - Add OTA partitions (a one-time USB flash to change the partition table) and an authenticated `/firmware` upload endpoint, with an on-screen Allow/Deny prompt.
  - Setup and a `deskhub-flash` command use it when the board is reachable, and fall back to USB.

## Publishing

- [ ] **GitHub repository.**
  - Make the first commit. The repo is already initialized, and the secrets check is clean.
  - Create the GitHub repo and fill in the clone URL in the README.
  - Add a GitHub Actions workflow that builds the firmware with ESP-IDF 5.5 and runs the companion tests.

## Done

- [x] Midnight theme, sidebar navigation, configurable pages and Home widgets, slim top bar
- [x] PC stats, media, weather, Google/Apple/ICS calendars, shortcuts
- [x] Claude Code usage with live limits, the Claude logo on Home and in the sidebar
- [x] Bambu Lab printers (cloud and local), including dual-nozzle models
- [x] One-command setup (`deskhub-setup`), public README with screenshots, MIT license
- [x] Claude Code "waiting for you" alert on the Home usage card and the AI page, with Show on PC and Not now
- [x] Codex usage on the AI page and Home, with the agent picked automatically and its own logo
- [x] Timer page: presets, countdown ring, pause and reset, a "Time's up" card, and the time left on its sidebar tab
- [x] Shortcut tiles that light up for mic and speaker mute, plus a `mic` action that mutes the microphone in Windows
- [x] Steam: a Games page and Home widget with the game being played, its cover and session time, and the last 5 games to launch with a tap
- [x] Steam extras with your own Web API key: friends in game and total playtime for every game
- [x] Internet stats: a Network page and Home widget with latency, jitter, loss, outages, data used and a Cloudflare speed test
