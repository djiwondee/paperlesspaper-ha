"""Logbook integration for paperlesspaper.

Registers describe-event hooks so that events fired by the integration
appear as human-readable entries on each device's Activity timeline
(Settings → Devices & Services → paperlesspaper → [device] → Logbook).

Without this module the events would still fire (and be usable as
automation triggers), but they would appear as raw "Event ...with data..."
lines instead of nicely formatted messages.

Covered events:
  - paperlesspaper_image_uploaded   (upload pipeline — success/skipped/failed)
  - paperlesspaper_device_woke_up   (activate event from the device)
  - paperlesspaper_device_state_changed (state event from the device)
"""
# =============================================================================
# CHANGE HISTORY
# 2026-05-11  0.3.0  New module. Describes EVENT_IMAGE_UPLOADED events for the
#                    HA logbook so that each upload appears as a readable line
#                    on the device's Activity timeline. Distinguishes success,
#                    skipped (API discarded as too similar), and failed states.
# 2026-06-01  1.0.2  Added describe hooks for the two new device event types:
#                    - EVENT_DEVICE_WOKE_UP: shows battery voltage, firmware
#                      version, and WiFi RSSI when available.
#                    - EVENT_DEVICE_STATE_CHANGED: shows the state string
#                      (update_ok, download_ok, update_failed, …) with a
#                      human-readable prefix label.
# =============================================================================

from __future__ import annotations

from collections.abc import Callable
import logging

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import Event, HomeAssistant, callback

from .const import (
    DEVICE_STATE_DOWNLOAD_OK,
    DEVICE_STATE_UPDATE_CHECKED_NOPICTURE,
    DEVICE_STATE_UPDATE_CHECKED_OK,
    DEVICE_STATE_UPDATE_FAILED,
    DEVICE_STATE_UPDATE_OK,
    DOMAIN,
    EVENT_DEVICE_STATE_CHANGED,
    EVENT_DEVICE_WOKE_UP,
    EVENT_IMAGE_UPLOADED,
    UPLOAD_STATUS_FAILED,
    UPLOAD_STATUS_SKIPPED,
    UPLOAD_STATUS_SUCCESS,
)

_LOGGER = logging.getLogger(__name__)

# Human-readable labels for the known device state values.
# Any unknown future state value falls through to a generic rendering.
_STATE_LABELS: dict[str, str] = {
    DEVICE_STATE_UPDATE_OK:                "Picture displayed",
    DEVICE_STATE_DOWNLOAD_OK:              "Picture downloaded",
    DEVICE_STATE_UPDATE_FAILED:            "Picture update failed",
    DEVICE_STATE_UPDATE_CHECKED_OK:        "Update check OK",
    DEVICE_STATE_UPDATE_CHECKED_NOPICTURE: "No new picture",
}


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[[str, str, Callable[[Event], dict]], None],
) -> None:
    """Register describe-event hooks for all paperlesspaper event types.

    Called once by Home Assistant's logbook integration on startup.
    """

    # ------------------------------------------------------------------
    # Upload events
    # ------------------------------------------------------------------

    @callback
    def async_describe_upload_event(event: Event) -> dict:
        """Return a human-readable logbook entry for an image upload event."""
        data = event.data or {}
        status = data.get("status", "unknown")
        image_uri = data.get("image_uri", "") or ""
        action = data.get("action", "upload")
        attempt = data.get("attempt")
        similarity = data.get("similarity_percentage")
        error = data.get("error")

        # Use the last path segment of the URI as a short display name.
        # Falls back to the full URI if no slash is present.
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

    # ------------------------------------------------------------------
    # Device wake-up events
    # ------------------------------------------------------------------

    @callback
    def async_describe_woke_up_event(event: Event) -> dict:
        """Return a human-readable logbook entry for a device wake-up event.

        Shows battery voltage (mV), firmware version, and WiFi RSSI when
        available. Fields that are absent in the payload are omitted from
        the message rather than shown as "None".
        """
        data = event.data or {}
        bat_mv = data.get("bat_mv")
        fw = data.get("fw")
        wifi_rssi = data.get("wifi_rssi")

        parts: list[str] = []
        if bat_mv is not None:
            parts.append(f"battery {bat_mv} mV")
        if fw is not None:
            parts.append(f"fw {fw}")
        if wifi_rssi is not None:
            parts.append(f"WiFi {wifi_rssi} dBm")

        message = ", ".join(parts) if parts else "device woke up"
        return {
            LOGBOOK_ENTRY_NAME: "Device woke up",
            LOGBOOK_ENTRY_MESSAGE: message,
        }

    # ------------------------------------------------------------------
    # Device state-change events
    # ------------------------------------------------------------------

    @callback
    def async_describe_state_changed_event(event: Event) -> dict:
        """Return a human-readable logbook entry for a device state event.

        Translates known state strings to descriptive labels; unknown future
        state values are shown as-is so they remain visible in the timeline
        without requiring a code update.
        """
        data = event.data or {}
        state = data.get("state", "")
        label = _STATE_LABELS.get(state, state)  # fall back to raw value

        return {
            LOGBOOK_ENTRY_NAME: "Device state",
            LOGBOOK_ENTRY_MESSAGE: label,
        }

    # Register all three hooks
    async_describe_event(DOMAIN, EVENT_IMAGE_UPLOADED,        async_describe_upload_event)
    async_describe_event(DOMAIN, EVENT_DEVICE_WOKE_UP,        async_describe_woke_up_event)
    async_describe_event(DOMAIN, EVENT_DEVICE_STATE_CHANGED,  async_describe_state_changed_event)
