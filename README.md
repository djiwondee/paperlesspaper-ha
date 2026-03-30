# paperlesspaper for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/paperlesspaper/paperlesspaper-ha/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Control your [paperlesspaper](https://paperlesspaper.de) ePaper displays directly from Home Assistant — including automations, scripts, and the full HA media library.

---

## Features

- **Automatic device discovery** — all devices in your paperlesspaper organization appear automatically in HA
- **upload_image action** — send any image from HA media sources to your ePaper display
- **Connectivity sensor** — monitor whether your display is reachable
- **Last loaded sensor** — see when your display last refreshed its image
- **Multi-device support** — manage multiple ePaper displays from a single integration entry
- **Automation-ready** — trigger image updates from time schedules, sensors, or any HA event

---

## Prerequisites

Before installing this integration you need:

1. A [paperlesspaper](https://paperlesspaper.de) account with at least one registered device
2. An API key — generate one at [paperlesspaper.de/posts/api](https://paperlesspaper.de/posts/api)
3. Home Assistant 2024.1 or newer
4. HACS installed in your Home Assistant instance

> **Important:** This integration requires your device to be set up in the paperlesspaper app first. New devices cannot be registered through Home Assistant.

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the three-dot menu → **Custom repositories**
4. Add `https://github.com/paperlesspaper/paperlesspaper-ha` as an **Integration**
5. Search for **paperlesspaper** and install it
6. Restart Home Assistant

### Manual

1. Download the latest release
2. Copy the `custom_components/paperlesspaper` folder to your HA `config/custom_components/` directory
3. Restart Home Assistant

---

## Configuration

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **paperlesspaper**
3. Enter your API key
4. If you have multiple organizations, select the one containing your devices
5. Click **Submit** — all your devices are discovered automatically

---

## Entities

For each ePaper device the integration creates:

| Entity | Type | Description |
|---|---|---|
| `sensor.<device>_last_loaded` | Sensor | Timestamp of the last successful image refresh |
| `binary_sensor.<device>_reachable` | Binary Sensor | `on` if the device is reachable, `off` if not |

---

## Actions

### `paperlesspaper.upload_image`

Upload an image to an ePaper display.

| Parameter | Required | Description |
|---|---|---|
| `target` | Yes | The paperlesspaper device to upload to |
| `media_content_id` | Yes | Path to the image — supports `media-source://` and `http://` URLs |

#### Example: Upload a local file

```yaml
action: paperlesspaper.upload_image
target:
  device_id: <your_device_id>
data:
  media_content_id: media-source://media_source/local/my_image.png
```

#### Example: Upload from external URL

```yaml
action: paperlesspaper.upload_image
target:
  device_id: <your_device_id>
data:
  media_content_id: https://example.com/image.png
```

---

## Automation Examples

### Update display every morning at 7:00

```yaml
automation:
  alias: "Morning ePaper update"
  trigger:
    - platform: time
      at: "07:00:00"
  action:
    - action: paperlesspaper.upload_image
      target:
        device_id: <your_device_id>
      data:
        media_content_id: media-source://media_source/local/morning.png
```

### Update display when a sensor changes

```yaml
automation:
  alias: "ePaper update on weather change"
  trigger:
    - platform: state
      entity_id: weather.home
  action:
    - action: paperlesspaper.upload_image
      target:
        device_id: <your_device_id>
      data:
        media_content_id: media-source://media_source/local/weather.png
```

---

## How it works

The integration polls the paperlesspaper API every 5 minutes to update device states. On first setup — and on every HA restart — it validates that a dedicated paper (screen slot) exists for each device. If the paper was deleted in the paperlesspaper app, a new one is created automatically.

Image uploads use the `POST /papers/uploadSingleImage` API endpoint. The API compares each new image against the current one and skips the upload if they are too similar — this avoids unnecessary ePaper refresh cycles which extend display lifetime.

> **Note:** The paperlesspaper API is v1 and some endpoints are still being finalized. The `GET /devices/events` endpoint currently returns HTTP 400 and is not used by this integration.

---

## Known limitations

- ePaper displays wake up on a schedule (default: every 60 minutes). Uploaded images appear on the next wake cycle — not instantly.
- The paperlesspaper API does not provide a push/webhook mechanism. All state updates are polled.
- Deleting papers is not supported via API — use the paperlesspaper app to manage papers.

---

## Contributing

Pull requests are welcome. For major changes, please open an issue first.

This integration is not officially affiliated with or endorsed by paperlesspaper / wirewire.

---

## License

MIT