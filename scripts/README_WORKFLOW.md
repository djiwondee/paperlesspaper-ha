# Development Workflow

This document describes the standard development workflow for the
**paperlesspaper** Home Assistant integration.

---

## Overview

All development happens in the **ha-core** dev container environment.
The **paperlesspaper-ha** repository is only touched when syncing finished,
tested work back for git commit and push.

```
paperlesspaper-ha (GitHub)
        │
        │  sync_from_release.sh  (before dev session)
        ▼
ha-core/config/custom_components/paperlesspaper/   ← develop & test here
        │
        │  sync_to_release.sh  (after successful test)
        ▼
paperlesspaper-ha (local) → git commit → git push → GitHub
```

---

## Workspace Paths

| Location | Path |
|---|---|
| Release repo | `/workspaces/paperlesspaper-ha` |
| HA dev environment | `/workspaces/ha-core/config/custom_components/paperlesspaper` |
| These scripts | `/workspaces/paperlesspaper-ha/scripts/` |

---

## Step-by-Step Workflow

### 1. Start of a development session

Pull the latest state from GitHub into ha-core:

```bash
# In paperlesspaper-ha: make sure you are on main and up to date
cd /workspaces/paperlesspaper-ha
git checkout main
git pull

# Sync into ha-core
./scripts/sync_from_release.sh
```

### 2. Develop in ha-core

Make all changes in:
```
/workspaces/ha-core/config/custom_components/paperlesspaper/
```

Restart Home Assistant after changes:
```bash
cd /workspaces/ha-core
hass -c config
```

Run hassfest validation:
```bash
cd /workspaces/ha-core
python -m script.hassfest --integration-path config/custom_components/paperlesspaper
```

### 3. Sync back and push to GitHub

Once development and testing are complete:

```bash
cd /workspaces/paperlesspaper-ha

# Sync with a new branch (recommended)
./scripts/sync_to_release.sh -b feature/your-feature-name

# Review, commit and push
git diff
git add -A
git commit -m "feat: describe your change"
git push origin HEAD
```

---

## Coding Standards

- All code is written in **English**
- All variable names are in **English**
- All user-facing labels and identifiers use the HA **translation/localization
  mechanism** — no hardcoded UI strings
- Supported GUI languages: **English (en)** and **German (de)**
- Code is **adequately commented**
- Changed modules carry a **change history comment** at the top of the file

### Change history comment format

```python
# =============================================================================
# CHANGE HISTORY
# 2026-04-08  0.1.3  Fixed syntax errors in sensor.py (ValueError/TypeError)
# =============================================================================
```

---

## Branch Naming Conventions

| Type | Pattern | Example |
|---|---|---|
| Feature | `feature/<short-description>` | `feature/add-rssi-sensor` |
| Bug fix | `fix/<short-description>` | `fix/syntax-error-sensor` |
| Refactor | `refactor/<short-description>` | `refactor/coordinator-cleanup` |
| Translation | `i18n/<short-description>` | `i18n/add-french` |

---

## Scripts Reference

### `sync_from_release.sh`

Copies the integration from `paperlesspaper-ha` into `ha-core`.
Run this at the **start** of every development session.

```bash
./scripts/sync_from_release.sh
```

### `sync_to_release.sh`

Copies the integration from `ha-core` back into `paperlesspaper-ha`.
Optionally creates a new git branch. Run this **after** successful testing.

```bash
./scripts/sync_to_release.sh                        # no branch
./scripts/sync_to_release.sh -b feature/my-feature  # with new branch
```
