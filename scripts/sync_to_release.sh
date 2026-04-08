#!/usr/bin/env bash
# =============================================================================
# sync_to_release.sh
# -----------------------------------------------------------------------------
# Syncs the paperlesspaper integration from the ha-core development environment
# back into the release repository, ready for git commit and push.
#
# Usage:
#   ./scripts/sync_to_release.sh [-b <branch-name>]
#
# Options:
#   -b <branch-name>   Create and switch to a new git branch before syncing.
#                      Recommended for every feature or fix.
#
# Examples:
#   ./scripts/sync_to_release.sh
#   ./scripts/sync_to_release.sh -b feature/add-battery-sensor
#   ./scripts/sync_to_release.sh -b fix/syntax-error-sensor
#
# Run this AFTER successful development and hassfest validation in ha-core.
#
# Source:      /workspaces/ha-core/config/custom_components/paperlesspaper/
# Destination: /workspaces/paperlesspaper-ha/custom_components/paperlesspaper/
# =============================================================================

set -euo pipefail

# --- Paths -------------------------------------------------------------------
SRC="/workspaces/ha-core/config/custom_components/paperlesspaper"
DST="/workspaces/paperlesspaper-ha/custom_components/paperlesspaper"
REPO="/workspaces/paperlesspaper-ha"

# --- Arguments ---------------------------------------------------------------
BRANCH=""
while getopts "b:" opt; do
  case $opt in
    b) BRANCH="$OPTARG" ;;
    *) echo "Usage: $0 [-b <branch-name>]"; exit 1 ;;
  esac
done

# --- Validation --------------------------------------------------------------
if [ ! -d "$SRC" ]; then
  echo "ERROR: Source not found: $SRC"
  echo "       Run development in ha-core first."
  exit 1
fi

if [ ! -d "$REPO/.git" ]; then
  echo "ERROR: paperlesspaper-ha is not a git repository: $REPO"
  exit 1
fi

# --- Hassfest reminder -------------------------------------------------------
echo "Pre-flight checklist:"
echo "  [ ] hassfest validation passed in ha-core?"
echo "  [ ] Manually tested in HA (restart + entity check)?"
echo ""
read -r -p "Continue? [y/N] " confirm
if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
  echo "Aborted."
  exit 0
fi

# --- Optional: create new git branch -----------------------------------------
if [ -n "$BRANCH" ]; then
  echo ""
  echo "Creating branch: $BRANCH"
  git -C "$REPO" checkout -b "$BRANCH"
fi

# --- Sync --------------------------------------------------------------------
echo ""
echo "Syncing: ha-core → paperlesspaper-ha"
echo "  From: $SRC"
echo "  To:   $DST"
echo ""

rm -rf "$DST"
cp -r "$SRC" "$DST"

# --- Summary -----------------------------------------------------------------
FILE_COUNT=$(find "$DST" -type f | wc -l | tr -d ' ')
echo "Done. $FILE_COUNT file(s) copied to paperlesspaper-ha."
echo ""

# Show git status
echo "Git status:"
git -C "$REPO" status --short
echo ""
echo "Next steps:"
echo "  1. Review changes:  git -C $REPO diff"
echo "  2. Stage all:       git -C $REPO add -A"
echo "  3. Commit:          git -C $REPO commit -m 'your message'"
echo "  4. Push:            git -C $REPO push origin HEAD"
