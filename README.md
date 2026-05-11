# paperlesspaper ePaper Display Integration for Home Assistant

[![HACS Custom](https://img.shields.io/badge/HACS-Custom-orange.svg)](https://github.com/hacs/integration)
[![Version](https://img.shields.io/badge/version-0.3.0-blue.svg)](https://github.com/djiwondee/paperlesspaper-ha/releases)
[![Beta](https://img.shields.io/badge/status-beta-orange.svg)](https://github.com/djiwondee/paperlesspaper-ha/releases)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

Control your [paperlesspaper](https://paperlesspaper.de) ePaper displays directly from Home Assistant — including automations, scripts, and the full HA media library.

<img width="976" height="393" alt="Overview paperlesspaper Integration" src="https://github.com/user-attachments/assets/e22850b8-ae5b-47ea-9919-676d1d46bebe" />

---

## Features

- **Automatic device discovery** - Devices in your paperlesspaper organization appear automatically in HA
- **Multi-device support** — Manage multiple ePaper displays from a single integration entry
- **Device sensors** — Monitor battery level, sync status, next wake-up time, sleep time, and more
- **Connectivity sensor** — Monitor whether your display is reachable
- **Update sensor** — Know when an update is available
- **Reset/Reboot Button** - Force a soft init of your ePaper device
- **upload_image action** — Send any image from HA media sources to your ePaper display
- **upload_random_image action** — Configure a media library folder once and have the integration cycle through it automatically. Each call shows the next random image; no repeats until the cycle finishes, and the same image is never shown on two frames at once
- **Activity feedback** — Every upload (success, skipped or failed) appears on the device's Activity timeline and is available as an automation trigger
- **Resilient upload pipeline**  — Transient API errors (HTTP 408/429/502/503/504, connection drops) are retried automatically with exponential backoff, honouring the server's `Retry-After` hint when provided
- **Force new paper** — Optionally create a fresh paper slot before uploading (useful for first-time setup or after clearing papers in the app)
- **Automation-ready** — Trigger image updates from time schedules, sensors, or any HA event

<img width="1007" height="895" alt="Device overview at a glance" src="https://github.com/user-attachments/assets/195fbcd3-4483-4e6b-9606-b040edd676b4" />

---

## Prerequisites

Before installing this integration you need:

1. A [paperlesspaper](https://paperlesspaper.de) account with at least one registered device
2. An API key — generate one at [paperlesspaper.de/posts/api](https://paperlesspaper.de/posts/api)
3. **A name set for your group (organization) in the paperlesspaper app.** New groups may be created without a name — make sure to assign one before setting up the integration, otherwise the configuration flow will fail.
4. Home Assistant 2026.3 or newer
5. HACS installed in your Home Assistant instance

> **Important:** This integration requires your device to be set up in the paperlesspaper app first. New devices cannot be registered through Home Assistant.

---

## Installation

### Via HACS (recommended)

1. Open HACS in Home Assistant
2. Go to **Integrations**
3. Click the three-dot menu → **Custom repositories**
4. Add `https://github.com/djiwondee/paperlesspaper-ha` as an **Integration**
5. Search for **paperlesspaper** and install it
6. Restart Home Assistant

### Manual

1. Download the latest release from the **[Releases page](https://github.com/djiwondee/paperlesspaper-ha/releases)**
2. Extract the archive
3. Copy the `custom_components/paperlesspaper` folder into your Home Assistant `config/custom_components/` directory (create the `custom_components` folder if it does not exist)
4. Restart Home Assistant
5. Go to **Settings → Devices & Services → Add Integration** and search for **paperlesspaper** and install it
6. Restart Home Assistant

---

## Configuration

### Setup

1. Go to **Settings → Devices & Services → Add Integration**
2. Search for **paperlesspaper**
3. Enter your API key
<img width="587" height="307" alt="Bildschirmfoto 2026-04-13 um 14 45 24" src="https://github.com/user-attachments/assets/8eb3effe-c79a-4c8f-a336-272b2801cc3f" />

4. **Select a group** — all available groups are shown, even if only one exists. Each group is set up as a separate integration entry in Home Assistant.
<img width="585" height="313" alt="Bildschirmfoto 2026-04-13 um 14 45 55" src="https://github.com/user-attachments/assets/500552bc-2e52-4175-9bae-cb16494435b1" />

5. **Confirm devices** — all ePaper devices found in the selected group are listed. Click **Submit** to confirm.
<img width="585" height="306" alt="Bildschirmfoto 2026-04-24 um 12 07 39" src="https://github.com/user-attachments/assets/e3cd6071-8533-4c78-8728-e3b925800dc2" />

All devices in the group are discovered automatically. No further manual configuration is required.

> **Note:** If you add a new device to your paperlesspaper group later, it will be detected automatically on the next poll cycle — no restart required.

### Reconfigure

If you need to update your API key or switch to a different group, use the **Reconfigure** option:

1. Go to **Settings → Devices & Services → paperlesspaper**
2. Click the **three-dot menu (⋮)** next to the integration entry
3. Select **Reconfigure**
4. Enter the new API key and select the desired group

The integration reloads automatically after reconfiguration.

### Options

After setup you can adjust the polling interval under **Settings → Devices & Services → paperlesspaper → ⚙️ Configure**:

| Option | Default | Min | Max | Description |
| --- | --- | --- | --- | --- |
| polling_interval | 300s | 60s | 3600s | How often HA polls the paperlesspaper API for device status updates |
| Reset random image history | — | — | — | *(Only shown after first use of `upload_random_image`)* When checked, clears the rotation memory for all devices in this group so the image cycle starts over. This **only** affects HA's internal list of already-shown images from the Home Assistant media library — nothing in the paperlesspaper app or cloud is changed |

<img width="580" height="373" alt="Configuring Polling Option" src="https://github.com/user-attachments/assets/039b7959-d278-45db-93c8-f8beafadff2b" />

> **Note:** After changing the polling interval the integration reloads automatically.


### Localization

The integration supports multiple languages. Entity names, buttons, and configuration dialogs are automatically displayed in the language set in your Home Assistant system preferences. To change the language go to **Settings → System → Home Information → Region Section** to set your language.

As a native German speaker with good English, I have provided translations for both languages. All other translations are machine-generated and try to follow the terminology currently used in the official paperlesspaper app. If you notice any inaccuracies or would like to contribute an improved translation for your language, pull requests are very welcome.

Currently supported languages:

| Language | Code |
| --- | --- |
| English | en |
| Deutsch | de |
| Français | fr |
| Svenska | sv |
| Nederlands | nl |
| Eesti      | et |
| Čeština    | cs |

> **Note:** After changing the language, don't forget to clear your browser cache.

---

## Entities

For each ePaper device the integration creates:

### Sensors

| Entity | Description | Unit |
|---|---|---|
| `sensor.<device>_battery_level` | Battery level | % |
| `sensor.<device>_battery_voltage` | Battery voltage | V |
| `sensor.<device>_next_sync` | Next scheduled wake-up time | datetime |
| `sensor.<device>_sleep_time` | Configured sleep interval | s |
| `sensor.<device>_sleep_time_predicted` | Predicted sleep interval | s |

### Binary Sensors

| Entity | Description |
|---|---|
| `binary_sensor.<device>_reachable` | `on` if the device is reachable |
| `binary_sensor.<device>_picture_synced` | `on` if the current picture is synced to the display |
| `binary_sensor.<device>_update_pending` | `on` if an update is pending |

### Buttons

| Entity | Description |
|---|---|
| `button.<device>_reboot` | Remotely reboot the ePaper device |
| `button.<device>_reset_sensors` | Reset all sensors on the device to factory defaults |

> **Warning:** The reset sensors button wipes all variables and memory on the device and triggers a reboot. Use with caution!

---

## Actions

### `paperlesspaper.upload_image`

Upload a specific image to an ePaper display. Each call uploads exactly the picture you select.

<img width="1002" height="512" alt="Upload_image action configuration" src="https://github.com/user-attachments/assets/606e1c3a-66db-42fa-91c2-71c7c5580f5d" />


| Parameter | Required | Default | Description |
|---|---|---|---|
| `device_id` | Yes | — | The paperlesspaper device to upload to |
| `media_content_id` | Yes | — | Image selected via the HA Media Picker, or a direct `https://` URL |
| `reuse_existing_paper` | No | `true` | When enabled (default), the existing paper slot is reused. When disabled, a new paper is created before uploading and saved as the new default for this device |

#### reuse_existing_paper

By default the integration reuses the paper slot that was created during initial setup. Toggle **Reuse existing paper** off when you want to force the creation of a fresh paper slot — for example after manually deleting papers in the paperlesspaper app, or when setting up a replacement device. When the toggle is _switched to off_, any papers with already published images remain untouched in the app — which is useful if you want to keep a history of previously displayed content or switch back to an earlier image directly from the paperlesspaper app.

> **Note:** When a new paper is created, its ID is automatically persisted as the new default for the device. Subsequent uploads will use this new paper unless the toggle is disabled again.

The `media_content_id` field supports two formats:

**Media Picker** (recommended) — use the built-in HA media browser to select an image from your media library. When using automations, the Media Picker returns a dictionary:

```yaml
data:
  media_content_id:
    media_content_id: media-source://media_source/local/my_image.png
    media_content_type: image/png
```

**Direct URL** — pass any public `https://` URL as a plain string:

```yaml
data:
  media_content_id: https://example.com/image.png
```

---

### `paperlesspaper.upload_random_image`

Configure a **media library folder once**, and have the integration cycle through its images automatically. Each time the action is triggered, one **new** image from that folder is shown on the display — no manual image selection required.

<img width="1009" height="655" alt="Upload_random_image action configuration" src="https://github.com/user-attachments/assets/3195404d-3cb6-45f4-9d3c-a218d8c5b076" />

This is the typical building block for a slideshow automation: *"every hour, show the next picture from my family photos folder"* — set it up once, then let your time- or event-based automation trigger the action whenever a new image should appear.

| Parameter | Required | Default | Description |
|---|---|---|---|
| `device_id` | Yes | — | The paperlesspaper device to upload to |
| `media_directory` | Yes | — | The media library folder to cycle through, given as a `media-source://` URI. See [Finding the right media_directory URI](#finding-the-right-media_directory-uri) below |
| `max_images` | No | `0` (= all) | Maximum number of images from the folder to include in the rotation pool. Useful when the folder contains hundreds of images but you only want to cycle through, e.g., 24 of them. If the folder contains fewer images than `max_images`, the cap is silently ignored and all images are used |
| `reuse_existing_paper` | No | `true` | Same behaviour as in `upload_image` |

> **Note:** Unlike `upload_image`, this action does **not** show the HA media picker for picking a single file. You enter the **folder URI once** in the action configuration; the integration then picks images from that folder automatically on every call.

#### How it works

On every call, the action:

1. Lists all images in the configured `media_directory`
2. If `max_images > 0`, restricts the pool to the first N images (stable order)
3. Excludes images already shown on this device for this folder (per-device, per-folder history)
4. Excludes the image currently shown on any **other** device, so the same picture is never visible on two frames at once
5. Picks one image at random from the remaining candidates
6. Uploads it via the same pipeline as `upload_image`
7. Persists the chosen image in the history

When all images of a folder have been shown on a device, the cycle resets automatically and starts over from the beginning of the pool — so a folder with 24 pictures plus an hourly trigger gives you a full day of rotating images, then starts again.

#### Finding the right `media_directory` URI

Home Assistant currently has no folder picker in the UI — `media_directory` is therefore a plain text field that expects a `media-source://` URI. Common examples:

| Source (as shown in the HA Media browser) | Example URI |
|---|---|
| **My media** (the root of your local media folder, default: `/media`) | `media-source://media_source/local` |
| A subfolder inside **My media** (e.g. `/media/photos`) | `media-source://media_source/local/photos` |
| A subfolder backed by an SMB or NFS share mounted into the local media folder | `media-source://media_source/local/nas/family` |
| A Synology Photos album | `media-source://synology_photos/<album-id>` |

> **Note:** "My media" is the HA UI name for the default `local` media directory (configured under the `media_source` integration, default path `/media`). Subfolders you create there appear as children of "My media" in the Media browser, and their URIs are built by appending the path to `media-source://media_source/local/`.

**The easiest way to find the correct URI for your setup:**

1. Open the **Media** browser in the Home Assistant sidebar
2. Navigate to the folder you want to use
3. Pick any image inside that folder via the HA **Media Picker** in a test automation (e.g. in `upload_image`)
4. Copy the `media_content_id` value — it ends with the file name
5. Drop the file name; what remains is your `media_directory` URI

For setting up local folders or SMB/NFS shares as media sources in the first place, see the official Home Assistant guide:
[Setup local media](https://www.home-assistant.io/more-info/local-media/setup-media).

#### History tracking

The history is stored inside the integration's config entry data — no additional storage layer or external database is needed. It survives Home Assistant restarts.

The history is keyed per **(device, folder)**, so:

- Multiple automations using **different folders** on the same device are tracked independently.
- Multiple devices using the **same folder** each maintain their own progress through the pool.
- When you change `media_directory` or `max_images` for a given device, the integration adapts automatically — stale entries are pruned from the history on the next call.

#### Robust against media library changes

- New images added to the folder appear in the candidate pool immediately on the next call.
- Deleted images are silently removed from the history.
- If the folder itself becomes unreachable (e.g. an SMB or NFS share goes offline), Home Assistant raises a **persistent notification** that automatically disappears as soon as the folder is reachable again. The history is never reset on connection errors, so the rotation resumes exactly where it left off.

#### Cross-device duplicate avoidance

If you have multiple frames using overlapping libraries, the integration tracks the image currently shown on each device. When picking a new image, the action excludes whatever is currently on any other frame — so you never see the same picture in two places at once.

In edge cases where there are more frames than images in a folder, the cross-device exclusion is relaxed automatically (with a warning logged) so a frame is never left without an image.

---

## Resilience: transient API errors and timing tips

### How the integration handles transient errors

The paperlesspaper API can briefly return transient errors — most commonly **HTTP 502 Bad Gateway** during wake-up spikes (when many devices contact the cloud simultaneously) or **HTTP 503 Service Unavailable** during short overload conditions. The provider documents that 503 responses may take up to about 5 minutes to clear.

To stay robust against these short-lived issues, the integration retries automatically:

| Component | Attempts | Backoff schedule | Total worst-case wait |
|---|---|---|---|
| `upload_image` and `upload_random_image` | 4 (1 + 3 retries) | 5s, 15s, 30s | 50 seconds |
| Coordinator (sensor polling) | 3 (1 + 2 retries) | 5s, 15s | 20 seconds |

Both components honour the standard HTTP **`Retry-After`** response header when the server provides it, capped at 120 seconds for uploads and 60 seconds for the coordinator.

The retry logic covers HTTP status codes `408`, `429`, `502`, `503`, and `504` as well as transient connection errors.

If the API stays unavailable for longer than the budget (which can happen during a real provider outage), the action fails with a `HomeAssistantError` and an entry of `status: failed` appears on the device's Activity timeline. The next scheduled run of the automation then gets a fresh chance.

### Avoid triggering on the device's wake-up minute

ePaper devices wake up on their own schedule (typically every 10, 30, or 60 minutes) to check for new content. The paperlesspaper cloud experiences a brief load spike at these wake-up moments because **all** devices on the network reach out at the same second.

If your automation triggers at the **exact same minute** as the device wake-up — for example both running at `:00` — the upload call can collide with that load spike. The integration handles this transparently via the retry logic above, but you can avoid the collision entirely by offsetting your automation triggers by a few minutes so they fire **between** wake-up cycles:

```yaml
# Triggers at :05 (good — between :00 and :10 wake-ups)
trigger:
  - platform: time_pattern
    hours: "/1"
    minutes: 5
```

This is purely a quality-of-life improvement; the integration will still work without an offset thanks to the built-in retry logic.

---

## Events & Activity timeline

Every image upload produces an entry on the device's **Activity timeline** (Settings → Devices & Services → paperlesspaper → [device]). The same event is also available as an **automation trigger**, so you can react to upload outcomes — for example notify yourself when an upload fails.

### What appears in the Activity timeline

Three kinds of upload outcomes are reported, each with a distinct, human-readable line:

| Outcome | Activity entry | When it happens |
|---|---|---|
| Success | **Image uploaded** — `<filename>` — similarity X% | API accepted the upload and the new image will be shown on the next device wake-up |
| Skipped | **Image upload skipped** — `<filename>` — too similar to current image (X%) | The API received the upload but discarded it because the image is too similar to the one currently shown. This is normal and explains why nothing changes on the display |
| Failed | **Image upload failed** — `<filename>` — after N attempt(s): `<error>` | All retry attempts failed. The HA system log also contains an ERROR-level entry with the cause |

When an upload succeeds on a retry (e.g. after a transient 502), the entry includes the attempt number: *"similarity 85%, attempt 2"*.

### Event: `paperlesspaper_image_uploaded`

The same information is available as an HA event that any automation can listen to.

**Event payload:**

| Key | Type | Description |
|---|---|---|
| `device_id` | string | HA device id (matches `device_id` used in actions) |
| `pp_device_id` | string | paperlesspaper internal device id |
| `paper_id` | string | Paper slot used for this upload |
| `status` | string | `success`, `skipped` or `failed` |
| `image_uri` | string | The URI/URL that was uploaded |
| `action` | string | `upload_image` or `upload_random_image` |
| `attempt` | int | The 1-based attempt number that produced the outcome |
| `similarity_percentage` | float | API-reported similarity (`success`/`skipped` only) |
| `skipped_upload` | bool | API skip flag (`success`/`skipped` only) |
| `error` | string | Error message (`failed` only) |

### Example: notify on failure

```yaml
automation:
  alias: "Notify on ePaper upload failure"
  trigger:
    - platform: event
      event_type: paperlesspaper_image_uploaded
      event_data:
        status: failed
  action:
    - action: notify.mobile_app_iphone
      data:
        title: "ePaper upload failed"
        message: >
          {{ trigger.event.data.image_uri }} —
          {{ trigger.event.data.error }}
```

### Example: log every skipped upload to a notification helper

```yaml
automation:
  alias: "Log skipped ePaper uploads"
  trigger:
    - platform: event
      event_type: paperlesspaper_image_uploaded
      event_data:
        status: skipped
  action:
    - action: persistent_notification.create
      data:
        title: "ePaper: upload skipped"
        message: >
          {{ trigger.event.data.image_uri }} was skipped — similarity
          {{ trigger.event.data.similarity_percentage }}%
```

---

## Automation Examples

### Update display every morning at 7:05

```yaml
automation:
  alias: "Morning ePaper update"
  trigger:
    - platform: time
      at: "07:05:00"
  action:
    - action: paperlesspaper.upload_image
      data:
        device_id: <your_device_id>
        media_content_id:
          media_content_id: media-source://media_source/local/morning.png
          media_content_type: image/png
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
      data:
        device_id: <your_device_id>
        media_content_id:
          media_content_id: media-source://media_source/local/weather.png
          media_content_type: image/png
```

### Update display from an external URL

```yaml
automation:
  alias: "ePaper update from URL"
  trigger:
    - platform: time
      at: "08:05:00"
  action:
    - action: paperlesspaper.upload_image
      data:
        device_id: <your_device_id>
        media_content_id: https://example.com/daily-image.jpg
```

### Force a new paper slot before uploading

```yaml
automation:
  alias: "ePaper update with new paper"
  trigger:
    - platform: time
      at: "09:05:00"
  action:
    - action: paperlesspaper.upload_image
      data:
        device_id: <your_device_id>
        reuse_existing_paper: false
        media_content_id:
          media_content_id: media-source://media_source/local/morning.png
          media_content_type: image/png
```

### Slideshow rotation — one new picture every hour

Set the `media_directory` once; every hour the trigger picks the next random image from that folder. The 5-minute offset keeps the trigger from colliding with the device's wake-up cycle.

```yaml
automation:
  alias: "ePaper hourly random rotation"
  trigger:
    - platform: time_pattern
      hours: "/1"
      minutes: 5
  action:
    - action: paperlesspaper.upload_random_image
      data:
        device_id: <your_device_id>
        media_directory: media-source://media_source/local/family-photos
        max_images: 24
```

### Slideshow rotation from an SMB/NFS share

```yaml
automation:
  alias: "ePaper random rotation from NAS"
  trigger:
    - platform: time
      at: "08:05:00"
  action:
    - action: paperlesspaper.upload_random_image
      data:
        device_id: <your_device_id>
        media_directory: media-source://media_source/local/nas/holiday-2025
```

### Different rotations on multiple frames

```yaml
automation:
  alias: "Living room random photos"
  trigger:
    - platform: time_pattern
      hours: "/2"
      minutes: 5
  action:
    - action: paperlesspaper.upload_random_image
      data:
        device_id: <living_room_device_id>
        media_directory: media-source://media_source/local/family-photos

automation:
  alias: "Bedroom random photos"
  trigger:
    - platform: time_pattern
      hours: "/3"
      minutes: 5
  action:
    - action: paperlesspaper.upload_random_image
      data:
        device_id: <bedroom_device_id>
        media_directory: media-source://media_source/local/family-photos
```

> Both frames pull from the same folder, but the integration ensures they never display the same image at the same time.

---

## How it works

The integration polls the paperlesspaper API every 5 minutes (configurable). Each poll calls `GET /devices/ping/:id?dataResponse=false` per device — this single endpoint returns both the reachability status and the full device telemetry (battery, sync status, firmware version, next wake-up time, etc.).

### Device discovery

During setup, all devices in the selected group are discovered automatically and added to Home Assistant. If new devices are added to the group in the paperlesspaper app at a later point, they are detected on the next poll cycle and their entities (sensors, binary sensors, buttons) are registered without requiring a restart.

Devices that are removed from the paperlesspaper app are **not** automatically removed from Home Assistant. They remain visible but become **unavailable**. To remove them, delete them manually in Home Assistant under **Settings → Devices & Services → paperlesspaper → [device] → Delete**.

### Papers

On first setup — and on every HA restart — the integration validates that a dedicated paper (screen slot) exists for each device. If the paper was deleted in the paperlesspaper app, a new one is created automatically.

When `reuse_existing_paper` is set to `false` in either upload action, a new paper is created unconditionally before the upload, and its Paper ID is persisted as the default for the selected device.

### Image uploads

Image uploads use the `POST /papers/uploadSingleImage` endpoint. The API compares each new image against the current one and skips the upload if they are too similar — this avoids unnecessary ePaper refresh cycles which extend display lifetime.

See [Resilience: transient API errors and timing tips](#resilience-transient-api-errors-and-timing-tips) for the retry behaviour and timing recommendations.

Each upload attempt outcome is reported via the `paperlesspaper_image_uploaded` event, which is both shown on the device's Activity timeline and available as an automation trigger. See [Events & Activity timeline](#events--activity-timeline) for details.

> **Note:** ePaper displays wake up on a schedule (default: every 60 minutes). Uploaded images appear on the next wake cycle — not instantly.

---

## Known limitations

- The paperlesspaper API is v1 and some endpoints are still being finalized
- The `GET /devices/events` endpoint currently returns HTTP 400 and is not used by this integration
- Deleting papers is not supported via the API — use the paperlesspaper app to manage papers
- Battery level is reported as a raw millivolt value from the device hardware — accuracy may vary
- Activity timeline entries for upload events are rendered in English regardless of the Home Assistant UI language
- Outages of the paperlesspaper upload service longer than the retry budget (~50 seconds for uploads) will fail the current action; the next scheduled automation run will retry
- **HEIC / HEIF images are not supported.** The paperlesspaper upload endpoint cannot process these formats and responds with HTTP 502. `upload_random_image` skips HEIC/HEIF files automatically when listing a folder, and the `upload_image` Media Picker does not offer them. If you have an Apple photo collection in `.heic`, convert it to JPEG (e.g. via a Home Assistant automation, a NAS tool, or macOS Photos export) before pointing the integration at the folder

---

## Disclaimer

This software is provided **free of charge** and **as-is**, without any warranty of any kind, express or implied. By using this integration, you accept full responsibility for any consequences arising from its use.

- This integration is **not officially affiliated with, endorsed by, or supported by** paperlesspaper
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
