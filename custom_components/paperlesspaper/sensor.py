"""Sensor platform for paperlesspaper."""
from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
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
    """Set up paperlesspaper sensors."""
    coordinator: PaperlessCoordinator = hass.data[DOMAIN][entry.entry_id]

    async_add_entities(
        PaperlessDeviceStatusSensor(coordinator, device)
        for device in coordinator.data
    )


class PaperlessDeviceStatusSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing when the device last loaded an image."""

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._device_id = device["id"]
        self._attr_unique_id = f"{device['id']}_status"
        self._attr_name = f"{device['meta'].get('name', device['id'])} Last Loaded"
        self._attr_icon = "mdi:image-frame"
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
    def native_value(self) -> str | None:
        """Return last loaded timestamp."""
        if self._device is None:
            return None
        return self._device.get("loadedAt")

    @property
    def extra_state_attributes(self) -> dict:
        """Return additional attributes."""
        if self._device is None:
            return {}
        return {
            "device_id": self._device.get("deviceId"),
            "kind": self._device.get("kind"),
            "paper_id": self._device.get("paper_id"),
            "updated_at": self._device.get("updatedAt"),
            "sleep_time": self._device.get("meta", {}).get("sleepTime"),
        }
