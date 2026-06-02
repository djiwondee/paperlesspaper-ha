"""DataUpdateCoordinator for paperlesspaper."""
# =============================================================================
# CHANGE HISTORY
# 2026-04-20  0.2.4  Fixed UTC timestamp handling: _ms_timestamp_to_datetime
#                    now returns a timezone-aware datetime object (UTC) instead
#                    of an ISO string. Returning a string caused HA to display
#                    incorrect local times because fromisoformat() on Python
#                    < 3.11 silently dropped the timezone offset. Storing a
#                    datetime object directly ensures HA always receives a
#                    timezone-aware value and converts it correctly.
#                    Kept timezone.utc (datetime.UTC requires Python 3.11+, not yet guaranteed)
# 2026-04-22  0.2.5  Added public method create_paper_and_store(): creates a
#                    new paper via the API unconditionally and persists the
#                    resulting paper_id as the device default in
#                    config_entry.data. Called by the upload_image service
#                    when force_new_paper=True.
# 2026-05-09  0.3.0  Added random-upload-history helpers:
#                    - get_random_history(): returns the full history dict
#                    - update_random_history(): persists the full history dict
#                    These methods are used by the upload_random_image action
#                    in __init__.py to track already-shown images per (device,
#                    directory) and the currently displayed image per device.
#                    The history lives in config_entry.data alongside paper_ids
#                    so it survives HA restarts without a separate storage layer.
# 2026-05-11  0.3.0  Added retry logic to _async_update_data: transient HTTP
#                    errors (408/429/502/503/504) and connection errors are
#                    retried up to 2 times with exponential backoff (3s, 8s)
#                    before raising UpdateFailed. This prevents sensors from
#                    flipping to "unavailable" during brief server-side load
#                    spikes — the same root cause that motivated the upload
#                    retry logic in __init__.py.
# 2026-05-11  0.3.0  Hardened transient-error handling:
#                    - Coordinator fetch retries now honour the HTTP Retry-After
#                      response header when the server provides it. Capped at
#                      60s (shorter cap than uploads because the next poll
#                      cycle will retry anyway).
#                    - Coordinator backoff lengthened slightly from 3s/8s to
#                      5s/15s for better resilience against transient outages
#                      documented by the provider (HTTP 503 may take ~5min to
#                      recover). The coordinator only needs to survive one
#                      poll cycle, hence the cap stays modest.
# 2026-05-11  0.3.0  Added reset_all_random_history(): clears the 'seen'
#                    lists for all devices of this integration entry so the
#                    upload_random_image cycle restarts from the beginning of
#                    the pool for every device. Per-device currently_showing
#                    values are preserved so cross-device duplicate avoidance
#                    keeps working. Called by the Options Flow reset checkbox.
# 2026-06-01  1.0.2  Added random_upload_lock (asyncio.Lock) to serialise
#                    concurrent upload_random_image calls. Without the lock,
#                    two automations firing simultaneously both read a stale
#                    history before either write, causing the same image to be
#                    shown on multiple devices at the same time.
# 2026-06-01  1.0.2  Added device event polling via GET /devices/events/{id}:
#                    - _last_event_poll_ts: in-memory dict[device_id -> int|None]
#                      tracking the timestamp of the last successfully fetched
#                      event per device. Intentionally not persisted — resets
#                      on HA restart so the first poll after restart uses
#                      time.time() as the start of the fetch window,
#                      preventing gaps while avoiding full history re-fetch.
#                    - _get_default_since_ts(): returns the appropriate
#                      DateStart timestamp when no prior event poll exists.
#                      Uses now minus one poll interval as the fetch window start
#                      or falls back to one poll-interval ago for fresh starts.
#                    - _fetch_device_events(): calls the API with DateStart
#                      filter; returns raw event list or [] on error.
#                    - _parse_device_event(): normalises a raw API event into
#                      a consistent internal dict. Handles the two structurally
#                      different event types:
#                        "activate" — EventMessage is a JSON string with keys
#                          file, fw, bat, wake, wifi, usb, orient, timeout.
#                        "state"    — EventMessage is a plain string, e.g.
#                          "update_ok", "download_ok", "update_failed".
#                      Unknown types are logged at DEBUG and returned as None.
#                    - _process_device_events(): orchestrates fetch → parse →
#                      chronological sort → HA event firing. All events are
#                      fired in ascending timestamp order so HA automation
#                      triggers fire in the correct sequence even when multiple
#                      events arrive within a single poll window.
#                    - _async_update_data(): calls _process_device_events()
#                      for each reachable device after the ping, passing the
#                      HA device_id looked up from the device registry.
# 2026-06-01  1.1.0  Extended _process_device_events: after processing all
#                    events, the latest activate-event values for wifi_rssi
#                    and orientation are merged into the device dict so the
#                    new WifiRssi and Orientation sensor entities can read
#                    them via coordinator.data like all other sensor fields.
# =============================================================================

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging
import time

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    API_BASE_URL,
    CONF_API_KEY,
    CONF_ORGANIZATION_ID,
    CONF_PAPER_IDS,
    CONF_POLLING_INTERVAL,
    CONF_RANDOM_UPLOAD_HISTORY,
    DEFAULT_POLLING_INTERVAL,
    DEVICE_STATE_UPDATE_FAILED,
    DOMAIN,
    EVENT_DEVICE_STATE_CHANGED,
    EVENT_DEVICE_WOKE_UP,
)

_LOGGER = logging.getLogger(__name__)

# Transient HTTP statuses that should trigger a retry rather than mark all
# sensors unavailable. Mirrors the list used in __init__.py for uploads.
_RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 502, 503, 504})

# Backoff schedule for coordinator fetches. Shorter than the upload schedule
# because the coordinator should not block too long — sensors would simply
# refresh on the next poll cycle. Total worst-case wait: 5 + 15 = 20 seconds.
_FETCH_RETRY_BACKOFF_SECONDS = (5, 15)

# Hard upper bound for any single backoff wait in the coordinator. Lower than
# the upload cap because the next poll cycle will give us another chance.
_MAX_BACKOFF_SECONDS = 60


def _parse_retry_after(header_value: str | None) -> int | None:
    """Parse the HTTP Retry-After header value.

    Per RFC 7231 the header is either a non-negative integer (delta-seconds)
    or an HTTP-date. This coordinator only honours the integer form; HTTP-date
    values are ignored so the caller falls back to the scheduled backoff.
    Capped at _MAX_BACKOFF_SECONDS to keep the coordinator responsive.
    """
    if not header_value:
        return None
    try:
        value = int(header_value.strip())
    except (TypeError, ValueError):
        return None
    if value < 0:
        return None
    return min(value, _MAX_BACKOFF_SECONDS)


class PaperlessCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch all devices for an organization."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        polling_interval = entry.options.get(
            CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
        )
        super().__init__(
            hass,
            _LOGGER,
            name="paperlesspaper",
            update_interval=timedelta(seconds=polling_interval),
            always_update=True,  # Always notify listeners, even if data unchanged
        )
        self.entry = entry
        self.api_key: str = entry.data[CONF_API_KEY]
        self.organization_id: str = entry.data[CONF_ORGANIZATION_ID]
        self._session = async_get_clientsession(hass)

        # Lock to serialise concurrent upload_random_image calls.
        # Ensures the history read → candidate selection → upload → history
        # write sequence is atomic across all devices in this org, so the
        # cross-device duplicate-avoidance logic always reads a consistent
        # currently_showing state.
        self.random_upload_lock: asyncio.Lock = asyncio.Lock()

        # Cache for sensor values sourced from device events (activate payload).
        # These values are NOT available from the ping endpoint — they are only
        # delivered when the device wakes up. We persist them here so sensors
        # keep their last-known value across poll cycles. The cache is in-memory
        # only and resets on HA restart (sensors show Unknown until first wake-up).
        # Structure: {pp_device_id: {"wifi_rssi": int|None, "orientation": int|None}}
        self._event_sensor_cache: dict[str, dict] = {}

        # In-memory tracking of the last successfully fetched event timestamp
        # per device (millisecond epoch). None means no prior fetch in this
        # session — _get_default_since_ts() will determine the start window.
        # Intentionally not persisted: resets on HA restart so the first poll
        # after restart uses now minus one poll interval as anchor, preventing
        # gaps without re-fetching the full event history.
        self._last_event_poll_ts: dict[str, int | None] = {}

    @property
    def _headers(self) -> dict:
        """Return auth headers."""
        return {"x-api-key": self.api_key}

    # ------------------------------------------------------------------
    # Paper ID helpers
    # ------------------------------------------------------------------

    def get_paper_id(self, device_id: str) -> str | None:
        """Return stored paper_id for a device."""
        return self.entry.data.get(CONF_PAPER_IDS, {}).get(device_id)

    async def _store_paper_id(self, device_id: str, paper_id: str) -> None:
        """Persist paper_id for a device in config_entry.data."""
        paper_ids = dict(self.entry.data.get(CONF_PAPER_IDS, {}))
        paper_ids[device_id] = paper_id
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, CONF_PAPER_IDS: paper_ids},
        )
        _LOGGER.debug("Stored paper_id %s for device %s", paper_id, device_id)

    # ------------------------------------------------------------------
    # Random upload history helpers
    # ------------------------------------------------------------------

    def get_random_history(self) -> dict:
        """Return the full random-upload history dict.

        Structure:
            {
              "<pp_device_id>": {
                "currently_showing": "<uri>",
                "<directory_uri>": {
                  "seen": ["<uri>", ...],
                  "max_images": <int>
                }
              }
            }

        Returns an empty dict when no history has been recorded yet.
        Always returns a deep-copyable plain dict — callers can safely mutate.
        """
        history = self.entry.data.get(CONF_RANDOM_UPLOAD_HISTORY, {})
        # Return a shallow copy so callers don't accidentally mutate live data
        return dict(history)

    def update_random_history(self, history: dict) -> None:
        """Persist the full random-upload history dict to config_entry.data.

        Caller is expected to have read the current history via
        get_random_history(), modified it, and now writes the full dict back.
        """
        self.hass.config_entries.async_update_entry(
            self.entry,
            data={**self.entry.data, CONF_RANDOM_UPLOAD_HISTORY: history},
        )
        _LOGGER.debug("Updated random upload history")

    def reset_all_random_history(self) -> int:
        """Clear all 'seen' lists for every device of this integration entry.

        Called by the Options Flow reset checkbox. Covers all devices in the
        organization so the entire rotation starts fresh on the next
        upload_random_image call. The per-device 'currently_showing' values
        are deliberately preserved so the cross-device duplicate avoidance
        keeps working across the reset.

        Returns the total number of seen entries that were cleared (used for
        info logging only).
        """
        history = self.get_random_history()
        if not history:
            _LOGGER.debug("Reset requested but random upload history is empty — nothing to do")
            return 0

        cleared = 0
        for device_history in history.values():
            if not isinstance(device_history, dict):
                continue
            for key, value in device_history.items():
                if key == "currently_showing":
                    continue  # preserved for cross-device duplicate avoidance
                if isinstance(value, dict) and "seen" in value:
                    cleared += len(value.get("seen") or [])
                    value["seen"] = []

        self.update_random_history(history)
        _LOGGER.info(
            "Reset all random upload history for integration entry %s "
            "— cleared %d seen entr%s across all devices",
            self.entry.entry_id,
            cleared,
            "y" if cleared == 1 else "ies",
        )
        return cleared

    # ------------------------------------------------------------------
    # Paper API helpers
    # ------------------------------------------------------------------

    async def _fetch_papers_for_device(self, device_id: str) -> list[dict]:
        """Fetch all papers for a device."""
        async with self._session.get(
            f"{API_BASE_URL}/papers/",
            headers=self._headers,
            params={"deviceId": device_id},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data.get("results", [])

    async def _create_paper(self, device_id: str) -> str | None:
        """Create a new paper for a device.

        Note: API returns HTTP 500 even on success (v1 bug).
        We parse the response body regardless of status code.
        """
        payload = {
            "deviceId": device_id,
            "kind": "image",
            "organization": self.organization_id,
            "meta": "",
        }
        _LOGGER.debug("Creating paper with payload: %s", payload)
        async with self._session.post(
            f"{API_BASE_URL}/papers/",
            headers=self._headers,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            response_text = await resp.text()
            _LOGGER.debug(
                "Create paper response: status=%s body=%s",
                resp.status,
                response_text,
            )
            try:
                data = json.loads(response_text)
                paper_id = data.get("id")
                if paper_id:
                    _LOGGER.info(
                        "Created new paper %s for device %s (HTTP %s)",
                        paper_id,
                        device_id,
                        resp.status,
                    )
                    return paper_id
            except (json.JSONDecodeError, KeyError):
                pass

            _LOGGER.error(
                "Failed to create paper for device %s: HTTP %s body=%s",
                device_id,
                resp.status,
                response_text,
            )
            return None

    async def create_paper_and_store(self, device_id: str) -> str | None:
        """Create a new paper unconditionally and persist the paper_id.

        Public method called by the upload_image service when
        force_new_paper=True. Unlike _ensure_paper_id(), this method always
        creates a brand-new paper regardless of any previously stored value,
        then saves the new paper_id as the device default.

        Returns the new paper_id on success, or None if creation failed.
        """
        paper_id = await self._create_paper(device_id)
        if paper_id:
            await self._store_paper_id(device_id, paper_id)
        return paper_id

    async def _ensure_paper_id(self, device_id: str, device: dict) -> str | None:
        """Ensure a valid paper_id exists for a device.

        Called during the regular coordinator poll cycle. Validates the stored
        paper_id against the API and falls back to the device's own paper
        field or creates a new one if neither is available.
        """
        stored_paper_id = self.get_paper_id(device_id)

        if stored_paper_id:
            try:
                papers = await self._fetch_papers_for_device(device_id)
                paper_ids_on_api = [p["id"] for p in papers]

                if stored_paper_id in paper_ids_on_api:
                    _LOGGER.debug(
                        "Paper %s still valid for device %s",
                        stored_paper_id,
                        device_id,
                    )
                    return stored_paper_id

                _LOGGER.warning(
                    "Stored paper_id %s no longer exists on API, will use device paper field",
                    stored_paper_id,
                )
            except aiohttp.ClientError as err:
                _LOGGER.warning("Could not validate paper_id: %s", err)
                return stored_paper_id

        # Use paper field from device response as fallback
        device_paper_id = device.get("paper")
        if device_paper_id:
            _LOGGER.info(
                "Using paper %s from device response for device %s",
                device_paper_id,
                device_id,
            )
            await self._store_paper_id(device_id, device_paper_id)
            return device_paper_id

        # Last resort: create new paper
        _LOGGER.warning("No paper found for device %s, creating new", device_id)
        paper_id = await self._create_paper(device_id)
        if paper_id:
            await self._store_paper_id(device_id, paper_id)
        return paper_id

    @staticmethod
    def _ms_timestamp_to_datetime(ms_timestamp: int | None) -> datetime | None:
        """Convert a millisecond epoch timestamp to a timezone-aware datetime (UTC).

        Returns a datetime object — NOT a string — so that HA receives a
        proper timezone-aware value and can convert it to the user's local
        timezone for display in the UI, history, and logbook.

        Returning an ISO string caused incorrect local times because
        fromisoformat() on Python < 3.11 silently dropped the timezone offset.
        Uses timezone.utc for compatibility (datetime.UTC requires Python 3.11+).
        """
        if ms_timestamp is None:
            return None
        try:
            return datetime.fromtimestamp(ms_timestamp / 1000, tz=timezone.utc)  # noqa: UP017
        except (ValueError, OSError):
            return None

    async def _ping_device(self, device_id: str) -> dict:
        """Ping device with dataResponse=false.

        Returns enriched device data including:
        - reachable: bool
        - iotDevice fields (fwVersion, serialNumber, ...)
        - deviceStatus fields (pictureSynced, batLevel, nextDeviceSync, ...)

        Timestamp fields (e.g. next_device_sync) are stored as timezone-aware
        datetime objects (UTC) so HA can display and convert them correctly.
        """
        try:
            async with self._session.get(
                f"{API_BASE_URL}/devices/ping/{device_id}",
                headers=self._headers,
                params={"dataResponse": "false"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug(
                        "Ping %s -> not reachable (HTTP %s)", device_id, resp.status
                    )
                    return {"reachable": False}

                data = await resp.json()
                ping = data.get("ping", {})
                device = data.get("device", {})
                iot = device.get("iotDevice", {})
                status = device.get("deviceStatus", {})

                next_sync_ms = status.get("nextDeviceSync")

                result = {
                    "reachable": ping.get("success", False),
                    "fw_version": iot.get("fwVersion"),
                    "fw_version_latest": iot.get("fwVersionLatest"),
                    "serial_number": iot.get("serialNumber"),
                    "picture_synced": status.get("pictureSynced"),
                    "bat_level": status.get("batLevel"),
                    # Stored as timezone-aware datetime (UTC); sensor reads directly
                    "next_device_sync": self._ms_timestamp_to_datetime(next_sync_ms),
                    "sleep_time": status.get("sleepTime"),
                    "sleep_time_predict": status.get("sleepTimePredict"),
                    "update_pending": status.get("updatePending"),
                }
                _LOGGER.debug("Ping %s -> reachable=%s", device_id, result["reachable"])
                return result

        except aiohttp.ClientError as err:
            _LOGGER.debug("Ping %s -> error: %s", device_id, err)
            return {"reachable": False}

    # ------------------------------------------------------------------
    # Device event parsing helpers (static — no instance state needed)
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_int(value: str | int | None) -> int | None:
        """Convert a string or int to int, returning None on failure."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_wifi_rssi(wifi_str: str | None) -> int | None:
        """Extract the RSSI value from the activate-event wifi field.

        The API encodes wifi as "<connected>,<rssi>", e.g. "1, -56".
        Returns the RSSI as a negative integer, or None if unparseable.
        """
        if not wifi_str:
            return None
        parts = wifi_str.split(",")
        if len(parts) >= 2:
            try:
                return int(parts[1].strip())
            except (ValueError, TypeError):
                return None
        return None

    @staticmethod
    def _parse_device_event(raw: dict) -> dict | None:
        """Normalise a raw API event dict into a consistent internal structure.

        The two event types have structurally different EventMessage fields:
          - "activate": EventMessage is a JSON-encoded string containing keys
            such as fw, bat, wifi, orient, timeout.
          - "state": EventMessage is a plain string, e.g. "update_ok".

        Returns None for events that cannot be parsed or have an unknown type,
        so the caller can simply filter with: [e for e in map(...) if e].
        """
        event_type = (raw.get("EventType") or "").lower()
        # Prefer EventTimestamp; fall back to AwsTimestamp if missing
        ts_ms = raw.get("EventTimestamp") or raw.get("AwsTimestamp")
        device_id = raw.get("DeviceId", "")
        message_raw = raw.get("EventMessage", "")

        if not ts_ms:
            _LOGGER.debug("Dropping event with no timestamp: %s", raw)
            return None

        if event_type == "activate":
            # EventMessage is a JSON string — parse it defensively
            try:
                payload = json.loads(message_raw)
            except (json.JSONDecodeError, TypeError):
                _LOGGER.warning(
                    "Could not parse activate payload for device %s: %r",
                    device_id, message_raw,
                )
                payload = {}

            return {
                "type": "activate",
                "device_id": device_id,
                "timestamp_ms": int(ts_ms),
                "fw": payload.get("fw"),
                "bat_mv": PaperlessCoordinator._safe_int(payload.get("bat")),
                "wifi_rssi": PaperlessCoordinator._parse_wifi_rssi(payload.get("wifi")),
                "orientation": PaperlessCoordinator._safe_int(payload.get("orient")),
                "timeout_s": PaperlessCoordinator._safe_int(payload.get("timeout")),
                "usb": payload.get("usb") == "1",
            }

        if event_type == "state":
            # EventMessage is a plain string
            return {
                "type": "state",
                "device_id": device_id,
                "timestamp_ms": int(ts_ms),
                "message": message_raw,
            }

        _LOGGER.debug(
            "Unknown event type %r for device %s — skipped", event_type, device_id
        )
        return None

    # ------------------------------------------------------------------
    # Device event polling helpers
    # ------------------------------------------------------------------

    def _get_default_since_ts(self) -> int:
        """Return the DateStart timestamp (ms) to use when no prior event poll exists.

        Called only when _last_event_poll_ts has no entry for the device yet
        (first poll after start or restart). Returns now minus one poll interval
        so the initial fetch window is bounded and predictable regardless of
        how long the device or HA has been running.

        We intentionally do not rely on any DataUpdateCoordinator attribute
        for the last success time — those attributes differ across HA versions.
        Instead we use the system clock directly, which is always available.
        """
        polling_interval = self.entry.options.get(
            CONF_POLLING_INTERVAL, DEFAULT_POLLING_INTERVAL
        )
        return int((time.time() - polling_interval) * 1000)

    async def _fetch_device_events(
        self, device_id: str, since_ts_ms: int
    ) -> list[dict]:
        """Fetch device events from the API since the given timestamp.

        Uses the DateStart query parameter to limit results to events that
        occurred after the last poll. Returns an empty list on any error so
        that a failed event fetch never interrupts the main poll cycle.

        The API endpoint: GET /devices/events/{deviceId}?DateStart=<ISO8601>

        DateStart expects an ISO 8601 date-time string. We convert the
        millisecond epoch timestamp to UTC ISO format before passing it.
        """
        # Convert ms epoch to ISO 8601 UTC string as required by the API.
        # Both DateStart and DateEnd are required — without them the endpoint
        # returns the device object instead of the events list.
        # Timestamps are truncated to whole seconds (%S without sub-seconds)
        # to match the API's second-granular comparison. Using millisecond
        # precision causes the same event to reappear on subsequent polls
        # because the API's DateStart filter is inclusive at second granularity.
        since_dt = datetime.fromtimestamp(since_ts_ms / 1000, tz=timezone.utc)  # noqa: UP017
        since_iso = since_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
        now_iso = datetime.fromtimestamp(time.time(), tz=timezone.utc).strftime(  # noqa: UP017
            "%Y-%m-%dT%H:%M:%SZ"
        )

        try:
            async with self._session.get(
                f"{API_BASE_URL}/devices/events/{device_id}",
                headers=self._headers,
                params={"DateStart": since_iso, "DateEnd": now_iso},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug(
                        "Event fetch for device %s returned HTTP %s — skipping",
                        device_id, resp.status,
                    )
                    return []
                data = await resp.json()
                # The API always returns a dict. Events are under the "message"
                # key. When no events exist in the time window, "message" is
                # absent or empty and only the "device" object is returned.
                if isinstance(data, dict):
                    events = data.get("message")
                    if isinstance(events, list):
                        _LOGGER.debug(
                            "Event fetch for device %s: %d event(s) in window",
                            device_id, len(events),
                        )
                        return events
                    # No "message" key — no events in this time window
                    _LOGGER.debug(
                        "No events in window for device %s", device_id,
                    )
                    return []
                # Unexpected top-level type (should not happen)
                _LOGGER.debug(
                    "Unexpected event response shape for device %s: %s",
                    device_id, type(data),
                )
                return []
        except aiohttp.ClientError as err:
            _LOGGER.debug(
                "Event fetch for device %s failed: %s — skipping", device_id, err
            )
            return []

    async def _process_device_events(
        self,
        pp_device_id: str,
        ha_device_id: str | None,
        since_ts_ms: int,
    ) -> None:
        """Fetch, parse, sort and fire HA events for all new device events.

        Guarantees chronological ordering by sorting parsed events by
        timestamp before firing — the API does not guarantee a specific
        order, and within a single poll window multiple events may arrive.

        Fires HA bus events in ascending timestamp order so HA automation
        triggers process events in the correct real-world sequence.

        After all events are fired, updates _last_event_poll_ts to the
        timestamp of the newest event seen (or the current time if no events
        were returned), so the next poll window starts exactly where this
        one ended.
        """
        raw_events = await self._fetch_device_events(pp_device_id, since_ts_ms)

        if not raw_events:
            # No new events — advance the poll window to now so we don't
            # re-request the same window on the next cycle.
            self._last_event_poll_ts[pp_device_id] = int(time.time() * 1000)
            return

        # Parse and drop unparseable events
        parsed = [
            e
            for e in (self._parse_device_event(r) for r in raw_events)
            if e is not None
        ]

        if not parsed:
            self._last_event_poll_ts[pp_device_id] = int(time.time() * 1000)
            return

        # Sort ascending by timestamp so HA triggers fire in the correct order
        parsed.sort(key=lambda e: e["timestamp_ms"])

        _LOGGER.debug(
            "Processing %d event(s) for device %s (since ts=%d)",
            len(parsed), pp_device_id, since_ts_ms,
        )

        # Track the last activate event to merge sensor values afterwards
        latest_activate: dict | None = None

        for event in parsed:
            if event["type"] == "activate":
                latest_activate = event
                _LOGGER.info(
                    "Device woke up: device=%s bat_mv=%s fw=%s wifi_rssi=%s timeout_s=%s",
                    pp_device_id,
                    event.get("bat_mv"),
                    event.get("fw"),
                    event.get("wifi_rssi"),
                    event.get("timeout_s"),
                )
                payload: dict = {
                    "pp_device_id": pp_device_id,
                    "bat_mv": event.get("bat_mv"),
                    "fw": event.get("fw"),
                    "wifi_rssi": event.get("wifi_rssi"),
                    "timeout_s": event.get("timeout_s"),
                    "timestamp_ms": event["timestamp_ms"],
                }
                if ha_device_id is not None:
                    # Attach HA device_id so logbook and device triggers can
                    # associate the event with the correct device.
                    payload["device_id"] = ha_device_id
                self.hass.bus.async_fire(EVENT_DEVICE_WOKE_UP, payload)

            elif event["type"] == "state":
                state_msg = event.get("message", "")
                log_fn = _LOGGER.warning if state_msg == DEVICE_STATE_UPDATE_FAILED else _LOGGER.info
                log_fn(
                    "Device state changed: device=%s state=%s",
                    pp_device_id, state_msg,
                )
                payload = {
                    "pp_device_id": pp_device_id,
                    "state": state_msg,
                    "timestamp_ms": event["timestamp_ms"],
                }
                if ha_device_id is not None:
                    payload["device_id"] = ha_device_id
                self.hass.bus.async_fire(EVENT_DEVICE_STATE_CHANGED, payload)

        # Cache the latest activate-event sensor values. These are NOT
        # available from the ping endpoint and must survive across poll cycles.
        # The cache is applied into coordinator.data in _async_update_data
        # after each poll so sensors always read the last-known values.
        if latest_activate is not None:
            self._event_sensor_cache[pp_device_id] = {
                "wifi_rssi": latest_activate.get("wifi_rssi"),
                "orientation": latest_activate.get("orientation"),
            }
            _LOGGER.debug(
                "Event sensor cache updated for device %s: wifi_rssi=%s orientation=%s",
                pp_device_id,
                latest_activate.get("wifi_rssi"),
                latest_activate.get("orientation"),
            )
            # The cache values will be applied into the device dict in
            # _async_update_data via device.update(cached) after the ping.
            # The coordinator's normal listener dispatch at the end of the
            # poll cycle will then notify all sensor entities to update.

        # Advance the poll window to the last event's timestamp rounded up
        # to the next full second. Combined with second-granular DateStart
        # formatting this ensures the processed event is excluded from the
        # next poll window without risking a gap that could miss new events
        # in the same second.
        last_ts_s = parsed[-1]["timestamp_ms"] // 1000
        self._last_event_poll_ts[pp_device_id] = (last_ts_s + 1) * 1000

    # ------------------------------------------------------------------
    # Device list fetch with retry
    # ------------------------------------------------------------------

    async def _fetch_device_list(self) -> list[dict]:
        """Fetch the list of devices for this organization.

        Retries up to 2 times with exponential backoff on transient HTTP
        errors (408/429/502/503/504) and connection errors. Honours the
        Retry-After response header when the server provides it.
        Raises the underlying aiohttp error on final failure — the caller
        wraps it into UpdateFailed.
        """
        url = f"{API_BASE_URL}/devices/"
        params = {"organization": self.organization_id}

        max_attempts = 1 + len(_FETCH_RETRY_BACKOFF_SECONDS)
        last_error: Exception | None = None
        last_retry_after: int | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                async with self._session.get(
                    url,
                    headers=self._headers,
                    params=params,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status in _RETRYABLE_HTTP_STATUSES:
                        last_error = aiohttp.ClientResponseError(
                            request_info=resp.request_info,
                            history=resp.history,
                            status=resp.status,
                            message=resp.reason or "",
                            headers=resp.headers,
                        )
                        last_retry_after = _parse_retry_after(
                            resp.headers.get("Retry-After")
                        )
                        _LOGGER.warning(
                            "Device list fetch returned HTTP %s on attempt %d/%d%s "
                            "— will %s",
                            resp.status, attempt, max_attempts,
                            f", server Retry-After={last_retry_after}s"
                            if last_retry_after is not None else "",
                            "retry" if attempt < max_attempts else "give up",
                        )
                    else:
                        resp.raise_for_status()
                        data = await resp.json()
                        return data.get("results", [])
            except aiohttp.ClientConnectionError as err:
                last_error = err
                last_retry_after = None
                _LOGGER.warning(
                    "Device list fetch connection error on attempt %d/%d: %s — will %s",
                    attempt, max_attempts, err,
                    "retry" if attempt < max_attempts else "give up",
                )
            except aiohttp.ClientResponseError:
                # Non-retryable HTTP error — propagate immediately
                raise

            # Wait before next attempt, honouring Retry-After hint if present
            if attempt < max_attempts:
                scheduled = _FETCH_RETRY_BACKOFF_SECONDS[attempt - 1]
                wait = (
                    last_retry_after
                    if last_retry_after is not None
                    else scheduled
                )
                _LOGGER.debug(
                    "Waiting %ds before next device list fetch attempt%s",
                    wait,
                    " (server Retry-After)" if last_retry_after is not None else "",
                )
                await asyncio.sleep(wait)

        # Exhausted retries — re-raise the last error so the caller can wrap it.
        if last_error is not None:
            raise last_error
        # Defensive: this branch is unreachable, but keeps type-checkers happy.
        raise aiohttp.ClientError("Device list fetch failed without specific error")

    # ------------------------------------------------------------------
    # Main poll cycle
    # ------------------------------------------------------------------

    async def _async_update_data(self) -> list[dict]:
        """Fetch device list, enrich each device with ping data, paper_id, and events.

        For each reachable device the poll cycle runs:
          1. _fetch_device_list()     — organisation device list
          2. _ensure_paper_id()       — validate / create paper slot
          3. _ping_device()           — telemetry (battery, sync status, …)
          4. _process_device_events() — new events since last poll (activate /
                                        state), fired as HA bus events in
                                        chronological order.

        Step 4 is only executed when the device is reachable (ping succeeded).
        A failure in step 4 never aborts the poll — errors are caught inside
        _fetch_device_events() and logged at DEBUG level.

        Transient errors (502/503/504, connection issues) are handled by
        _fetch_device_list() with backoff. Only persistent failures bubble up
        as UpdateFailed.
        """
        # Build a lookup from pp_device_id → HA device_id once per poll cycle
        # so _process_device_events can attach the correct device_id to events.
        device_registry = dr.async_get(self.hass)
        ha_device_id_map: dict[str, str] = {}
        for ha_device in device_registry.devices.values():
            for identifier_tuple in ha_device.identifiers:
                # Use positional access instead of tuple unpacking — the
                # identifiers tuple may contain more than 2 elements in some
                # HA versions, causing a ValueError on (domain, identifier)
                # unpacking. We only need the first two elements.
                if len(identifier_tuple) >= 2 and identifier_tuple[0] == DOMAIN:
                    ha_device_id_map[identifier_tuple[1]] = ha_device.id

        try:
            devices = await self._fetch_device_list()
            _LOGGER.debug("Fetched %d device(s)", len(devices))

            for device in devices:
                device_id = device["id"]

                # Ensure valid paper_id
                device["paper_id"] = await self._ensure_paper_id(device_id, device)

                # Ping device → enriched status data
                ping_data = await self._ping_device(device_id)
                device.update(ping_data)

                # Apply cached event sensor values (wifi_rssi, orientation)
                # from previous activate events. These survive poll cycles so
                # sensors keep their last-known value until the next wake-up.
                cached = self._event_sensor_cache.get(device_id, {})
                if cached:
                    device.update(cached)

                # Poll device events — only when device is reachable
                if ping_data.get("reachable"):
                    ha_device_id = ha_device_id_map.get(device_id)
                    since_ts = self._last_event_poll_ts.get(device_id)
                    if since_ts is None:
                        since_ts = self._get_default_since_ts()
                    await self._process_device_events(
                        device_id, ha_device_id, since_ts
                    )

        except aiohttp.ClientResponseError as err:
            raise UpdateFailed(f"API error: {err.status}") from err
        except aiohttp.ClientConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Client error: {err}") from err
        else:
            return devices
