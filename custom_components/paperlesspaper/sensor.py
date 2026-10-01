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
# 2026-09-08  2.1.1  PaperlessOrientationSensor: firmware-aware orientation
#                    mapping. Firmware 3.x reports a 4-state orient value
#                    (0=landscape_right, 1=portrait, 2=landscape_left,
#                    3=portrait_upside_down) instead of 2.x's 2-state value
#                    (0=portrait, 3=landscape) - selects the map from device
#                    fw_version (major version >= 3). Firmware 3.x's 4 states
#                    are exposed as-is (not down-mapped to coarse
#                    portrait/landscape) since the exact rotation matters for
#                    use cases like orienting an image before upload. icon
#                    now derives from the resolved native_value instead of
#                    its own separate orient==3 check. Unmapped orient values
#                    now log a one-time warning per (device, value) instead
#                    of silently returning "unknown". (Issue #34)
# 2026-10-01  2.1.3  PaperlessOrientationSensor: firmware-3.x mapping is now
#                    also device-model-aware (interim fix, see below). The
#                    vendor confirmed the raw orient encoding differs by PCB
#                    alignment: Paper 7 (device kind "epd7") uses
#                    0=portrait, 1=landscape_left, 2=portrait_upside_down,
#                    3=landscape_right, while Paper 13/L (kind
#                    "openpaper13", also the default for an unrecognized
#                    kind) keeps the previously-shipped mapping.
#                    _ORIENTATION_MAP_V3 renamed to
#                    _ORIENTATION_MAP_V3_PAPER13; added
#                    _ORIENTATION_MAP_V3_PAPER7. An unrecognized device kind
#                    on firmware >=3 now also logs a one-time warning (same
#                    dedup pattern as unmapped orient values) before falling
#                    back to the Paper 13 table. Known limitation: the vendor
#                    plans a future firmware update that unifies Paper 13
#                    devices onto the Paper 7 table too (no version number
#                    yet) - this mapping will need a firmware-version-bounded
#                    follow-up once that ships. (Issue #34)
# =============================================================================

from __future__ import annotations

from datetime import datetime
import logging
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

_LOGGER = logging.getLogger(__name__)

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

    The raw 'orient' encoding differs by firmware generation AND, for
    firmware 3.x, by device model/hardware (Issue #34):
        Firmware 2.x: 0 = Portrait, 3 = Landscape (both rotation directions
            map to 3). Values 1 and 2 are not reported. Reported as the
            coarse states "portrait" / "landscape" — that's all this
            firmware generation can distinguish.
        Firmware 3.x: 4-state encoding, one value per physical rotation —
            but which integer maps to which rotation depends on the PCB
            alignment of the device model (confirmed by the vendor,
            smarthomeagentur, on Issue #34):
                Paper 7 (device kind "epd7"): 0=Portrait, 1=Landscape tilted
                    left, 2=Portrait upside-down, 3=Landscape tilted right.
                Paper 13/L (device kind "openpaper13", also the default for
                    any unrecognized kind): 0=Landscape tilted right,
                    1=Portrait, 2=Landscape tilted left, 3=Portrait
                    upside-down.
            Reported as the 4 distinct states "landscape_right" / "portrait"
            / "landscape_left" / "portrait_upside_down" in both cases, since
            the exact rotation matters for use cases like orienting an image
            before upload — down-mapping to coarse portrait/landscape would
            lose that information.
    The device's fw_version (see coordinator._last_known_fw_version) decides
    whether the legacy or a firmware-3.x map applies, compared by major
    version only — see CHANGE HISTORY for why patch-level differentiation
    isn't warranted. The device's 'kind' field then picks between the two
    firmware-3.x maps.

    Known limitation: the vendor stated a future firmware update will unify
    Paper 13 devices onto the Paper 7 table too (tracked at
    https://github.com/paperlesspaper/paperlesspaper-firmware/issues/61, no
    version number yet). When that ships, "openpaper13" devices on the new
    firmware will need the Paper 7 map, not the Paper 13 one — this will
    need a firmware-version-bounded follow-up once that version is known.

    The sensor exposes a human-readable string state rather than the raw
    integer so the HA UI displays a meaningful label without requiring a
    template. The raw integer is preserved in extra_state_attributes for
    automation authors who need it directly.
    """

    _field = "orientation"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    # No device_class, no unit, no state_class — string state sensor
    # Enabled by default — useful for diagnosing frame mounting issues

    # Map raw API integer → internal state string (used as translation key)
    _ORIENTATION_MAP_LEGACY: ClassVar[dict[int, str]] = {
        0: "portrait",
        3: "landscape",
    }
    # Firmware 3.x: two maps, selected by device model (device["kind"]) —
    # the PCB alignment differs between models, so the same raw orient value
    # means a different physical rotation on each (confirmed by the vendor
    # on Issue #34). Paper 13 is also the default for an unrecognized kind,
    # since it was the first confirmed-working mapping (itchensen's device).
    _ORIENTATION_MAP_V3_PAPER13: ClassVar[dict[int, str]] = {
        0: "landscape_right",       # tilted right
        1: "portrait",              # normal
        2: "landscape_left",        # tilted left
        3: "portrait_upside_down",  # upside-down
    }
    _ORIENTATION_MAP_V3_PAPER7: ClassVar[dict[int, str]] = {
        0: "portrait",              # normal
        1: "landscape_left",        # tilted left
        2: "portrait_upside_down",  # upside-down
        3: "landscape_right",       # tilted right
    }
    _DEVICE_KIND_PAPER7 = "epd7"
    _DEVICE_KIND_PAPER13 = "openpaper13"

    # Tracks (device_id, raw_value) pairs already logged as unmapped, so a
    # persistently unmapped value only warns once instead of on every poll.
    _warned_unmapped_values: ClassVar[set[tuple[str, int]]] = set()

    # Tracks (device_id, kind) pairs already logged as an unrecognized
    # device kind, so a persistently unrecognized kind only warns once.
    _warned_unknown_kinds: ClassVar[set[tuple[str, str | None]]] = set()

    def __init__(self, coordinator: PaperlessCoordinator, device: dict) -> None:
        """Initialize."""
        super().__init__(coordinator, device, "orientation", "frame_orientation")

    @staticmethod
    def _major_fw_version(fw_version: str | None) -> int | None:
        """Return the leading integer component of a fw_version string.

        Returns None if fw_version is missing or doesn't start with a
        parseable integer (e.g. "3.0.14" -> 3, None/"" -> None).
        """
        if not fw_version:
            return None
        try:
            return int(str(fw_version).split(".")[0])
        except (ValueError, TypeError):
            return None

    def _resolve_map(self) -> dict[int, str]:
        """Return the orientation map matching this device's firmware/model."""
        fw_version = self._device.get("fw_version") if self._device else None
        major = self._major_fw_version(fw_version)
        if major is None or major < 3:
            return self._ORIENTATION_MAP_LEGACY

        kind = self._device.get("kind") if self._device else None
        if kind == self._DEVICE_KIND_PAPER7:
            return self._ORIENTATION_MAP_V3_PAPER7
        if kind != self._DEVICE_KIND_PAPER13:
            warn_key = (self._device_id, kind)
            if warn_key not in self._warned_unknown_kinds:
                self._warned_unknown_kinds.add(warn_key)
                _LOGGER.warning(
                    "Unrecognized device kind %r for device %s (fw_version=%s); "
                    "defaulting to the Paper 13 orientation table. Please "
                    "report this on Issue #34 so the mapping can be extended.",
                    kind,
                    self._device.get("deviceId") or self._device_id,
                    fw_version,
                )
        return self._ORIENTATION_MAP_V3_PAPER13

    @property
    def icon(self) -> str:
        """Return an icon matching the current (resolved) orientation."""
        val = self.native_value
        if val is not None and val.startswith("landscape"):
            return "mdi:phone-rotate-landscape"
        return "mdi:phone-rotate-portrait"

    @property
    def native_value(self) -> str | None:
        """Return orientation as a human-readable string state.

        Returns "portrait", "landscape", or "unknown" for unmapped values
        (a one-time warning is logged per unmapped (device, value) pair).
        Returns None when no activate event has been received yet.
        """
        if self._device is None:
            return None
        val = self._device.get("orientation")
        if val is None:
            return None
        try:
            val_int = int(val)
        except (ValueError, TypeError):
            return None

        mapping = self._resolve_map()
        result = mapping.get(val_int)
        if result is not None:
            return result

        warn_key = (self._device_id, val_int)
        if warn_key not in self._warned_unmapped_values:
            self._warned_unmapped_values.add(warn_key)
            _LOGGER.warning(
                "Unmapped orientation value %s for device %s (fw_version=%s); "
                "reporting 'unknown'. Please report this on Issue #34 so the "
                "mapping can be extended.",
                val_int,
                self._device.get("deviceId") or self._device_id,
                self._device.get("fw_version"),
            )
        return "unknown"

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
