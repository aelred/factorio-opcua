#!/usr/bin/env bash
# Start (or restart) the local Factorio dev server with the current mod sources.
# Usage: [FACTORIO_ADMINS=you] [DLC_SPACE_AGE=true] scripts/dev-server.sh [up|down|logs]  (default: up)
# The RCON password is written to .dev/factorio/config/rconpw on first start.
set -euo pipefail
cd "$(dirname "$0")/.."

data=.dev/factorio
mkdir -p "$data/mods" "$data/config"
rm -rf "$data/mods/opc-io"
cp -r mod/opc-io "$data/mods/opc-io"

# Admins (can use /c, /editor and /cheat): FACTORIO_ADMINS="name1,name2", using
# your Factorio username. Unset leaves the current admin list alone.
if [[ -n "${FACTORIO_ADMINS:-}" ]]; then
  python3 -c 'import json, sys; print(json.dumps([n.strip() for n in sys.argv[1].split(",") if n.strip()]))' \
    "$FACTORIO_ADMINS" > "$data/config/server-adminlist.json"
fi

# Server settings: LAN-only, no account check. Override with SERVER_SETTINGS=path.
SERVER_SETTINGS="${SERVER_SETTINGS:-docker/server-settings.dev.json}"
if [[ -n "$SERVER_SETTINGS" ]]; then
  cp "$SERVER_SETTINGS" "$data/config/server-settings.json"
fi

compose=(docker compose -f docker/compose.yml)
case "${1:-up}" in
  # --wait returns once the healthcheck passes: RCON is up and opc-io answers.
  up)   "${compose[@]}" up -d --force-recreate --wait --wait-timeout 300 ;;
  down) "${compose[@]}" down ;;
  logs) "${compose[@]}" logs -f ;;
  *)    echo "usage: $0 [up|down|logs]" >&2; exit 2 ;;
esac
