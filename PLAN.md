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
| Game version | Factorio 2.0 (Space Age optional; signals carry quality) — *assumed* |

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
- **OPC Reader** (game → OPC). A small entity with circuit connectors that
  only listens, for example a lamp-based or `simple-entity` prototype. It
  must not emit anything itself, so the values it reads are clean. Values
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
- `rcon.py`: a small asyncio Source-RCON client (auth, request IDs,
  multi-packet replies, reconnect with backoff). It's about 100 lines, which
  avoids blocking third-party libraries.
- `game.py`: a typed wrapper over the mod commands (handshake and version
  check, browse, poll, write), with a serialized command queue because RCON
  is one request at a time.
- `model.py`: builds and syncs the OPC UA address space from browse results
  and `model_version`.
- `server.py`: the asyncua server, the poll loop (default 10 Hz,
  configurable), and the write handlers.
- `config.py`: TOML config covering the RCON host, port and password, the
  OPC endpoint, poll rate, security policy and users.
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
- Writes to `Writers/<tag>/Signals/<sig>` turn into `/opc_write`. Writes are
  batched per poll cycle.
- Quality: while RCON is down, all values switch to `BadNotConnected` (or
  `UncertainLastUsableValue`). Source timestamps are taken from the game tick
  in the poll reply.

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
mod/tests/             busted unit tests for pure Lua (deltas, signal keys)
bridge/factorio_opc/   rcon.py, game.py, model.py, server.py, config.py, __main__.py
bridge/tests/          pytest with a fake RCON server; asyncua client e2e
docker/                compose: factoriotools/factorio headless + bridge
docs/                  setup, address-space reference, protocol spec
```

## 5. Milestones
1. **Spike (de-risk):** headless server in Docker, a trivial mod command, and
   a Python RCON round-trip. Measure latency and the maximum reply size, and
   check behaviour while the server is auto-paused (the plan is to recommend
   `auto_pause=false`).
2. **Mod MVP:** the Writer and Reader entities, the registry, a name GUI, and
   `hello`/`browse`/`snapshot`/`write`.
3. **Bridge MVP:** RCON client, static address space from browse, 10 Hz
   snapshot polling, writable writer nodes. Verified in UaExpert.
4. **Deltas and dynamic model:** `opc_poll` deltas, model-change events,
   rename and remove handling, reconnect and resync, status codes.
5. **Hardening:** security policies and users, config file, structured
   logging, metrics (`Status/*`), and a load test (for example 500 readers
   at 10 Hz) with a UPS-impact measurement.
6. **Packaging:** mod zip for the Factorio mod portal, `pip install`able
   bridge, Docker compose example, docs, and CI (busted, pytest, and an
   optional headless e2e job).

## 6. Risks / to verify in spike
- RCON reply size limits and multi-packet framing in Factorio.
  Mitigation: deltas, plus chunking with `/opc_poll` continuation.
- RCON throughput, since commands run on the next tick. A 10–20 Hz poll rate
  is realistic; 60 Hz probably isn't.
- UPS cost of reading many circuit networks per poll. The mitigation is
  per-tick caching of `network_id` → signals so a shared network is read
  once.
- Exact 2.0 API for the constant-combinator sections, and quality on
  signals.

## 7. Open questions
- Factorio 2.0 only, or also 1.1? (Assumed 2.0, which affects the
  combinator and wire APIs.)
- Is a 10 Hz default update rate enough, or do you need single-tick pulse
  capture?
- Should Writers support pulse/one-shot writes (set for N ticks, then
  clear)?
- Publish the mod on the official mod portal? Licence (MIT?).
- Multiple Factorio servers behind one bridge (one namespace folder per
  server)?
