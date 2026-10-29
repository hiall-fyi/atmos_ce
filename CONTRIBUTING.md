# Contributing to Atmos CE

Thanks for your interest in contributing.

## Development Setup

```bash
git clone https://github.com/hiall-fyi/atmos_ce.git
cd atmos_ce
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
```

The pinned Home Assistant needs Python 3.14.2 or newer for the development environment. The integration itself supports older Home Assistant releases than that (see `hacs.json`).

To try a change in Home Assistant, copy or symlink `custom_components/atmos_ce/` into your HA config's `custom_components/` folder and restart.

## Checks

```bash
ruff check custom_components/
mypy custom_components/atmos_ce/
```

The ruff and mypy settings live in a `pyproject.toml` that isn't part of this repository (the comment at the top of `requirements-dev.txt` explains why), so a bare run checks against the tools' defaults. Treat anything they report as worth a look, and don't be put off if a maintainer's run is stricter.

CI runs HACS validation, hassfest, secret scanning and CodeQL on every pull request. It doesn't run the test suite, so please run your own tests before you submit.

## Project Structure

Everything lives under `custom_components/atmos_ce/`:

- **Sources** — `sources/` has one file per weather service (`met_office.py`, `meteoalarm.py`, `nws.py`, `environment_canada.py`, `dwd.py`, `cwa_taiwan.py`, `worldwide_forecast.py`). They share a base class in `source_base.py`.
- **Fetching** — `http_retry.py` is the one place requests are made and retried, and where error text is cleaned of addresses, keys and coordinates. `forecast_backend.py` talks to Open-Meteo.
- **Setup and data** — `__init__.py`, `config_flow.py`, `coordinator.py`, `models.py`, `storage.py`.
- **Entities** — `weather.py`, `binary_sensor.py`, `entity.py` and the `sensor/` folder (alerts, forecast, astronomy, stability, insights).
- **Diagnostics** — `diagnostics.py`.

## Pull Request Guidelines

- Keep each pull request to one change.
- Add tests for new behaviour, and run them before you submit.
- Add a line to `CHANGELOG.md` under `[Unreleased]`, written for someone using the integration rather than reading the code.
- Leave ticket and issue numbers out of source comments, docstrings and log messages. The CHANGELOG and the pull request description are where they belong.

## Code Style

- Python 3.12 or newer, with `from __future__ import annotations`.
- Lazy logging (`_LOGGER.debug("...%s", value)`), never an f-string.
- Listeners registered with Home Assistant (`async_track_state_change_event` and similar) and `_handle_coordinator_update` overrides need the `@callback` decorator. Without it the failure only shows on a real event loop, not in a test.
- A broad `except Exception` needs a comment saying why it has to be broad, and must log at least once.
- Anything that goes into a log, an error message or a diagnostics file must not contain the user's coordinates or API keys. If you add a new request path, send it through `http_retry.py` rather than calling `aiohttp` directly.

## Reporting Issues

Please use the [issue templates](https://github.com/hiall-fyi/atmos_ce/issues/new/choose) and include:

- Your Atmos CE and Home Assistant versions
- Which weather source the problem is about
- A debug log if something behaves unexpectedly, not just a screenshot (remove your latitude and longitude from it first if you'd rather not share them)
- Steps to reproduce

For security problems, see [SECURITY.md](SECURITY.md) instead of opening a public issue.
