# factorio-opc

Factorio 2.0 mod (`mod/opc-io`, Lua) and Python OPC UA bridge (`bridge/`, asyncua) talking over RCON.
Design and milestones are in PLAN.md, protocol in docs/protocol.md, and the OPC address space in docs/address-space.md.

## Working on it
- Tests: `.venv/bin/pytest`. Integration tests in `mod/tests/integration` need the dev server
  (`scripts/dev-server.sh up`) and are skipped without it.
- The mod's pure Lua modules (`lib/signals.lua`, `names.lua`, `poll.lua`) are unit tested from Python via lupa (Lua 5.2).
- Every RCON command handler must go through `rcon_only` in `lib/api.lua`, and event handlers through `safe` in
  `control.lua`: an uncaught Lua error stops a multiplayer server.
- Bump `mod/opc-io/info.json` version when control-stage data changes (on_configuration_changed migrates storage),
  and `api.PROTO` plus `game.PROTO` in the bridge when the RCON protocol changes.

## Manual checks (docs/manual-test-checklist.md)
- The user is on macOS and tests with FreeOpcUa **opcua-client** (not UaExpert). Write all client steps for its UI:
  Connect/Disconnect buttons, "Subscribe to data change" → Subscriptions pane, Attributes pane to write a Value,
  right-click "Call" for methods, "Subscribe to events" on Objects/Server → Events pane (shows Message only).
- opcua-client caches the tree and ignores model change events: refreshing means Disconnect then Connect.
- Things only a game client can check (GUI, graphics, blueprints, paste) go on that checklist too.
