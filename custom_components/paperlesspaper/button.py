"""Button platform for paperlesspaper."""
# =============================================================================
# CHANGE HISTORY
# 2026-04-11  0.2.0  Dynamic entity discovery: startup entities are added
#                    directly from coordinator.data (guaranteed to be populated
#                    after async_config_entry_first_refresh). A coordinator
#                    listener handles devices added later without a restart.
#                    Removed devices are NOT auto-removed — their entities
#                    remain in HA and become unavailable.
# =============================================================================

from __future__ import annotations

import logging

import aiohttp

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import API_BASE_URL, DOMAIN
from .coordinator import PaperlessCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up paperlesspaper buttons.

    Adds button entities for all devices currently known to the coordinator
    (coordinator.data is always populated at this point because
    async_config_entry_first_refresh has already run in __init__.py).

    A coordinator listener is also registered to detect devices that are
    added to the paperlesspaper organization later — those entities are
    registered dynamically without requiring a restart.
    """
    coordinator: PaperlessCoordinator = hass.data[DOMAIN][entry.entry_id]

    # Seed known_device_ids with all devices present at startup and add
    # their entities immediately — this is the reliable path.
    known_device_ids: set[str] = set()
    initial_entities = []
    for device in coordinator.data or []:
        known_device_ids.add(device["id"])
        initial_entities.extend(_buttons_for_device(coordinator, device))

    if initial_entities:
        async_add_entities(initial_entities)

    # Listener for devices added after initial setup.
    @callback
    def _async_add_buttons_for_new_devices() -> None:
        """Detect new devices on every coordinator refresh and add their buttons."""
        new_entities = []
        for device in coordinator.data or []:
            if device["id"] not in known_device_ids:
                known_device_ids.add(device["id"])
                new_entities.extend(_buttons_for_device(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        coordinator.async_add_listener(_async_add_buttons_for_new_devices)
    )


def _buttons_for_device(
    coordinator: PaperlessCoordinator, device: dict
) -> list:
    """Return all button entities for a single device."""
    return [
        PaperlessRebootButton(coordinator, device),
        PaperlessResetButton(coordinator, device),
    ]


def _device_info(device: dict) -> DeviceInfo:
    """Return DeviceInfo for a device."""
    return DeviceInfo(
        identifiers={(DOMAIN, device["id"])},
        name=device["meta"].get("name", device["id"]),
        manufacturer="paperlesspaper",
        model=device.get("kind", "epd"),
        sw_version=device.get("fw_version"),
        serial_number=device.get("serial_number"),
    )


class PaperlessBaseButton(CoordinatorEntity, ButtonEntity):
    """Base button for paperlesspaper devices."""

    _endpoint: str
    _action_name: str
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: PaperlessCoordinator,
        device: dict,
        unique_suffix: str,
        translation_key: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._device_id = device["id"]
        self._attr_unique_id = f"{device['id']}_{unique_suffix}"
        self._attr_translation_key = translation_key
        self._attr_device_info = _device_info(device)

    async def async_press(self) -> None:
        """Handle button press."""
        session = async_get_clientsession(self.hass)
        try:
            async with session.post(
                f"{API_BASE_URL}/devices/{self._endpoint}/{self._device_id}",
                headers={"x-api-key": self.coordinator.api_key},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                action_result = data.get(self._action_name, {})
                if action_result.get("success"):
                    _LOGGER.info(
                        "%s successful for device %s: %s",
                        self._action_name,
                        self._device_id,
                        action_result.get("message", ""),
                    )
                else:
                    _LOGGER.warning(
                        "%s returned unexpected response for device %s: %s",
                        self._action_name,
                        self._device_id,
                        data,
                    )
        except aiohttp.ClientResponseError as err:
            raise HomeAssistantError(
                f"{self._action_name} failed for device {self._device_id}: HTTP {err.status}"
            ) from err
        except aiohttp.ClientError as err:
            raise HomeAssistantError(
                f"{self._action_name} failed for device {self._device_id}: {err}"
            ) from err


class PaperlessRebootButton(PaperlessBaseButton):
    """Button to reboot the ePaper device."""

    _endpoint = "reboot"
    _action_name = "reboot"
    _attr_icon = "mdi:restart"

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "reboot", "reboot")


class PaperlessResetButton(PaperlessBaseButton):
    """Button to reset all sensors on the ePaper device to factory defaults."""

    _endpoint = "reset"
    _action_name = "reset"
    _attr_icon = "mdi:restore"

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "reset", "reset_sensors")
