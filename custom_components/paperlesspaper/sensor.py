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
# =============================================================================

from __future__ import annotations

from datetime import datetime

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

    # Seed known_device_ids with all devices present at startup and add
    # their entities immediately — this is the reliable path.
    known_device_ids: set[str] = set()
    initial_entities = []
    for device in coordinator.data or []:
        known_device_ids.add(device["id"])
        initial_entities.extend(_sensors_for_device(coordinator, device))

    if initial_entities:
        async_add_entities(initial_entities)

    # Listener for devices added after initial setup.
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
            # Clamp to valid range to handle out-of-range hardware readings
            return max(0, min(100, round(percentage)))
        except (ValueError, TypeError):
            return None


class PaperlessBatVoltageSensor(PaperlessBaseSensor):
    """Sensor: raw battery voltage in Volts.

    Provides the raw voltage reading from the API (converted from mV to V).
    Useful for diagnostics and for users who want to monitor exact voltage.
    """

    _field = "bat_level"
    _attr_icon = "mdi:sine-wave"
    _attr_device_class = SensorDeviceClass.VOLTAGE
    _attr_native_unit_of_measurement = "V"
    _attr_state_class = SensorStateClass.MEASUREMENT
    # Disabled by default — enable manually if raw voltage monitoring is needed
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
    """Sensor: next scheduled device wake-up time as datetime.

    The API field 'nextDeviceSync' contains the timestamp at which the device
    is scheduled to wake up and check for new content. This represents the
    device's periodic update interval — NOT a one-time sync event and NOT the
    time at which a newly uploaded image will be displayed.

    The coordinator stores this value as a timezone-aware datetime object (UTC).
    HA automatically converts it to the user's local timezone for display.

    Translation key: next_device_sync
    EN label: "Update Interval"
    DE label: "Aktualisierungsintervall"
    """

    _field = "next_device_sync"
    _attr_icon = "mdi:clock-outline"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "next_device_sync", "next_device_sync")

    @property
    def native_value(self) -> datetime | None:
        """Return next sync as a timezone-aware datetime object (UTC).

        The coordinator already provides a datetime object — no conversion
        needed here. HA uses the timezone info to display the correct local
        time in the UI, history, and logbook.
        """
        if self._device is None:
            return None
        return self._device.get("next_device_sync")


class PaperlessSleepTimeSensor(PaperlessBaseSensor):
    """Sensor: configured sleep interval in seconds.

    This is the sleep duration currently configured on the device firmware.
    It describes how long the device sleeps between wake cycles.
    A new value only takes effect after the device fetches it on its next
    wake cycle.

    Note: This is the raw configured value — not a prediction and not a
    timestamp indicating when the next image will be displayed.
    """

    _field = "sleep_time"
    _attr_icon = "mdi:sleep"
    _attr_native_unit_of_measurement = "s"
    # No entity_category — sensor remains visible in the main Sensors section

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "sleep_time", "sleep_time")


class PaperlessSleepTimePredictSensor(PaperlessBaseSensor):
    """Sensor: predicted sleep interval in seconds until the next device wake-up.

    This is the API's prediction of how long the device will sleep in its
    current cycle. It differs from sleep_time (the configured value) in that
    it reflects the device's actual expected behavior based on current state.

    Important: This sensor does NOT indicate when a newly uploaded image will
    appear on the display — it only describes the predicted sleep duration of
    the current wake/sleep cycle.

    Marked as diagnostic and disabled by default, as it is rarely needed
    for day-to-day automations. Enable manually if sleep prediction monitoring
    is required.
    """

    _field = "sleep_time_predict"
    _attr_icon = "mdi:sleep"
    _attr_native_unit_of_measurement = "s"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # Disabled by default — enable manually if sleep prediction monitoring is needed
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(
            coordinator, device, "sleep_time_predict", "sleep_time_predict"
        )
