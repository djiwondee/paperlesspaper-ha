"""Constants for the paperlesspaper integration."""

DOMAIN = "paperlesspaper"

PLATFORMS = ["sensor", "binary_sensor", "button"]

API_BASE_URL = "https://api.memo.wirewire.de/v1"

CONF_API_KEY = "api_key"
CONF_ORGANIZATION_ID = "organization_id"
CONF_PAPER_IDS = "paper_ids"

POLLING_INTERVAL = 60  # 1 Minute
