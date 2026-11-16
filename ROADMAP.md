# Roadmap

Ideas for Desk Hub, roughly in order of value. Each item notes how it would work.

## Usefulness

- [ ] **Codex usage, and other agents.** The same gauges as Claude, for whichever agent you use.
  - Read Codex usage from its local files (`~/.codex/`) in the companion.
  - Add a `provider` field to the `claude` message, renamed to `ai`, so the board knows which agent it is showing.
  - Add each agent's logo in `firmware/tools/make_logos.py` and pick it in `ui_agent_logo()`.

- [ ] **Timer / Pomodoro page.** It runs on the board alone and works without the PC.
  - Quick presets (5, 15, 25 minutes), a big countdown ring, pause and reset, and a full-screen "done" alert.
  - It could also show on Home as a small widget while running.

- [ ] **Shortcut tiles that light up.** Toggle tiles reflect the real state.
  - The companion reads mic mute and speaker mute from Windows every second (pycaw) and sends which tiles are "on".
  - The board highlights those tiles.

## Integrations

- [ ] **Steam: the current game and quick launch.**
  - **Now playing:** while a game runs, show it on the board with its cover art (like album art), the session time and total playtime. A Home widget and/or a section on the Stats page.
    - The companion reads the running game from Steam's registry value `HKCU\Software\Valve\Steam\RunningAppID`.
    - The name comes from the game's `appmanifest_<id>.acf`. Cover art comes from Steam's public CDN header image, resized like album covers.
  - **Quick launch:** a tile, or a strip of the last 3 to 5 games played, that starts a game on the PC.
    - Recent games and last-played times come from `userdata/<id>/config/localconfig.vdf`, locally with no API key.
    - Launching uses `steam://rungameid/<id>`.
  - Optional: show which friends are in game, via the Steam Web API with the user's own API key (opt-in).

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
- [x] Claude Code "waiting for you" alert: full-screen on the board, with Show on PC and Not now
