"""paperlesspaper integration."""
# =============================================================================
# CHANGE HISTORY
# 2026-04-22  0.2.5  upload_image service: added optional reuse_existing_paper
#                    boolean parameter (default: true). When set to false, a
#                    new paper is created via the API before the image upload,
#                    ignoring any previously stored paper_id. The newly created
#                    paper_id is persisted as the new default for the device in
#                    config_entry.data.
#                    Note: the field is named reuse_existing_paper (default true)
#                    so that HA renders only a toggle without an additional
#                    opt-in checkbox. Setting it to false triggers the
#                    force-new-paper behaviour internally.
#                    Refactored: handle_upload_image extracted into module-level
#                    helpers (_async_handle_upload_image, _fetch_media_source,
#                    _fetch_http, _upload_to_api) to reduce complexity of
#                    async_setup_entry (fixes Ruff C901).
#                    Moved async_resolve_media import to module level and fixed
#                    import order (fixes Ruff I001/PLC0415).
#                    Fixed TRY300: return moved into else block in
#                    _fetch_media_source.
# =============================================================================

from __future__ import annotations

import logging
import mimetypes

import aiofiles
import aiohttp

from homeassistant.components.media_source import async_resolve_media
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import API_BASE_URL, DOMAIN, PLATFORMS
from .coordinator import PaperlessCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up paperlesspaper from a config entry."""
    coordinator = PaperlessCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload integration when options change (e.g. polling interval)
    entry.async_on_unload(
        entry.add_update_listener(async_reload_entry)
    )

    async def handle_upload_image(call: ServiceCall) -> None:
        """Delegate to module-level helper (keeps async_setup_entry simple)."""
        await _async_handle_upload_image(hass, call)

    hass.services.async_register(
        DOMAIN,
        "upload_image",
        handle_upload_image,
    )

    return True


async def _async_handle_upload_image(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the upload_image service call.

    Parameters
    ----------
    call.data["device_id"]           : str | list[str]
        Target HA device ID(s).
    call.data["media_content_id"]    : str | dict
        media-source:// URI or direct https:// URL.
    call.data["reuse_existing_paper"]: bool (optional, default True)
        When True (default), the stored paper_id is reused.
        When False, a new paper is created on the API before uploading
        and its ID is persisted as the new device default.
    """
    media_raw = call.data["media_content_id"]

    # Media selector returns a dict: {"media_content_id": "...", "media_content_type": "..."}
    # Text input returns a plain string
    if isinstance(media_raw, dict):
        media_content_id = media_raw.get("media_content_id", "")
    else:
        media_content_id = media_raw

    # reuse_existing_paper=True  -> use stored paper_id (normal path)
    # reuse_existing_paper=False -> create a new paper before uploading
    reuse_existing_paper: bool = bool(call.data.get("reuse_existing_paper", True))
    force_new_paper: bool = not reuse_existing_paper

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

    # Determine paper_id
    if force_new_paper:
        _LOGGER.info(
            "Creating new paper for device %s (reuse_existing_paper=False)",
            pp_device_id,
        )
        paper_id = await coordinator.create_paper_and_store(pp_device_id)
        if not paper_id:
            raise HomeAssistantError(
                f"Could not create a new paper for device {pp_device_id}"
            )
    else:
        paper_id = coordinator.get_paper_id(pp_device_id)
        if not paper_id:
            raise HomeAssistantError(f"No paper_id found for device {pp_device_id}")

    # Fetch image bytes
    session = async_get_clientsession(hass)

    if media_content_id.startswith("media-source://"):
        image_data, content_type = await _fetch_media_source(
            hass, session, media_content_id
        )
    elif media_content_id.startswith("http"):
        image_data, content_type = await _fetch_http(session, media_content_id)
    else:
        raise HomeAssistantError(
            f"Unsupported media_content_id format: {media_content_id}. "
            "Use media-source://... or http://..."
        )

    if not image_data:
        raise HomeAssistantError("No image data received")

    # Upload to paperlesspaper API
    await _upload_to_api(
        session, coordinator, paper_id, pp_device_id,
        image_data, content_type, reuse_existing_paper,
    )


async def _fetch_media_source(
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    media_content_id: str,
) -> tuple[bytes, str]:
    """Resolve a media-source:// URI and return (image_data, content_type)."""
    try:
        media = await async_resolve_media(hass, media_content_id, None)
        media_url = media.url
    except Exception as err:
        raise HomeAssistantError(f"Could not resolve media source: {err}") from err

    _LOGGER.debug("Resolved media URL: %s", media_url)

    if not media_url.startswith("http"):
        # Fix path: /media/local/ -> /media/
        media_url = media_url.replace("/media/local/", "/media/")
        # Local file — read directly from filesystem (no auth needed)
        try:
            async with aiofiles.open(media_url, "rb") as f:
                image_data = await f.read()
        except OSError as err:
            raise HomeAssistantError(f"Could not read image file: {err}") from err
        else:
            content_type = mimetypes.guess_type(media_url)[0] or "image/jpeg"
            _LOGGER.debug(
                "Read image from filesystem %s: %d bytes, type=%s",
                media_url, len(image_data), content_type,
            )
            return image_data, content_type

    # External URL resolved from media source
    return await _fetch_http(session, media_url)


async def _fetch_http(
    session: aiohttp.ClientSession,
    url: str,
) -> tuple[bytes, str]:
    """Fetch image bytes from an HTTP/HTTPS URL."""
    try:
        async with session.get(url) as resp:
            resp.raise_for_status()
            image_data = await resp.read()
            content_type = resp.headers.get("Content-Type", "image/jpeg")
            _LOGGER.debug(
                "Fetched image from %s: %d bytes, type=%s",
                url, len(image_data), content_type,
            )
            return image_data, content_type
    except aiohttp.ClientError as err:
        raise HomeAssistantError(f"Could not fetch image: {err}") from err


async def _upload_to_api(
    session: aiohttp.ClientSession,
    coordinator: PaperlessCoordinator,
    paper_id: str,
    pp_device_id: str,
    image_data: bytes,
    content_type: str,
    reuse_existing_paper: bool,
) -> None:
    """Upload image bytes to the paperlesspaper API."""
    try:
        form = aiohttp.FormData()
        form.add_field(
            "picture",
            image_data,
            filename="image.jpg",
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
                "Image uploaded to paper %s (device %s): "
                "similarity=%.1f%% skipped=%s reuse_existing_paper=%s",
                paper_id,
                pp_device_id,
                result.get("similarityPercentage") or 0,
                result.get("skippedUpload", False),
                reuse_existing_paper,
            )
    except aiohttp.ClientError as err:
        raise HomeAssistantError(f"Upload failed: {err}") from err


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
