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
# =============================================================================

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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

    async def _async_update_data(self) -> list[dict]:
        """Fetch device list, enrich each device with ping data and paper_id.

        Transient errors (502/503/504, connection issues) are handled by
        _fetch_device_list with backoff. Only persistent failures bubble up
        as UpdateFailed.
        """
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

        except aiohttp.ClientResponseError as err:
            raise UpdateFailed(f"API error: {err.status}") from err
        except aiohttp.ClientConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
        except aiohttp.ClientError as err:
            raise UpdateFailed(f"Client error: {err}") from err
        else:
            return devices
