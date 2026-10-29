<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="custom_components/atmos_ce/brand/dark_logo@2x.png" />
  <img src="custom_components/atmos_ce/brand/logo@2x.png" alt="Atmos CE" width="480" />
</picture>

<br />

# Atmos CE - Weather warnings, forecasts, air quality and astronomy for Home Assistant

![Home Assistant](https://img.shields.io/badge/Home%20Assistant-2024.12%2B-blue?style=for-the-badge&logo=home-assistant) ![HACS](https://img.shields.io/badge/HACS-Custom-orange?style=for-the-badge) ![Stable](https://img.shields.io/badge/Stable-2.1.0-brightgreen?style=for-the-badge) ![License](https://img.shields.io/badge/License-AGPL--3.0-lightgrey?style=for-the-badge)

![GitHub stars](https://img.shields.io/github/stars/hiall-fyi/atmos_ce?style=for-the-badge&logo=github) [![Buy Me A Coffee](https://img.shields.io/badge/Support-Buy%20Me%20A%20Coffee-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/hiallfyi)

**Atmos CE brings official weather warnings, forecasts, air quality and sun and moon times into Home Assistant. Pick your country's warning service and you get all of it from one integration, with no API key (except CWA Taiwan).**

[Quick Start](#quick-start) • [Supported sources](#supported-sources) • [Features](#features) • [Configuration](#configuration) • [FAQ](#faq) • [Discussions](https://github.com/hiall-fyi/atmos_ce/discussions)

</div>

---

## About

Atmos CE is a community-built Home Assistant integration. It reads warnings from national weather services, and forecasts and air quality from [Open-Meteo](https://open-meteo.com/). Sun and moon times are worked out locally. It is developed independently of every service it talks to.

---

## Why use Atmos CE

Three situations where it is worth a look:

1. **You want official warnings you can build automations on.** Every warning service reports in its own format. Atmos CE turns them all into the same four entities and the same four severity levels, so an automation written for one source needs only its entity names changed to work with another.
2. **You want forecasts, air quality and sun and moon times next to the warnings.** Each source comes with all four, and you switch off what you do not need.
3. **You follow more than one place.** Add the integration once per source. Each runs on its own schedule, so you can watch the UK and Germany at the same time.

If all you need is a weather card, a built-in weather integration is enough. Atmos CE is for when you also want warnings or the extra sensors.

---

## Supported sources

| Source | Coverage | API key | Warnings |
| --- | --- | --- | --- |
| **Met Office** | United Kingdom | No | Yellow, amber and red warnings, filtered by region and local authority |
| **Meteoalarm** | 39 European countries | No | Warnings from each country's national weather service |
| **National Weather Service** | United States | No | Active alerts, filtered by one or more states |
| **Environment Canada** | Canada | No | Alerts, filtered by one or more provinces |
| **Deutscher Wetterdienst (DWD)** | Germany | No | Warnings at municipality level |
| **CWA Taiwan** | Taiwan | Yes (free) | Typhoon, rain, wind and cold warnings, filtered by county |
| **Worldwide Forecast** | Anywhere | No | None. Forecasts, air quality and astronomy only |

Forecasts, air quality and astronomy come with every source above. For a country with no warning service in the list, such as Japan or Australia, use Worldwide Forecast.

A CWA Taiwan key is free from the [CWA open data platform](https://opendata.cwa.gov.tw/).

---

## Quick start

### Prerequisites

- Home Assistant 2024.12 or newer
- [HACS](https://hacs.xyz/) installed

### 1. Install via HACS

Atmos CE is added to HACS as a custom repository.

1. In HACS, open the three-dot menu, choose **Custom repositories**, and add `https://github.com/hiall-fyi/atmos_ce` with the type **Integration**.
2. Search for **Atmos CE** and click **Download**.
3. Restart Home Assistant.

[![Open your Home Assistant instance and open a repository inside HACS.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hiall-fyi&repository=atmos_ce&category=integration)

<details>
<summary>Manual installation</summary>

Copy the `custom_components/atmos_ce/` folder from this repository into your Home Assistant `config/custom_components/` folder and restart.

</details>

### 2. Add a source

1. **Settings → Devices & Services → Add Integration → Atmos CE**
2. Pick your weather source.
3. Fill in the source's own settings (regions, states, provinces or counties, or the API key for CWA Taiwan).

Forecasts, air quality and astronomy are included. To follow another place, add the integration again with another source.

### 3. Verify

Open **Settings → Devices & Services → Atmos CE**. Your source should show as a device with its entities, and **Alert Active** should read `off` if nothing is in force. If something looks wrong, check **Settings → System → Logs** and filter by `atmos_ce`.

---

## Features

### Warnings

Four entities per source: the highest-priority **Active Alert**, the next **Upcoming Alert**, an **Alert Count** and an **Alert Active** on/off sensor. Alerts are sorted into 13 types (rain, wind, snow, ice, fog, thunderstorm, heat, cold, flood, tornado, fire, coastal hazard and avalanche) and four severity levels, whichever service they came from. Warnings with no end time stay visible instead of disappearing. The attributes carry the type, severity, level, start and end, affected places, progress, time until start or end, the description and a link to the official page.

### Forecasts and current conditions

A standard Home Assistant weather entity with current conditions, hourly (48 hours) and daily (7 days) forecasts, plus 25 sensors for current conditions such as temperature, wind, rain, cloud cover, UV index, visibility and soil moisture. The `atmos_ce.get_extended_forecast` service returns every forecast field for automations and custom cards.

### Atmospheric stability and weather insights

CAPE, lifted index, wind shear, lapse rate and LCL height, with a composite stability rating from None to High and a note on how confident it is. Plain-language sensors for dew point comfort, visibility category and feels-like context, and a 3-hour pressure trend.

### Air quality

European AQI, US AQI, PM2.5, PM10, NO₂, O₃, SO₂, CO and CO₂, each with a category in its attributes.

### Astronomy

Golden hour and blue hour, moon phase in your Home Assistant language with the illumination percentage, moonrise, moonset and daylight duration. Everything is calculated on your Home Assistant machine, and polar day and night are handled: daylight reads 24 hours in midnight sun and 0 in polar night, and `sun_always_up` and `sun_always_down` are available to automations.

### Honest availability

If a weather service errors, times out or sends back something the integration cannot read, the alert sensors go `unavailable` rather than saying there are no alerts, so an automation can tell "all clear" from "no answer". Short outages are retried quietly in the background, and the sensors return as soon as a refresh works.

---

## Configuration

Open **Settings → Devices & Services → Atmos CE → Configure**. Changes apply straight away, with no restart.

| Setting | What it does |
| --- | --- |
| **Enabled** | Turns a source on or off without removing it |
| **Update interval** | How often to check for new data, from 5 to 1440 minutes. The default is 30, or 15 for Worldwide Forecast |
| **Location filters** | Keeps only alerts whose place matches. Separate several places with commas. Leave it blank to see everything the source covers |
| **Source-specific** | Met Office: regions and local authorities. Meteoalarm: countries. NWS: states. Environment Canada: provinces. CWA Taiwan: API key and counties |
| **Data types** | Switch Warnings, Forecasts and Air Quality on or off for each source. All three start on. Entities are removed when a type is off and come back when you turn it on again |
| **Forecast location** | Forecasts use your Home Assistant home location by default. Set another latitude and longitude if your warning area is somewhere else, for example forecasts for one town while watching a whole region |

---

## Entities and services

Each source creates up to 59 entities, depending on its data type settings.

| Group | Entities |
| --- | --- |
| Warnings | 4: Active Alert, Upcoming Alert, Alert Count, Alert Active. Not created for Worldwide Forecast |
| Current conditions | 25 sensors |
| Atmospheric stability | 4 sensors |
| Weather insights | 4 sensors |
| Air quality | 9 sensors |
| Astronomy | 12 sensors. Moon phase and daylight duration are on by default, and the others are off until you enable them in the entity settings |
| Weather | 1 weather entity |

When an alert's attributes would be too large for Home Assistant's history database (16 KB), they are shortened: only the first 20 places are kept (`locations_count` holds the full number), long descriptions in `all_alerts` are cut, and `attributes_truncated` is set to `true`. The alerts themselves are unchanged.

**Service `atmos_ce.get_extended_forecast`** returns the full hourly or daily forecast, including dew point, CAPE, the rain, showers and snowfall breakdown and other fields the standard `weather.get_forecasts` service leaves out. Pick the Atmos CE source and the type (`hourly` or `daily`) under **Developer Tools → Actions**.

---

## Known limitations

These are how the integration and its data sources work today, not bugs. Check here before opening a report.

| Limitation | Detail |
| --- | --- |
| A finished warning can stay shown until the next refresh | The active and upcoming lists are worked out each time data refreshes, so a warning that has just ended can show as active for up to one update interval (30 minutes by default). A shorter interval narrows the gap. |
| Met Office times are read as UK local time | The Met Office feed gives clock times without a time zone. Atmos CE assumes UK local time. That has not yet been checked against a summer-time warning, so while the UK is on British Summer Time a warning could start or end an hour off. |
| DWD counts each municipality's warning separately | DWD's feed lists warnings per municipality, so in widespread weather **Alert Count** can run into the hundreds. A location filter keeps it to the places you care about. |
| One failing Meteoalarm country makes the source's alert sensors unavailable | The warnings for all selected countries are fetched together. If one country's feed is down or has been retired, remove it in the options to get the others back. |
| Environment Canada makes many small requests | It reads several folders of alert files on every refresh, roughly 60 to 70 requests. A longer update interval keeps this light. |
| Daily sunrise and sunset in the extended forecast service | They are written in the forecast location's local time as it was today, so for days after a clock change they can read an hour off. The astronomy sensors are not affected. |

---

## FAQ

<details>
<summary><strong>Can I use more than one source?</strong></summary>

Yes. Add the integration once per source, for example Met Office for home and DWD for a second place. Each has its own settings and update schedule.

</details>

<details>
<summary><strong>My country is not listed.</strong></summary>

Use **Worldwide Forecast** for forecasts, air quality and astronomy anywhere. If your country has a public warning service, [start a Discussion](https://github.com/hiall-fyi/atmos_ce/discussions) and say which one.

</details>

<details>
<summary><strong>Why does Active Alert say "unknown"?</strong></summary>

It means no warning is in force, so there is nothing to show. For automations, use **Alert Active** (on or off) or **Alert Count**, which always have a value.

</details>

<details>
<summary><strong>No alerts are showing, but I expect some.</strong></summary>

Usually there really are none, and the official site will confirm it. If warnings exist but do not appear:

1. Check that your location filters are not too narrow.
2. Wait for the next refresh. The sensor's last update time shows when the data was last fetched.
3. Turn on debug logging (below) and look at what the source returned.

</details>

<details>
<summary><strong>Alert sensors say "unavailable".</strong></summary>

The last request for warnings either failed or came back as something the integration could not read, such as an error page. Instead of reporting no alerts, the alert sensors go `unavailable` until the next refresh works. Forecast and air quality sensors keep their own data.

Common causes are a network problem, the weather service being down for a while, or a wrong or expired CWA Taiwan key, in which case Home Assistant asks you to enter the key again. Nothing needs switching back on. The integration tries again at the next update interval. If it keeps failing, turn on debug logging and check the log for the message that explains why.

</details>

<details>
<summary><strong>Where does the data come from?</strong></summary>

Warnings come from the national service you picked. Forecasts and air quality come from Open-Meteo, and sun and moon times are calculated locally. Only CWA Taiwan needs a key.

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

Restart Home Assistant, reproduce the problem, then check **Settings → System → Logs** and filter by `atmos_ce`. Atmos CE is built not to write your coordinates into the log, but glance through it before you share it publicly.

</details>

For anything not covered here, search the [existing issues](https://github.com/hiall-fyi/atmos_ce/issues) and, if it is new, [open a bug report](https://github.com/hiall-fyi/atmos_ce/issues/new/choose). The form asks for your versions, which weather source is involved and a debug log, which is what turns a back-and-forth into a quick fix.

---

## Uninstall

1. **Settings → Devices & Services → Atmos CE → ⋮ → Delete**
2. Restart Home Assistant.
3. In HACS, find Atmos CE and choose **⋮ → Remove**. For a manual install, delete the `config/custom_components/atmos_ce/` folder.
4. Restart Home Assistant again.

---

## Documentation

| Document | Purpose |
| --- | --- |
| [CHANGELOG.md](CHANGELOG.md) | Version history |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setting up, checks and pull request guidelines |
| [SECURITY.md](SECURITY.md) | How to report a security problem |

---

## Contributing

Atmos CE grows through reports, data and testing from people who use it. If you have hit a problem, [open a bug report](https://github.com/hiall-fyi/atmos_ce/issues/new/choose). If you want something changed or just want to ask, [start a Discussion](https://github.com/hiall-fyi/atmos_ce/discussions). Logs and the name of the weather source involved are what make the difference between a long thread and a quick fix.

Code contributions are welcome too. See [CONTRIBUTING.md](CONTRIBUTING.md), and float an idea in Discussions before you write code for a new source.

---

## License

Released under the **GNU Affero General Public License v3.0 (AGPL-3.0)**. Modifications must be released as open source under the same licence with attribution. See [LICENSE](LICENSE) for the full text.

**Original author:** Joe Yiu ([@hiall-fyi](https://github.com/hiall-fyi))

---

<details>
<summary><strong>Disclaimer</strong></summary>

This project is not affiliated with, endorsed by, or connected to any of the weather services it uses (Met Office, Meteoalarm, the National Weather Service, Environment Canada, DWD, CWA Taiwan and Open-Meteo) or to Home Assistant. All trademarks belong to their respective owners.

Weather warnings are provided for information only. Always follow your local weather service for official safety guidance.

This integration is provided "as is" without warranty. Use at your own risk.

</details>
