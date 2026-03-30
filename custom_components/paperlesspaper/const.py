"""Constants for the paperlesspaper integration."""

DOMAIN = "paperlesspaper"

PLATFORMS = ["sensor", "binary_sensor", "button"]

API_BASE_URL = "https://api.memo.wirewire.de/v1"

CONF_API_KEY = "api_key"
CONF_ORGANIZATION_ID = "organization_id"
CONF_PAPER_IDS = "paper_ids"

POLLING_INTERVAL = 60  # 1 Minute

CONF_POLLING_INTERVAL = "polling_interval"
DEFAULT_POLLING_INTERVAL = 300  # 5 minutes
MIN_POLLING_INTERVAL = 60       # 1 minute minimum
MAX_POLLING_INTERVAL = 3600     # 1 hour maximum
