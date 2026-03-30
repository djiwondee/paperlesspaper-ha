"""Binary sensor platform for paperlesspaper."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    """Set up paperlesspaper binary sensors."""
    coordinator: PaperlessCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        PaperlessDeviceReachableSensor(coordinator, device)
        for device in coordinator.data
    )


class PaperlessDeviceReachableSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor for device reachability via ping."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._device_id = device["id"]
        self._attr_unique_id = f"{device['id']}_reachable"
        self._attr_name = f"{device['meta'].get('name', device['id'])} Reachable"
        self._attr_icon = "mdi:wifi-check"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, device["id"])},
            name=device["meta"].get("name", device["id"]),
            manufacturer="paperlesspaper",
            model=device.get("kind", "epd"),
        )

    @property
    def _device(self) -> dict | None:
        """Return current device data from coordinator."""
        return next(
            (d for d in self.coordinator.data if d["id"] == self._device_id),
            None,
        )

    @property
    def is_on(self) -> bool | None:
        """Return true if device is reachable."""
        if self._device is None:
            return None
        return self._device.get("reachable")
