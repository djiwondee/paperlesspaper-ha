# Changelog

All notable changes to `paperlesspaper-ha` are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- `hassfest` validation failure with Home Assistant 2026.10: removed `aiohttp` from the manifest
  `requirements`. It is a dependency of Home Assistant itself and must not be listed by a custom
  integration.

## [2.1.2] - 2026-09-30

### Fixed

- Repeated `Timeout fetching paperlesspaper data` errors: API timeouts raise `TimeoutError`, which
  is not an `aiohttp.ClientError` and was not caught anywhere in the coordinator, so a single slow
  request aborted the whole poll and made all entities unavailable for that cycle. A slow ping or
  event request now only marks that device as unreachable / skips its events for the cycle, device
  list timeouts are retried with the existing backoff, a timeout while validating the stored
  paper ID falls back to the stored value, and remaining timeouts surface as a
  descriptive `UpdateFailed` instead of HA's generic message.

## [2.1.1] - 2026-09-08

### Fixed

- `frame_orientation` sensor showed `unknown` on devices running firmware 3.0.x: firmware 3.x
  reports a 4-state `orient` value (one per physical rotation) while the sensor's mapping only
  understood firmware 2.x's 2-state value (`0=portrait`, `3=landscape`). The mapping is now
  firmware-aware — selected from the device's `fw_version` (major version `>= 3` picks the new
  4-state map) — so both firmware generations report correctly. Firmware ≥ 3.x devices now report
  the exact rotation as one of 4 distinct, fully localized states (`landscape_right`, `portrait`,
  `landscape_left`, `portrait_upside_down`) instead of being down-mapped to coarse
  `portrait`/`landscape` — needed to pick the correct image orientation before upload. Firmware
  < 3.x devices are unaffected and still report the coarse `portrait`/`landscape` state, which is
  all that firmware generation can distinguish. An unmapped `orient` value now logs a one-time
  warning per device instead of silently returning `unknown`. The sensor's `icon` property, which
  had its own separate (and equally outdated) orientation check, now derives from the same
  resolved value.
  Also fixes a related reliability gap: `fw_version` is now persisted across a transient ping
  failure instead of disappearing from the device's data for that poll cycle, which — since the
  orientation mapping now depends on it — could otherwise have caused a momentary incorrect
  mapping. (Issue #34)

## [2.1.0] - 2026-09-07

### Fixed

- Fetch-stage failures in `upload_image`/`upload_random_image` (media resolution, local file read,
  HTTP fetch) previously discarded which file/URL caused them and never fired the upload event —
  the only upload-failure path that didn't show up on the device's Activity timeline or as an
  automation trigger. `_fetch_media_source` and `_fetch_http` now include the failing
  `media_content_id`/URL in both the logged error and the raised error message, and both service
  handlers now fire a `status: failed` event before re-raising. (Issue #35)

## [2.0.1] - 2026-08-03

### Added

- Repo-scoped `pyproject.toml` pinning Ruff/isort behavior and `target-version`; CI now pins the
  Ruff version and bumps Python to 3.14.

### Changed

- Release preparation: documented automatic device re-linking and the HACS Default Store listing.

### Fixed

- Ruff lint issues across several modules (import order, unused `noqa` comments, missing
  `ClassVar` on a mutable class attribute) — style-only, no behavioral change.

## [1.2.0] - 2026-07-21

### Added

- Automatic orphaned-device detection and remapping: `coordinator._reconcile_devices()` matches a
  device's stable hardware `deviceId` to remap the existing HA device (and all its entities,
  history, automation references) onto the new paperlesspaper `id` after the physical frame is
  re-registered in the app, instead of leaving an orphan and creating a duplicate.
- `OrphanedDeviceRepairFlow`: a Repairs UI menu offering "Delete" or "Relink to another device"
  (manual remap) for devices that were already orphaned before automatic `deviceId`-based
  remapping was introduced.
- `async_remove_config_entry_device()` enabling the manual "Delete device" button in
  Settings → Devices & Services for devices no longer reported by the API (blocked for devices
  that are still active, to avoid entity/device desync).
- `ORPHANED_DEVICE_MISSING_THRESHOLD`, `ISSUE_ORPHANED_DEVICE_PREFIX`, and
  `ISSUE_DEVICE_REMAPPED_PREFIX` constants backing the new Repairs issues.

### Fixed

- `DeviceInfo.serial_number` was always `None` in `sensor.py`/`binary_sensor.py`/`button.py` — it
  read a `serial_number` key that does not exist in the `/devices/` API response. Now sourced from
  `deviceId`, which is present on every device and stable across re-registration.
- Confusing UX in the manual remap step when no unclaimed devices are available to relink to
  (previously showed an empty form with only a Submit button); now aborts with a clear translated
  message instead.

## [1.1.1] - 2026-07-05

### Added

- MIT license.

## [1.1.0] - 2026-06-02

### Added

- `PaperlessWifiRssiSensor` and `PaperlessOrientationSensor` diagnostic sensors, sourced from the
  latest polled device "activate" event.

### Fixed

- `ValueError: too many values to unpack` from defensive identifier-tuple unpacking, discovered in
  beta testing.
- Handling of a `null` `iotDevice`/`deviceStatus` in the API ping response.

## [1.0.2] - 2026-06-01

### Added

- Device event polling via `GET /devices/events/{deviceId}`: new `paperlesspaper_device_woke_up`
  and `paperlesspaper_device_state_changed` events (with logbook Activity-timeline entries), fired
  in chronological order after each coordinator poll.

### Fixed

- Race condition in `upload_random_image`: concurrent automations firing simultaneously could both
  read a stale rotation history and pick the same image. History read/write is now wrapped in an
  `asyncio.Lock` per config entry.

## [1.0.1] - 2026-05-18

### Added

- CI: HACS validation, `hassfest`, and Ruff lint GitHub Actions workflows; bug report and feature
  request issue templates; `brands/icon.png` for HACS Default Store submission.

### Changed

- First stable release — beta status removed; CI badges added to the README.

## [0.3.1] - 2026-05-12

### Fixed

- `KeyError` in the config flow when an organization has no `name` set in the paperlesspaper API
  (the field is optional) — falls back to a random HA-compatible display name.

## [0.3.0] - 2026-05-11

### Added

- `upload_random_image` action: picks a random image from a media-source directory, tracks
  per-(device, directory) rotation history to avoid repeats until the cycle resets, excludes the
  image currently shown on any other device, self-heals against media library changes, and shows a
  persistent HA notification when the directory is unreachable.
- Retry logic with exponential backoff for transient upload and coordinator-fetch errors
  (HTTP 408/429/502/503/504, connection errors); honors the HTTP `Retry-After` response header when
  present.
- `paperlesspaper_image_uploaded` event (+ logbook Activity-timeline entry) fired after every
  upload attempt (success, skipped, or failed), usable as an automation trigger.
- Options Flow: conditional checkbox to reset the `upload_random_image` rotation history across all
  devices of the config entry (only shown once history data exists).

### Changed

- HEIC/HEIF files are excluded from the `upload_random_image` candidate pool and the
  `upload_image` Media Picker MIME whitelist — the API returns HTTP 502 for these instead of a
  clean 415, burning all retry attempts before failing.

### Removed

- **BREAKING:** `PaperlessResetRandomHistoryButton` — the per-device reset button was removed; the
  reset function moved to the Options Flow as a global operation covering all devices of the
  config entry at once. Automations referencing the old button entity will break.

### Fixed

- Unnecessary integration reloads: the options update listener previously reloaded on every
  `async_update_entry` call, including routine data writes, briefly flipping every sensor to
  "unknown" on each successful upload. It now only reloads when options actually changed.

## [0.2.5] - 2026-04-24

### Added

- `upload_image` action: new `reuse_existing_paper` option (default `true`). When set to `false`,
  a new paper is created via the API before the upload instead of reusing the stored paper ID.

## [0.2.4] - 2026-04-20

### Fixed

- UTC timestamp handling: timestamps are now returned as timezone-aware `datetime` objects instead
  of ISO strings, fixing incorrect local-time display caused by `fromisoformat()` silently
  dropping the timezone offset on older Python versions.

## [0.2.3] - 2026-04-20

### Changed

- **BREAKING:** The config flow's devices step now shows a plain summary screen instead of a
  multi-select checkbox list — the config entry always covers *all* devices in the organization.
  Per-device selective inclusion is no longer supported.
- `sleep_time_predict` sensor marked diagnostic and disabled by default; `sleep_time` sensor is no
  longer diagnostic; `next_device_sync` relabeled from "Next Sync" to "Update Interval" (EN) /
  "Aktualisierungsintervall" (DE) to reflect that it describes the device's periodic wake interval,
  not a one-time sync event.

### Fixed

- Restored missing translations and corrected sensor labels.

## [0.2.2] - 2026-04-16

### Fixed

- API base URL updated; submit button label fixed in the English translation file.

## [0.2.1] - 2026-04-13

### Added

- `async_step_reconfigure`: change the API key and/or organization for an existing config entry
  without deleting and re-adding the integration.
- Organization selection is now always shown (even for a single org), and a new devices
  confirmation step lets the user review discovered devices before the entry is created; aborts
  with a dedicated error when no devices are found in the selected organization.

## [0.2.0] - 2026-04-11

### Added

- Dynamic entity discovery: entities for devices added after initial setup are picked up by a
  coordinator listener without requiring a Home Assistant restart. (Devices removed from the API
  are not auto-removed — their entities remain and become unavailable.)

### Changed

- Config flow devices step replaced the single radio selector with a multi-select checkbox list.

## [0.1.9] - 2026-04-11

### Fixed

- Sensor state values appearing in English regardless of the configured non-English language.

## [0.1.8] - 2026-04-11

### Added

- Swedish (`sv`) and French (`fr`) translations, with wording aligned to the paperlesspaper
  app/web frontend.

## [0.1.7] - 2026-04-09

### Fixed

- Localized Options Flow validation errors by replacing the voluptuous `Range` validator with
  manual validation.

## [0.1.6] - 2026-04-09

### Fixed

- Sensor updates not appearing reliably: introduced `PaperlessBaseSensor`/`PaperlessBaseBinarySensor`
  base classes with `_handle_coordinator_update` to ensure the HA state machine updates on every
  coordinator poll cycle.

## [0.1.5] - 2026-04-08

### Changed

- `PaperlessPictureSyncedSensor` moved from a regular sensor to a binary sensor; entity categories
  added across sensors.

## [0.1.4] - 2026-04-08

### Changed

- Battery sensor split into two: `PaperlessBatLevelSensor` (percentage) and
  `PaperlessBatVoltageSensor` (raw voltage).

## [0.1.3] - 2026-04-08

### Removed

- Unused `POLLING_INTERVAL` constant.

### Fixed

- Resolved `hassfest` validation errors.
- Python 2-style exception syntax (`except A, B`) corrected to Python 3 syntax
  (`except (A, B)`).

## [0.1.2] - 2026-04-07

### Added

- Brand icons (`icon.png` 256×256, `icon@2x.png` 512×512).

### Changed

- Minimum supported Home Assistant version set to 2026.3, required for brand icon support.

## [0.1.1] - 2026-04-07

### Added

- Service translations (English/German).

### Fixed

- Integration label.

## [0.1.0] - 2026-03-30

### Added

- Initial working integration.
- Device sensors: battery, next sync, sleep time, update pending.
- Reboot and reset buttons.
- Configurable polling interval via the Options Flow, with auto-reload on change.
- German and English translations, including entity translations.
- Media source picker for the `upload_image` action, supporting `media-source://` and `http://`
  URLs as well as local files.

[2.1.0]: https://github.com/djiwondee/paperlesspaper-ha/compare/v2.0.1...HEAD
[2.0.1]: https://github.com/djiwondee/paperlesspaper-ha/compare/v1.2.0b1...v2.0.1
[1.2.0]: https://github.com/djiwondee/paperlesspaper-ha/compare/v1.1.1...v1.2.0b1
[1.1.1]: https://github.com/djiwondee/paperlesspaper-ha/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/djiwondee/paperlesspaper-ha/compare/v1.0.1...v1.1.0
[1.0.2]: https://github.com/djiwondee/paperlesspaper-ha/compare/v1.0.1...v1.1.0
[1.0.1]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.3.1...v1.0.1
[0.3.1]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.3.0...v0.3.1
[0.3.0]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.2.5...v0.3.0
[0.2.5]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.2.4...v0.2.5
[0.2.4]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.2.3...v0.2.4
[0.2.3]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.2.2...v0.2.3
[0.2.2]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.9...v0.2.1
[0.2.0]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.9...v0.2.1
[0.1.9]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.8...v0.1.9
[0.1.8]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.7...v0.1.8
[0.1.7]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.5...v0.1.7
[0.1.6]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.5...v0.1.7
[0.1.5]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.2...v0.1.5
[0.1.4]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.2...v0.1.5
[0.1.3]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.2...v0.1.5
[0.1.2]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.0...v0.1.2
[0.1.1]: https://github.com/djiwondee/paperlesspaper-ha/compare/v0.1.0...v0.1.2
[0.1.0]: https://github.com/djiwondee/paperlesspaper-ha/releases/tag/v0.1.0
