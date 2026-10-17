# OPC UA address space

Endpoint (default): `opc.tcp://127.0.0.1:4840/factorio-opc/`. Encryption,
logins and read-only users are described in [security.md](security.md).

Everything lives in the namespace **`urn:factorio-opc`**. Look up its index
at runtime; it is usually 2. NodeIds are strings that spell out the path,
so clients can address nodes directly, for example
`ns=2;s=Readers/line_1/Red/item/iron-plate`.

```
Objects/Factorio/
  Status/
    Connected          Boolean   true while the bridge is connected and synced
    GameTick           UInt64
    TickPaused         Boolean
    GameSpeed          Double
    ModVersion         String    opc-io version
    FactorioVersion    String
    ModelVersion       UInt32    changes when tags are added, removed or renamed
    LastPollLatencyMs  Double    round-trip of the last poll
    Polls              UInt64    polls completed since the bridge started
    LatePolls          UInt64    polls that started late (the game or RCON couldn't keep up with poll_hz)
    Reconnects         UInt32    times the bridge reconnected to the game
    Writes             UInt64    writes accepted by the game (values and methods)
    WriteErrors        UInt64    writes refused or failed
    Tags               UInt32    reader and writer tags currently published
    SignalNodes        UInt32    signal variables currently published
    ConnectedSince     DateTime  start of the current game connection
  Readers/
    <tag>/
      Red/<signal>     Int32  read-only
      Green/<signal>   Int32  read-only
      Total/<signal>   Int32  read-only, Red + Green with 32-bit wraparound (as in game)
  Writers/
    <tag>/
      Signals/<signal> Int32  writable
      SetSignals(SignalsJson: String, [Mode: String]) -> Signals: String
      ClearAll()
```

`<tag>` is the in-game tag name, and `<signal>` is a signal key such as
`item/iron-plate`, `virtual/signal-A` or `item/iron-plate/rare` (see
[protocol.md](protocol.md#signal-keys-and-values)). Browse names are the
same strings.

## Signal nodes
- **Creation:** a signal node is created the first time its signal is seen,
  then kept with value 0 when the signal goes away, so subscriptions stay
  valid. A node only disappears when its tag does.
- **Readers:** a signal seen on either wire gets a node in Red, Green and
  Total.
- **Writers:** a writer has nodes only for the signals it has output. Add
  new signals with `SetSignals`, for example
  `SignalsJson = {"item/iron-plate": 5}` and `Mode = "merge"`. After that,
  write the node directly.

## Values, timestamps and quality
- Values update at the bridge's `poll_hz` (default 10 Hz). Each node is
  updated only when its value changes.
- `SourceTimestamp` is the time the bridge received the poll reply. For the
  exact game time, read `Status/GameTick`.
- If the connection to the game drops, every signal keeps its last value
  with status **`Uncertain_NoCommunicationLastUsableValue`**, and
  `Status/Connected` becomes false. Values return to Good after reconnecting
  (with backoff from 1 s up to 30 s).

## Writing
- A write to `Writers/<tag>/Signals/<signal>` is passed straight to the game.
  The client's write completes once the game has accepted it, which takes
  about one tick, and its status code is the game's verdict.
- Any numeric type holding a whole number in the int32 range is accepted.
  Writing `0` removes the signal from the writer's output; the node stays,
  at 0.
- Several signals of the same writer written in one request become one game
  write.

| Status | Meaning |
|---|---|
| `Good` | Applied in game |
| `BadTypeMismatch` | Not a number, or not a whole number |
| `BadOutOfRange` | Outside int32 |
| `BadInvalidArgument` | Rejected by the game (logged by the bridge), or bad method arguments |
| `BadNoCommunication` | Not connected to the game |
| `BadCommunicationError` | The connection failed during the write |
| `BadUserAccessDenied` | A read-only user or anonymous client tried to write or call a method |
| `BadNotWritable` | Tried to write a read-only node |

`SetSignals` and `ClearAll` return the same codes as the call result, plus
`BadArgumentsMissing`, `BadTooManyArguments` or `BadTypeMismatch` for wrong
arguments. `Mode` may be left out and defaults to `merge`. `SetSignals`
returns the writer's full new output as JSON.

## Calling the methods from common tools

**FreeOpcUa `opcua-client`** (a GUI built on asyncua, works on macOS,
Linux and Windows, no sign-in) is the easiest client to recommend. It can
browse, subscribe, write, and call methods, giving each argument its own
field, so JSON with several signals works. To install and start it:
```sh
uv tool install --python 3.14 "opcua-client==1.0.1"   # uv fetches Python 3.14 if needed
# or, with Python 3.14 active (e.g. mise use -g python@3.14): python3 -m pip install "opcua-client==1.0.1"
opcua-client
```
Use **1.0.1** for now:
- 0.9.99 and later need Python 3.14. On an older Python, pip quietly
  installs 0.8.4 (2022). Its certificate dialog crashes, and it can't use
  the Aes256 policy.
- 1.0.2 broke right-click **Call**
  (`AttributeError: 'TreeWidget' object has no attribute 'get_parent_node'`).
  The repository's code was still broken as of 2026-10-18.

Connect to `opc.tcp://127.0.0.1:4840/factorio-opc/`, then right-click
`SetSignals` and choose **Call**. Checked with opcua-client 1.0.1 (and,
earlier, 0.8.4), through the main window's Call action: one call set two
signals.

**asyncua's `uacall`** is installed alongside the bridge. Prefix the method
name with the namespace index (`2:`), or you'll get `BadNoMatch`:
```sh
uacall -u opc.tcp://127.0.0.1:4840/factorio-opc/ -n "ns=2;s=Writers/press" \
       -m 2:SetSignals '{"item/iron-plate": 5}'            # merge
uacall ... -m 2:SetSignals '{"item/iron-plate": 5},replace'  # replace
uacall ... -m 2:ClearAll
```
`uacall` splits its arguments at commas, so JSON holding more than one
signal arrives as extra arguments (`BadTooManyArguments`). Make one call per
signal instead, or use a client that passes arguments separately (UaExpert,
Node-RED, or a short asyncua script, as below).

To change a signal the writer already outputs, write its node instead:
`uawrite -u ... -n "ns=2;s=Writers/press/Signals/item/iron-plate" -t int32 9`.

**opcua-commander** (checked at 1.2.5): its help screen lists `k` as "Call
Method", but the handler only logs the node ID and never makes the call. It
can't call `SetSignals`. Its `w` (Write Value) works on existing signal
nodes.

**A script**, for several signals at once:
```python
import asyncio, json
from asyncua import Client, ua

async def main():
    async with Client("opc.tcp://127.0.0.1:4840/factorio-opc/") as c:
        ns = await c.get_namespace_index("urn:factorio-opc")
        writer = c.get_node(ua.NodeId("Writers/press", ns))
        print(await writer.call_method(ua.NodeId("Writers/press/SetSignals", ns),
                                       json.dumps({"item/iron-plate": 5, "virtual/signal-A": 1}), "merge"))

asyncio.run(main())
```

## Tag changes and model change events
- **When the bridge re-syncs:** whenever `ModelVersion` changes or the mod
  sends a full reply, the bridge re-browses the game.
  - New tags get nodes, filled from current values straight away.
  - Removed tags lose theirs.
  - A rename appears as a removal plus an addition, because NodeIds contain
    the tag name.
- **Subscribers to a removed tag:** their signals first receive the status
  `BadNodeIdUnknown`, so they notice. The nodes are deleted after that.
- **Events:** every poll cycle that adds or deletes nodes (tags or new
  signal nodes) emits one **`GeneralModelChangeEvent`**.
  - Each entry in its `Changes` names the affected node with a `Verb` of
    5 (NodeAdded + ReferenceAdded) or 10 (NodeDeleted + ReferenceDeleted).
    `AffectedType` is BaseObjectType for tags and BaseDataVariableType for
    signals.
  - The event is emitted from the Server object, where most clients
    subscribe, and from `Objects/Factorio`.

## Polling
- **Requests:** the bridge sends one `/opc_poll` per cycle (see
  [protocol.md](protocol.md#opc_poll-json)). The first reply on a connection
  is full; after that the mod sends only changes.
- **Cost:** a quiet factory costs about 136 bytes per poll whatever its size
  (measured with 400 tags; a full read is about 50 KB).
- **Resync:** if the mod has lost track of the session, for example after
  the server reloads an older save, the reply is full and the bridge
  resynchronizes everything.

## Performance

These figures were measured on Factorio 2.0.77 headless.

**RCON timing:**
- An RCON command runs at the next game tick, so a round trip takes one
  tick (about 16.7 ms).
- That limits `poll_hz` to 30. The default is 10.
- Writes from clients take effect on the next tick too.

**Auto-pause:**
- Set `"auto_pause": false` in the server settings.
- With auto-pause on and no players connected, every RCON command still
  advances the game by one tick. The bridge's polling then becomes what
  drives the factory, at `poll_hz` ticks per second.

**Cost inside the game:** the mod reads every reader's networks on each
poll. Timed with Factorio's profiler, with 5 signals per writer:

| Setup | Time per poll | Share of the tick budget at 10 Hz |
|---|---|---|
| 100 writers, each wired to its own reader | 1.9 ms | 1.9% |
| 500 writers, each wired to its own reader | 10.7 ms | 10.7% |
| 1 writer, 100 readers on one network | 0.7 ms | 0.7% |
| 1 writer, 500 readers on one network | 3.3 ms | 3.3% |

**What drives the cost:**
- Readers dominate, at about 7 µs each, mostly in engine calls.
- A network shared by many readers is read only once per poll.
- Writer values are cached. Each poll re-checks 1/20 of the writers, so a
  change made outside the bridge, such as by another mod, shows within
  about 2 seconds at 10 Hz.

**Large setups:** the whole read lands in a single tick, so hundreds of
separately wired readers can cause a visible hitch on a busy server. Keep
`poll_hz` low, or wire readers onto shared networks where you can.
