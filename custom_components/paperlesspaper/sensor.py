"""Sensor platform for paperlesspaper."""
# =============================================================================
# CHANGE HISTORY
# 2026-04-08  0.1.3  Fixed Python 3 exception syntax: except (A, B) instead
#                    of except A, B (Python 2 syntax) in PaperlessBatLevelSensor
#                    and PaperlessNextSyncSensor.
# 2026-04-08  0.1.4  Split battery sensor into two separate sensors:
#                    - PaperlessBatLevelSensor: percentage (0-100%) calculated
#                      from voltage using ((V - 4.4) / (6.0 - 4.4) * 100)
#                    - PaperlessBatVoltageSensor: raw voltage in V (mV -> V)
# 2026-04-08  0.1.5  Moved PaperlessPictureSyncedSensor to binary_sensor.py
# 2026-04-09  0.1.6  Fixed sensor updates: added _handle_coordinator_update to
#                    PaperlessBaseSensor to ensure HA state machine is updated
#                    on every coordinator poll cycle.
# 2026-04-11  0.2.0  Dynamic entity discovery: startup entities are added
#                    directly from coordinator.data (guaranteed to be populated
#                    after async_config_entry_first_refresh). A coordinator
#                    listener handles devices added later without a restart.
#                    Removed devices are NOT auto-removed — their entities
#                    remain in HA and become unavailable.
# 2026-04-20  0.2.3  sleep_time_predict: marked as EntityCategory.DIAGNOSTIC
#                    and disabled by default (_attr_entity_registry_enabled_default
#                    = False). Clarified docstring: describes the predicted sleep
#                    duration, NOT the next image display time.
#                    sleep_time: removed EntityCategory.DIAGNOSTIC — sensor stays
#                    visible in main Sensors section (not Diagnostic).
#                    next_device_sync: corrected label — renamed from "Next Sync"
#                    to "Update Interval" (EN) / "Aktualisierungsintervall" (DE).
#                    It describes the device's periodic wake/check interval, not
#                    a one-time sync event.
# 2026-04-20  0.2.4  Fixed UTC timestamp display: coordinator now stores
#                    next_device_sync as a timezone-aware datetime object (UTC)
#                    instead of an ISO string. PaperlessNextSyncSensor.native_value
#                    returns the datetime directly — no fromisoformat() conversion
#                    needed. This ensures HA correctly converts and displays the
#                    timestamp in the user's local timezone everywhere (UI,
#                    history, logbook, Activities).
# 2026-06-01  1.1.0  Added two new diagnostic sensors sourced from the
#                    activate events polled via GET /devices/events:
#                    - PaperlessWifiRssiSensor: WiFi signal strength in dBm.
#                      Updated on every device wake-up (activate event).
#                    - PaperlessOrientationSensor: display orientation (0–3).
#                      Updated on every device wake-up (activate event).
#                    Both sensors are diagnostic, enabled by default, and
#                    read from the coordinator device dict fields wifi_rssi
#                    and orientation which are populated by the coordinator's
#                    _process_device_events() after each activate event.
# =============================================================================

from __future__ import annotations

from datetime import datetime
from typing import ClassVar

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import PaperlessCoordinator

# Battery voltage range for percentage calculation (in Volts)
BAT_VOLTAGE_MIN = 4.4  # 0% — minimum operating voltage
BAT_VOLTAGE_MAX = 6.0  # 100% — fully charged voltage


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up paperlesspaper sensors.

    Adds sensor entities for all devices currently known to the coordinator
    (coordinator.data is always populated at this point because
    async_config_entry_first_refresh has already run in __init__.py).

    A coordinator listener is also registered to detect devices that are
    added to the paperlesspaper organization later — those entities are
    registered dynamically without requiring a restart.
    """
    coordinator: PaperlessCoordinator = hass.data[DOMAIN][entry.entry_id]

    known_device_ids: set[str] = set()
    initial_entities = []
    for device in coordinator.data or []:
        known_device_ids.add(device["id"])
        initial_entities.extend(_sensors_for_device(coordinator, device))

    if initial_entities:
        async_add_entities(initial_entities)

    @callback
    def _async_add_sensors_for_new_devices() -> None:
        """Detect new devices on every coordinator refresh and add their sensors."""
        new_entities = []
        for device in coordinator.data or []:
            if device["id"] not in known_device_ids:
                known_device_ids.add(device["id"])
                new_entities.extend(_sensors_for_device(coordinator, device))
        if new_entities:
            async_add_entities(new_entities)

    entry.async_on_unload(
        coordinator.async_add_listener(_async_add_sensors_for_new_devices)
    )


def _sensors_for_device(
    coordinator: PaperlessCoordinator, device: dict
) -> list:
    """Return all sensor entities for a single device."""
    return [
        PaperlessBatLevelSensor(coordinator, device),
        PaperlessBatVoltageSensor(coordinator, device),
        PaperlessNextSyncSensor(coordinator, device),
        PaperlessSleepTimeSensor(coordinator, device),
        PaperlessSleepTimePredictSensor(coordinator, device),
        PaperlessWifiRssiSensor(coordinator, device),
        PaperlessOrientationSensor(coordinator, device),
    ]


def _device_info(device: dict) -> DeviceInfo:
    """Return DeviceInfo for a device."""
    return DeviceInfo(
        identifiers={(DOMAIN, device["id"])},
        name=device["meta"].get("name", device["id"]),
        manufacturer="paperlesspaper",
        model=device.get("kind", "epd"),
        sw_version=device.get("fw_version"),
        serial_number=device.get("deviceId"),
    )


class PaperlessBaseSensor(CoordinatorEntity, SensorEntity):
    """Base sensor for paperlesspaper devices."""

    _field: str
    _attr_icon: str = "mdi:image-frame"
    _attr_has_entity_name = True
    _attr_force_update = True  # Always write state, even if value unchanged

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

    @property
    def native_value(self):
        """Return sensor value."""
        if self._device is None:
            return None
        return self._device.get(self._field)


class PaperlessBatLevelSensor(PaperlessBaseSensor):
    """Sensor: battery level as percentage (0-100%).

    Calculates percentage from raw millivolt API value using:
        percentage = (voltage_V - BAT_VOLTAGE_MIN) / (BAT_VOLTAGE_MAX - BAT_VOLTAGE_MIN) * 100

    Result is clamped to 0-100 to handle out-of-range hardware readings.
    """

    _field = "bat_level"
    _attr_icon = "mdi:battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "bat_level", "bat_level")

    @property
    def native_value(self) -> int | None:
        """Return battery level as percentage (0-100).

        API provides millivolts; converts to volts first, then calculates
        percentage based on the defined voltage range.
        """
        if self._device is None:
            return None
        val = self._device.get("bat_level")
        if val is None:
            return None
        try:
            voltage_v = int(val) / 1000
            percentage = (
                (voltage_v - BAT_VOLTAGE_MIN)
                / (BAT_VOLTAGE_MAX - BAT_VOLTAGE_MIN)
                * 100
            )
            return max(0, min(100, round(percentage)))
        except (ValueError, TypeError):
            return None


class PaperlessBatVoltageSensor(PaperlessBaseSensor):
    """Sensor: raw battery voltage in Volts."""

    _field = "bat_level"
    _attr_icon = "mdi:sine-wave"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = "V"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_registry_enabled_default = False
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "bat_voltage", "bat_voltage")

    @property
    def native_value(self) -> float | None:
        """Return battery voltage in Volts (API provides millivolts)."""
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
    """Sensor: next scheduled device wake-up time as datetime."""

    _field = "next_device_sync"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "next_device_sync", "next_device_sync")

    @property
    def native_value(self) -> datetime | None:
        """Return next sync as a timezone-aware datetime object (UTC)."""
        if self._device is None:
            return None
        return self._device.get("next_device_sync")


class PaperlessSleepTimeSensor(PaperlessBaseSensor):
    """Sensor: configured sleep interval in seconds."""

    _field = "sleep_time"
    _attr_icon = "mdi:sleep"
    _attr_native_unit_of_measurement = "s"

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "sleep_time", "sleep_time")


class PaperlessSleepTimePredictSensor(PaperlessBaseSensor):
    """Sensor: predicted sleep interval in seconds until the next device wake-up."""

    _field = "sleep_time_predict"
    _attr_icon = "mdi:sleep"
    _attr_native_unit_of_measurement = "s"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(
            coordinator, device, "sleep_time_predict", "sleep_time_predict"
        )


class PaperlessWifiRssiSensor(PaperlessBaseSensor):
    """Sensor: WiFi signal strength in dBm from the latest activate event.

    Updated on every device wake-up cycle when the activate event is received
    via GET /devices/events. The value is populated by the coordinator's
    _process_device_events() method into the device dict field 'wifi_rssi'.

    Typical range: -30 dBm (excellent) to -90 dBm (very weak).
    Returns None between the initial setup and the first wake-up event.

    Note: device_class is intentionally omitted. SensorDeviceClass.SIGNAL_STRENGTH
    causes HA to override the entity name with its own built-in translation
    ("Signal strength") instead of our translation_key "wifi_rssi". Without
    device_class the translation_key is used and the correct label is shown.
    """

    _field = "wifi_rssi"
    _attr_icon = "mdi:wifi"
    # No device_class — see docstring above
    _attr_native_unit_of_measurement = "dBm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Enabled by default — useful for diagnosing connectivity issues

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "wifi_rssi", "wifi_signal_strength")

    @property
    def native_value(self) -> int | None:
        """Return WiFi RSSI in dBm."""
        if self._device is None:
            return None
        val = self._device.get("wifi_rssi")
        if val is None:
            return None
        try:
            return int(val)
        except (ValueError, TypeError):
            return None


class PaperlessOrientationSensor(PaperlessBaseSensor):
    """Sensor: display orientation from the latest activate event.

    Updated on every device wake-up cycle when the activate event is received
    via GET /devices/events. The value is populated by the coordinator's
    _process_device_events() method into the device dict field 'orientation'.

    Known device values:
        0 = Portrait
        3 = Landscape (both +90° and -90° map to 3)
    Values 1 and 2 are not currently reported by the hardware.

    The sensor exposes a human-readable string state ("portrait" / "landscape"
    / "unknown") rather than the raw integer so the HA UI displays a
    meaningful label without requiring a template. The raw value is preserved
    in extra_state_attributes for automation authors who need the integer.
    """

    _field = "orientation"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # No device_class, no unit, no state_class — string state sensor
    # Enabled by default — useful for diagnosing frame mounting issues

    # Map raw API integer → internal state string (used as translation key)
    _ORIENTATION_MAP: ClassVar[dict[int, str]] = {
        0: "portrait",
        3: "landscape",
    }

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "orientation", "frame_orientation")

    @property
    def icon(self) -> str:
        """Return an icon matching the current orientation."""
        val = self._device.get("orientation") if self._device else None
        if val is not None:
            try:
                if int(val) == 3:
                    return "mdi:phone-rotate-landscape"
            except (ValueError, TypeError):
                pass
        return "mdi:phone-rotate-portrait"

    @property
    def native_value(self) -> str | None:
        """Return orientation as a human-readable string state.

        Returns "portrait", "landscape", or "unknown" for unmapped values.
        Returns None when no activate event has been received yet.
        """
        if self._device is None:
            return None
        val = self._device.get("orientation")
        if val is None:
            return None
        try:
            return self._ORIENTATION_MAP.get(int(val), "unknown")
        except (ValueError, TypeError):
            return None

    @property
    def extra_state_attributes(self) -> dict:
        """Expose the raw orientation integer for automations."""
        if self._device is None:
            return {}
        val = self._device.get("orientation")
        if val is None:
            return {}
        try:
            return {"orientation_raw": int(val)}
        except (ValueError, TypeError):
            return {}
