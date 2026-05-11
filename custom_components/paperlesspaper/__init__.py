"""paperlesspaper integration."""
# =============================================================================
# CHANGE HISTORY
# 2026-04-22  0.2.5  upload_image service: added optional reuse_existing_paper
#                    boolean parameter (default: true). When set to false, a
#                    new paper is created via the API before the image upload,
#                    ignoring any previously stored paper_id. The newly created
#                    paper_id is persisted as the new default for the device in
#                    config_entry.data.
#                    Refactored: handle_upload_image extracted into module-level
#                    helpers (_async_handle_upload_image, _fetch_media_source,
#                    _fetch_http, _upload_to_api) to reduce complexity of
#                    async_setup_entry (fixes Ruff C901).
# 2026-05-09  0.3.0  Added new action upload_random_image:
#                    - Picks one image randomly from a media-source directory
#                    - Tracks per-(device, directory) history of seen images
#                      in config_entry.data so repeats are avoided until the
#                      cycle resets
#                    - Cross-device guard: excludes the image currently shown
#                      on any other device (Interpretation B — no simultaneous
#                      duplicates across multiple frames)
#                    - Self-healing against media library changes: stale URIs
#                      are pruned from seen on every call; new images appear
#                      in the candidate pool automatically
#                    - Persistent HA notification when the directory cannot be
#                      reached (e.g. SMB/NFS offline) — auto-dismissed when
#                      the directory becomes reachable again
#                    Code reuse: the actual image fetch + API upload reuses
#                    the existing helpers (_fetch_media_source, _fetch_http,
#                    _upload_to_api) — no duplication of upload logic.
# 2026-05-11  0.3.0  Added retry logic for transient upload errors:
#                    - _upload_to_api now retries up to 3 times with exponential
#                      backoff (2s, 5s, 10s) on HTTP 408/429/502/503/504 and
#                      connection errors. Final failure still raises
#                      HomeAssistantError so the automation log shows the error.
# 2026-05-11  0.3.0  Added event-based Activity feedback:
#                    - _upload_to_api now fires EVENT_IMAGE_UPLOADED after each
#                      attempt outcome (success / skipped / failed). The event
#                      includes the HA device_id so the logbook integration
#                      shows it on the device's Activity timeline.
#                    - Both actions (upload_image, upload_random_image) now
#                      track the HA device_id from the moment of resolution
#                      and forward it into the upload helper.
#                    - The events are also available as automation triggers
#                      (event_type: paperlesspaper_image_uploaded), so users
#                      can notify themselves on failures or skips.
# 2026-05-11  0.3.0  Hardened transient-error handling based on field tests
#                    and the provider's documented behavior:
#                    - Upload backoff extended from 2s/5s/10s (17s total) to
#                      5s/15s/30s (50s total) — better matches the provider's
#                      "HTTP 503 may take ~5min to recover" advisory while
#                      keeping the total action runtime bounded.
#                    - Honour the HTTP Retry-After response header when the
#                      server provides it; falls back to the scheduled backoff
#                      otherwise. Capped at 120s to prevent unreasonable waits.
#                    - Final upload failure now logged at ERROR level (not
#                      just propagated to the automation log) so the cause is
#                      visible in the HA system log without needing automation
#                      context.
#                    - Coordinator fetch retries also use the Retry-After hint
#                      when present.
# 2026-05-11  0.3.0  Bug fix: prevent unnecessary integration reloads.
#                    The update listener previously triggered a full reload
#                    on every async_update_entry call, including entry.data
#                    writes for paper_ids and random_upload_history. The
#                    consequence was that every successful upload caused all
#                    sensors to briefly flip to "unknown" while the
#                    coordinator was rebuilt. The listener now compares the
#                    options snapshot against the previous one and only
#                    reloads when options actually changed (e.g. polling
#                    interval changed via the OptionsFlow). Routine data
#                    writes no longer trigger a reload.
#                    The obsolete async_reload_entry helper was removed.
# 2026-05-11  0.3.0  Excluded HEIC/HEIF from the random-upload candidate
#                    pool. The paperlesspaper upload endpoint responds with
#                    HTTP 502 for these formats instead of a clean 415,
#                    burning all 4 retry attempts before failing. Apple-photo
#                    folders frequently contain .heic files; filtering them
#                    out at the pool stage spares the user from inevitable
#                    upload failures. The MIME-type whitelist in services.yaml
#                    (used by the upload_image Media Picker) was also trimmed.
# =============================================================================

from __future__ import annotations

import asyncio
import logging
import mimetypes
import random

import aiofiles
import aiohttp

from homeassistant.components import persistent_notification
from homeassistant.components.media_source import (
    BrowseMediaSource,
    async_browse_media,
    async_resolve_media,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    API_BASE_URL,
    DOMAIN,
    EVENT_IMAGE_UPLOADED,
    PLATFORMS,
    UPLOAD_STATUS_FAILED,
    UPLOAD_STATUS_SKIPPED,
    UPLOAD_STATUS_SUCCESS,
)
from .coordinator import PaperlessCoordinator

_LOGGER = logging.getLogger(__name__)

# HTTP status codes that indicate a transient server-side issue and should be
# retried.
#   408 = Request Timeout
#   429 = Too Many Requests (rate limit, provider documents 300 req/min/key)
#   502 = Bad Gateway
#   503 = Service Unavailable (provider documents up to ~5 min recovery time)
#   504 = Gateway Timeout
_RETRYABLE_HTTP_STATUSES = frozenset({408, 429, 502, 503, 504})

# Exponential backoff schedule for upload retries.
# Length defines max attempts AFTER the initial try — total of 4 attempts
# (initial + 3 retries). Total worst-case wait time: 5 + 15 + 30 = 50 seconds.
# Tuned to absorb the most common transient spikes (wake-up bursts, brief
# gateway hiccups) without blocking an HA action for an unbounded time. For
# longer outages (5+ minutes) the action will fail and the next scheduled
# automation cycle gets a fresh chance to upload.
_UPLOAD_RETRY_BACKOFF_SECONDS = (5, 15, 30)

# Hard upper bound for any single backoff wait — protects against unreasonable
# Retry-After hints from the server.
_MAX_BACKOFF_SECONDS = 120


def _parse_retry_after(header_value: str | None) -> int | None:
    """Parse the HTTP Retry-After header value.

    Per RFC 7231 the header is either a non-negative integer (delta-seconds)
    or an HTTP-date. This integration treats only the integer form and
    ignores HTTP-date values. Returns None on parse failure so the caller
    can fall back to the scheduled backoff.

    Capped at _MAX_BACKOFF_SECONDS to prevent the server from blocking us
    for an arbitrary amount of time.
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


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up paperlesspaper from a config entry."""
    coordinator = PaperlessCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Reload integration only when OPTIONS change (e.g. polling interval).
    #
    # The update listener fires for any async_update_entry call, including
    # writes to entry.data (paper_ids, random_upload_history). Without the
    # snapshot check below, every successful image upload would trigger a
    # full integration reload, which briefly flips all sensors to "unknown".
    # That's the regression observed after the 0.3.0 random-upload-history
    # writes started landing per upload.
    #
    # We snapshot the current options at setup time and only reload when the
    # options actually changed compared to the snapshot.
    last_options = dict(entry.options)

    async def _async_options_changed_listener(
        hass_inner: HomeAssistant, entry_inner: ConfigEntry
    ) -> None:
        nonlocal last_options
        new_options = dict(entry_inner.options)
        if new_options == last_options:
            # async_update_entry was called with new data but unchanged options
            # (typical for paper_ids / random_upload_history persistence) —
            # do NOT reload.
            return
        last_options = new_options
        await hass.config_entries.async_reload(entry_inner.entry_id)

    entry.async_on_unload(
        entry.add_update_listener(_async_options_changed_listener)
    )

    async def handle_upload_image(call: ServiceCall) -> None:
        """Delegate to module-level helper (keeps async_setup_entry simple)."""
        await _async_handle_upload_image(hass, call)

    async def handle_upload_random_image(call: ServiceCall) -> None:
        """Delegate to module-level helper for the random-image action."""
        await _async_handle_upload_random_image(hass, call)

    hass.services.async_register(
        DOMAIN,
        "upload_image",
        handle_upload_image,
    )

    hass.services.async_register(
        DOMAIN,
        "upload_random_image",
        handle_upload_random_image,
    )

    return True


# =============================================================================
# Shared helpers — used by both upload_image and upload_random_image
# =============================================================================


def _resolve_target_device(
    hass: HomeAssistant, target_device_ids: list[str]
) -> tuple[PaperlessCoordinator | None, str | None, str | None]:
    """Resolve the HA device id list to (coordinator, pp_device_id, ha_device_id).

    Returns (None, None, None) when the target cannot be matched to any
    paperlesspaper device. The ha_device_id is needed for firing logbook-aware
    events at the right device.
    """
    registry = dr.async_get(hass)
    coordinator: PaperlessCoordinator | None = None
    pp_device_id: str | None = None
    ha_device_id_matched: str | None = None

    for ha_device_id in target_device_ids:
        ha_device = registry.async_get(ha_device_id)
        if ha_device is None:
            continue
        for identifier in ha_device.identifiers:
            if identifier[0] == DOMAIN:
                pp_device_id = identifier[1]
                ha_device_id_matched = ha_device_id
                break
        if pp_device_id:
            for coord in hass.data[DOMAIN].values():
                if any(d["id"] == pp_device_id for d in coord.data or []):
                    coordinator = coord
                    break
        if coordinator:
            break

    return coordinator, pp_device_id, ha_device_id_matched


async def _resolve_paper_id(
    coordinator: PaperlessCoordinator,
    pp_device_id: str,
    reuse_existing_paper: bool,
) -> str:
    """Return a usable paper_id for the device.

    Either reuses the stored paper_id or creates a new one. Raises
    HomeAssistantError when no paper_id can be obtained.
    """
    if not reuse_existing_paper:
        _LOGGER.info(
            "Creating new paper for device %s (reuse_existing_paper=False)",
            pp_device_id,
        )
        paper_id = await coordinator.create_paper_and_store(pp_device_id)
        if not paper_id:
            raise HomeAssistantError(
                f"Could not create a new paper for device {pp_device_id}"
            )
        return paper_id

    paper_id = coordinator.get_paper_id(pp_device_id)
    if not paper_id:
        raise HomeAssistantError(f"No paper_id found for device {pp_device_id}")
    return paper_id


def _fire_upload_event(
    hass: HomeAssistant,
    *,
    ha_device_id: str | None,
    pp_device_id: str,
    paper_id: str,
    status: str,
    image_uri: str,
    action: str,
    attempt: int,
    similarity_percentage: float | None = None,
    skipped_upload: bool | None = None,
    error: str | None = None,
) -> None:
    """Fire EVENT_IMAGE_UPLOADED with a consistent payload.

    The HA logbook integration picks this up via logbook.py and renders it as
    a human-readable Activity entry on the device's timeline.
    """
    payload: dict = {
        "pp_device_id": pp_device_id,
        "paper_id": paper_id,
        "status": status,
        "image_uri": image_uri,
        "action": action,
        "attempt": attempt,
    }
    if ha_device_id is not None:
        # Required by the logbook integration to associate the event with a
        # specific device on the Activity timeline.
        payload["device_id"] = ha_device_id
    if similarity_percentage is not None:
        payload["similarity_percentage"] = similarity_percentage
    if skipped_upload is not None:
        payload["skipped_upload"] = skipped_upload
    if error is not None:
        payload["error"] = error

    hass.bus.async_fire(EVENT_IMAGE_UPLOADED, payload)


# =============================================================================
# upload_image action
# =============================================================================


async def _async_handle_upload_image(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle the upload_image service call."""
    media_raw = call.data["media_content_id"]

    # Media selector returns a dict; text input returns a string
    if isinstance(media_raw, dict):
        media_content_id = media_raw.get("media_content_id", "")
    else:
        media_content_id = media_raw

    reuse_existing_paper: bool = bool(call.data.get("reuse_existing_paper", True))

    target_device_ids = call.data.get("device_id", [])
    if isinstance(target_device_ids, str):
        target_device_ids = [target_device_ids]

    if not target_device_ids:
        raise HomeAssistantError("No target device specified")

    coordinator, pp_device_id, ha_device_id = _resolve_target_device(
        hass, target_device_ids
    )
    if coordinator is None or pp_device_id is None:
        raise HomeAssistantError("Could not find paperlesspaper device for target")

    paper_id = await _resolve_paper_id(coordinator, pp_device_id, reuse_existing_paper)

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

    await _upload_to_api(
        hass, session, coordinator, paper_id, pp_device_id, ha_device_id,
        image_data, content_type, reuse_existing_paper,
        image_uri=media_content_id,
        action="upload_image",
    )


# =============================================================================
# upload_random_image action
# =============================================================================

# Notification id template — one notification per device id.
_DIR_UNAVAILABLE_NOTIFICATION_PREFIX = "paperlesspaper_dir_unavailable_"

# Image MIME types we consider valid candidates from a media directory.
# HEIC/HEIF are intentionally excluded: the paperlesspaper upload endpoint
# does not support these formats and the server responds with HTTP 502
# rather than a clean 415 — burning all 4 retry attempts. Common Apple-photo
# folders frequently contain HEIC files, so filtering them out at the pool
# stage spares the user from inevitable upload failures.
_IMAGE_MIME_PREFIXES = ("image/",)
_IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")
# MIME types that pass the image/ prefix test but should still be excluded
# from the random pool because the upload endpoint cannot handle them.
_EXCLUDED_IMAGE_MIME_TYPES = frozenset({"image/heic", "image/heif"})


async def _async_handle_upload_random_image(
    hass: HomeAssistant, call: ServiceCall
) -> None:
    """Handle the upload_random_image service call.

    Parameters
    ----------
    call.data["device_id"]            : str | list[str] (required)
    call.data["media_directory"]      : str — media-source:// URI (required)
    call.data["max_images"]           : int — 0 means "use all" (optional, default 0)
    call.data["reuse_existing_paper"] : bool (optional, default True)
    """
    media_directory: str = (call.data.get("media_directory") or "").strip()
    if not media_directory:
        raise HomeAssistantError("media_directory is required")
    if not media_directory.startswith("media-source://"):
        raise HomeAssistantError(
            f"media_directory must be a media-source:// URI, got: {media_directory}"
        )

    max_images: int = int(call.data.get("max_images") or 0)
    # Normalize negative values to 0 (treat as "no cap"). Using max() over an
    # if-block satisfies Ruff PLR1730 (if-else-block-instead-of-if-exp).
    max_images = max(max_images, 0)

    reuse_existing_paper: bool = bool(call.data.get("reuse_existing_paper", True))

    target_device_ids = call.data.get("device_id", [])
    if isinstance(target_device_ids, str):
        target_device_ids = [target_device_ids]
    if not target_device_ids:
        raise HomeAssistantError("No target device specified")

    coordinator, pp_device_id, ha_device_id = _resolve_target_device(
        hass, target_device_ids
    )
    if coordinator is None or pp_device_id is None:
        raise HomeAssistantError("Could not find paperlesspaper device for target")

    notification_id = f"{_DIR_UNAVAILABLE_NOTIFICATION_PREFIX}{pp_device_id}"

    # ---------- 1. Browse directory --------------------------------------
    try:
        pool = await _list_images_in_directory(hass, media_directory)
    except HomeAssistantError as err:
        # Directory unreachable — raise a persistent notification that
        # auto-dismisses on the next successful run. Do NOT reset seen.
        persistent_notification.async_create(
            hass,
            message=(
                f"The media directory `{media_directory}` could not be reached "
                f"for device `{pp_device_id}`.\n\n"
                f"Error: {err}\n\n"
                "This notification will disappear automatically as soon as the "
                "directory is reachable again on the next run of "
                "`paperlesspaper.upload_random_image`."
            ),
            title="paperlesspaper: media directory unavailable",
            notification_id=notification_id,
        )
        raise HomeAssistantError(
            f"Media directory unavailable: {media_directory} ({err})"
        ) from err

    # Directory reachable — make sure any previous notification is gone.
    persistent_notification.async_dismiss(hass, notification_id)

    # ---------- 2. Apply max_images cap ----------------------------------
    if max_images > 0 and len(pool) > max_images:
        pool = pool[:max_images]
        _LOGGER.debug(
            "Pool capped to %d images (max_images=%d) for device %s",
            len(pool), max_images, pp_device_id,
        )

    if not pool:
        raise HomeAssistantError(
            f"No images found in directory {media_directory}"
        )

    pool_set = set(pool)

    # ---------- 3. Read history & validate seen --------------------------
    history = coordinator.get_random_history()
    device_history = dict(history.get(pp_device_id, {}))

    dir_history = dict(device_history.get(media_directory, {})) if isinstance(
        device_history.get(media_directory), dict
    ) else {}

    seen: list[str] = list(dir_history.get("seen", []))
    # Drop URIs that no longer exist in the pool (deleted files / shrunk max_images)
    seen = [uri for uri in seen if uri in pool_set]

    # ---------- 4. Cross-device exclusion --------------------------------
    excluded_uris: set[str] = set()
    for other_device_id, other_state in history.items():
        if other_device_id == pp_device_id:
            continue
        if not isinstance(other_state, dict):
            continue
        currently_showing = other_state.get("currently_showing")
        if currently_showing:
            excluded_uris.add(currently_showing)

    # ---------- 5. Build candidates --------------------------------------
    candidates = [uri for uri in pool if uri not in seen and uri not in excluded_uris]

    cycle_reset = False
    if not candidates:
        # All images of this directory have been shown for this device → reset.
        _LOGGER.info(
            "Random upload cycle reset for device %s, directory %s "
            "(all %d images seen)",
            pp_device_id, media_directory, len(pool),
        )
        seen = []
        cycle_reset = True
        candidates = [uri for uri in pool if uri not in excluded_uris]

    if not candidates:
        # More devices than images — accept cross-device collision rather than
        # failing. This is a corner case; warn but keep things working.
        _LOGGER.warning(
            "Cross-device exclusion left no candidates for device %s, "
            "directory %s (pool=%d, excluded=%d) — falling back to full pool",
            pp_device_id, media_directory, len(pool), len(excluded_uris),
        )
        candidates = list(pool)

    # ---------- 6. Pick one image ----------------------------------------
    chosen_uri = random.choice(candidates)
    _LOGGER.info(
        "Random upload: device=%s directory=%s chosen=%s "
        "(pool=%d, seen=%d, excluded=%d, cycle_reset=%s)",
        pp_device_id, media_directory, chosen_uri,
        len(pool), len(seen), len(excluded_uris), cycle_reset,
    )

    # ---------- 7. Resolve paper_id --------------------------------------
    paper_id = await _resolve_paper_id(
        coordinator, pp_device_id, reuse_existing_paper
    )

    # ---------- 8. Fetch image bytes -------------------------------------
    session = async_get_clientsession(hass)
    image_data, content_type = await _fetch_media_source(hass, session, chosen_uri)
    if not image_data:
        raise HomeAssistantError(f"No image data received for {chosen_uri}")

    # ---------- 9. Upload -------------------------------------------------
    await _upload_to_api(
        hass, session, coordinator, paper_id, pp_device_id, ha_device_id,
        image_data, content_type, reuse_existing_paper,
        image_uri=chosen_uri,
        action="upload_random_image",
    )

    # ---------- 10. Persist updated history ------------------------------
    # Note: we persist the history even when the API discards the upload as
    # "too similar" (skippedUpload=true). That mirrors what the user actually
    # sees: from the device's perspective the image was processed, and we
    # don't want to retry the same too-similar image on the next call.
    # If the upload failed entirely, _upload_to_api raises and we never reach
    # this point, so the failed image stays in the candidate pool for the
    # next call.
    seen.append(chosen_uri)
    dir_history["seen"] = seen
    dir_history["max_images"] = max_images
    device_history[media_directory] = dir_history
    device_history["currently_showing"] = chosen_uri
    history[pp_device_id] = device_history
    coordinator.update_random_history(history)


async def _list_images_in_directory(
    hass: HomeAssistant, media_directory: str
) -> list[str]:
    """Return a stable, sorted list of image URIs in the given media-source directory.

    Raises HomeAssistantError when the directory cannot be browsed (e.g. the
    underlying SMB/NFS share is offline). The caller is expected to translate
    this into a persistent notification.
    """
    try:
        browse_root: BrowseMediaSource = await async_browse_media(
            hass, media_directory
        )
    except Exception as err:
        raise HomeAssistantError(str(err)) from err

    children = browse_root.children or []

    image_uris: list[str] = []
    for child in children:
        # Skip subdirectories — only direct image children are considered
        if getattr(child, "can_expand", False) and not getattr(child, "can_play", False):
            continue
        media_class = getattr(child, "media_class", "") or ""
        media_content_type = getattr(child, "media_content_type", "") or ""
        media_content_id = getattr(child, "media_content_id", "") or ""

        # Explicit exclusion: HEIC/HEIF files are not supported by the upload
        # endpoint (returns HTTP 502). Filter them out at the pool stage.
        content_type_lower = media_content_type.lower()
        if content_type_lower in _EXCLUDED_IMAGE_MIME_TYPES:
            continue
        media_id_lower = media_content_id.lower()
        if media_id_lower.endswith((".heic", ".heif")):
            continue

        is_image_class = media_class == "image"
        is_image_mime = any(
            content_type_lower.startswith(p) for p in _IMAGE_MIME_PREFIXES
        )
        is_image_ext = media_id_lower.endswith(_IMAGE_EXTENSIONS)

        # Combined: media_content_id must be set AND the file must be image-like
        if media_content_id and (is_image_class or is_image_mime or is_image_ext):
            image_uris.append(media_content_id)

    # Stable sort so max_images cap is deterministic across calls
    image_uris.sort()
    return image_uris


# =============================================================================
# Shared image fetch & upload helpers
# =============================================================================


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
    hass: HomeAssistant,
    session: aiohttp.ClientSession,
    coordinator: PaperlessCoordinator,
    paper_id: str,
    pp_device_id: str,
    ha_device_id: str | None,
    image_data: bytes,
    content_type: str,
    reuse_existing_paper: bool,
    *,
    image_uri: str,
    action: str,
) -> None:
    """Upload image bytes to the paperlesspaper API.

    Retries up to 3 times with exponential backoff (5s, 15s, 30s) on transient
    failures (HTTP 408/429/502/503/504 and connection errors). Total worst-case
    wait time is 50 seconds before raising HomeAssistantError. If the server
    supplies a Retry-After header, its value (capped at 120s) takes precedence
    over the scheduled backoff for that wait step.

    After every attempt outcome an EVENT_IMAGE_UPLOADED event is fired:
    - status=success: API accepted and processed the upload
    - status=skipped: API accepted but discarded the upload as too similar
    - status=failed:  All retry attempts failed

    On final failure the error is logged at ERROR level so it appears
    prominently in the HA system log, in addition to the HomeAssistantError
    that propagates to the automation log.
    """
    url = f"{API_BASE_URL}/papers/uploadSingleImage/{paper_id}"
    headers = {"x-api-key": coordinator.api_key}

    # Total attempts = 1 (initial) + len(_UPLOAD_RETRY_BACKOFF_SECONDS) (retries)
    max_attempts = 1 + len(_UPLOAD_RETRY_BACKOFF_SECONDS)

    last_error: Exception | None = None
    last_error_msg: str | None = None
    last_retry_after: int | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            # FormData must be rebuilt for every attempt — aiohttp consumes
            # the underlying buffer on send, so a second use would fail.
            form = aiohttp.FormData()
            form.add_field(
                "picture",
                image_data,
                filename="image.jpg",
                content_type=content_type,
            )
            async with session.post(
                url,
                headers=headers,
                data=form,
                timeout=aiohttp.ClientTimeout(total=60),
            ) as resp:
                if resp.status in _RETRYABLE_HTTP_STATUSES:
                    # Read body for log context, then trigger a retry.
                    body_preview = (await resp.text())[:200]
                    last_error = HomeAssistantError(
                        f"Upload failed: HTTP {resp.status} — {body_preview}"
                    )
                    last_error_msg = f"HTTP {resp.status}: {body_preview.strip()}"
                    last_retry_after = _parse_retry_after(
                        resp.headers.get("Retry-After")
                    )
                    _LOGGER.warning(
                        "Upload to paper %s returned HTTP %s on attempt %d/%d "
                        "(device %s)%s — will %s",
                        paper_id, resp.status, attempt, max_attempts, pp_device_id,
                        f", server Retry-After={last_retry_after}s"
                        if last_retry_after is not None else "",
                        "retry" if attempt < max_attempts else "give up",
                    )
                else:
                    resp.raise_for_status()
                    result = await resp.json()
                    similarity = result.get("similarityPercentage")
                    skipped_upload = bool(result.get("skippedUpload", False))

                    _LOGGER.info(
                        "Image uploaded to paper %s (device %s) on attempt %d: "
                        "similarity=%.1f%% skipped=%s reuse_existing_paper=%s",
                        paper_id,
                        pp_device_id,
                        attempt,
                        similarity or 0,
                        skipped_upload,
                        reuse_existing_paper,
                    )

                    # Fire success or skipped event based on the API's response.
                    _fire_upload_event(
                        hass,
                        ha_device_id=ha_device_id,
                        pp_device_id=pp_device_id,
                        paper_id=paper_id,
                        status=(
                            UPLOAD_STATUS_SKIPPED
                            if skipped_upload
                            else UPLOAD_STATUS_SUCCESS
                        ),
                        image_uri=image_uri,
                        action=action,
                        attempt=attempt,
                        similarity_percentage=(
                            float(similarity) if similarity is not None else None
                        ),
                        skipped_upload=skipped_upload,
                    )
                    return
        except aiohttp.ClientConnectionError as err:
            last_error = HomeAssistantError(f"Upload failed: {err}")
            last_error_msg = f"Connection error: {err}"
            last_retry_after = None
            _LOGGER.warning(
                "Upload to paper %s connection error on attempt %d/%d "
                "(device %s): %s — will %s",
                paper_id, attempt, max_attempts, pp_device_id, err,
                "retry" if attempt < max_attempts else "give up",
            )
        except aiohttp.ClientResponseError as err:
            # Non-retryable HTTP status — fire failed event and raise immediately.
            err_text = (
                f"{err.status}, message={err.message!r}, url={err.request_info.url!s}"
            )
            _LOGGER.error(
                "Upload to paper %s failed with non-retryable HTTP error "
                "(device %s): %s",
                paper_id, pp_device_id, err_text,
            )
            _fire_upload_event(
                hass,
                ha_device_id=ha_device_id,
                pp_device_id=pp_device_id,
                paper_id=paper_id,
                status=UPLOAD_STATUS_FAILED,
                image_uri=image_uri,
                action=action,
                attempt=attempt,
                error=err_text,
            )
            raise HomeAssistantError(f"Upload failed: {err_text}") from err
        except aiohttp.ClientError as err:
            # Other client errors (e.g. timeout) are treated as transient.
            last_error = HomeAssistantError(f"Upload failed: {err}")
            last_error_msg = f"Client error: {err}"
            last_retry_after = None
            _LOGGER.warning(
                "Upload to paper %s client error on attempt %d/%d "
                "(device %s): %s — will %s",
                paper_id, attempt, max_attempts, pp_device_id, err,
                "retry" if attempt < max_attempts else "give up",
            )

        # If there are more attempts left, wait — using the Retry-After hint
        # from the server if available, otherwise the scheduled backoff.
        # Backoff index = attempt - 1, since attempt 1 uses backoff[0] before
        # attempt 2 starts.
        if attempt < max_attempts:
            scheduled = _UPLOAD_RETRY_BACKOFF_SECONDS[attempt - 1]
            if last_retry_after is not None:
                wait = last_retry_after
                _LOGGER.debug(
                    "Honouring server Retry-After=%ds before next upload attempt "
                    "for paper %s (scheduled was %ds)",
                    wait, paper_id, scheduled,
                )
            else:
                wait = scheduled
                _LOGGER.debug(
                    "Waiting %ds (scheduled backoff) before next upload attempt "
                    "for paper %s",
                    wait, paper_id,
                )
            await asyncio.sleep(wait)

    # Exhausted all attempts — fire failed event, log at ERROR level, and
    # raise the last seen error.
    final_error_text = last_error_msg or "unknown error"
    _LOGGER.error(
        "Upload to paper %s failed permanently after %d attempts "
        "(device %s, action %s): %s",
        paper_id, max_attempts, pp_device_id, action, final_error_text,
    )
    _fire_upload_event(
        hass,
        ha_device_id=ha_device_id,
        pp_device_id=pp_device_id,
        paper_id=paper_id,
        status=UPLOAD_STATUS_FAILED,
        image_uri=image_uri,
        action=action,
        attempt=max_attempts,
        error=final_error_text,
    )

    if last_error is not None:
        raise last_error
    raise HomeAssistantError("Upload failed: exhausted retries without error")


# =============================================================================
# Entry lifecycle
# =============================================================================


# Note: previously this module also defined async_reload_entry which was
# registered as an update listener. That was removed because it caused a
# full integration reload on every async_update_entry call, including
# entry.data writes (paper_ids, random_upload_history) which happen during
# normal operation. The setup function now uses a snapshot-based options
# listener instead that only reloads when entry.options actually change.


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)
    return unload_ok
