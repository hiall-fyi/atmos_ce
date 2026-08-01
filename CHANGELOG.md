# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).


## [1.1.0] - 2026-08-01

**If you have an automation matching CWA Taiwan warnings on the `severity` attribute** (`advisory`, `watch`, `warning`), switch it to the `level` number or to the new wording. Every source now reports the same four names, so `level` is the reliable thing to compare on. No other source is affected.

### Bug fixes

- **Opening the options page could wipe your region filter.** Saving options rewrote your whole configuration from the form, so any field left blank was dropped rather than kept. For a National Weather Service setup that meant the state filter disappeared and you started receiving alerts for the entire country. Saving options now keeps the settings you did not change, matching how the reconfigure page already behaved.

- **Location filters could not be removed once set.** Clearing the location filter box and saving left the old filter in place, so you carried on seeing only the alerts it matched. Emptying the box now removes the filter.

- **Warning severity did not mean the same thing across sources.** CWA Taiwan labelled its warnings advisory, watch, warning, and severe, while every other source used the yellow/amber/red or minor/moderate/severe/extreme wording. Worse, "severe" from Taiwan sat at the top tier where the same word means one tier lower everywhere else, so an automation matching on it caught the wrong warnings. Every source now reports the same four names, and the name always agrees with the numeric level beside it.

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
