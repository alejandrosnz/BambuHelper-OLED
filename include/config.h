#ifndef CONFIG_H
#define CONFIG_H

// =============================================================================
//  Firmware version and release location
// =============================================================================
#define FW_VERSION          "v3.9.5"

// This fork publishes its own OTA builds. The web UI reads the latest release
// from this repository and only offers assets named
//   BambuHelper-OLED-<BOARD_VARIANT>-<FW_VERSION>-ota.bin
#define FW_REPO_SLUG        "alejandrosnz/BambuHelper-OLED"
#define FW_REPO_URL         "https://github.com/alejandrosnz/BambuHelper-OLED"
#define FW_ASSET_PREFIX     "BambuHelper-OLED-"

// Board variant — injected into the web UI for OTA asset filtering.
// Normally set via build_flags in platformio.ini; this is a fallback.
#ifndef BOARD_VARIANT
#define BOARD_VARIANT       "sh1106_esp32c3"
#endif

// =============================================================================
//  Display
// =============================================================================
// The mono env has no controllable backlight; the build sets BACKLIGHT_PIN=-1.
#ifndef BACKLIGHT_PIN
#define BACKLIGHT_PIN   -1
#endif

// =============================================================================
//  Color palette (RGB565)
// =============================================================================
#define CLR_BG          0x0000   // black
#define CLR_CARD        0x1926   // dark card bg
#define CLR_HEADER      0x10A2   // header bar bg
// Text colors are user-configurable (#163), so these two are only the factory
// DEFAULTS. The live values are CLR_TEXT / CLR_TEXT_DIM, defined in settings.h
// as dispSettings lookups - a drawing file must include settings.h to paint
// text, and gets a compile error rather than a silently unthemed screen if it
// forgets. Do not reintroduce CLR_TEXT here.
#define CLR_TEXT_DEFAULT     0xFFFF   // white
#define CLR_TEXT_DIM_DEFAULT 0xC618   // gray text
#define CLR_TEXT_DARK        0x7BEF   // darker gray (chrome: inactive dots,
                                      // arc tracks - not text, stays fixed)
#define CLR_GREEN        0x07E0   // bright green
#define CLR_GREEN_DARK   0x0400   // dark green (track)
#define CLR_BLUE         0x34DF   // accent blue
#define CLR_ORANGE       0xFBE0   // nozzle accent
#define CLR_CYAN         0x07FF   // bed accent
#define CLR_RED          0xF800   // error / hot
#define CLR_YELLOW       0xFFE0   // pause / warm
#define CLR_GOLD         0xFEA0   // progress near done
#define CLR_TRACK        0x18E3   // arc background track

// =============================================================================
//  MQTT / Bambu
// =============================================================================
#define BAMBU_PORT                  8883
#define BAMBU_USERNAME              "bblp"
#define BAMBU_BUFFER_SIZE           40960   // 40KB - H2C with 3 AMS sends ~33KB
#define BAMBU_RECONNECT_INTERVAL    10000   // 10s between attempts
#define BAMBU_BACKOFF_PHASE1        5       // first N attempts at normal interval
#define BAMBU_BACKOFF_PHASE2_MS     60000   // 60s after phase 1 exhausted
#define BAMBU_BACKOFF_PHASE2        10      // next N attempts at phase 2 interval
#define BAMBU_BACKOFF_PHASE3_MS     120000  // 120s after phase 2 exhausted
#define BAMBU_OFFLINE_PROBE_MS      20000   // LAN: TCP probe interval while the printer is off
#define BAMBU_STALE_TIMEOUT         60000   // 60s no data = stale
#define BAMBU_PRINT_STALE_TIMEOUT   120000  // cloud: 120s no core print data = stale (LAN uses BAMBU_STALE_TIMEOUT)
#define BAMBU_PUSHALL_INTERVAL      30000   // request full status every 30s (LAN)
#define BAMBU_PUSHALL_INITIAL_DELAY 2000    // wait 2s after connect
#define BAMBU_CLOUD_IDLE_PUSHALL_INTERVAL 300000 // cloud: poll full status every 5 min while NOT printing, to catch a cloud-dropped IDLE->RUNNING delta. Safe: stricter than the 2-min recovery throttle, far above the ~30s LAN cadence that risks access_denied, within the documented >=5-min pushall guidance.
#define BAMBU_MIN_FREE_HEAP         40000   // min heap for TLS allocation
#define BAMBU_KEEPALIVE             60
#define BAMBU_CLOUD_KEEPALIVE       30      // cloud: longer than LAN to tolerate internet jitter

// =============================================================================
//  WiFi
// =============================================================================
#define WIFI_AP_PREFIX      "BambuHelper-"
#define WIFI_AP_PASSWORD    "bambu1234"
#define WIFI_CONNECT_TIMEOUT 15000  // 15s STA connect timeout
#define WIFI_RECONNECT_TIMEOUT 60000 // 60s before re-entering AP mode
#define WIFI_BACKOFF_PHASE1_MS    10000   // 10s between attempts in phase 1
#define WIFI_BACKOFF_PHASE2_MS    30000   // 30s between attempts after phase 1
#define WIFI_BACKOFF_PHASE3_MS    60000   // 60s between attempts after phase 2
#define WIFI_BACKOFF_PHASE2_START 5       // start phase 2 after this many attempts
#define WIFI_BACKOFF_PHASE3_START 10      // start phase 3 after this many attempts
#define WIFI_STA_PROBE_INTERVAL   120000  // 2 min between STA probes while in AP mode
#define WIFI_STA_PROBE_CHECK_MS    10000  // 10s after probe start before checking result
#define WIFI_AP_FALLBACK_MS       900000  // 15 min in phase 3 before falling back to AP
// AP-fallback hint: below WEAK the failure is blamed on signal outright; below
// MARGINAL only when the AP never rejected the password.
#define WIFI_RSSI_WEAK            -85
#define WIFI_RSSI_MARGINAL        -78

// Improv WiFi serial setup window on first boot (no stored credentials).
// During this window the device listens for Improv commands from the web
// flasher; on timeout it falls back to the AP captive portal.
// 3 minutes is generous on purpose: ESP Web Tools needs ~15s to probe after
// flash, then the user has to find their SSID, fetch the password from a
// router sticker / password manager, and type it in. Anything shorter
// punishes slow users with a "you missed the dialog" cliff.
#define IMPROV_SETUP_WINDOW_MS    180000  // 3 min window for Improv setup at first boot

// =============================================================================
//  NVS
// =============================================================================
#define NVS_NAMESPACE       "bambu"

// Any epoch below this means NTP has not answered yet and the RTC is still at
// its power-on value, so a wall-clock reading must not be trusted or displayed.
#define NTP_SYNCED_EPOCH    1704067200UL   // 2024-01-01 00:00:00 UTC

// =============================================================================
//  Multi-printer
// =============================================================================
#define MAX_PRINTERS          4       // NVS config slots
// The mono build targets the ESP32-C3 SuperMini, which has no PSRAM: two
// simultaneous TLS+MQTT sessions is the proven ceiling there. Each session
// costs ~40 KB MQTT buffer + ~40-50 KB mbedTLS, so a third handshake would run
// out of internal SRAM mid-flight and trip the watchdog.
#define MAX_ACTIVE_PRINTERS   2

// =============================================================================
//  Board capability derivation
// =============================================================================
// Logic files test these capabilities, never board names. Each capability is
// ALWAYS defined 0/1 and tested with `#if CAP`, so a typo in a consumer resolves
// to 0 at build time.

// The mono build has no colour panel, touch controller, display expander or
// onboard RGB LED. The only board-level flag left is the C3 radio workaround.

// ESP32-C3 radio: capping AP/STA TX power works around a C3 range/brownout issue
// (see wifi_manager.cpp).
#define BOARD_NEEDS_WIFI_TX_LIMIT  1

// The WS2812 pixel driver pulls in the RMT peripheral driver (~12 KB flash);
// the three-pin PWM path is a few hundred bytes. The -fno-exceptions build
// reclaims ~148 KB, so the pixel driver fits and single / RGB / WS2812 are all
// offered for a hand-wired LED.
#define HAS_LED_PIXEL  1

// HMS / print_error reporting:
//
//   HAS_HMS_UI           the feature exists at all - state fields, parser,
//                        badge, error screen, alerts
//   HAS_ERROR_TEXT_TABLE embedded print_error sentences (~36 KB flash)
//   HAS_FULL_HMS_TABLE   embedded HMS sentences (~194 KB flash)
//   HAS_HMS_KNOWN_TABLE  embedded HMS key set, no sentences (~6 KB flash)
//
// The C3 app slot has no room for either text table, so the screen shows
// "<MODULE> <SEVERITY>" plus the formatted code; the portal still shows the
// full wording, because it resolves both domains from the published mirror in
// the user's browser. Codes on the screen, sentences in the portal.
//
// Size a 4 MB board with `stat .pio/build/<env>/firmware.bin`, never with the
// build summary: PlatformIO's "Flash: used" line is the linker section sum,
// while firmware.bin is roughly 88 KB larger because of segment padding.
#define HAS_HMS_UI            1
#define HAS_ERROR_TEXT_TABLE  0
#define HAS_FULL_HMS_TABLE    0

// Whether Bambu describes a code at all decides whether it reaches the screen
// (issue #164 - an X2D standing on two codes its own UI does not list, because
// Bambu registers them and publishes no sentence). Answering that needs the key
// set, not the text: hms_known.h carries the same 2014 keys with the sentences
// dropped and grouped by attr - ~6 KB instead of ~194 KB. Both tables come out
// of the same generator run, so the two paths can never disagree.
#define HAS_HMS_KNOWN_TABLE  1

// The portal's "Printer Errors" section is markup, and markup is flash: it
// costs ~7 KB. Kept as its own capability - and PAGE_HTML kept split into three
// streamed literals - so a build that runs out of app slot can still drop the
// settings page while keeping the parts that matter without a keyboard: the
// badge, the error screen, the cancel wording. Such a device runs on the
// defaults (reporting on, important-only, no alert channels), which a settings
// import can override.
//
// Defined in terms of HAS_HMS_UI rather than as a literal, so "the section
// cannot exist without the feature" is structural.
#define HAS_HMS_WEB_UI  HAS_HMS_UI

// Published mirror of Bambu's error-text feed, read by the portal page in the
// user's browser - never by the device. e.bambulab.com sends no CORS header at
// all, so the page cannot read the feed directly; GitHub Pages sends
// "Access-Control-Allow-Origin: *". This fork has no Pages site, so it reads the
// upstream mirror; the data is Bambu's, not the upstream firmware's.
#define HMS_MIRROR_URL  "https://keralots.github.io/BambuHelper/errors/hms_en.json"

// Signing into a Bambu account from the device itself (portal form -> cloud
// token, no Companion Tool). Kept as a capability so a future flash-starved
// build can drop it without touching anything but this block.
#define HAS_CLOUD_LOGIN  1

// =============================================================================
//  Display rotation (multi-printer)
// =============================================================================
#define ROTATE_INTERVAL_MS    60000   // default auto-rotate: 1 min
#define ROTATE_MIN_MS         10000   // min allowed interval (10s)
#define ROTATE_MAX_MS         600000  // max allowed interval (10 min)

// =============================================================================
//  Gauge full-scale ranges (user-configurable arc maxima)
//  Defaults cover every Bambu printer; lowering a scale makes the arc sweep
//  fuller for a printer's normal range (better visual resolution).
// =============================================================================
#define GAUGE_NOZZLE_SCALE_DEFAULT  300   // C
#define GAUGE_NOZZLE_SCALE_MIN      100
#define GAUGE_NOZZLE_SCALE_MAX      400
#define GAUGE_BED_SCALE_DEFAULT     120   // C
#define GAUGE_BED_SCALE_MIN         40
#define GAUGE_BED_SCALE_MAX         150
#define GAUGE_CHAMBER_SCALE_DEFAULT 60    // C (also AMS unit-temp gauge)
#define GAUGE_CHAMBER_SCALE_MIN     30
#define GAUGE_CHAMBER_SCALE_MAX     120
#define GAUGE_POWER_SCALE_DEFAULT   1000  // W (Tasmota power gauge)
#define GAUGE_POWER_SCALE_MIN       100
#define GAUGE_POWER_SCALE_MAX       5000

// =============================================================================
//  Physical button
// =============================================================================
#define BUTTON_DEFAULT_PIN    4       // GPIO4 on the ESP32-C3 SuperMini

// =============================================================================
//  Display refresh
// =============================================================================
#define DISPLAY_STATE_TIMEOUT_MS   60000  // 60s timeout for intermediate display states

// =============================================================================
//  Buzzer (optional passive buzzer)
// =============================================================================
// GPIO3 on the ESP32-C3 SuperMini; 0 disables the GPIO backend. The user picks
// the pin in the web UI when a buzzer is actually wired.
#define BUZZER_DEFAULT_PIN    3

// =============================================================================
//  Status LED (optional: single PWM channel, 3-pin RGB, or one WS2812)
// =============================================================================
// LEDC channel budget: tone() sits on channel 0 and the C3 bank tops out at 5,
// so 2/3/4 are free.
#define LED_PWM_CH      2     // LEDC channel (single mode; RGB mode: red)
#define LED_PWM_CH_G    3     // RGB mode: green
#define LED_PWM_CH_B    4     // RGB mode: blue
#define LED_PWM_FREQ    5000  // PWM frequency (Hz)
#define LED_PWM_RES     8     // PWM resolution (bits) -> 0..255 duty

#define LED_DEFAULT_PIN 0     // no status LED assumed; user configures in web UI

// LED effect tuning (ms periods)
#define LED_BREATH_PERIOD_MS      2000   // breathing pulse 0->peak->0
#define LED_HEARTBEAT_PERIOD_MS   1500   // pyk-pyk-pause cycle
#define LED_PAUSE_PERIOD_MS       3500   // slow breath while printer paused
#define LED_ERROR_STROBE_MS        180   // strobe half-period (180 on / 180 off)
#define LED_ERROR_STROBE_DEFAULT_S  60   // error strobe auto-off after N s (0 = never)
#define LED_TICK_MIN_INTERVAL_MS    16   // throttle ledTick() to ~60Hz
#define LED_TEST_DURATION_S          8   // /led/test runs the chosen effect for 8s

// Default per-state colours, 0xRRGGBB. Intensity is the brightness slider's job,
// so these are saturated hues: white = standby, blue = working, amber = wants
// attention, green = done, red = fault.
#define LED_COLOR_IDLE_DEFAULT      0xFFFFFF
#define LED_COLOR_PRINTING_DEFAULT  0x0080FF
#define LED_COLOR_PAUSED_DEFAULT    0xFF9000
#define LED_COLOR_FINISHED_DEFAULT  0x00FF40
#define LED_COLOR_ERROR_DEFAULT     0xFF0000

#endif // CONFIG_H
