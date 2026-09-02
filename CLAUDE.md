# CLAUDE.md — paperlesspaper-ha

Persistent project context for Claude Code. Read this file first in every session.

## Project Purpose

- `paperlesspaper-ha` is a HACS-compatible Home Assistant custom integration.
- Connects HA to the **paperlesspaper** ePaper picture frame ecosystem via the cloud API
  `https://api.paperlesspaper.de/v1` (auth header: `x-api-key`).
- Maintainer: Roland (GitHub: `djiwondee`). Roland has direct contact with the paperlesspaper
  manufacturer's dev team.
- **No relation to Paperless-ngx** (the document management system). Never research, cite, or
  reference Paperless-ngx sources — they are irrelevant and confusing false positives.
- Accepted into the official HACS default store. Current stable release: **v2.0.1**.

## Session Workflow (applies to every new chat/session on this project)

These rules govern how any assistant (Claude in chat, or Claude Code) operates at the start of,
and during, a work session on this repo — each session typically results in changes to the main
codebase and must not proceed carelessly.

1. **At the start of every new chat/session, read the underlying GitHub repository first**, not
   just this file from memory. `CLAUDE.md` reflects the state as of its last edit, but the actual
   repo may have moved on since (other commits, manual edits, a previous session's uncommitted
   work). In chat sessions, use `project_knowledge_search` first, then fetch files via
   `https://raw.githubusercontent.com/djiwondee/paperlesspaper-ha/main/[path]` or the repo page —
   assume `raw.githubusercontent.com`/`github.com` are fetchable, this is a public repo. In a
   Claude Code session inside the dev container, read the live checkout directly (`git log`,
   `git status`, `git diff`) instead of assuming any prior description is current.
2. **Explicitly verify against actual current file contents** — don't rely solely on what's
   described in this document or in prior chat history.
3. **Before making any code change — feature or bugfix — propose a plan first** and get it
   confirmed before touching code.
4. **For every change, propose one or more solution options and explicitly ask which option to
   implement** before writing code — do not silently pick one approach and implement it. This
   applies even when only one option seems reasonable: state it as a proposal and wait for
   confirmation rather than assuming approval.
5. **Always deliver complete corrected files**, never patches/diffs, when presenting finished code.
6. **Run `diff`** to verify file changes before presenting work as complete.
7. **After completing a feature, bugfix, or release, always**:
   - Remind Roland to check that the `hassfest` GitHub Action passed after pushing — **not** to
     run `script.hassfest` locally (see Development Workflow below for why).
   - Propose an English-language commit message summarizing the change.

## Coding Standards

- Language: Python, must satisfy Home Assistant custom integration standards and HACS standards.
- All identifiers, variable names, function names, and code comments: **English only**.
- Code must be **sufficiently commented in English**.
- Every changed module gets a **changelog comment block at the top of the file** describing what
  changed (skip this for lint-only fixes).
- GUI-facing labels/strings must use HA's translation/localization keys — never hardcoded
  user-facing text.
- Minimum supported GUI languages: **English and German** (project actually ships 7: en, de, fr,
  sv, nl, et, cs — keep all 7 in sync when touching translation files).
- Ruff-clean codebase. Scoped `pyproject.toml` lives in
  `custom_components/paperlesspaper/pyproject.toml`:
  - No `known-first-party = ["homeassistant"]` in the scoped config.
  - `target-version = "py313"` pinned due to Ruff bug astral-sh/ruff#24041 (recheck before
    bumping to py314).
  - `lint.yml` CI pins Ruff version and runs on Python 3.14.
  - **Always validate against CI as the final gate**, even though local `ruff check
    custom_components/` (see Development Workflow below) should now match CI closely, since the
    new single-container setup no longer has a separate `ha-core` `pyproject.toml` on the path to
    cause import-order drift the way the old dual-workspace setup did.

## Development Workflow

- Single dev container defined in `.devcontainer/devcontainer.json`: base image
  `mcr.microsoft.com/devcontainers/python:1-3.13-bookworm`, `postCreateCommand: scripts/setup`,
  port `8123` forwarded (label "Home Assistant", `onAutoForward: notify`), VS Code extensions
  `ms-python.python`, `ms-python.vscode-pylance`, `charliermarsh.ruff`, `anthropic.claude-code`,
  `redhat.vscode-yaml`, `esbenp.prettier-vscode`, interpreter pinned to `/usr/local/bin/python`,
  `files.eol: "\n"`, `editor.formatOnSave: true`, `remoteUser: vscode`. `custom_components` is
  live-mounted into this container; `scripts/develop` symlinks it into
  `config/custom_components/paperlesspaper` so HA Core discovers it — confirmed working, see
  Setup status below.
  A lightweight non-VS Code alternative is also available via `docker-compose.yml` at the repo
  root (`docker compose up`) — same base image, installs `homeassistant`, symlinks
  `custom_components/paperlesspaper`, and starts `hass --config /workspace/config --debug`
  directly, for anyone who doesn't want the full VS Code devcontainer experience.
  This replaces the earlier two-workspace (`ha-core` + `paperlesspaper-ha`) setup with manual
  `sync_to_release.sh` / `sync_from_release.sh` scripts — those scripts and the dual-workspace
  layout have been removed now that the single-container workflow is confirmed working
  end-to-end.
- Claude Code runs directly in the container terminal and has automatic access to this file plus
  the full codebase — no more manually copying context out of a chat/project session.
- **Credentials for live tests against the real gateway**: never commit credentials to any file.
  A `.env`/`.env.example`-based approach was considered and is **obsolete for this project** —
  do not reintroduce it. Until an alternative mechanism is defined, provide credentials via
  environment variables set directly inside the dev container session (not persisted to disk in
  the repo). Ask Roland if a concrete mechanism needs to be documented here.
- **`hassfest` cannot be run locally in this dev container.** `script.hassfest` only exists inside
  a full `home-assistant/core` git checkout, not in the `homeassistant` PyPI package this
  container installs — attempting it locally fails with `ModuleNotFoundError: No module named
  'script'`. Rely on the GitHub Action instead: `.github/workflows/validate.yml` runs the
  equivalent `home-assistant/actions/hassfest` action on every push. Check the "Actions" tab on
  GitHub after pushing.
- `.github/workflows/lint.yml` runs `ruff check` against `custom_components/` only — scoped to
  shipped integration code. No `tests/` folder is planned; `scripts/` holds dev-only helpers never
  loaded by Home Assistant or checked by `hassfest`/HACS (loose style there, e.g. broad
  `except Exception`, is fine and not worth linting).
- Ruff **can and should be run locally before pushing** — it has no dependency on a full Home
  Assistant checkout: `pip install ruff && ruff check custom_components/`.
- **`BLE001`** is active in Ruff's default rule set — flagged only when a broad `except Exception`
  is the *sole* handler in its `try` (no more specific `except` before it) and doesn't re-raise.
  `config_flow.py`'s `validate_input()` ping-fallback carries a justified `# noqa: BLE001` by
  design, so setup never blocks on a diagnostic `/api/ping` hiccup — don't remove it, and don't add
  new bare `# noqa: BLE001` elsewhere without confirming Ruff actually flags that line.
- `pre-commit` hook `no-commit-to-branch` blocks direct commits to `dev`-style protected branches —
  use feature branches. Icon assets (`brand/` folder: `icon.png`, `logo.png`) live inside
  `custom_components/paperlesspaper/` — `home-assistant/brands` no longer accepts custom
  integration PRs since HA 2026.3.0, so this in-folder approach is the current correct pattern.

### Setup status

- `.devcontainer/devcontainer.json` exists and is the primary dev entry point (specs captured
  above).
- `scripts/setup` (devcontainer `postCreateCommand`): installs `ffmpeg` + `libturbojpeg0` via apt
  (valid Debian bookworm packages — confirmed), installs `homeassistant` via pip (**unpinned —
  always pulls latest, no version pin against the README's stated minimum of HA 2026.3**),
  installs `requirements_test.txt` (now present at repo root), and idempotently writes a minimal
  `config/configuration.yaml` (deliberately omits `default_config:` to avoid the camera/streaming
  stack). `config/` is gitignored — it's generated at setup time, not committed.
- **Confirmed**: `scripts/develop` symlinks `custom_components/paperlesspaper` into
  `config/custom_components/paperlesspaper` (see `scripts/develop`) before starting
  `hass --config config --debug` — Home Assistant does discover the integration this way.
- Minor doc/config mismatch worth a look after first boot: the comment on the `ffmpeg`/
  `libturbojpeg0` install cites HA-onboarding defaults (Met weather, Google Translate TTS), which
  don't typically need those libs — harmless either way, but confirm they're actually exercised
  before treating them as required.
- `.env.example` is **not needed** — deliberately not part of this project.
- No `tests/` folder — deliberately not planned for this project.
- Already present and confirmed working: `.github/workflows/validate.yml`,
  `.github/workflows/lint.yml`. The legacy dual-workspace scripts
  (`sync_to_release.sh`/`sync_from_release.sh`/`README_WORKFLOW.md`) have been removed — the
  single-container devcontainer workflow (plus the `docker-compose.yml` alternative) is now the
  only supported dev path.

## Key Technical Facts (do not re-derive, do not re-break)

- Use `device["id"]` (MongoDB ObjectId) as the URL parameter for API endpoints (e.g. events) —
  **not** `deviceId`. This has been a repeated mistake.
- `deviceId` (e.g. `epd7-b43a459a7fe4`) is the stable hardware ID across device re-registration —
  confirmed via live API testing, underlies the orphaned-device fix in v2.0.1.
- `POST /papers/` returns HTTP 500 even on success (known v1 API bug) — body still contains the
  created paper ID; do not treat 500 as fatal here.
- `GET /devices/events/:deviceId` requires `DateStart`, `DateEnd`, and `TypeFilter` all provided;
  response wrapped under a `"message"` key; timestamps must be **second-granular ISO format** to
  avoid duplicate event firing.
- `meta` key may be absent on freshly re-registered devices — always guard with `.get()` / `or {}`.
- `DeviceInfo.serial_number` must come from `deviceId` — there is no `serial_number` field in the
  API.
- HA entity translations follow the **system** language (Settings → System → General → Language),
  not the user profile language.
- Options Flow reload listener: compare an **options snapshot**, don't hook
  `add_update_listener(async_reload_entry)` — that fires on every `async_update_entry` call
  including routine data writes, causing spurious reloads.
- Boolean service parameter UI quirk: `default: true` renders a single toggle in the HA frontend;
  `default: false` renders both a checkbox and a toggle simultaneously — prefer `default: true`
  semantics where possible.
- `translate_key` values `"orientation"` and `"frame_orientation"` collide with HA internals — use
  an `_attr_name` fallback instead.
- HACS icon shows correctly in HA Settings → Devices & Services but not in HACS's own UI — this is
  a known HACS-side bug (hacs/integration#5171, #5223), not something to "fix" in this repo.

## Current State (v2.0.1)

- Dynamic device discovery + auto re-linking via stable `deviceId`.
- `OrphanedDeviceRepairFlow` (Delete / manual Relink) + `async_remove_config_entry_device`.
- `upload_image` action (`reuse_existing_paper`, default `true`) with coordinator refresh; paper
  creation always forced on first setup.
- `upload_random_image` action: media-source directory, per-(device, directory) rotation history,
  cross-device duplicate avoidance, `asyncio.Lock`, retry/backoff, HEIC/HEIF excluded; history
  reset available in Options Flow.
- Event firing: `paperlesspaper_image_uploaded` (+ logbook), plus polled
  `paperlesspaper_device_woke_up` / `paperlesspaper_device_state_changed` (sliding-window
  `DateStart`/`DateEnd` to avoid dupes).
- Sensors: battery, next sync, sleep time (+ predict diagnostic), wifi signal, frame orientation
  (buggy on firmware 3.0.14 — see below), picture synced, last wakeup, wake reason, last update
  state. Binary sensors: reachable, update pending. Buttons: reboot, reset sensors.
- Full Repairs flow, reconfigure flow, complete 7-language translation coverage.

## Open Issues / On the Horizon

- **Issue #35** (contributor itchensen): enrich `_fetch_media_source()` errors with
  `media_content_id`, fire `paperlesspaper_image_uploaded` with `status: failed` on fetch failures
  in `upload_image`/`upload_random_image`. Assessed low-risk, technically sound. Queued pending
  review of event payload shape, logging conventions, translations.
- **Firmware 3.0.14 orientation bug**: `_ORIENTATION_MAP` in `sensor.py` doesn't handle the new
  4-state encoding — orient values 0/1/2 surface as `unknown`. Preferred fix (Option B): collapse
  to coarse portrait/landscape states, expose raw value via
  `extra_state_attributes["orientation_raw"]`. Blocked on manufacturer documentation + Roland
  getting a 3.0.14 device.
- Future `paperlesspaper_local` integration (separate, offline firmware support) — prerequisites:
  stable offline firmware, reliable multi-frame local discovery (mDNS), documented local device
  API. Hybrid/middleware designs explicitly ruled out.
- Recheck astral-sh/ruff#24041 before bumping `target-version` to `py314`.
- Optional: engage on hacs/integration#5171/#5223, or add a README note about the HACS icon
  display bug.

## Communication Style

- GitHub issue replies: professional, first-person, collegial maintainer voice — concise, direct,
  not AI-structured or overly formal. Apply the `humanizer` skill if asked.
