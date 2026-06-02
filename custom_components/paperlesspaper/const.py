"""Constants for the paperlesspaper integration."""
# =============================================================================
# CHANGE HISTORY
# 2026-04-08  0.1.3  Removed unused POLLING_INTERVAL constant
# 2026-05-09  0.3.0  Added CONF_RANDOM_UPLOAD_HISTORY for the new
#                    upload_random_image action. Stores per-device, per-
#                    directory history of already-shown images plus the
#                    currently displayed image for cross-device duplicate
#                    avoidance.
# 2026-05-11  0.3.0  Added event constants for image upload activity:
#                    - EVENT_IMAGE_UPLOADED: HA event type fired after each
#                      upload attempt (success, skipped, or failed). Picked up
#                      by logbook.py to produce human-readable Activity entries
#                      on the device timeline.
#                    - UPLOAD_STATUS_* constants for the event's status field.
# 2026-06-01  1.0.2  Added event constants for device events polled from
#                    GET /devices/events/{deviceId}:
#                    - EVENT_DEVICE_WOKE_UP: fired on every "activate" event,
#                      i.e. each time the device wakes up. Payload includes
#                      battery voltage, firmware version, WiFi RSSI, and
#                      the configured sleep timeout.
#                    - EVENT_DEVICE_STATE_CHANGED: fired on every "state"
#                      event (update_ok, download_ok, update_failed, …).
#                      Generic single event — callers filter on the "state"
#                      field in the event payload.
#                    - DEVICE_STATE_* string constants for the known state
#                      values documented by the API.
# =============================================================================

DOMAIN = "paperlesspaper"

PLATFORMS = ["binary_sensor", "button", "sensor"]

API_BASE_URL = "https://api.paperlesspaper.de/v1"

CONF_API_KEY = "api_key"
CONF_ORGANIZATION_ID = "organization_id"
CONF_PAPER_IDS = "paper_ids"

# Persistent state for the upload_random_image action.
# Structure in config_entry.data:
# {
#   "random_upload_history": {
#     "<pp_device_id>": {
#       "currently_showing": "<media-source-uri>",
#       "<directory_uri>": {
#         "seen": ["<uri>", ...],
#         "max_images": <int>
#       }
#     }
#   }
# }
CONF_RANDOM_UPLOAD_HISTORY = "random_upload_history"

CONF_POLLING_INTERVAL = "polling_interval"
DEFAULT_POLLING_INTERVAL = 300  # 5 minutes
MIN_POLLING_INTERVAL = 60       # 1 minute minimum
MAX_POLLING_INTERVAL = 3600     # 1 hour maximum

# ----------------------------------------------------------------------------
# Upload event type & status values
# ----------------------------------------------------------------------------
# Event fired after every image upload attempt. Listened to by the logbook
# integration to produce human-readable Activity entries, and available to
# users as an automation trigger.
#
# Event data payload:
#   - device_id (str)              : HA device id (used by logbook)
#   - pp_device_id (str)           : paperlesspaper internal device id
#   - paper_id (str)               : paper slot id used for this upload
#   - status (str)                 : one of UPLOAD_STATUS_*
#   - image_uri (str)              : media-source URI or http(s) URL uploaded
#   - action (str)                 : "upload_image" or "upload_random_image"
#   - attempt (int)                : 1-based attempt number that produced the
#                                    final outcome (relevant for retries)
#   - similarity_percentage (float | None)
#                                    API-reported similarity to previous image
#                                    (None for failed uploads)
#   - skipped_upload (bool | None) : API-reported skip flag
#                                    (None for failed uploads)
#   - error (str | None)           : error message for failed uploads
EVENT_IMAGE_UPLOADED = "paperlesspaper_image_uploaded"

UPLOAD_STATUS_SUCCESS = "success"
UPLOAD_STATUS_SKIPPED = "skipped"
UPLOAD_STATUS_FAILED  = "failed"

# ----------------------------------------------------------------------------
# Device event types (polled from GET /devices/events/{deviceId})
# ----------------------------------------------------------------------------
# EVENT_DEVICE_WOKE_UP
#   Fired for every API event of type "activate" — i.e. each time the device
#   wakes up from sleep. The activate payload is a JSON string embedded in the
#   "EventMessage" field; the coordinator parses and normalises it.
#
#   Event data payload:
#     - device_id (str)      : HA device id
#     - pp_device_id (str)   : paperlesspaper internal device id
#     - bat_mv (int | None)  : battery voltage in millivolts
#     - fw (str | None)      : firmware version string, e.g. "2.0.35"
#     - wifi_rssi (int|None) : WiFi signal strength in dBm (negative integer)
#     - timeout_s (int|None) : configured sleep interval in seconds
#     - timestamp_ms (int)   : event timestamp as millisecond epoch (UTC)
EVENT_DEVICE_WOKE_UP = "paperlesspaper_device_woke_up"

# EVENT_DEVICE_STATE_CHANGED
#   Fired for every API event of type "state". The EventMessage is a plain
#   string describing the state transition. One generic event is used for all
#   state values; automation authors filter on the "state" field in the payload.
#
#   Event data payload:
#     - device_id (str)      : HA device id
#     - pp_device_id (str)   : paperlesspaper internal device id
#     - state (str)          : one of the DEVICE_STATE_* constants below,
#                              or an unknown future value
#     - timestamp_ms (int)   : event timestamp as millisecond epoch (UTC)
EVENT_DEVICE_STATE_CHANGED = "paperlesspaper_device_state_changed"

# Known values for the "state" field in EVENT_DEVICE_STATE_CHANGED payloads.
# New values introduced by the API in future will be forwarded as-is without
# requiring a code change — these constants exist only for convenience in
# automations and tests.
DEVICE_STATE_UPDATE_OK               = "update_ok"
DEVICE_STATE_UPDATE_FAILED           = "update_failed"
DEVICE_STATE_DOWNLOAD_OK             = "download_ok"
DEVICE_STATE_UPDATE_CHECKED_OK       = "update_checked_ok"
DEVICE_STATE_UPDATE_CHECKED_NOPICTURE = "update_checked_nopicture"
