"""Logbook integration for paperlesspaper.

Registers a describe-event hook so that the image upload events fired by
the upload pipeline appear as human-readable entries on each device's
Activity timeline (Settings → Devices & Services → paperlesspaper →
[device] → Logbook / Activity).

Without this module the events would still fire (and be usable as
automation triggers), but they would appear as raw "Event ...with data..."
lines instead of nicely formatted upload status messages.
"""
# =============================================================================
# CHANGE HISTORY
# 2026-05-11  0.3.0  New module. Describes EVENT_IMAGE_UPLOADED events for the
#                    HA logbook so that each upload appears as a readable line
#                    on the device's Activity timeline. Distinguishes success,
#                    skipped (API discarded as too similar), and failed states.
# =============================================================================

from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    DOMAIN,
    EVENT_IMAGE_UPLOADED,
    UPLOAD_STATUS_FAILED,
    UPLOAD_STATUS_SKIPPED,
    UPLOAD_STATUS_SUCCESS,
)

_LOGGER = logging.getLogger(__name__)


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict]], None],
) -> None:
    """Register the describe_event hook for paperlesspaper upload events.

    Called once by Home Assistant's logbook integration on startup.
    """

    @callback
    def async_describe_upload_event(event: Event) -> dict:
        """Return a human-readable logbook entry for an upload event.

        The 'name' field becomes the bold prefix line of the entry; the
        'message' field is the secondary line shown below it.
        """
        data = event.data or {}
        status = data.get("status", "unknown")
        image_uri = data.get("image_uri", "") or ""
        action = data.get("action", "upload")
        attempt = data.get("attempt")
        similarity = data.get("similarity_percentage")
        error = data.get("error")

        # Use the last path segment of the URI as a short display name for
        # the uploaded image. Falls back to the full URI if no slash present.
        short_name = image_uri.rsplit("/", 1)[-1] if image_uri else "(unknown image)"

        if status == UPLOAD_STATUS_SUCCESS:
            if similarity is not None:
                message = (
                    f"{short_name} — similarity {float(similarity):.0f}%, "
                    f"attempt {attempt}"
                    if attempt and attempt > 1
                    else f"{short_name} — similarity {float(similarity):.0f}%"
                )
            else:
                message = short_name
            return {
                LOGBOOK_ENTRY_NAME: "Image uploaded",
                LOGBOOK_ENTRY_MESSAGE: message,
            }

        if status == UPLOAD_STATUS_SKIPPED:
            # API accepted the upload but discarded it as too similar.
            if similarity is not None:
                message = (
                    f"{short_name} — too similar to current image "
                    f"({float(similarity):.0f}%)"
                )
            else:
                message = f"{short_name} — too similar to current image"
            return {
                LOGBOOK_ENTRY_NAME: "Image upload skipped",
                LOGBOOK_ENTRY_MESSAGE: message,
            }

        if status == UPLOAD_STATUS_FAILED:
            attempts_text = f" after {attempt} attempt(s)" if attempt else ""
            err_text = f": {error}" if error else ""
            return {
                LOGBOOK_ENTRY_NAME: "Image upload failed",
                LOGBOOK_ENTRY_MESSAGE: (
                    f"{short_name}{attempts_text}{err_text}"
                ).strip(),
            }

        # Unknown status — render something rather than nothing.
        return {
            LOGBOOK_ENTRY_NAME: "Image upload event",
            LOGBOOK_ENTRY_MESSAGE: f"{action}: {status}",
        }

    async_describe_event(DOMAIN, EVENT_IMAGE_UPLOADED, async_describe_upload_event)
