# opc-io RCON protocol (proto 2)

The bridge talks to the `opc-io` mod with ordinary RCON console commands.
Each command replies with **one JSON object** containing `"ok"`. Commands
are rejected when a player types them in game; they only work over RCON.

```
> /opc_write {"tag":"line_1","signals":{"item/iron-plate":5}}
< {"ok":true,"tick":7656,"tag":"line_1","signals":{"item/iron-plate":5}}
```

## General rules
- **Errors** come back as `{"ok":false,"error":"<message>"}`. The mod never
  lets a Lua error escape a command, because an uncaught error stops a
  multiplayer server.
- **Unknown commands** return Factorio's plain-text `Unknown command ...`,
  which isn't JSON. Treat a reply that doesn't parse as a protocol error.
- **Empty maps and lists** both encode as `{}`. Factorio's `table_to_json`
  can't tell an empty array from an empty object, so `tags` can be `{}`.
- **One line only**: RCON commands must not contain newlines. JSON
  parameters must be compact.
- `tick` is the game tick at which the command ran. Commands in the same
  batch of pipelined requests usually share a tick.
- `model_version` increases whenever a tag is added, removed or renamed.
  When it changes, re-run `/opc_browse`.

## Signal keys and values
A signal key is `type/name` or `type/name/quality`:
`item/iron-plate`, `fluid/water`, `virtual/signal-A`,
`item/iron-plate/rare`, `quality/legendary`.

- Normal quality is never included in a key. On input, `.../normal` is
  accepted and normalized away.
- Types are `item`, `fluid`, `virtual`, `entity`, `recipe`,
  `space-location`, `asteroid-chunk` and `quality`.
- Values are int32. A signal that isn't present in a map has the value 0.

## Tags
Each OPC Reader and OPC Writer entity has a unique **tag name**: 1–64
characters from `[A-Za-z0-9_.-]`. New entities get `reader-N` or
`writer-N`. Players rename them in the entity's panel; other mods and
scripts use `remote.call("opc-io", "rename", old, new)`, which returns
`nil` on success or an error string. Blueprints carry the name, and a
copy whose name is already taken gets `-2`, `-3`, ... appended.

## Commands

Protocol 2 (opc-io 0.3.0) added `/opc_poll`. Bridge 0.4.0 and later
require it.

### `/opc_hello`
```json
{"ok":true,"proto":2,"mod_version":"0.3.0","factorio_version":"2.0.77",
 "tick":7172,"tick_paused":false,"speed":1,"model_version":2}
```

### `/opc_browse`
```json
{"ok":true,"tick":7170,"model_version":2,"tags":[
  {"name":"reader-1","kind":"reader","unit":17,"surface":"nauvis","position":{"x":12.5,"y":10.5}},
  {"name":"writer-1","kind":"writer","unit":16,"surface":"nauvis","position":{"x":10.5,"y":10.5}}]}
```
Tags are sorted by name.

### `/opc_snapshot`
All current values. For each reader, the red and green networks are
reported separately (an unconnected wire gives an empty map). For each
writer, its current output is reported.
```json
{"ok":true,"tick":7658,"model_version":2,
 "readers":{"reader-1":{"red":{"item/iron-plate":5,"virtual/signal-A":-3},"green":{}}},
 "writers":{"writer-1":{"item/iron-plate":5,"virtual/signal-A":-3}}}
```
A writer's output shows up on wired networks on the next tick.

### `/opc_poll <json>`
Change-only polling, which is what the bridge uses on every cycle.
```json
{"session":"8f2c...","ack":41}
```
- `session` is 1–64 characters of `[A-Za-z0-9_-]`. The bridge picks a new
  random one for each connection.
- `ack` is the `seq` of the last reply the caller applied; leave it out on
  the first poll. Add `"full":true` to force a full reply.

Reply:
```json
{"ok":true,"seq":42,"full":false,"tick":7700,"tick_paused":false,"speed":1,"model_version":3,
 "readers":{"reader-1":{"red":{"item/iron-plate":6},"green":{}}},
 "writers":{"writer-1":{"virtual/signal-A":0}},
 "removed":["old-tag"]}
```
- **Full replies:** when `full` is true, `readers` and `writers` hold every
  value, as in `/opc_snapshot`.
- **Delta replies:** otherwise they hold only tags that changed since reply
  `ack`:
  - A reader lists only the changed keys of each wire.
  - A signal that went away is reported as `0`.
  - A tag that is new to this session appears with all its values.
  - `removed` lists tags that no longer exist.
- **When the mod falls back to a full reply:** the mod remembers, per
  session, what it last sent. If the session is unknown, has expired (5
  minutes without a poll; at most 16 sessions are kept), or its last `seq`
  doesn't equal `ack`, the reply is full. A mismatch happens, for example,
  when a reply was lost or the server reloaded an older save. So a
  caller that always sends the `seq` it applied can't drift out of sync.
- **Tag changes:** when `model_version` changes, re-run `/opc_browse`.
- **Storage:** session state lives in the save (`storage.opc.sessions`).

### `/opc_write <json>`
```json
{"tag":"writer-1","signals":{"item/iron-plate":5,"fluid/water":0},"mode":"merge"}
```
- `mode` is `merge` (the default), which updates the listed signals, or
  `replace`, which makes the writer output exactly the listed signals.
- A value of `0` removes that signal.
- A writer holds at most 1,000 signals.
- Special virtual signals (`signal-everything`, `signal-anything`,
  `signal-each`) are rejected.

Reply: `{"ok":true,"tick":...,"tag":"writer-1","signals":{...full new output...}}`.

## Entity behaviour
- **OPC Writer**: a constant combinator with exactly one signal section and
  no logistic group. The mod enforces this after builds, pastes and
  blueprints, because a logistic group would share values between
  combinators.
- **OPC Reader**: a constant combinator kept disabled and empty, so it
  never adds to the networks it reads.
- Both replace the combinator panel with an OPC panel that edits the tag
  name and shows current signals. Players can't edit writer values by hand.
