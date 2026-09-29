# Spotipy Visualizer — Spotify Now Playing Display for Raspberry Pi

**A self-hosted Spotify album art display with playback controls, automatic themes, and a clock screensaver.**

![Version 1.0.3](https://img.shields.io/badge/version-1.0.3-blue)
[![License: GPL v3](https://img.shields.io/badge/license-GPLv3-blue)](LICENSE)

Spotipy Visualizer turns a **Raspberry Pi touchscreen**, tablet browser, or Linux desktop into a fullscreen **Spotify now playing display**. Show album artwork, song titles, and artists beside touch-friendly playback controls. Build a dedicated music dashboard for your desk or hi-fi setup, with macOS-inspired and classic themes that switch between light and dark on a schedule.

Built with **Python, Flask, and Spotipy**, the app reads playback state through the **Spotify Web API** and runs locally as a Python application or Linux snap. **Music plays on your existing Spotify device**; this application displays playback information and sends control commands. It does not stream audio or generate audio-reactive visual effects.

![Spotify now playing dashboard with album artwork, shuffle, and playback controls in the macOS dark theme](docs/images/player.png)

<p align="center">
  <img src="docs/images/desktop-display-enhanced.png" width="480" alt="Dedicated Spotify display running Spotipy Visualizer in a 3D-printed Macintosh-style Raspberry Pi enclosure">
  <br>
  <em>A dedicated desktop display. Photo enhanced for clarity. The enclosure is from the <a href="https://www.printables.com/model/1259764-raspberry-pi-5-macintosh-plus">Raspberry Pi 5 Macintosh Plus model on Printables</a>.</em>
</p>

[Quick start](#quick-start) · [Spotify setup](#connect-spotify) · [Snap installation](#snap-installation) · [Themes](#themes-and-scheduling) · [FAQ](#frequently-asked-questions) · [Troubleshooting](#troubleshooting) · [License](#license-and-credit)

## Spotify display features

- Large album artwork with song, artist, album, and active device information.
- Play/pause, previous/next track, shuffle, and like/unlike controls.
- Playback progress and elapsed/total time.
- Responsive layout with touch controls and a fullscreen button.
- Four themes: macOS light/dark and classic light/dark.
- Automatic daytime/nighttime themes with configurable hours and timezone.
- A matching clock on idle startup, and after three consecutive paused/stopped playback checks later (configurable).
- Separate Spotify credentials and appearance configuration.
- Snap background service and desktop browser launcher, including a launch path for Raspberry Pi OS Trixie/Wayland.

## Build a dedicated Spotify display

- **Raspberry Pi music dashboard:** show album art and control the Spotify device already playing your music.
- **Touchscreen desk display:** use large playback buttons and fullscreen artwork beside your computer or hi-fi system.
- **Tablet or spare monitor:** open the player in a browser on your trusted local network.
- **Retro Macintosh-style project:** pair the interface with the [Raspberry Pi 5 Macintosh Plus enclosure](https://www.printables.com/model/1259764-raspberry-pi-5-macintosh-plus) shown above.

## Requirements: Spotify account, Python, and a browser

You need a modern browser, an internet connection, a Spotify developer application, and an account permitted to use that application. Spotify currently requires the app owner to have Premium for Development Mode; playback control also requires Premium. Review [Spotify's Development Mode requirements](https://developer.spotify.com/documentation/web-api/tutorials/february-2026-migration-guide) for account and access limits.

For source installation, use Python 3 with `venv` and `pip`. Development tests run with Python 3.13. For a snap installation, you need snapd and a package matching your system architecture. A physical Raspberry Pi display is optional: any browser on the trusted local network can show the player.

<a id="quick-start"></a>

## Quick start: Raspberry Pi and Linux installation

Download or clone this repository, then open a terminal in its directory. On Raspberry Pi OS/Debian, install the Python prerequisites if needed:

```sh
sudo apt update
sudo apt install python3 python3-venv python3-pip
```

Start the application:

```sh
./run_local.sh
```

This creates `.venv`, installs dependencies from `requirements.txt`, and starts the server. On first startup, configuration files are created without overwriting existing settings.

1. Complete [Spotify setup](#connect-spotify) below, editing `Flask/spotify.ini`.
2. Open **http://127.0.0.1:60123** on the server computer.
3. Click **Connect Spotify** and authorize your account.
4. Start a song in Spotify on your phone, computer, or speaker.
5. Click the fullscreen button to fill your display.

Leave the terminal running; press `Ctrl+C` to stop. For other devices on your LAN, use `http://SERVER_LAN_IP:60123`. The default listener is `0.0.0.0`; use `HOST=127.0.0.1 ./run_local.sh` for local-only access.

<a id="connect-spotify"></a>

## Connect Spotify: Web API credentials and authorization

Create an application in the [Spotify developer dashboard](https://developer.spotify.com/dashboard) and register this exact redirect URI:

```text
http://127.0.0.1:60123/auth/callback
```

Edit the configuration for your installation:

| Installation | Spotify configuration |
| --- | --- |
| Source | `Flask/spotify.ini` |
| Snap | `/var/snap/spotipy-visualizer/common/Flask/spotify.ini` |

```ini
[spotify]
client_id = YOUR_SPOTIFY_CLIENT_ID
client_secret = YOUR_SPOTIFY_CLIENT_SECRET
redirect_uri = http://127.0.0.1:60123/auth/callback
```

Add other allowed accounts to your developer app's user access list as needed. Credentials are reread on requests, so editing this file does not require a restart.

Use `127.0.0.1`, not `localhost`. Spotify permits HTTP loopback callbacks but requires HTTPS for non-loopback callbacks; see [redirect URI rules](https://developer.spotify.com/documentation/web-api/concepts/redirect_uri). If you change the server port, update both the configuration and the registered callback.

### Authorizing a headless Pi

From a computer with a browser, open an SSH tunnel:

```sh
ssh -L 60123:127.0.0.1:60123 user@SERVER_IP
```

Keep it running while you visit `http://127.0.0.1:60123` on that computer and authorize Spotify. Once connected, the display can use the server's LAN address normally.

For an HTTPS reverse proxy, register an HTTPS callback ending in `/auth/callback`, preserve the Host header, and forward `X-Forwarded-Proto: https`. Set `TRUSTED_PROXY` to the proxy's IP address.

## Snap installation

Install the locally built package matching your architecture. For example, on a 64-bit ARM system:

```sh
sudo snap install --dangerous ./spotipy-visualizer_1.0.3_arm64.snap
sudoedit /var/snap/spotipy-visualizer/common/Flask/spotify.ini
```

`--dangerous` allows installation of a local snap without a store assertion. The install hook creates **both** `spotify.ini` and `theme.conf` from their bundled examples, with mode `0600`, only when missing. Existing configurations are preserved. The hook does not start Python; snapd manages the background service.

Open **Spotipy Visualizer** from the desktop applications menu, or run:

```sh
spotipy-visualizer.desktop-launch
```

Useful service commands:

```sh
sudo snap services spotipy-visualizer
sudo snap logs spotipy-visualizer.flask-server
sudo snap restart spotipy-visualizer.flask-server
```

The launcher asks the host desktop to open its default browser using `snapctl user-open`. It requires an active desktop session, a configured browser, and the `desktop` interface. Source users can run `./shscripts/desktop-launch` after starting the server; it tries `xdg-open`, `gio open`, then installed browsers. If using a custom `PORT`, pass the same value to the server and launcher.

### Build a snap

With Snapcraft and a suitable build environment installed, run from the repository root:

```sh
snapcraft pack
```

The manifest defines version `1.0.3` and multiple target architectures. Availability of a declaration is not a claim that every architecture has been tested. Rebuild after changing code or package metadata; an existing `.snap` file does not update automatically.

`spotipy-visualizer` is a different snap identity from the earlier `spotify-visualizer` package. Its data directory is separate; moving to the new name does not automatically transfer the old package's configuration or authorization.

<a id="themes-and-scheduling"></a>

## Light and dark themes: macOS, classic, and automatic scheduling

Edit `Flask/theme.conf` for source runs, or `/var/snap/spotipy-visualizer/common/Flask/theme.conf` for snaps. See the complete [configuration template](Flask/theme.conf.example).

| Theme name | Appearance |
| --- | --- |
| `macos-light` | Light gray background, blue controls, rounded artwork |
| `macos-dark` | Dark gray background, blue controls, rounded artwork |
| `classic-light` | Light background, green accents, classic layout |
| `classic-dark` | Original dark background and green accents |

The default configuration uses light from **06:00 to 18:00**, then dark overnight:

```ini
[theme]
mode = auto
name = macos-light
light_theme = macos-light
dark_theme = macos-dark
light_start = 06:00
dark_start = 18:00
timezone =
```

- `mode = auto` selects `light_theme` or `dark_theme` using the schedule.
- `mode = manual` uses `name` all day.
- Times use 24-hour `HH:MM`. Overnight light windows are supported; equal start times mean light all day.
- A blank `timezone` uses the server/Pi's local timezone. Use an IANA name such as `Europe/Rome` to override it, including seasonal clock changes.
- Invalid times fall back to `06:00`/`18:00`; an invalid timezone falls back to server local time.

For classic automatic switching, set `light_theme = classic-light` and `dark_theme = classic-dark`. The legacy names `macos` and `classic` remain aliases for `macos-light` and `classic-dark`. Old files without `mode` retain manual selection.

Optional settings are `accent`, `background`, `foreground`, `muted`, `surface`, `border`, and `hover` (six-digit hex colors), plus `artwork_radius` (0–48 pixels). Overrides apply to both scheduled themes; leave them blank to retain each palette.

**An open player applies changes within 30 seconds**, without restarting the server or refreshing the page.

## Clock screensaver

On startup, the first confirmed paused or stopped playback result opens the clock
immediately (or the configured idle rotation). After music has played, three consecutive successful paused or stopped playback
checks open it again. Set `idle_checks = 3` (1–20) in `[idle_display]` in
`theme.conf`, or use **Settings → Idle playback checks before showing the clock**.
Missing settings are added automatically. Errors reset the pending count;
Spotify cooldowns never count as checks. Existing polling intervals stay unchanged,
so three checks typically take about two to three minutes with 60-second idle polling.
Setup and connection errors never count as confirmed idle playback. The macOS themes use thin clock
typography and a soft background; classic themes use a bolder clock and their
existing palette. The screensaver follows the same automatic light/dark schedule,
color overrides, and server/configured timezone as the player.

Music resuming returns to the player on the next playback poll (normally within the configured
idle polling interval (60 seconds by default)). Tap, click, scroll, or press a key to wake it manually;
this resets the idle-check count. The wake-up tap does not activate a
player control. Playback and theme polling continue while the clock is visible.
Setup and authorization errors open the player so you can reconnect. Temporary
connection failures and Spotify cooldowns preserve an already-visible idle display;
they do not return it to “Nothing playing.” Mouse movement alone does not dismiss it. A subtle clock drift is disabled when reduced motion is requested.

The screensaver stays inside the browser and preserves fullscreen mode. It does
not change the operating system's screen blanking or power-management settings.

## Optional stocks and Treasury yields while idle

Open **Settings** in the player header (or `/settings`) to enable idle-page
rotation. The page also displays your complete `theme.conf` in an editable field,
including theme selection, light/dark schedule, timezone, and color overrides.
Saving validates the configuration, preserves comments, and detects conflicting
changes made after loading. The theme updates on the settings page immediately
and on other open displays within 30 seconds. It starts immediately on an idle startup; later it uses the same configurable idle-check
threshold as the clock screensaver. Defaults are **disabled**, including when upgrading an existing
installation. Enabling it rotates through the clock, one rates page, and one
page per stock, in that order. Playback resuming or interaction wakes the player.

The defaults are Apple (`AAPL`), Nvidia (`NVDA`), and Ouster (`OUST`). You can
choose up to 12 Yahoo symbols, include/exclude the clock, rates, or stocks, and
adjust stocks (`page_seconds`) and Treasury rates (`rates_seconds`) independently
(default 10 seconds each, range 5–300), as well as the clock duration
(`clock_seconds`, default 30 seconds, range 5–3600). Market data refresh is separate:
default 1800 seconds (30 minutes), configurable from 300 to 86400 seconds, shared across browsers.
A background worker refreshes at server startup when enabled and then on the
configured interval, even without a browser open. Enabling rotation later starts
the worker. Browser requests read only the shared cache; page changes never call
Yahoo. Disabled rotation makes no new Yahoo requests (an in-flight request may finish).
Yahoo requests are sequential; a 429 stops the batch and pauses for at least the
configured refresh interval or Yahoo's Retry-After, whichever is longer, plus a
small buffer. This is a conservative local policy, not a published Yahoo quota.
The previous shipped 300-second refresh default upgrades to 1800 seconds when
adding the clock-duration option; other valid custom refresh values are retained; old intervals below five minutes
are raised to the new five-minute minimum.

Settings are saved in the existing `theme.conf`. Upgrades add `rates_seconds`
using your existing `page_seconds` value, preserving the current rotation timing:

```ini
[idle_display]
enabled = false
show_clock = true
show_rates = true
show_stocks = true
page_seconds = 10
rates_seconds = 10
clock_seconds = 30
refresh_seconds = 1800
symbols = AAPL,NVDA,OUST
```

On startup, missing settings are added with comments and defaults while existing
appearance settings and custom values are preserved. Open displays reread the
settings within 30 seconds. The idle-display form writes only this section; the full configuration editor
can also change the theme settings. As with
playback controls, use it on a trusted LAN. It has no separate login.

The rates page places large yields in four corners: 2Y top left, 5Y top right,
10Y bottom left, and 30Y bottom right. The rotation continues while playback
remains idle, including through temporary Spotify failures.

The rates page uses Yahoo Finance's **2-Year Yield Futures (`2YY=F`)** and
**5Y (`^FVX`), 10Y (`^TNX`), and 30Y (`^TYX`) Treasury yield indices**. These are
not the Federal Reserve's policy rate; the 2Y futures series is explicitly labeled
and is not a spot Treasury yield. See [Yahoo's 2Y series](https://finance.yahoo.com/quote/2YY%3DF/)
and [5Y yield index](https://finance.yahoo.com/quote/%5EFVX/).

Yahoo chart endpoints are accessed directly without a key. Availability may
change and quotes may be delayed. Each card shows its quote timestamp; an older
quote may reflect a closed market. Failures preserve cached values marked as
cached, or display “Unavailable” when no value is available. Yahoo 429 responses
pause refreshes. Fetches use a separate background worker and shared cache, so
market requests do not consume Spotify's request allowance. All pages inherit
the current macOS/classic palette and light/dark schedule.

## Spotify request limits and tuning

Spotify counts requests in an app-wide rolling 30-second window. The allowance
varies by quota mode, and some endpoints have additional limits. Spotify does
not publish a universal safe request count; other instances using the same
client ID share that allowance. See [Spotify rate limits](https://developer.spotify.com/documentation/web-api/concepts/rate-limits).

The `[rate_limit]` section of `spotify.ini` contains these local safety settings:

```ini
[rate_limit]
playback_poll_seconds = 15
idle_poll_seconds = 60
liked_cache_seconds = 600
max_requests_per_30_seconds = 8
control_interval_seconds = 2
retry_after_fallback_seconds = 60
retry_after_buffer_seconds = 2
```

Playback reads are cached across all browser displays connected to this server.
Playing-track progress continues locally between reads. Liked status is cached
per track; likes changed through this app update the cache immediately. Changes
made in another Spotify app may take up to the cache interval to appear.
The server tells each browser when to poll again. Paused/idle polling is slower,
so detecting playback started elsewhere can take up to 60 seconds by default.

All Web API reads and controls share the local 30-second budget. Control commands
also have a minimum interval; commands rejected by these local limits are not
queued or automatically replayed. OAuth authorization/token exchanges are separate
from this Web API budget. Separate server processes do not share the local budget.

On a Spotify HTTP 429, the server and browsers stop requesting playback/control
until `Retry-After` plus the safety buffer has elapsed, even for long cooldowns.
If the header is missing or invalid, the fallback increases on repeated 429s.
Each Spotify 429 also doubles playback/idle intervals, up to eight times the
configured values for that server session. A cooldown is saved privately in
`.spotify-rate-limit.json` and restored after a restart; restarting does not
bypass it. The last displayed track stays visible with a status message while
controls wait for the cooldown.

Increase polling/cache intervals or lower the request budget if limits recur.
The defaults reduce traffic but cannot guarantee that Spotify never returns 429.
Invalid/out-of-range values fall back to the documented defaults; see the
comments in [spotify.ini.example](Flask/spotify.ini.example) for accepted ranges.
Edits are reread on requests and do not require restarting the server.

On startup after an upgrade, missing tuning keys are added automatically with
comments and defaults. Existing credentials, custom values, comments, and other
sections are retained. Malformed configuration files are left untouched for
manual correction. The upgrade runs when the server starts, including after a
snap refresh; the install hook still preserves existing files.

### Suggested latency profiles

These are application tuning suggestions, not Spotify guarantees. Adjust the
existing `[rate_limit]` values in `spotify.ini`:

| Profile | Playing interval | Idle interval | Playing-state reads per minute, approximately |
| --- | --- | --- | --- |
| More responsive | 5 seconds | 15 seconds | 12 |
| Balanced (default) | 15 seconds | 60 seconds | 4 |
| Conservative | 30 seconds | 120 seconds | 2 |

A playback change made in another Spotify app normally appears within one poll
interval plus network time. Liked-status reads, controls, token requests, and
other instances are additional traffic; adaptive backoff can increase these
intervals. A 5-second interval may hit your quota sooner. Spotify publishes no
universal requests-per-minute ceiling or number of hours until failure. Its
rolling 30-second rate window and the actual `429`/`Retry-After` response determine
when to back off. Use your developer dashboard's request graph when tuning.

### Recovery from a display that stops updating

The browser bounds both request and response-body waits, recovers missing polling
timers, and refreshes playback when connectivity returns or the page becomes
visible again. Late responses are discarded after timeout. Theme/configuration
requests have the same protection. Recovery preserves the current page and
fullscreen state; it never automatically repeats a playback control command.
A visible countdown distinguishes a Spotify cooldown from a stuck page.

The following settings are added automatically to older configurations:

```ini
# Inside the existing [rate_limit] section:
spotify_request_timeout_seconds = 10
browser_request_timeout_seconds = 60
recovery_grace_seconds = 15
network_retry_seconds = 30
```

The Spotify timeout is a per-request connect/read inactivity timeout. The browser
uses a deadline for the complete response; its effective minimum is six times
the Spotify timeout to allow sequential token, playback, and liked-status calls.
The **Settings → Text size and display recovery** controls save these options in
`theme.conf` under `[idle_display]`. Existing files automatically receive missing
defaults while preserving your settings and comments. Open displays apply edits
within 30 seconds, including when market rotation is disabled.

```ini
recovery_enabled = true
recovery_stall_seconds = 5
stock_text_percent = 100
treasury_text_percent = 100
```

Text sizes accept 80–130%; 100% keeps the enlarged responsive default. The recovery
threshold accepts 5–120 seconds and is checked every five seconds. This switch
controls clock/market timer repair only; Spotify request recovery and cooldowns
remain active. It cannot restart a completely frozen browser.

The recovery check also repairs stopped clock and market-rotation timers, keeping
the current rotation and cached quotes. Stock prices, Treasury yields and their
labels use larger responsive text for viewing at a distance.

The recovery check runs every five seconds and repairs an idle polling loop once
its scheduled check is overdue by `recovery_grace_seconds`. It does not treat
normal idle intervals, adaptive backoff, or `Retry-After` waits as a freeze.
Recovery settings are reread by the browser every minute.

These checks recover network/request stalls while JavaScript is running. If the
browser process, graphics driver, or operating system itself has stopped,
JavaScript cannot restart it. If the clock and all controls stop responding,
check the Pi's power supply, browser process, and system logs; if the clock or
countdown is still moving, check the connection/status message first.

## Configuration and storage

| Setting | Default | Purpose |
| --- | --- | --- |
| `HOST` | `0.0.0.0` | Server listening address |
| `PORT` | `60123` | HTTP port; must match your callback configuration |
| `SNAP_COMMON` | Unset outside snaps | When set, data goes under `$SNAP_COMMON/Flask` |
| `TRUSTED_PROXY` | Unset | IP address of a trusted HTTPS reverse proxy |

Outside snaps, data lives alongside the Python application in `Flask/`. Inside snaps, data lives in `/var/snap/spotipy-visualizer/common/Flask/`, shared across revisions. Code and static assets are read from the installed package. Legacy revision-local credentials, tokens, and session keys are copied to common storage only when missing.

Credentials, `.spotify-token.json`, and `.session-key` are stored outside static assets with mode `0600`. Keep these files private and out of commits. When switching accounts or developer apps, stop the server, remove only `.spotify-token.json` from the relevant data directory, restart, and reconnect.

This is a **single-account application for a trusted LAN**. Anyone who can reach the server can view playback and use its controls. Add access control before exposing it beyond that network. Control routes reject cross-origin browser requests; OAuth uses state validation.

## Frequently asked questions

### Can I use a Raspberry Pi as a Spotify album art display?

Yes. Run Spotipy Visualizer on the Pi, connect your Spotify account, and open the
local player in a browser. A touchscreen adds direct playback controls; a regular
monitor works too. Follow the [Raspberry Pi installation steps](#quick-start).

### Does this app play music or replace Spotify Connect?

It controls an existing Spotify playback device through the Web API. It does not
stream audio, turn the Pi into a Spotify Connect receiver, or replace the Spotify
app. Start music on your phone, computer, or speaker, then use this display to
view and control playback.

### Is this an audio-reactive music visualizer?

The visualization is a now-playing dashboard with album artwork and track
information. It does not analyze audio or draw spectrum bars or waveforms.

### Does it need a Raspberry Pi or a touchscreen?

No. The server can run on another suitable Python/Linux machine, and the display
can be a desktop or tablet browser. A touchscreen and the pictured enclosure are
optional. The desktop launcher includes support for Raspberry Pi OS Trixie sessions.

### Can the display switch to a clock when Spotify is paused?

Yes. It opens immediately when startup playback is idle, or after three consecutive paused/stopped playback checks later (configurable). The [clock screensaver](#clock-screensaver) appears. It follows the selected theme,
light/dark schedule, and timezone, and wakes when playback resumes or you interact.

### Do I need Spotify Premium and my own developer app?

You need developer credentials and an authorized account. See the
[requirements](#requirements-spotify-account-python-and-a-browser) and
[Spotify setup](#connect-spotify) sections for Premium and developer-access details.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| Spotify setup message | Fill in `client_id`, `client_secret`, and a valid `redirect_uri`. |
| Login or callback fails | Match the dashboard callback exactly; use the SSH tunnel for headless setup. |
| Nothing playing / controls disabled | Start playback on a Spotify device; restricted devices can disable controls. |
| Spotify denies an action | Check Premium, developer app access, and device restrictions. |
| Theme changes at the wrong time | Check the Pi clock, timezone, `mode`, and schedule; wait up to 30 seconds. |
| Desktop launcher fails | Confirm the service is running, the desktop has a default browser, and `snap connections spotipy-visualizer` shows `desktop` connected. Try the URL directly. |
| Another device cannot connect | Check the LAN address, listener setting, and firewall access to port `60123`. |
| Rate-limit message | Let the player retry; repeated manual requests can prolong the problem. |

## Development and contributions

To install dependencies, run checks, and start the app:

```sh
./run.sh
```

To run checks without starting the server:

```sh
./run.sh --test-only
```

If dependencies are already installed:

```sh
.venv/bin/python -m unittest discover -s tests -v
```

Optional browser checks for the clock (requires Playwright and Chromium):

```sh
.venv/bin/python -m pip install playwright
.venv/bin/python tests/browser_screensaver.py
.venv/bin/python tests/browser_rate_limits.py
.venv/bin/python tests/browser_recovery.py
.venv/bin/python tests/browser_idle_market.py
```

These use mocked playback and an accelerated browser clock to verify the idle
delay, wake-up, all four palettes, timezone, touch, a small display, and browser
polling/cooldown behavior.

Tests cover playback/control routes with mocked Spotify calls, authorization checks, configuration persistence, launcher dispatch, theme palettes, and schedule boundaries. They do not replace live Spotify or Raspberry Pi desktop testing.

| Location | Contents |
| --- | --- |
| `Flask/app.py` | Application factory and Waitress startup |
| `Flask/spotify_player.py` | Spotify authorization, state, and controls |
| `Flask/theme.py` | Theme configuration and scheduled CSS |
| `Flask/static/` | Browser interface and bundled icons |
| `snap/`, `snapcraft.yaml` | Packaging, install hook, desktop entry |
| `shscripts/` | Server and desktop launchers |
| `tests/` | Automated tests |

Issues and pull requests are welcome. Include your OS, installation method, reproduction steps, and relevant logs with credentials and tokens removed. For UI changes, include screenshots; for behavior changes, run the tests and describe what you verified.

## License and credit

Copyright © 2020–2026 [mauringo](https://github.com/mauringo).

The current project is licensed under **GNU GPL version 3 only** (`GPL-3.0-only`); see [LICENSE](LICENSE) and [NOTICE](NOTICE). Preserve copyright and license notices, identify modifications, and provide corresponding source under the GPL when distributing covered modified versions or binaries. Commercial use is permitted. This is a copyleft license, with stronger redistribution obligations than MIT; see the [GPLv3 overview](https://choosealicense.com/licenses/gpl-3.0/).

For a visible project credit, use **“Based on Spotipy Visualizer by mauringo.”** This is a suggested credit line, not an additional advertising requirement. The license requires preservation of legal notices, not a mention in every use or social post.

Earlier MIT releases retain their original permissions; the historical notice is preserved in [LICENSES/legacy-MIT.txt](LICENSES/legacy-MIT.txt). Third-party components keep their own licenses, including the bundled [Lucide/Feather notices](Flask/static/lucide.LICENSE). Album artwork and Spotify branding shown in the images belong to their respective owners and are not relicensed here.

The 3D-printed enclosure shown in the photo is from [Raspberry Pi 5 Macintosh Plus on Printables](https://www.printables.com/model/1259764-raspberry-pi-5-macintosh-plus). Credit for the enclosure design belongs to its creator; see the model page for its license and printing details. The enclosure design is not covered by this software’s GPL license.

Independent project; not affiliated with or endorsed by Spotify or Apple. The photo enhancement used the built-in imagegen tool; its [editing record](docs/images/EDITING.md) includes the prompt, and the original photos remain in the repository.
