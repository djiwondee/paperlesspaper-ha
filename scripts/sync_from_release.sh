#!/usr/bin/env bash
# =============================================================================
# sync_from_release.sh
# -----------------------------------------------------------------------------
# Syncs the paperlesspaper integration from the release repository into the
# ha-core development environment.
#
# Usage:
#   ./scripts/sync_from_release.sh
#
# Run this BEFORE starting any development session to ensure ha-core reflects
# the current GitHub release state.
#
# Source:      /workspaces/paperlesspaper-ha/custom_components/paperlesspaper/
# Destination: /workspaces/ha-core/config/custom_components/paperlesspaper/
# =============================================================================

set -euo pipefail

# --- Paths -------------------------------------------------------------------
SRC="/workspaces/paperlesspaper-ha/custom_components/paperlesspaper"
DST="/workspaces/ha-core/config/custom_components/paperlesspaper"

# --- Validation --------------------------------------------------------------
if [ ! -d "$SRC" ]; then
  echo "ERROR: Source not found: $SRC"
  echo "       Make sure the paperlesspaper-ha workspace is available."
  exit 1
fi

if [ ! -d "/workspaces/ha-core/config" ]; then
  echo "ERROR: ha-core config directory not found."
  echo "       Make sure the ha-core dev container is set up correctly."
  exit 1
fi

# --- Sync --------------------------------------------------------------------
echo "Syncing: paperlesspaper-ha → ha-core"
echo "  From: $SRC"
echo "  To:   $DST"
echo ""

# Remove destination first to catch deleted files
rm -rf "$DST"
cp -r "$SRC" "$DST"

# --- Summary -----------------------------------------------------------------
FILE_COUNT=$(find "$DST" -type f | wc -l | tr -d ' ')
echo "Done. $FILE_COUNT file(s) copied to ha-core."
echo ""
echo "Next steps:"
echo "  1. Make your changes in $DST"
echo "  2. Test in ha-core (restart HA, run hassfest)"
echo "  3. Run sync_to_release.sh when done"
