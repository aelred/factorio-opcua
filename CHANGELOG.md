# Changelog

The mod (opc-io) and the bridge (factorio-opc) share one version number.

## 0.6.0

First release.

**Mod (opc-io), RCON protocol 1:**
- **Entities:** OPC Writer and OPC Reader combinators, unlocked by Circuit
  network.
- **Tag names:** every reader and writer has a tag name, set in its panel,
  kept in blueprints (taken names get a `-2` suffix), and renameable through
  `remote.call("opc-io", "rename", ...)`.
- **RCON commands:** `/opc_hello`, `/opc_browse`, `/opc_poll`, which
  returns only changes after a session's first poll, and `/opc_write`. Errors come back
  as JSON and never stop the server.
- **Quality:** quality signals are supported with Space Age.

**Bridge (factorio-opc):**
- **Address space:** an OPC UA server with readers (Red/Green/Total), writers
  (writable signals, plus `SetSignals` and `ClearAll`), and `Status/`
  metrics.
- **Polling:** change-only polling at 1–30 Hz, with reconnect and resync.
  Stale values are marked Uncertain.
- **Model changes:** GeneralModelChangeEvents for tag changes; removed tags
  report `BadNodeIdUnknown`.
- **Security:** none/sign/sign_encrypt endpoints with a self-signed
  certificate, users with read or write roles, and a refusal to expose
  unencrypted anonymous access to the network.
- **Logging:** a write audit log, and JSON logs.
- **Commands:** `factorio-opc hash-password`.
- **Docker:** a Docker image, and `deploy/compose.yml` running Factorio with
  the bridge.
