"""Sensor platform for paperlesspaper."""
from __future__ import annotations

from datetime import datetime

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
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

    entities = []
    for device in coordinator.data:
        entities.extend([
            PaperlessPictureSyncedSensor(coordinator, device),
            PaperlessBatLevelSensor(coordinator, device),
            PaperlessNextSyncSensor(coordinator, device),
            PaperlessSleepTimeSensor(coordinator, device),
            PaperlessSleepTimePredictSensor(coordinator, device),
        ])

    async_add_entities(entities)


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


class PaperlessBaseSensor(CoordinatorEntity, SensorEntity):
    """Base sensor for paperlesspaper devices."""

    _field: str
    _attr_icon: str = "mdi:image-frame"

    def __init__(
        self,
        coordinator: PaperlessCoordinator,
        device: dict,
        unique_suffix: str,
        name_suffix: str,
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self._device_id = device["id"]
        self._attr_unique_id = f"{device['id']}_{unique_suffix}"
        self._attr_name = f"{device['meta'].get('name', device['id'])} {name_suffix}"
        self._attr_device_info = _device_info(device)

    @property
    def _device(self) -> dict | None:
        """Return current device data from coordinator."""
        return next(
            (d for d in self.coordinator.data if d["id"] == self._device_id),
            None,
        )

    @property
    def native_value(self):
        """Return sensor value."""
        if self._device is None:
            return None
        return self._device.get(self._field)


class PaperlessPictureSyncedSensor(PaperlessBaseSensor):
    """Sensor: picture synced status."""

    _field = "picture_synced"
    _attr_icon = "mdi:image-check"

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "picture_synced", "Picture Synced")


class PaperlessBatLevelSensor(PaperlessBaseSensor):
    """Sensor: battery level (raw mV value from API)."""

    _field = "bat_level"
    _attr_icon = "mdi:battery"
    _attr_native_unit_of_measurement = "V"

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "bat_level", "Battery Level")

    @property
    def native_value(self) -> float | None:
        """Return battery level in Volts (API provides mV)."""
        if self._device is None:
            return None
        val = self._device.get("bat_level")
        if val is None:
            return None
        try:
            return round(int(val) / 1000, 2)
        except (ValueError, TypeError):
            return None


class PaperlessNextSyncSensor(PaperlessBaseSensor):
    """Sensor: next device sync as datetime object."""

    _field = "next_device_sync"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "next_device_sync", "Next Sync")

    @property
    def native_value(self) -> datetime | None:
        """Return next sync as datetime object."""
        if self._device is None:
            return None
        iso_str = self._device.get("next_device_sync")
        if iso_str is None:
            return None
        try:
            return datetime.fromisoformat(iso_str)
        except (ValueError, TypeError):
            return None


class PaperlessSleepTimeSensor(PaperlessBaseSensor):
    """Sensor: configured sleep time in seconds."""

    _field = "sleep_time"
    _attr_icon = "mdi:sleep"
    _attr_native_unit_of_measurement = "s"

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "sleep_time", "Sleep Time")


class PaperlessSleepTimePredictSensor(PaperlessBaseSensor):
    """Sensor: predicted sleep time in seconds."""

    _field = "sleep_time_predict"
    _attr_icon = "mdi:sleep"
    _attr_native_unit_of_measurement = "s"

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "sleep_time_predict", "Sleep Time Predicted")
