# =============================================================================
# CHANGE HISTORY
# 2026-04-09  0.1.7  Options flow: replaced voluptuous Range validator with
#                    manual validation to enable localized error messages for
#                    out-of-range polling interval values.
#                    Removed custom __init__ from PaperlessOptionsFlow —
#                    self.config_entry is provided by HA automatically.
#                    Fixed async_get_options_flow to not pass config_entry
#                    to PaperlessOptionsFlow constructor.
# 2026-04-11  0.1.9  Config flow UX improvements:
#                    - Organization selection is now always shown (even for a
#                      single org), giving the user explicit confirmation.
#                    - Added new async_step_devices step: after selecting an
#                      org, the user sees the list of discovered devices and
#                      confirms before the entry is created.
#                    - Abort with dedicated error when no devices are found
#                      in the selected organization.
# 2026-04-11  0.2.0  devices step: replaced single radio selector with a
#                    multi-select checkbox list (SelectSelector with
#                    multiple=True) so users can see and confirm all devices
#                    at once. Fixed field name selected_device -> selected_devices.
# 2026-04-11  0.2.1  Added async_step_reconfigure: allows changing the API key
#                    and/or organization for an existing config entry without
#                    deleting and re-adding the integration.
# 2026-04-20  0.2.3  devices step: replaced checkbox SelectSelector with a
#                    plain summary screen. The device list is shown as text in
#                    the description placeholder — no form field, no false
#                    promise that de-selecting a device has any effect.
#                    The config entry always covers all devices in the
#                    organization. Removed selected_devices from data_schema
#                    and all related SelectSelector imports.
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
    DOMAIN,
    MAX_POLLING_INTERVAL,
    MIN_POLLING_INTERVAL,
)


class PaperlessConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for paperlesspaper.

    Initial setup flow (3 steps):
        1. async_step_user         — enter & validate API key
        2. async_step_organization — select organization (always shown)
        3. async_step_devices      — summary of discovered devices, confirm

    Reconfigure flow (re-uses steps 2 & 3 after re-validating the API key):
        1. async_step_reconfigure  — enter & validate new API key
        2. async_step_organization — select organization
        3. async_step_devices      — summary of discovered devices, confirm

    Note on the devices step: the config entry always covers ALL devices in
    the selected organization. The devices step is purely informational —
    it shows which devices will be added so the user can confirm, but there
    is no selection that affects which devices are actually managed.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Initialize flow state."""
        self._api_key: str = ""
        self._organizations: list[dict] = []
        self._selected_org: dict = {}
        self._devices: list[dict] = []
        # True when the flow was started via reconfigure.
        self._reconfigure: bool = False

    # ------------------------------------------------------------------
    # Step 1a: Initial setup — API key entry
    # ------------------------------------------------------------------

    async def async_step_user(self, user_input=None) -> ConfigFlowResult:
        """Step 1 (initial setup): Enter and validate API Key."""
        self._reconfigure = False
        return await self._async_step_api_key(step_id="user", user_input=user_input)

    # ------------------------------------------------------------------
    # Step 1b: Reconfigure — re-enter API key
    # ------------------------------------------------------------------

    async def async_step_reconfigure(self, user_input=None) -> ConfigFlowResult:
        """Step 1 (reconfigure): Re-enter and validate API Key.

        Allows changing the API key and/or organization for an existing
        config entry without deleting and re-adding the integration.
        """
        self._reconfigure = True
        return await self._async_step_api_key(
            step_id="reconfigure", user_input=user_input
        )

    # ------------------------------------------------------------------
    # Shared API key validation logic (used by both user & reconfigure)
    # ------------------------------------------------------------------

    async def _async_step_api_key(
        self, step_id: str, user_input
    ) -> ConfigFlowResult:
        """Validate the API key and advance to organization selection."""
        errors: dict[str, str] = {}

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
                            return await self.async_step_organization()

            except aiohttp.ClientConnectionError:
                errors["base"] = "cannot_connect"
            except TimeoutError:
                errors["base"] = "cannot_connect"

        # Pre-fill with current API key when reconfiguring.
        # _get_reconfigure_entry() is the correct way to access the existing
        # entry from within a ConfigFlow (self.config_entry is only available
        # on OptionsFlow).
        current_api_key = ""
        if self._reconfigure:
            current_api_key = self._get_reconfigure_entry().data.get(CONF_API_KEY, "")

        return self.async_show_form(
            step_id=step_id,
            data_schema=vol.Schema({
                vol.Required(CONF_API_KEY, default=current_api_key): str,
            }),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 2: Organization selection (always shown)
    # ------------------------------------------------------------------

    async def async_step_organization(self, user_input=None) -> ConfigFlowResult:
        """Step 2: Select organization.

        Always shown — even when only one organization exists — so the
        user has explicit control and visibility over which group is used.
        After a valid selection the flow fetches devices for that org and
        advances to async_step_devices.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            org_id = user_input[CONF_ORGANIZATION_ID]
            org = next((o for o in self._organizations if o["id"] == org_id), None)

            if org is None:
                errors["base"] = "unknown"
            else:
                devices = await self._fetch_devices(org_id)

                if devices is None:
                    errors["base"] = "cannot_connect"
                elif len(devices) == 0:
                    errors["base"] = "no_devices"
                else:
                    self._selected_org = org
                    self._devices = devices
                    return await self.async_step_devices()

        # Pre-select the currently configured org when reconfiguring.
        current_org_id = ""
        if self._reconfigure:
            current_org_id = self._get_reconfigure_entry().data.get(
                CONF_ORGANIZATION_ID, ""
            )

        org_options = {org["id"]: org["name"] for org in self._organizations}

        return self.async_show_form(
            step_id="organization",
            data_schema=vol.Schema({
                vol.Required(
                    CONF_ORGANIZATION_ID,
                    default=current_org_id if current_org_id in org_options else vol.UNDEFINED,
                ): vol.In(org_options),
            }),
            errors=errors,
        )

    # ------------------------------------------------------------------
    # Step 3: Device summary (informational only — no form fields)
    # ------------------------------------------------------------------

    async def async_step_devices(self, user_input=None) -> ConfigFlowResult:
        """Step 3: Show a plain summary of discovered devices and confirm.

        This step is purely informational. The config entry always covers
        ALL devices in the organization — there is no selection that would
        affect which devices are managed. Showing checkboxes would imply
        that de-selecting a device has an effect, which it does not.

        The device names are rendered as a simple list in the description
        placeholder so the user knows exactly what will be added before
        clicking Submit.
        """
        if user_input is not None:
            if self._reconfigure:
                return await self._async_update_entry(self._selected_org)
            return await self._create_entry(self._selected_org)

        # Build a plain text device list for the description placeholder.
        # Each device is shown as "• Device Name" on its own line.
        device_list = "\n".join(
            f"• {d.get('meta', {}).get('name') or d['id']}"
            for d in self._devices
        )

        return self.async_show_form(
            step_id="devices",
            data_schema=vol.Schema({}),  # No fields — summary screen only
            description_placeholders={
                "device_count": str(len(self._devices)),
                "device_list": device_list,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    async def _fetch_devices(self, org_id: str) -> list[dict] | None:
        """Fetch devices for an organization.

        Returns the device list on success, [] when org has no devices,
        or None on network/API error.
        """
        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                f"{API_BASE_URL}/devices/",
                headers={"x-api-key": self._api_key},
                params={"organization": org_id},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("results", [])
        except (aiohttp.ClientError, TimeoutError):
            return None

    async def _create_entry(self, org: dict) -> ConfigFlowResult:
        """Create a new config entry for the selected organization."""
        await self.async_set_unique_id(org["id"])
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=org["name"],
            data={
                CONF_API_KEY: self._api_key,
                CONF_ORGANIZATION_ID: org["id"],
            },
        )

    async def _async_update_entry(self, org: dict) -> ConfigFlowResult:
        """Update the existing config entry during reconfigure.

        _get_reconfigure_entry() is the correct way to access the existing
        entry from within a ConfigFlow (self.config_entry is only available
        on OptionsFlow).
        """
        reconfigure_entry = self._get_reconfigure_entry()
        return self.async_update_reload_and_abort(
            reconfigure_entry,
            title=org["name"],
            data={
                **reconfigure_entry.data,
                CONF_API_KEY: self._api_key,
                CONF_ORGANIZATION_ID: org["id"],
            },
        )

    # ------------------------------------------------------------------
    # Options flow
    # ------------------------------------------------------------------

    @staticmethod
    @callback
    def async_get_options_flow(config_entry) -> OptionsFlow:
        """Return the options flow."""
        return PaperlessOptionsFlow()


class PaperlessOptionsFlow(OptionsFlow):
    """Handle options for paperlesspaper.

    No __init__ needed — self.config_entry is provided by HA automatically.
    """

    async def async_step_init(self, user_input=None) -> ConfigFlowResult:
        """Manage options."""
        errors: dict[str, str] = {}

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
                ): int,
            }),
            errors=errors,
        )
