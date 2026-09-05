<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/atmos_ce/brand/dark_logo@2x.png" />
  <img src="custom_components/atmos_ce/brand/logo@2x.png" alt="Atmos CE" width="480" />
</picture>

<br />

<em>Comprehensive Weather Suite for Home Assistant</em>

<!-- Platform Badges -->
![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12.0+-blue?style=for-the-badge&logo=home-assistant)
![Python](https://img.shields.io/badge/Python-3.13%2B-blue?style=for-the-badge&logo=python&logoColor=white)
![HACS](https://img.shields.io/badge/HACS-Custom-orange.svg?style=for-the-badge)

<!-- Status Badges -->
![Version](https://img.shields.io/badge/Version-2.0.0-purple?style=for-the-badge)
![License](https://img.shields.io/badge/License-AGPL--3.0-blue?style=for-the-badge)
![Maintained](https://img.shields.io/badge/Maintained-Yes-green.svg?style=for-the-badge)
![Coverage](https://img.shields.io/badge/Coverage-97%25-brightgreen?style=for-the-badge)

<!-- Community Badges -->
![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/atmos_ce?style=for-the-badge&logo=github)
![GitHub issues](https://img.shields.io/github/issues/hiall-fyi/atmos_ce?style=for-the-badge&logo=github)
![GitHub Release Date](https://img.shields.io/github/release-date/hiall-fyi/atmos_ce?style=for-the-badge&logo=github)

<!-- Support -->
[![Buy Me A Coffee](https://img.shields.io/badge/Support-Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

**Warnings, forecasts, air quality, and astronomical data — all in one integration.**

**7 weather sources · 59 entities · golden hour · moon phase · zero API keys required (except CWA Taiwan)**

[Quick Start](#quick-start) • [Features](#features) • [Supported Sources](#supported-sources) • [Entities](#entities) • [Configuration](#configuration) • [Services](#services) • [Troubleshooting](#troubleshooting) • [Discussions](https://github.com/hiall-fyi/atmos_ce/discussions)

</div>

---

## Why Atmos CE?

Add one weather source and you get everything — official government warnings, current conditions, hourly and daily forecasts, air quality readings, and astronomical data like golden hour times and moon phase. No need to set up multiple integrations or piece things together.

You choose what you want. Each source comes with toggles for warnings, forecasts, and air quality, so you only see the data you care about. If you're in the UK, add Met Office and you're done. Travelling between the UK and Germany? Add both Met Office and DWD — each runs independently with its own update schedule.

For locations without a dedicated warning source (like Japan or Australia), the Worldwide Forecast option gives you forecasts, air quality, and astronomical data for any location on Earth.

---

## Features

- **7 Weather Sources** — Met Office, Meteoalarm (40 European countries), NWS, Environment Canada, DWD, CWA Taiwan, plus Worldwide Forecast for anywhere else
- **Everything Built In** — Every source includes forecasts, air quality, and astronomical data. Toggle what you need.
- **13 Alert Types** — Rain, wind, snow, ice, fog, thunderstorm, heat, cold, flood, tornado, fire, coastal hazard, and avalanche — each with 4 severity levels
- **59 Entities** — Current conditions, hourly/daily forecasts, air quality (2 AQI indices + 7 pollutants), atmospheric stability, weather insights, pressure trend, and astronomical data
- **Atmospheric Stability** — CAPE, lifted index, wind shear, lapse rate, LCL height, and a composite stability assessment rated from None to High — so you can see storm potential at a glance
- **Weather Insights** — Dew point comfort (dry to oppressive), visibility category (fog to clear), feels-like context (wind chill, heat index, or neutral), and 3-hour pressure trend (rising, steady, falling)
- **Astronomical Sensors** — Golden hour and blue hour times for photography, localised moon phase (illumination percentage in attributes), moonrise/moonset, and daylight duration — all calculated locally with correct polar day / polar night handling above the Arctic and Antarctic circles
- **Air Quality** — European AQI, US AQI, PM2.5, PM10, NO₂, O₃, SO₂, CO, CO₂ with category classification
- **Extended Forecast Service** — Call `atmos_ce.get_extended_forecast` to get the full hourly or daily forecast with all fields, including dew point, CAPE, and precipitation breakdown — perfect for automations and custom cards
- **Data Type Toggles** — Choose which data types each source shows (warnings, forecasts, air quality) to keep things tidy
- **"Until Further Notice" Alerts** — Alerts without an explicit end time stay visible instead of disappearing
- **Automatic Retries** — If a weather service is temporarily down, the integration retries quietly in the background so you don't have to do anything
- **Honest Availability** — Sensors go `unavailable` when the upstream fetch fails instead of holding stale values, so automations can react accordingly

---

## Quick Start

**Prerequisites:** Home Assistant 2024.12.0+ with HACS installed.

### 1. Install via HACS

1. Add `https://github.com/hiall-fyi/atmos_ce` as a custom repository in HACS
2. Install "Atmos CE"
3. Restart Home Assistant

<details>
<summary>Manual Installation</summary>

Copy the `custom_components/atmos_ce/` folder to your Home Assistant `config/custom_components/` directory and restart.
</details>

### 2. Add a Source

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **Atmos CE**
3. Pick your weather source from the dropdown
4. Configure source-specific settings (regions, states, API key, etc.)

That's it. Forecasts, air quality, and astronomical data are included automatically.

You can add the integration multiple times — once per source.

### 3. Verify

Check **Settings → System → Logs** and filter for `atmos_ce`. You should see successful setup messages with no errors.

---

## Supported Sources

| Source | Country | API Key? | What You Get |
|--------|---------|----------|-------------|
| **Met Office** | 🇬🇧 UK | No | Yellow/Amber/Red weather warnings with region and local authority filtering |
| **Meteoalarm** | 🇪🇺 40 European countries | No | Severe weather alerts from national meteorological services across Europe |
| **National Weather Service** | 🇺🇸 USA | No | Active weather alerts with state filtering |
| **Environment Canada** | 🇨🇦 Canada | No | Weather alerts with province filtering |
| **Deutscher Wetterdienst** | 🇩🇪 Germany | No | Weather warnings at municipality level |
| **CWA Taiwan** | 🇹🇼 Taiwan | Yes (free) | Typhoon, rain, wind, and cold warnings with county filtering |
| **Worldwide Forecast** | 🌍 Anywhere | No | Forecasts, air quality, and astronomical data for any location (no warnings) |

Every warning source above also comes with forecasts, air quality, and astronomical data built in — powered by Open-Meteo behind the scenes. You can toggle each data type on or off in the options. If you're in a country without a dedicated warning source, use Worldwide Forecast to get everything except warnings.

---

## Entities

Each source creates up to 59 entities depending on your data type settings. Here's what you get when everything is enabled:

### Warnings (4 entities)

| Entity | Type | What It Shows |
|--------|------|--------------|
| **Active Alert** | Sensor | The highest-priority warning currently in effect, with full details in attributes |
| **Upcoming Alert** | Sensor | The next warning that hasn't started yet |
| **Alert Count** | Sensor | Number of active warnings right now |
| **Alert Active** | Binary Sensor | On/off — are there any active warnings? |

Alert sensors include rich attributes: alert type, severity, level, start/end times, affected locations, progress percentage, time until start/end, description, and a link to the official alert page.

Not available for Worldwide Forecast (no warning source).

### Current Conditions (25 sensors)

Temperature, apparent temperature, dew point, humidity, pressure, surface pressure, wind speed/direction/gusts, precipitation, rain, showers, snowfall, cloud cover (total/low/mid/high), UV index, visibility, CAPE, lifted index, freezing level height, soil temperature, and soil moisture.

### Atmospheric Stability (4 sensors)

Wind shear (0–6 km), lapse rate (700–500 hPa), LCL height, and a composite stability assessment that combines all available parameters into a single rating from None to High. The assessment also tells you how confident it is based on how many parameters are available.

### Weather Insights (4 sensors)

Dew point comfort (dry → comfortable → slightly humid → humid → oppressive), visibility category (fog → poor → moderate → good → clear), feels-like context (wind chill, heat index, or neutral), and 3-hour pressure trend (rising, steady, or falling) with the actual pressure change in attributes.

### Air Quality (9 sensors)

European AQI, US AQI, PM2.5, PM10, NO₂, O₃, SO₂, CO, CO₂ — each with category classification in attributes.

### Astronomical (12 sensors)

Golden hour (morning/evening start and end), blue hour (morning/evening start and end), moon phase (translated to your HA language, illumination percentage in attributes), moonrise, moonset, and daylight duration.

Polar locations are handled correctly — daylight duration reads 24 hours during midnight sun and 0 hours during polar night, and the astro data exposes `sun_always_up` / `sun_always_down` flags for automations.

Moon phase and daylight duration are enabled by default. Golden hour, blue hour, moonrise, and moonset are disabled by default — enable the ones you want in the entity settings.

### Weather Entity (1)

A standard Home Assistant weather entity with current conditions, hourly (48h), and daily (7d) forecasts. Works with weather cards out of the box.

---

## Configuration

Access via **Settings → Devices & Services → Atmos CE → Configure** (gear icon).

### Source Settings

- **Enabled** — turn a source on or off without removing it
- **Update Interval** — how often to check for new data (5–1440 minutes; default 30, or 15 for Worldwide Forecast)
- **Location Filters** — comma-separated text to filter alerts by location name

Plus source-specific settings:
- **Met Office** — select UK regions and/or local authorities
- **Meteoalarm** — select one or more European countries
- **NWS** — select a US state
- **Environment Canada** — select one or more provinces
- **CWA Taiwan** — API key + optional county selection

### Data Type Toggles

Each source has toggles for the data types it provides:

- **Warnings** — weather warning alerts (not available for Worldwide Forecast)
- **Forecasts** — current conditions, hourly and daily forecasts, weather entity
- **Air Quality** — pollutant readings and AQI indices

All toggles default to on. Turn off what you don't need — entities are removed when a toggle is off and come back when you turn it on again. No restart needed.

### Forecast Location

By default, forecasts use your Home Assistant home coordinates. You can override this in the options if your warning region doesn't match your exact location — for example, if you monitor Met Office warnings for South East England but want forecasts for a specific town.

---

## Services

### `atmos_ce.get_extended_forecast`

Returns the full hourly or daily forecast with all fields — including dew point, CAPE, rain/showers/snowfall breakdown, snow depth, and other fields not available through the standard `weather.get_forecasts` service.

**Parameters:**
- **Config Entry ID** — pick your Atmos CE source from the dropdown
- **Type** — `hourly` (default) or `daily`

Use this in automations, scripts, or custom cards when you need the complete forecast data.

---

## Troubleshooting

<details>
<summary><strong>No alerts showing up</strong></summary>

This usually means there are genuinely no active warnings for your area. Check the official source website to confirm. If warnings exist but don't appear:

1. Check your location filters aren't too restrictive
2. Verify the update interval hasn't passed yet (check the sensor's `last_updated` attribute)
3. Enable debug logging (see below)
</details>

<details>
<summary><strong>Source disabled after failures</strong></summary>

A source is automatically paused after 5 failed attempts to reach the weather service. Check **Settings → System → Repairs** for details.

Common causes:
- Your network connection is down or unstable
- The weather service is temporarily unavailable
- Invalid API key (CWA Taiwan)

Fix the underlying issue, then reload the integration or restart HA to re-enable.
</details>

<details>
<summary><strong>Enable debug logging</strong></summary>

Add to `configuration.yaml`:

```yaml
logger:
  default: info
  logs:
    custom_components.atmos_ce: debug
```

Restart Home Assistant and check **Settings → System → Logs**.
</details>

For issues not covered here, check **Settings → System → Logs** (filter by `atmos_ce`), search the existing [GitHub Issues](https://github.com/hiall-fyi/atmos_ce/issues), and if it's new, [open a bug report](https://github.com/hiall-fyi/atmos_ce/issues/new/choose). The form walks you through what to include (your versions, which weather source, and a debug log), which is what turns a triage round-trip into a same-day fix.

---

## Uninstall

1. Go to **Settings → Devices & Services → Atmos CE**
2. Click the **three-dot menu** (⋮) and select **Delete**
3. Restart Home Assistant
4. If installed via HACS: open **HACS → Integrations**, find Atmos CE, click the three-dot menu and **Remove**
5. If installed manually: delete the `custom_components/atmos_ce/` folder
6. Restart Home Assistant again

---

## License

**GNU Affero General Public License v3.0 (AGPL-3.0)**

Free to use, modify, and distribute. Modifications must be open source under AGPL-3.0 with attribution.

**Original Author:** Joe Yiu ([@hiall-fyi](https://github.com/hiall-fyi))

See [LICENSE](LICENSE) for full details.

---

## Contributing

Contributions welcome! Whether it's a new warning source, bug fix, or documentation improvement.

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/new-source`)
3. Commit your changes
4. Open a Pull Request

Hit a problem? [Open a bug report](https://github.com/hiall-fyi/atmos_ce/issues/new/choose). Want something changed, or just want to ask? [Start a Discussion](https://github.com/hiall-fyi/atmos_ce/discussions). Logs and the name of the weather source involved are what make the difference between a triage round-trip and a same-day fix.

---

<details>
<summary><strong>Disclaimer</strong></summary>

This project is not affiliated with, endorsed by, or connected to any of the weather services it integrates with (Met Office, NWS, Environment Canada, DWD, CWA, Meteoalarm, Open-Meteo) or Home Assistant. All trademarks belong to their respective owners.

Weather warnings are provided for informational purposes only. Always refer to your local weather service for official safety guidance.

This integration is provided "as is" without warranty. Use at your own risk.
</details>
