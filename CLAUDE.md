# factorio-opc

Factorio 2.0 mod (`mod/opc-io`, Lua) and Python OPC UA bridge (`bridge/`, asyncua) talking over RCON.
The RCON protocol is in docs/protocol.md, the OPC address space in docs/address-space.md,
security in docs/security.md, Docker in docs/docker.md and releases in docs/releasing.md.

## Working on it
- Tests: `.venv/bin/pytest`. Integration tests in `mod/tests/integration` need the dev server
  (`scripts/dev-server.sh up`) and are skipped without it.
- The mod's pure Lua modules (`lib/signals.lua`, `names.lua`, `poll.lua`) are unit tested from Python via lupa (Lua 5.2).
- Every RCON command handler must go through `rcon_only` in `lib/api.lua`, and event handlers through `safe` in
  `control.lua`: an uncaught Lua error stops a multiplayer server.
- Bridge tests and scripts that start a Bridge should pass `security=["none"]` (or a tmp `pki_dir`) so no
  certificate is written to ~/.factorio-opc.
- The mod and bridge share one version (info.json, bridge/pyproject.toml, factorio_opc/__init__.py); bump all three
  together (scripts/check-version.py checks them) and add a CHANGELOG.md section. Bump `api.PROTO` plus `game.PROTO`
  in the bridge when the RCON protocol changes. Releases: docs/releasing.md (tag vX.Y.Z; don't tag without asking).
- bridge/LICENSE is a copy of LICENSE (CI compares them).

## Manual checks
When something needs checking by hand (GUI, graphics, blueprints, paste, or an OPC client), give steps in chat.
- Write OPC client steps for FreeOpcUa **opcua-client 1.0.1**, the client the docs recommend (Python 3.14; 1.0.2's
  right-click Call crashes with a missing TreeWidget.get_parent_node). Its UI: Connect button → "Connect to server"
  dialog (security mode radio, endpoint list, Anonymous/Username login), Disconnect button, "Subscribe to data
  change" → Subscriptions pane, Attributes pane to write a Value, right-click "Call" for methods, "Subscribe to
  events" on Objects/Server → Events pane (shows Message only).
- opcua-client caches the tree and ignores model change events: refreshing means Disconnect then Connect.
- Encrypted connections need opcua-client's own certificate first: Settings → Client Application Certificate →
  "Generate self-signed certificate". Both policies work.
