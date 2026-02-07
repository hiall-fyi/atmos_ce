"""Config flow for Atmos CE integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import DOMAIN, HTTP_TIMEOUT
from .source_base import WeatherWarningSource
from .source_registry import get_available_sources, get_source_by_id

_LOGGER = logging.getLogger(__name__)


async def _validate_source_config(
    hass: HomeAssistant,
    source: WeatherWarningSource,
    user_input: dict[str, Any],
) -> tuple[bool, dict[str, str]]:
    """Validate source configuration and return errors dict.

    Args:
        hass: HomeAssistant instance.
        source: Source plugin to validate against.
        user_input: User-provided configuration to validate.

    Returns:
        Tuple of (valid, errors) where errors is empty on success.

    """
    session = async_get_clientsession(hass)
    errors: dict[str, str] = {}

    try:
        valid, error = await asyncio.wait_for(
            source.validate_config(session, user_input),
            timeout=HTTP_TIMEOUT,
        )
    except TimeoutError:
        _LOGGER.warning("Validation timeout for %s", source.source_name)
        errors["base"] = "validation_timeout"
        return False, errors
    except Exception:
        _LOGGER.exception(
            "Error validating config for %s", source.source_name,
        )
        errors["base"] = "validation_error"
        return False, errors

    if not valid:
        errors["base"] = error or "validation_failed"
        return False, errors

    return True, errors


class AtmosCEConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Atmos CE.

    Flow:
    1. Source selection (single-select dropdown)
    2. Source-specific configuration (national sources)
       OR forecast location (Worldwide Forecast)
    3. Entry created
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow."""
        self.source_id: str | None = None
        self.source_name: str | None = None
        self.source_config: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle the initial step, source selection.

        Args:
            user_input: User input from the form.

        Returns:
            Flow result (form or next step).

        """
        errors: dict[str, str] = {}

        if user_input is not None:
            self.source_id = user_input.get("source")

            if not self.source_id:
                errors["source"] = "no_source_selected"
            else:
                await self.async_set_unique_id(f"{DOMAIN}_{self.source_id}")
                self._abort_if_unique_id_configured()
                return await self.async_step_configure_source()

        return self.async_show_form(
            step_id="user",
            data_schema=self._get_source_selection_schema(),
            errors=errors,
        )

    @staticmethod
    def _get_source_selection_schema() -> vol.Schema:
        """Get schema for source selection step.

        Returns:
            Voluptuous schema with dropdown for single source selection.

        """
        sources = get_available_sources()
        source_options = {
            source.source_id: source.source_name
            for source in sources
        }
        return vol.Schema({
            vol.Required("source"): vol.In(source_options),
        })

    async def async_step_configure_source(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Configure source-specific settings.

        Args:
            user_input: User input from the form.

        Returns:
            Flow result (form or next step).

        """
        if not self.source_id:
            _LOGGER.error("configure_source called without source_id")
            return self.async_abort(reason="invalid_state")

        self.source_config = {}

        source = get_source_by_id(self.source_id)
        if source is None:
            _LOGGER.error("Source %s not found", self.source_id)
            return self.async_abort(reason="source_not_found")

        self.source_name = source.source_name

        # Worldwide Forecast goes to forecast location step instead
        if self.source_id == "worldwide_forecast":
            return await self.async_step_forecast_location(user_input)

        if user_input is not None:
            valid, errors = await _validate_source_config(
                self.hass, source, user_input,
            )
            if not valid:
                return self.async_show_form(
                    step_id="configure_source",
                    data_schema=source.get_config_schema(),
                    errors=errors,
                    description_placeholders={
                        "source_name": source.source_name,
                    },
                )
            self.source_config = user_input
            return self._create_entry()

        return self.async_show_form(
            step_id="configure_source",
            data_schema=source.get_config_schema(),
            description_placeholders={"source_name": source.source_name},
        )

    async def async_step_forecast_location(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Configure forecast location (Worldwide Forecast only).

        Args:
            user_input: User input from the form.

        Returns:
            Flow result (form or next step).

        """
        if self.source_id != "worldwide_forecast":
            _LOGGER.error(
                "forecast_location called for non-worldwide_forecast source: %s",
                self.source_id,
            )
            return self.async_abort(reason="invalid_state")

        errors: dict[str, str] = {}

        if user_input is not None:
            latitude = user_input.get("forecast_latitude")
            longitude = user_input.get("forecast_longitude")
            location_name = user_input.get("location_name", "").strip()

            if not location_name:
                errors["location_name"] = "location_name_required"

            if latitude is not None:
                try:
                    lat_float = float(latitude)
                    if not -90 <= lat_float <= 90:
                        errors["forecast_latitude"] = "invalid_latitude_range"
                except (ValueError, TypeError):
                    errors["forecast_latitude"] = "invalid_latitude_format"
            else:
                errors["forecast_latitude"] = "latitude_required"

            if longitude is not None:
                try:
                    lon_float = float(longitude)
                    if not -180 <= lon_float <= 180:
                        errors["forecast_longitude"] = "invalid_longitude_range"
                except (ValueError, TypeError):
                    errors["forecast_longitude"] = "invalid_longitude_format"
            else:
                errors["forecast_longitude"] = "longitude_required"

            if not errors:
                self.source_config = {
                    "location_name": location_name,
                    "forecast_latitude": float(latitude),
                    "forecast_longitude": float(longitude),
                }
                return self._create_entry()

        default_lat = self.hass.config.latitude
        default_lon = self.hass.config.longitude

        return self.async_show_form(
            step_id="forecast_location",
            data_schema=vol.Schema({
                vol.Required("location_name", default="Home"): cv.string,
                vol.Required("forecast_latitude", default=default_lat): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=-90, max=90),
                ),
                vol.Required("forecast_longitude", default=default_lon): vol.All(
                    vol.Coerce(float),
                    vol.Range(min=-180, max=180),
                ),
            }),
            errors=errors,
        )

    def _create_entry(self) -> FlowResult:
        """Create the config entry.

        Returns:
            Flow result with created entry.

        """
        title = self.source_name or self.source_id or "Unknown"
        data = {
            "source_id": self.source_id,
            "source_config": self.source_config,
        }
        return self.async_create_entry(title=title, data=data)

    async def async_step_reauth(
        self, entry_data: dict[str, Any],
    ) -> FlowResult:
        """Handle re-authentication when API key becomes invalid.

        Args:
            entry_data: Data from the config entry that needs re-auth.

        Returns:
            Flow result.

        """
        self.source_id = entry_data.get("source_id")
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle re-authentication confirmation step.

        Args:
            user_input: User input from the form.

        Returns:
            Flow result.

        """
        errors: dict[str, str] = {}

        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        source_id = entry.data.get("source_id")
        if not source_id:
            return self.async_abort(reason="missing_source_id")

        source = get_source_by_id(source_id)
        if source is None:
            return self.async_abort(reason="source_not_found")

        if user_input is not None:
            new_config = dict(entry.data.get("source_config", {}))
            new_config["api_key"] = user_input["api_key"]

            valid, errors = await _validate_source_config(
                self.hass, source, new_config,
            )
            if valid:
                update_kwargs: dict[str, Any] = {
                    "data": {**entry.data, "source_config": new_config},
                }
                if entry.options:
                    # Setup reads entry.options once it exists, so the new
                    # key has to land there too.
                    update_kwargs["options"] = {
                        **entry.options,
                        "api_key": user_input["api_key"],
                    }
                self.hass.config_entries.async_update_entry(
                    entry, **update_kwargs,
                )
                await self.hass.config_entries.async_reload(entry.entry_id)
                return self.async_abort(reason="reauth_successful")
            if errors.get("base") == "validation_failed":
                errors["base"] = "invalid_auth"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required("api_key"): cv.string,
            }),
            errors=errors,
            description_placeholders={"source_name": source.source_name},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AtmosCEOptionsFlow:
        """Get the options flow for this handler.

        Args:
            config_entry: Config entry instance.

        Returns:
            Options flow handler.

        """
        return AtmosCEOptionsFlow()

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle reconfiguration of an existing entry.

        Args:
            user_input: User input from the form.

        Returns:
            Flow result.

        """
        entry = self.hass.config_entries.async_get_entry(self.context["entry_id"])
        if entry is None:
            return self.async_abort(reason="entry_not_found")

        source_id = entry.data.get("source_id")
        if not source_id:
            return self.async_abort(reason="missing_source_id")

        source = get_source_by_id(source_id)
        if source is None:
            return self.async_abort(reason="source_not_found")

        existing_config: dict[str, Any] = (
            dict(entry.options) if entry.options else entry.data.get("source_config", {})
        )

        if user_input is not None:
            valid, errors = await _validate_source_config(
                self.hass, source, user_input,
            )
            if not valid:
                return self.async_show_form(
                    step_id="reconfigure",
                    data_schema=self.add_suggested_values_to_schema(
                        source.get_config_schema(), existing_config,
                    ),
                    errors=errors,
                    description_placeholders={"source_name": source.source_name},
                )
            new_data = {**entry.data, "source_config": user_input}
            if entry.options:
                # Setup reads entry.options once it exists, so merge the new
                # values in there too, keeping the existing data-type toggles.
                new_options = {**entry.options, **user_input}
                return self.async_update_reload_and_abort(
                    entry, data=new_data, options=new_options,
                )
            return self.async_update_reload_and_abort(entry, data=new_data)

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=self.add_suggested_values_to_schema(
                source.get_config_schema(), existing_config,
            ),
            description_placeholders={"source_name": source.source_name},
        )


class AtmosCEOptionsFlow(config_entries.OptionsFlowWithReload):
    """Handle options flow for Atmos CE.

    Shows source-specific settings, data type toggles, and forecast
    location override on a single page.
    """

    def __init__(self) -> None:
        """Initialize the AtmosCEOptionsFlow."""
        self.source_id: str | None = None

    def _build_extended_schema(
        self,
        source: WeatherWarningSource,
        existing_config: dict[str, Any],
    ) -> vol.Schema:
        """Build the full options schema with data type toggles and forecast location.

        Args:
            source: The source instance.
            existing_config: Existing options for suggested values.

        Returns:
            Extended schema.

        """
        base = dict(source.get_config_schema().schema)

        # Data type toggles
        if source.has_warning_backend:
            base[vol.Optional(
                "enable_warnings",
                default=existing_config.get("enable_warnings", True),
            )] = cv.boolean
        base[vol.Optional(
            "enable_forecast",
            default=existing_config.get("enable_forecast", True),
        )] = cv.boolean
        base[vol.Optional(
            "enable_air_quality",
            default=existing_config.get("enable_air_quality", True),
        )] = cv.boolean

        # Forecast location override
        base[vol.Optional(
            "forecast_latitude",
            default=existing_config.get(
                "forecast_latitude", self.hass.config.latitude,
            ),
        )] = vol.All(vol.Coerce(float), vol.Range(min=-90, max=90))
        base[vol.Optional(
            "forecast_longitude",
            default=existing_config.get(
                "forecast_longitude", self.hass.config.longitude,
            ),
        )] = vol.All(vol.Coerce(float), vol.Range(min=-180, max=180))

        return vol.Schema(base)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle options flow initialization.

        Args:
            user_input: User input from the form.

        Returns:
            Flow result.

        """
        self.source_id = self.config_entry.data.get("source_id")
        existing_config: dict[str, Any] = (
            dict(self.config_entry.options)
            if self.config_entry.options
            else self.config_entry.data.get("source_config", {})
        )

        if not self.source_id:
            _LOGGER.error("Config entry missing source_id")
            return self.async_abort(reason="missing_source_id")

        source = get_source_by_id(self.source_id)
        if source is None:
            _LOGGER.error("Source %s not found", self.source_id)
            return self.async_abort(reason="source_not_found")

        extended_schema = self._build_extended_schema(source, existing_config)

        if user_input is not None:
            valid, errors = await _validate_source_config(
                self.hass, source, user_input,
            )
            if not valid:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self.add_suggested_values_to_schema(
                        extended_schema, existing_config,
                    ),
                    errors=errors,
                    description_placeholders={
                        "source_name": source.source_name,
                    },
                )
            return self.async_create_entry(title="", data=user_input)

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                extended_schema, existing_config,
            ),
            description_placeholders={
                "source_name": source.source_name,
            },
        )
