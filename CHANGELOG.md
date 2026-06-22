# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).


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
