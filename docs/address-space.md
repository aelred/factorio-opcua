# OPC UA address space

Endpoint (default): `opc.tcp://127.0.0.1:4840/factorio-opc/`, no security,
anonymous login. Security and users arrive in milestone 5.

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
  Readers/
    <tag>/
      Red/<signal>     Int32  read-only
      Green/<signal>   Int32  read-only
      Total/<signal>   Int32  read-only, Red + Green with 32-bit wraparound (as in game)
  Writers/
    <tag>/
      Signals/<signal> Int32  writable
      SetSignals(SignalsJson: String, Mode: String) -> Signals: String
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
| `BadUserAccessDenied` / `BadNotWritable` | Tried to write a read-only node |

`SetSignals` and `ClearAll` return the same codes as the call result.
`SetSignals` returns the writer's full new output as JSON.

## Tag changes
When `ModelVersion` changes, the bridge re-browses the game:
- New tags get nodes.
- Removed tags lose theirs.
- A rename appears as a removal plus an addition.

ModelChange events arrive in milestone 4.
