# Roadmap

Ideas for Desk Hub, roughly in order of value. Each item notes how it would work.

## Integrations

- [ ] **Phone notifications and text messages.**
  - **Approach:** read phone notifications through Windows rather than talking to the phone directly. Windows' Phone Link already mirrors texts and app notifications from Android phones and iPhones into Windows notifications. The companion reads them with the `UserNotificationListener` API (Windows asks the user for permission once), and could show other PC notifications too, such as Discord or Teams.
  - **On the board:** a Messages page plus a small Home widget with the latest few texts (sender, a preview and the time), and a brief pop-up when a new one arrives.
  - **Privacy:** off by default. Options to show the sender only, to hide previews, and to pick which apps count. Message text only goes to the paired board over the LAN and isn't stored.
  - **Limits:** replying from the board isn't possible with this approach. Phone Link has no supported way for other apps to send messages, so replies stay on the phone or in Phone Link. iPhone support in Phone Link is more limited than Android.
  - **Alternative for Android:** the open KDE Connect protocol could give the companion texts, battery level and "find my phone" directly, without Phone Link. It's more work and Android-only.

## Day-to-day polish

- [ ] **Home as a 5 × 3 grid with sized widgets.** Replace today's two columns with a grid of 5 columns by 3 rows, so widgets fill the screen without odd gaps or squeezed cards.
  - **Sizes per widget:** each widget lists the sizes it supports, such as 1×1, 2×1, 1×2 or 2×2, and lays itself out for each. For example, weather at 1×1 shows the temperature and icon, and at 2×1 adds high, low and conditions. The clock can be 2×1 or 3×1, and Up next 2×2 or 2×3.
  - **Config:** `[home]` lists widgets with a position and size, for example `{ widget = "weather", x = 0, y = 0, w = 2, h = 1 }`. The companion checks for overlaps and unsupported sizes before sending.
  - **Cell size:** computed from the space the navigation bar leaves (beside the rail or above the dock), with one gap value, so every widget lines up.
  - **Setup and Configurator:** pick a widget, then a size from its list. The Configurator UI gets a drag-and-drop grid editor.

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

- [x] Sidebar navigation, configurable pages and Home widgets, slim top bar
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
- [x] The board sleeps with the PC: when Windows turns the monitor off, the board goes dark or shows a clock screensaver
- [x] Graphite design: flat near-black cards, an amber accent, cool data colours and the Inter font, on every page
- [x] Calendar dot on the sidebar: an event still to come today, in its calendar's colour, when Home doesn't show Up next
