"""DataUpdateCoordinator for paperlesspaper."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone

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
    DEFAULT_POLLING_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


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

    async def _ensure_paper_id(self, device_id: str, device: dict) -> str | None:
        """Ensure a valid paper_id exists for a device."""
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
    def _ms_timestamp_to_datetime(ms_timestamp: int | None) -> str | None:
        """Convert a millisecond epoch timestamp to ISO datetime string."""
        if ms_timestamp is None:
            return None
        try:
            return datetime.fromtimestamp(
                ms_timestamp / 1000, tz=timezone.utc
            ).isoformat()
        except (ValueError, OSError):
            return None

    async def _ping_device(self, device_id: str) -> dict:
        """Ping device with dataResponse=false.

        Returns enriched device data including:
        - reachable: bool
        - iotDevice fields (fwVersion, serialNumber, ...)
        - deviceStatus fields (pictureSynced, batLevel, nextDeviceSync, ...)
        """
        try:
            async with self._session.get(
                f"{API_BASE_URL}/devices/ping/{device_id}",
                headers=self._headers,
                params={"dataResponse": "false"},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug("Ping %s -> not reachable (HTTP %s)", device_id, resp.status)
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

    async def _async_update_data(self) -> list[dict]:
        """Fetch device list, enrich each device with ping data and paper_id."""
        try:
            async with self._session.get(
                f"{API_BASE_URL}/devices/",
                headers=self._headers,
                params={"organization": self.organization_id},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                devices = data.get("results", [])
                _LOGGER.debug("Fetched %d device(s)", len(devices))

                for device in devices:
                    device_id = device["id"]

                    # Ensure valid paper_id
                    device["paper_id"] = await self._ensure_paper_id(device_id, device)

                    # Ping device → enriched status data
                    ping_data = await self._ping_device(device_id)
                    device.update(ping_data)

                return devices

        except aiohttp.ClientResponseError as err:
            raise UpdateFailed(f"API error: {err.status}") from err
        except aiohttp.ClientConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
