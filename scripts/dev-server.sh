#!/usr/bin/env bash
# Start (or restart) the local Factorio dev server with the current mod sources.
# Usage: scripts/dev-server.sh [up|down|logs]  (default: up)
# The RCON password is written to .dev/factorio/config/rconpw on first start.
set -euo pipefail
cd "$(dirname "$0")/.."

data=.dev/factorio
mkdir -p "$data/mods" "$data/config"
rm -rf "$data/mods/opc-io"
cp -r mod/opc-io "$data/mods/opc-io"

# Server settings: LAN-only, no account check. Override with SERVER_SETTINGS=path.
SERVER_SETTINGS="${SERVER_SETTINGS:-docker/server-settings.dev.json}"
if [[ -n "$SERVER_SETTINGS" ]]; then
  cp "$SERVER_SETTINGS" "$data/config/server-settings.json"
fi

compose=(docker compose -f docker/compose.yml)
case "${1:-up}" in
  up)   "${compose[@]}" up -d --force-recreate ;;
  down) "${compose[@]}" down ;;
  logs) "${compose[@]}" logs -f ;;
  *)    echo "usage: $0 [up|down|logs]" >&2; exit 2 ;;
esac
