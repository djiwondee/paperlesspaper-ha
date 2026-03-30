# paperlesspaper for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-0.1.0-blue.svg)](https://github.com/paperlesspaper/paperlesspaper-ha/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Control your [paperlesspaper](https://paperlesspaper.de) ePaper displays directly from Home Assistant — including automations, scripts, and the full HA media library.

---

## Features

- **Automatic device discovery** — all devices in your paperlesspaper organization appear automatically in HA
- **upload_image action** — send any image from HA media sources to your ePaper display
- **Device sensors** — monitor battery level, sync status, next wake-up time, sleep time, and more
- **Connectivity sensor** — monitor whether your display is reachable
- **Update sensor** — know when an update is available
- **Reset/Reboot Button** - to force a soft init of your ePaper device
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

### Options

After setup you can adjust the polling interval under **Settings → Devices & Services → paperlesspaper → Configure**:

| Option | Default | Min | Max | Description |
| --- | --- | --- | --- | --- |
| polling_interval | 300s | 60s | 3600s | How often HA polls the paperlesspaper API for device status updates |

> **Note:** After changing the polling interval the integration reloads automatically.
---

## Entities

For each ePaper device the integration creates:

### Sensors

| Entity | Description | Unit |
|---|---|---|
| `sensor.<device>_battery_level` | Battery voltage | V |
| `sensor.<device>_next_sync` | Next scheduled wake-up time | datetime |
| `sensor.<device>_sleep_time` | Configured sleep interval | s |
| `sensor.<device>_sleep_time_predicted` | Predicted sleep interval | s |
| `sensor.<device>_picture_synced` | Whether the current image is synced | — |

### Binary Sensors

| Entity | Description |
|---|---|
| `binary_sensor.<device>_reachable` | `on` if the device is reachable |
| `binary_sensor.<device>_update_pending` | `on` if an update is available |

### Buttons

| Entity | Description |
|---|---|
| `button.<device>_reboot` | Remotely reboot the ePaper device |
| `button.<device>_reset_sensors` | Reset all sensors on the device to factory defaults |

> **Warning:** The reset button wipes all variables and memory on the device and triggers a reboot. Use with caution!

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

The integration polls the paperlesspaper API every 5 minutes. Each poll calls `GET /devices/ping/:id?dataResponse=false` per device — this single endpoint returns both the reachability status and the full device telemetry (battery, sync status, firmware version, next wake-up time, etc.).

On first setup — and on every HA restart — the integration validates that a dedicated paper (screen slot) exists for each device. If the paper was deleted in the paperlesspaper app, a new one is created automatically.

Image uploads use the `POST /papers/uploadSingleImage` endpoint. The API compares each new image against the current one and skips the upload if they are too similar — this avoids unnecessary ePaper refresh cycles which extend display lifetime.

> **Note:** ePaper displays wake up on a schedule (default: every 60 minutes). Uploaded images appear on the next wake cycle — not instantly.

---

## Known limitations

- The paperlesspaper API is v1 and some endpoints are still being finalized
- The `GET /devices/events` endpoint currently returns HTTP 400 and is not used by this integration
- Deleting papers is not supported via the API — use the paperlesspaper app to manage papers
- Battery level is reported as a raw millivolt value from the device hardware — accuracy may vary

---

## Disclaimer

This software is provided **free of charge** and **as-is**, without any warranty of any kind, express or implied. By using this integration, you accept full responsibility for any consequences arising from its use.

- This integration is **not officially affiliated with, endorsed by, or supported by** paperlesspaper / wirewire
- The author provides **no guarantee** of functionality, reliability, or fitness for any particular purpose
- Use of this integration is **entirely at your own risk**
- The author accepts **no liability** for any damage, data loss, costs, or other harm arising from the use or inability to use this software

If you encounter issues with the paperlesspaper API or your devices, please contact [paperlesspaper support](https://paperlesspaper.de/posts/contact) directly.

---

## Contributing

Pull requests and issue reports are welcome. For major changes, please open an issue first to discuss what you would like to change.

---

## License

MIT License

Copyright (c) 2026 paperlesspaper-ha contributors

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files (the "Software"), to deal in the Software without restriction, including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of the Software.

**THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.**
