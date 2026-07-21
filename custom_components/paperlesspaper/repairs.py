"""Repairs platform for paperlesspaper.

Implements the fix flow for the 'orphaned_device_*' issue family created by
the coordinator (see coordinator._reconcile_devices()) when a device that is
registered in Home Assistant is no longer reported by the paperlesspaper API
for several consecutive poll cycles, and no automatic deviceId-based remap
was possible.

The user is offered two options:
  - Delete the device (and all its entities) from Home Assistant.
  - Manually relink it to a currently-unclaimed device reported by the API —
    for cases where the device was already orphaned before the automatic
    deviceId-based remap (introduced in v1.2.0) was in place, so no stored
    deviceId was available yet to match against automatically.
"""
# =============================================================================
# CHANGE HISTORY
# 2026-07-18  1.2.0  New module. OrphanedDeviceRepairFlow with a single
#                    confirm step that removes the orphaned device.
# 2026-07-20  1.2.0  Replaced the single confirm step with a menu offering
#                    "Delete" or "Relink to another device" (manual remap).
#                    The manual remap path covers devices that were already
#                    orphaned before the automatic deviceId-based remap in
#                    coordinator._reconcile_devices() was in place (no stored
#                    deviceId to match against for those). Uses
#                    coordinator.async_candidate_devices_for_remap() and
#                    coordinator.async_manual_remap().
# 2026-07-21  1.2.0  Fixed confusing UX in async_step_remap when no unclaimed
#                    devices are available to relink to: previously showed an
#                    empty form with only a Submit button, which looked broken.
#                    Now aborts clearly with a translated "no_candidates"
#                    message; the issue stays open so the user can retry
#                    later or use "Delete" instead.
# =============================================================================

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import data_entry_flow
from homeassistant.components.repairs import RepairsFlow
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class OrphanedDeviceRepairFlow(RepairsFlow):
    """Let the user delete an orphaned device, or manually relink it."""

    def __init__(self, device_id: str, pp_device_id: str, config_entry_id: str) -> None:
        """Initialize with HA device id, paperlesspaper id, and entry id."""
        self._device_id = device_id
        self._pp_device_id = pp_device_id
        self._config_entry_id = config_entry_id

    def _device_name(self) -> str:
        """Return a display name for the orphaned device."""
        device_registry = dr.async_get(self.hass)
        device_entry = device_registry.async_get(self._device_id)
        if device_entry is None:
            return self._pp_device_id
        return device_entry.name_by_user or device_entry.name or self._pp_device_id

    async def async_step_init(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Show the delete-or-relink menu."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["delete", "remap"],
            description_placeholders={"device_name": self._device_name()},
        )

    async def async_step_delete(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Confirm and remove the device."""
        if user_input is not None:
            device_registry = dr.async_get(self.hass)
            if device_registry.async_get(self._device_id) is not None:
                device_registry.async_remove_device(self._device_id)
                _LOGGER.info(
                    "Removed orphaned paperlesspaper device %s (pp id %s) "
                    "via Repairs flow",
                    self._device_id, self._pp_device_id,
                )
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="delete",
            data_schema=vol.Schema({}),
            description_placeholders={"device_name": self._device_name()},
        )

    async def async_step_remap(
        self, user_input: dict[str, str] | None = None
    ) -> data_entry_flow.FlowResult:
        """Let the user manually pick which new device is the same physical frame."""
        coordinator = self.hass.data[DOMAIN][self._config_entry_id]
        candidates = coordinator.async_candidate_devices_for_remap()

        if not candidates:
            # Nothing to relink to yet. An empty form with just a Submit
            # button (the previous behaviour) is confusing — the user can't
            # tell whether something is broken or there's simply nothing to
            # pick. Abort clearly instead: the issue stays open (not marked
            # fixed) so the user can retry later, e.g. via "Delete" or by
            # coming back to "Relink" once a new device has appeared.
            return self.async_abort(
                reason="no_candidates",
                description_placeholders={"device_name": self._device_name()},
            )

        if user_input is not None:
            new_pp_id = user_input["new_device"]
            success = coordinator.async_manual_remap(
                self._device_id, self._pp_device_id, new_pp_id
            )
            if not success:
                _LOGGER.warning(
                    "Manual remap failed: HA device %s no longer exists",
                    self._device_id,
                )
            return self.async_create_entry(data={})

        return self.async_show_form(
            step_id="remap",
            data_schema=vol.Schema({
                vol.Required("new_device"): vol.In(candidates),
            }),
            description_placeholders={"device_name": self._device_name()},
        )


async def async_create_fix_flow(
    hass: HomeAssistant,
    issue_id: str,
    data: dict[str, Any] | None,
) -> RepairsFlow:
    """Create the repair flow instance for a given issue id.

    'data' contains 'device_id' (HA device registry id), 'pp_device_id'
    (paperlesspaper device id), and 'config_entry_id', as set by
    coordinator._reconcile_devices().
    """
    data = data or {}
    return OrphanedDeviceRepairFlow(
        device_id=data["device_id"],
        pp_device_id=data["pp_device_id"],
        config_entry_id=data["config_entry_id"],
    )
