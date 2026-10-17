# factorio-opc — Implementation Plan

Goal: let OPC UA clients (UaExpert, Ignition, KEPServerEX, Node-RED, PLCs/SCADA)
read and write Factorio **circuit-network signals** through dedicated in-game
I/O entities. The setup works like PLC I/O cards wired into the factory.

Decisions so far:

| Topic        | Decision                                    |
|--------------|---------------------------------------------|
| Protocol     | OPC UA                                      |
| Data scope   | Circuit-network I/O (reader/writer entities) |
| Hosting      | Factorio headless server with RCON          |
| Bridge       | Python 3.11+ with `asyncua`                 |
| Game version | Factorio 2.0 only (Space Age optional; signals carry quality) |
| Update rate  | 10 Hz default, configurable (`poll_hz` in bridge config) |
| Writes       | Level (latched) values only — no pulse/one-shot writes |
| Servers      | One Factorio server per bridge instance |
| Distribution | GitHub releases (mod zip + Python package), not the mod portal |
| Licence      | MIT |

---

## 1. Architecture

```
 OPC UA clients ──opc.tcp:4840──▶ ┌──────────────────────┐ ──RCON (TCP)──▶ ┌─────────────────────┐
 (UaExpert, Ignition, PLC…)       │  factorio-opc bridge │                 │ Factorio headless   │
                                  │  Python / asyncua    │ ◀─JSON replies─ │  + "opc-io" Lua mod │
                                  └──────────────────────┘                 └─────────────────────┘
```

Why there is a bridge process: Factorio mods run in a sandboxed,
deterministic Lua VM. They cannot open sockets, read files, or spawn
processes. The only supported way in from outside is **RCON**. A mod can
register its own commands (`commands.add_command`) and answer the caller with
`rcon.print`. So the OPC UA server has to run outside the game and talk to
the mod over RCON. Mature tools such as Clusterio work the same way.

Mod-registered commands also **don't disable achievements**, unlike raw
`/c` Lua. They also run inside the lockstep simulation, so they are
multiplayer-safe.

## 2. Component A — Factorio mod (`mod/opc-io`)

### 2.1 Entities
- **OPC Writer** (OPC → game). Based on the `constant-combinator` prototype.
  The bridge sets its output signals through the 2.0 logistic-section API
  (`control_behavior.get_section(1)` with `set_slot` or `filters`).
- **OPC Reader** (game → OPC). Also a constant-combinator prototype, kept
  disabled with no sections by script, so it emits nothing and the values
  it reads are clean. Values
  come from `entity.get_circuit_network(defines.wire_connector_id.circuit_red / circuit_green)`
  and `.signals`. Red and green are reported separately and also summed.
- Item, recipe, technology unlock (or unlocked from the start), and simple
  graphics reused or recoloured from the combinator sprites.

### 2.2 Tag identity
- Each I/O entity gets a **tag name** (for example `smelter_line_1`) that the
  player sets in a small custom GUI. The GUI replaces the default panel
  through `on_gui_opened`.
- The registry lives in `storage.opc` (2.0 renamed `global` to `storage`),
  keyed by tag name, with each entry holding the entity, its kind, and the
  writer's last values.
- Lifecycle events to handle: `on_built_entity`, `on_robot_built_entity`,
  `script_raised_built`, `script_raised_revive`, `on_space_platform_built_entity`,
  `register_on_object_destroyed` for removals, and `on_entity_settings_pasted`.
- Names survive blueprints through `on_player_setup_blueprint` tags (with a
  collision suffix on paste).
- Duplicate names are rejected or auto-suffixed. A
  `storage.opc.model_version` counter is bumped on every add, remove or rename.

### 2.3 RCON command API (all JSON through `helpers.table_to_json` / `json_to_table`)
| Command | Purpose | Reply |
|---|---|---|
| `/opc_hello` | Handshake, protocol version | `{proto, mod_version, tick, model_version}` |
| `/opc_browse` | Full list of tags | `[{name, kind, surface, position}]` |
| `/opc_poll <session> <since_tick>` | Reader values that changed since the last poll in this session | `{tick, model_version, changes:{tag:{sig:val}}, removed:[...]}` |
| `/opc_snapshot` | All current values (on connect or resync) | same shape, full |
| `/opc_write <json>` | `{tag, signals:{sig:val}, mode:"merge"\|"replace"}` | `{ok, error?}` |

- *(As built in M4: `/opc_poll` takes `{session, ack, full}` and returns
  `seq`; see `docs/protocol.md`.)*
- *(As built in M2: `/opc_poll` is deferred to M4; `/opc_snapshot` returns
  red and green separately and the bridge computes Total. Writer values live
  in the combinator itself, not in `storage`. See `docs/protocol.md`.)*
- Signals are keyed as `type/name[/quality]`, for example `item/iron-plate`,
  `virtual/signal-A` and `item/iron-plate/rare`. Values are int32. An absent
  signal means 0, following circuit semantics.
- Delta logic runs in the mod, per bridge session, to keep RCON payloads
  small. The pure Lua functions get unit tests.
- Writers keep their values in `storage`, so they survive save/load and
  bridge restarts.
- Reading happens at poll time (O(readers)), so the mod does no per-tick
  work when nobody is polling. An optional per-tick sampling mode can come
  later if clients need edge or one-tick-pulse capture.

## 3. Component B — Bridge (`bridge/`, Python)

### 3.1 Modules
- `rcon.py` (done in M1): a small asyncio Source-RCON client with auth,
  request IDs and pipelining. Factorio replies with one packet of any size,
  so no reassembly is needed. Reconnects with backoff live in `game.py`.
- `game.py`: a typed wrapper over the mod commands (handshake and version
  check, browse, poll, write), with a serialized command queue because RCON
  is one request at a time.
- `model.py`: builds and syncs the OPC UA address space from browse results
  and `model_version`.
- `server.py`: the asyncua server, the poll loop (`poll_hz`, default 10,
  validated range 1–30). Each cycle pipelines its reads and writes so they
  land in one game tick, and the write handlers.
- `config.py`: TOML config covering the RCON host, port and password, the
  OPC endpoint, `poll_hz`, security policy and users. CLI flags and
  environment variables override the file (for example `--poll-hz 5`).
- CLI: `factorio-opc --config bridge.toml`.

### 3.2 OPC UA address space (namespace `urn:factorio-opc`)
```
Objects/
  Factorio/
    Status/   Connected (Bool), GameTick (UInt64), ModVersion, LastPollLatencyMs
    Readers/
      <tag>/  Red/<sig>, Green/<sig>, Total/<sig>   (Int32, read-only)
              SignalsJson (String)                  (convenience)
    Writers/
      <tag>/  Signals/<sig>  (Int32, writable)
              SetSignals(json)  ClearAll()          (Methods)
```
- Signal nodes are created the first time a signal appears and are then kept
  (value 0) so client subscriptions stay valid. A `GeneralModelChangeEvent`
  fires when nodes are added or removed.
- Writes to `Writers/<tag>/Signals/<sig>` turn into `/opc_write`. *(As
  built: each client write request goes to the game straight away, grouped
  per writer, and the client receives the game's verdict as its status
  code. That proved simpler and more useful than batching per poll cycle.)*
- Quality: while RCON is down, all values keep their last value with
  `Uncertain_NoCommunicationLastUsableValue`. *(As built: SourceTimestamp
  is the poll's receive time; the game tick is in `Status/GameTick`.)*

### 3.3 Security
- Endpoints: `None` for local development only, and
  `Basic256Sha256 Sign&Encrypt` with a generated self-signed certificate as
  the default. Username/password user tokens with a read-only or read-write
  role.
- RCON is plaintext. The bridge should run on the same host or private
  network as the server, and this should be documented clearly.

## 4. Repository layout
```
mod/opc-io/            info.json, data.lua, control.lua, locale/, graphics/, lib/*.lua
mod/tests/             pytest + lupa (Lua 5.2) unit tests; mod/tests/integration against a live server
bridge/factorio_opc/   rcon.py, game.py, model.py, server.py, config.py, __main__.py
bridge/tests/          pytest with a fake RCON server; asyncua client e2e
docker/                compose: factoriotools/factorio headless + bridge
docs/                  setup, address-space reference, protocol spec
```

## 5. Milestones
1. ✅ **Spike (de-risk):** headless server in Docker, a trivial mod command,
   and a Python RCON round-trip; measure latency and the maximum reply size,
   and check behaviour while the server is auto-paused. Done; results in
   `docs/spike-results.md`.
2. ✅ **Mod MVP:** the Writer and Reader entities, the registry, a name GUI,
   and `hello`/`browse`/`snapshot`/`write`. Done; protocol in
   `docs/protocol.md`, and the game-client checklist
   (`docs/manual-test-checklist.md`) passed.
3. ✅ **Bridge MVP:** RCON client, address space from browse, 10 Hz snapshot
   polling, writable writer nodes. Done; see `docs/address-space.md`. The
   UaExpert walkthrough is in `docs/manual-test-checklist.md`.
4. ✅ **Deltas and dynamic model:** `opc_poll` deltas, model-change events,
   rename and remove handling, reconnect and resync, status codes. Done:
   seq/ack sessions fall back to a full reply on any mismatch, the bridge
   polls once per cycle, removed tags send `BadNodeIdUnknown`, and
   GeneralModelChangeEvents are emitted. Measured in
   `docs/spike-results.md`.
5. ✅ **Hardening:** security policies and users, config file, structured
   logging, metrics (`Status/*`), and a load test (for example 500 readers
   at 10 Hz) with a UPS-impact measurement. Done:
   - security: `docs/security.md`, with users, read/write roles and a
     self-signed certificate;
   - logging: JSON logs and a write audit log;
   - metrics: eight new `Status/` values;
   - load test: `docs/spike-results.md`. Optimizing the mod cut a 500-pair
     poll from 18 ms to 11 ms.

   Spreading reads over several ticks is left as an option if large setups
   need it.
6. ✅ **Packaging:** done.
   - **CI:** `.github/workflows/ci.yml` runs unit tests on Python 3.11 and
     3.13, integration tests against the headless server, and package and
     Docker builds.
   - **Releases:** `.github/workflows/release.yml` publishes the mod zip and
     the bridge wheel and sdist on `v*` tags (`docs/releasing.md`).
   - **Docker:** `bridge/Dockerfile` and `deploy/compose.yml`
     (`docs/docker.md`).
   - **Versions:** the mod and bridge share one version, starting at 0.6.0.

## 6. Risks (updated after the M1 spike)
- ~~RCON reply size limits~~: resolved. Replies are a single packet of any
  size (10 MB tested). Sending only changes still matters for speed.
- RCON round-trips take one tick (~16.7 ms). Sequential polling tops out
  near 30 Hz, so `poll_hz` is capped at 30.
- **An uncaught Lua error in a command stops the server.** All handlers go
  through the `pcall` wrapper in `control.lua`, and request parsing must
  assume malformed input.
- Auto-pause: with no players, each RCON command advances the game one
  tick. Document `auto_pause: false`, and show `tick_paused` under
  `Status/`.
- UPS cost of reading many circuit networks per poll is still unmeasured
  (fake payloads had no effect at 60 UPS). Mitigation: read each
  `network_id` once per poll.
- ~~Exact 2.0 API for constant-combinator sections and quality~~:
  confirmed in M2 on base and Space Age.
- `helpers.table_to_json` writes empty arrays as `{}`, so the bridge must
  accept either form.
- GUI, graphics and blueprint/paste paths can't be tested headless; they
  need the manual checklist in a game client before a release.

- `asyncua` notes from M3: a user logging in as "admin" would skip
  access-level checks, so the bridge turns remote admin off. Exceptions
  raised in methods become `BadUnexpectedError`, so methods return a status
  code instead.

## 7. Resolved scope
Resolved:
- Factorio 2.0 only; no 1.1 compatibility layer.
- 10 Hz default update rate, configurable. One-tick pulses may be missed and
  that is accepted; no per-tick sampling mode.
- Writers hold their values until changed again; no pulse writes.
- One Factorio server per bridge; run a second bridge on another port for
  another server.
- Not published on the mod portal.
- Licence: MIT.
