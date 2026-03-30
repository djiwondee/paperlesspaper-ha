"""paperlesspaper integration."""
from __future__ import annotations

import logging

import aiohttp

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers import device_registry as dr

from .const import API_BASE_URL, DOMAIN, PLATFORMS
from .coordinator import PaperlessCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up paperlesspaper from a config entry."""
    coordinator = PaperlessCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    async def handle_upload_image(call: ServiceCall) -> None:
        """Handle upload_image service call."""
        media_content_id = call.data["media_content_id"]

        # Resolve target device
        target_device_ids = call.data.get("device_id", [])
        if isinstance(target_device_ids, str):
            target_device_ids = [target_device_ids]

        if not target_device_ids:
            raise HomeAssistantError("No target device specified")

        registry = dr.async_get(hass)
        coordinator: PaperlessCoordinator | None = None
        pp_device_id: str | None = None

        for ha_device_id in target_device_ids:
            ha_device = registry.async_get(ha_device_id)
            if ha_device is None:
                continue
            for identifier in ha_device.identifiers:
                if identifier[0] == DOMAIN:
                    pp_device_id = identifier[1]
                    break
            if pp_device_id:
                for coord in hass.data[DOMAIN].values():
                    if any(d["id"] == pp_device_id for d in coord.data or []):
                        coordinator = coord
                        break
            if coordinator:
                break

        if coordinator is None or pp_device_id is None:
            raise HomeAssistantError("Could not find paperlesspaper device for target")

        paper_id = coordinator.get_paper_id(pp_device_id)
        if not paper_id:
            raise HomeAssistantError(f"No paper_id found for device {pp_device_id}")

        # Resolve media URL
        # Supports:
        # - media-source://media_source/local/file.png
        # - http://localhost:8123/local/file.png
        # - any external http/https URL
        session = async_get_clientsession(hass)

        if media_content_id.startswith("media-source://"):
            try:
                from homeassistant.components.media_source import async_resolve_media
                media = await async_resolve_media(hass, media_content_id, None)
                media_url = media.url
                if media_url.startswith("/"):
                    media_url = f"http://localhost:8123{media_url}"
            except Exception as err:
                raise HomeAssistantError(f"Could not resolve media source: {err}") from err
        elif media_content_id.startswith("http"):
            media_url = media_content_id
        else:
            raise HomeAssistantError(
                f"Unsupported media_content_id format: {media_content_id}. "
                "Use media-source://... or http://..."
            )

        # Fetch image bytes
        try:
            async with session.get(media_url) as resp:
                resp.raise_for_status()
                image_data = await resp.read()
                content_type = resp.headers.get("Content-Type", "image/png")
                _LOGGER.debug(
                    "Fetched image from %s: %d bytes, type=%s",
                    media_url,
                    len(image_data),
                    content_type,
                )
        except aiohttp.ClientError as err:
            raise HomeAssistantError(f"Could not fetch image: {err}") from err

        # Upload to paperlesspaper API
        try:
            form = aiohttp.FormData()
            form.add_field(
                "picture",
                image_data,
                filename="image.png",
                content_type=content_type,
            )

            async with session.post(
                f"{API_BASE_URL}/papers/uploadSingleImage/{paper_id}",
                headers={"x-api-key": coordinator.api_key},
                data=form,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                resp.raise_for_status()
                result = await resp.json()
                _LOGGER.info(
                    "Image uploaded to paper %s: similarity=%.1f%% skipped=%s",
                    paper_id,
                    result.get("similarityPercentage", 0),
                    result.get("skippedUpload", False),
                )
        except aiohttp.ClientError as err:
            raise HomeAssistantError(f"Upload failed: {err}") from err

    hass.services.async_register(
        DOMAIN,
        "upload_image",
        handle_upload_image,
    )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
