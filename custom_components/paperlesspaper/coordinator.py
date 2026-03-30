"""DataUpdateCoordinator for paperlesspaper."""
from __future__ import annotations

import logging
from datetime import timedelta

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
    POLLING_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


class PaperlessCoordinator(DataUpdateCoordinator):
    """Coordinator to fetch all devices for an organization."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize."""
        super().__init__(
            hass,
            _LOGGER,
            name="paperlesspaper",
            update_interval=timedelta(seconds=POLLING_INTERVAL),
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

    async def _create_paper(self, device_id: str) -> str:
        """Create a new paper for a device, return its id."""
        payload = {
            "deviceId": device_id,
            "kind": "image",
            "meta": "",
            "organization": self.organization_id,
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
            resp.raise_for_status()
            import json
            data = json.loads(response_text)
            paper_id = data["id"]
            _LOGGER.info("Created new paper %s for device %s", paper_id, device_id)
            return paper_id

    async def _ensure_paper_id(self, device_id: str) -> str | None:
        """Ensure a valid paper_id exists for a device."""
        stored_paper_id = self.get_paper_id(device_id)

        if stored_paper_id:
            try:
                papers = await self._fetch_papers_for_device(device_id)
                paper_ids_on_api = [p["id"] for p in papers]
                _LOGGER.debug(
                    "Papers on API for device %s: %s", device_id, paper_ids_on_api
                )

                if stored_paper_id in paper_ids_on_api:
                    _LOGGER.debug(
                        "Paper %s still valid for device %s",
                        stored_paper_id,
                        device_id,
                    )
                    return stored_paper_id

                _LOGGER.warning(
                    "Stored paper_id %s no longer exists, creating new",
                    stored_paper_id,
                )
            except aiohttp.ClientError as err:
                _LOGGER.warning("Could not validate paper_id: %s", err)
                return stored_paper_id

        try:
            paper_id = await self._create_paper(device_id)
            await self._store_paper_id(device_id, paper_id)
            return paper_id
        except aiohttp.ClientResponseError as err:
            _LOGGER.error(
                "Failed to create paper for device %s: HTTP %s", device_id, err.status
            )
            return None
        except Exception as err:
            _LOGGER.error("Unexpected error creating paper: %s", err)
            return None

    async def _ping_device(self, device_id: str) -> bool:
        """Ping a single device, return True if reachable."""
        try:
            async with self._session.get(
                f"{API_BASE_URL}/devices/ping/{device_id}",
                headers=self._headers,
                params={"dataResponse": "false"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                reachable = resp.status == 200
                _LOGGER.debug("Ping %s -> %s", device_id, reachable)
                return reachable
        except aiohttp.ClientError:
            return False

    async def _async_update_data(self) -> list[dict]:
        """Fetch all devices, ensure paper_ids, ping each device."""
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
                    device["paper_id"] = await self._ensure_paper_id(device_id)
                    device["reachable"] = await self._ping_device(device_id)

                return devices

        except aiohttp.ClientResponseError as err:
            raise UpdateFailed(f"API error: {err.status}") from err
        except aiohttp.ClientConnectionError as err:
            raise UpdateFailed(f"Connection error: {err}") from err
