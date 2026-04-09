# =============================================================================
# CHANGE HISTORY
# 2026-04-09  0.1.7  Options flow: replaced voluptuous Range validator with
#                    manual validation to enable localized error messages for
#                    out-of-range polling interval values.
#                    Removed custom __init__ from PaperlessOptionsFlow —
#                    self.config_entry is provided by HA automatically.
#                    Fixed async_get_options_flow to not pass config_entry
#                    to PaperlessOptionsFlow constructor.
# =============================================================================

"""Config flow for paperlesspaper integration."""
from __future__ import annotations

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_BASE_URL,
    CONF_API_KEY,
    CONF_ORGANIZATION_ID,
    CONF_POLLING_INTERVAL,
    DEFAULT_POLLING_INTERVAL,
    MAX_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
    DOMAIN,
)


class PaperlessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for paperlesspaper."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize."""
        self._api_key: str = ""
        self._organizations: list[dict] = []

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Step 1: Enter and validate API Key."""
        errors = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            session = async_get_clientsession(self.hass)

            try:
                async with session.get(
                    f"{API_BASE_URL}/organizations/",
                    headers={"x-api-key": api_key},
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status == 401:
                        errors[CONF_API_KEY] = "invalid_auth"
                    elif resp.status != 200:
                        errors["base"] = "cannot_connect"
                    else:
                        data = await resp.json()
                        orgs = data.get("results", [])

                        if len(orgs) == 0:
                            errors["base"] = "no_organizations"
                        else:
                            self._api_key = api_key
                            self._organizations = orgs

                            if len(orgs) == 1:
                                return await self._create_entry(orgs[0])
                            else:
                                return await self.async_step_organization()

            except aiohttp.ClientConnectionError:
                errors["base"] = "cannot_connect"
            except TimeoutError:
                errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY): str,
            }),
            errors=errors,
        )

    async def async_step_organization(self, user_input=None) -> ConfigFlowResult:
        """Step 2: Select organization (only shown when multiple exist)."""
        errors = {}

        if user_input is not None:
            org_id = user_input[CONF_ORGANIZATION_ID]
            org = next((o for o in self._organizations if o["id"] == org_id), None)
            if org:
                return await self._create_entry(org)
            errors["base"] = "unknown"

        org_options = {org["id"]: org["name"] for org in self._organizations}

        return self.async_show_form(
            step_id="organization",
            data_schema=vol.Schema({
                vol.Required(CONF_ORGANIZATION_ID): vol.In(org_options),
            }),
            errors=errors,
        )

    async def _create_entry(self, org: dict) -> ConfigFlowResult:
        """Create config entry."""
        await self.async_set_unique_id(org["id"])
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=org["name"],
            data={
                CONF_API_KEY: self._api_key,
                CONF_ORGANIZATION_ID: org["id"],
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the options flow.

        Note: config_entry is passed by HA but not forwarded to the constructor —
        PaperlessOptionsFlow accesses it via self.config_entry automatically.
        """
        return PaperlessOptionsFlow()


class PaperlessOptionsFlow(OptionsFlow):
    """Handle options for paperlesspaper."""

    # No __init__ needed — self.config_entry is provided by HA automatically.

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Manage options."""
        errors = {}

        if user_input is not None:
            interval = user_input.get(CONF_POLLING_INTERVAL)
            if interval is not None and interval < MIN_POLLING_INTERVAL:
                errors[CONF_POLLING_INTERVAL] = "polling_interval_too_low"
            elif interval is not None and interval > MAX_POLLING_INTERVAL:
                errors[CONF_POLLING_INTERVAL] = "polling_interval_too_high"
            else:
                return self.async_create_entry(title="", data=user_input)

        current_interval = self.config_entry.options.get(
            CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_POLLING_INTERVAL,
                    default=current_interval,
                ): int,  # No Range here — validated manually above
            }),
            errors=errors,
        )