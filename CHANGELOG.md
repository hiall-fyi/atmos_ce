# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).


## [2.0.0] - 2026-09-05

**If you have an automation or template matching the literal text `"None"` on the Active Alert or Upcoming Alert sensors**, switch it to check for the `unknown` state instead. With no alert, both sensors now report the standard Unknown state rather than the word "None".

### Bug fixes

- **Fixed: a warning with no expiry never showed as active.** Environment Canada and Meteoalarm warnings that don't carry an expiry time fell back to the warning's own start time or last-updated time instead of leaving it open-ended, so the active-warning check was never true. However serious the warning, it never appeared in the active or upcoming sensors, or turned on the alert-active binary sensor.

- **Fixed: several forecast, air quality, and stability sensors credited the wrong data source.** Temperature, humidity, air quality, and the derived stability/comfort sensors said "Data provided by" whichever warning service you'd picked, even though that data comes from Open-Meteo. They now credit Open-Meteo, with the licence attribution it requires.

- **Fixed: a Meteoalarm warning with no severity field showed one tier lower than intended.** A title with no colour word and no CAP severity field defaulted to Minor instead of the intended Yellow, silently understating the warning.

- **Fixed: a Met Office warning whose title didn't match the expected format showed as a real Yellow warning.** It now shows as unknown, matching how every other source already handles a warning it can't classify.

- **Fixed: changing a source's forecast location could blend two places' air pressure into one trend.** Editing the forecast coordinates in Options kept comparing against pressure readings from the old location for up to 4 hours, so the pressure trend sensor could show rising or falling based on the difference between two locations rather than a real change at either one.

- **Fixed: a missing weather code showed as "Sunny."** When Open-Meteo's response was missing the weather code for the current, hourly, or daily forecast, conditions defaulted to sunny or clear-night instead of showing as unrecognised.

- **Fixed: diagnostics kept reporting success after a login failure.** Once a source's API key was rejected, the diagnostics page kept showing the last successful fetch indefinitely rather than reflecting that fetches were failing.

- **Fixed: three config-flow messages stayed in English for German, Spanish, French, Italian, Dutch, and Portuguese.** "This source is already set up," "source not found," and the generic setup error were never translated; they now read in your language like the rest of the setup flow.

### Improvements

- **Worldwide Forecast's device now uses the name you gave it.** The location name entered during setup was collected but never used; the device showed the generic "Worldwide Forecast" regardless. It now reads, for example, "Home Forecast."

- **Active/Upcoming Alert sensors no longer show the English word "None" in every language.** They now show the standard translated "Unknown" state, matching how every other sensor with no current value behaves.

- **The Stability Assessment icon no longer shows a sunny icon when the reading is actually unknown.** Missing CAPE and Lifted Index data now shows a question-mark icon instead of the calm-weather one.

- **Alert Active no longer reads "Unsafe" for a routine minor advisory.** The binary sensor now shows "Alert" / "No alert" rather than borrowing the safety device class's "Unsafe" / "Safe" wording, which overstated a low-severity warning.


## [1.1.0] - 2026-08-01

**If you have an automation matching CWA Taiwan warnings on the `severity` attribute** (`advisory`, `watch`, `warning`), switch it to the `level` number or to the new wording. Severity names still vary by source (some use minor/moderate/severe/extreme, others use yellow/amber/red), but `level` now means the same thing everywhere, so it's the reliable thing to compare on. No other source is affected.

### Bug fixes

- **Opening the options page could wipe your region filter.** Saving options rewrote your whole configuration from the form, so any field left blank was dropped rather than kept. For a National Weather Service setup that meant the state filter disappeared and you started receiving alerts for the entire country. Saving options now keeps the settings you did not change, matching how the reconfigure page already behaved.

- **Location filters could not be removed once set.** Clearing the location filter box and saving left the old filter in place, so you carried on seeing only the alerts it matched. Emptying the box now removes the filter.

- **Warning severity did not mean the same thing across sources.** CWA Taiwan labelled its warnings advisory, watch, warning, and severe, while every other source used the yellow/amber/red or minor/moderate/severe/extreme wording. Worse, "severe" from Taiwan sat at the top tier where the same word means one tier lower everywhere else, so an automation matching on it caught the wrong warnings. CWA Taiwan now uses the same four-tier scale as the rest, and every source's severity name agrees with its numeric level, so `level` is safe to compare across sources even where the wording differs.

- **An unrecognised severity word from a weather service left the two severity attributes disagreeing.** If a feed sent a severity outside the standard set, the alert kept that raw word while its numeric level fell back to the lowest tier, so a template comparing the two got contradictory answers. Unrecognised words now report as unknown, matching the level. The level itself is unchanged.

### Improvements

- **Five sensors showed raw internal values instead of readable text.** Stability Assessment, Dew Point Comfort, Visibility Category, Feels Like Context, and Pressure Trend displayed values like `slightly_humid` and `wind_chill`, and stayed in English in every language. They now read properly in all seven supported languages. The stability tiers also use each language's established forecasting terms rather than a literal word-for-word translation.

- **Multiple states can be monitored for National Weather Service.** The state picker took a single state; it now takes several, matching the region and province pickers the other sources already offered. Existing setups keep their state.

- **Feels Like Context is easier to read.** The values were named after the formula behind them (`wind_chill`, `heat_index`). They now say whether it feels colder, warmer, or about the same as the actual temperature.


## [1.0.1] - 2026-06-22

### Features

- **Full warning list exposed for cards and automations.** The active-alert sensor now carries the complete set of warnings (active and upcoming) as an attribute, each one tagged as active or upcoming. Previously a consumer could only read one warning per sensor, so a region with several warnings at once would only ever show two of them. A card or automation can now see every warning for the area.

### Bug fixes

- **Most severe warning could go missing during a busy spell.** When a region had several warnings overlapping (say two amber and one red during a heat event), upcoming warnings were ordered by start time, so a red warning starting later was pushed behind an earlier amber and never surfaced. Upcoming warnings now sort by severity first, so the most serious one leads.

- **Amber warnings were coloured red, yellow ones orange.** The colour table was off by one against the severity levels every source emits, so each warning was painted one tier too high. Yellow now shows yellow, amber shows amber/orange, and red shows red.

- **README in-page navigation links were broken.** The links in the table of contents pointed at the wrong anchors after emoji were stripped from the section headers at the 1.0.0 release. They now jump to the right sections.


## [1.0.0] - 2026-06-14

**First stable release of Atmos CE, a multi-source weather suite for Home Assistant.**

Pulls warnings, forecasts, air quality, atmospheric stability, weather insights, and astronomical data from Met Office, Meteoalarm (40 European countries), NWS, Environment Canada, DWD, CWA Taiwan, and Open-Meteo. Each source offers forecasts, air quality, and astronomy with per-data-type toggles.

57 entities across the sensor, binary_sensor, and weather platforms, with 13 alert types at four severity levels and county, region, and country filtering. Pressure history and last-fetch state survive restarts, and the coordinator tolerates one backend failing without dropping the rest of the update.
