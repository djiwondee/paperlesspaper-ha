"""Binary sensor platform for paperlesspaper."""
# =============================================================================
# CHANGE HISTORY
# 2026-04-08  0.1.5  Added PaperlessPictureSyncedSensor (moved from sensor.py)
#                    Fixed docstring of PaperlessUpdatePendingSensor:
#                    updatePending reflects picture update state, not firmware
# 2026-04-09  0.1.6  Fixed sensor updates: introduced PaperlessBaseBinarySensor
#                    base class with _handle_coordinator_update to ensure HA
#                    state machine is updated on every coordinator poll cycle.
#                    Removed duplicated _device property from each sensor class.
# 2026-04-11  0.2.0  Dynamic entity discovery: startup entities are added
#                    directly from coordinator.data (guaranteed to be populated
#                    after async_config_entry_first_refresh). A coordinator
#                    listener handles devices added later without a restart.
#                    Removed devices are NOT auto-removed — their entities
#                    remain in HA and become unavailable.
# =============================================================================

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PaperlessCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up paperlesspaper binary sensors.

    Adds binary sensor entities for all devices currently known to the
    coordinator (coordinator.data is always populated at this point because
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
        initial_entities.extend(_binary_sensors_for_device(coordinator, device))

    if initial_entities:
        async_add_entities(initial_entities)

    # Listener for devices added after initial setup.
    @callback
    def _async_add_binary_sensors_for_new_devices() -> None:
        """Detect new devices on every coordinator refresh and add their sensors."""
        new_entities = []
        for device in coordinator.data or []:
            if device["id"] not in known_device_ids:
                known_device_ids.add(device["id"])
                new_entities.extend(_binary_sensors_for_device(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        coordinator.async_add_listener(_async_add_binary_sensors_for_new_devices)
    )


def _binary_sensors_for_device(
    coordinator: PaperlessCoordinator, device: dict
) -> list:
    """Return all binary sensor entities for a single device."""
    return [
        PaperlessDeviceReachableSensor(coordinator, device),
        PaperlessPictureSyncedSensor(coordinator, device),
        PaperlessUpdatePendingSensor(coordinator, device),
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


class PaperlessBaseBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Base binary sensor for paperlesspaper devices.

    Provides shared functionality for all binary sensors:
    - Device data lookup from coordinator
    - Explicit state push on every coordinator update cycle
    """

    _attr_has_entity_name = True
    _attr_force_update = True  # Always write state, even if value unchanged

    def __init__(
        self,
        coordinator: PaperlessCoordinator,
        device: dict,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._device_id = device["id"]
        self._attr_device_info = _device_info(device)

    @callback
    def _handle_coordinator_update(self) -> None:
        """Push updated state to HA on every coordinator refresh."""
        self.async_write_ha_state()

    @property
    def _device(self) -> dict | None:
        """Return current device data from coordinator.

        Returns None when the device is no longer returned by the API —
        the entity stays in HA and becomes unavailable until removed manually.
        """
        return next(
            (d for d in self.coordinator.data if d["id"] == self._device_id),
            None,
        )


class PaperlessDeviceReachableSensor(PaperlessBaseBinarySensor):
    """Binary sensor for device reachability via ping."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_translation_key = "reachable"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device['id']}_reachable"
        self._attr_icon = "mdi:wifi-check"

    @property
    def is_on(self) -> bool | None:
        """Return true if device is reachable."""
        if self._device is None:
            return None
        return self._device.get("reachable")


class PaperlessPictureSyncedSensor(PaperlessBaseBinarySensor):
    """Binary sensor: True if the current picture is synced to the display.

    The API field 'pictureSynced' is True when the display is showing the
    latest uploaded image, and False when a new image has been uploaded but
    not yet fetched by the device on its next wake cycle.
    """

    _attr_translation_key = "picture_synced"
    _attr_icon = "mdi:image-check"

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device['id']}_picture_synced"

    @property
    def is_on(self) -> bool | None:
        """Return True if the picture is synced to the display."""
        if self._device is None:
            return None
        return self._device.get("picture_synced")


class PaperlessUpdatePendingSensor(PaperlessBaseBinarySensor):
    """Binary sensor: True if a picture update is pending.

    The API field 'updatePending' reflects whether the device has a pending
    picture update to process. Value 'update_ok' means no update is pending.
    """

    _attr_device_class = BinarySensorDeviceClass.UPDATE
    _attr_translation_key = "update_pending"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device)
        self._attr_unique_id = f"{device['id']}_update_pending"
        self._attr_icon = "mdi:update"

    @property
    def is_on(self) -> bool | None:
        """Return True if a picture update is pending."""
        if self._device is None:
            return None
        val = self._device.get("update_pending")
        if val is None:
            return None
        return val != "update_ok"
