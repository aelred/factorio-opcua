# Demo

The `/opc_demo` command builds a ready-made demo with OPC Readers and
Writers already wired up. It goes on its own surface, `opcua-demo`, so it
never touches your map, and it's saved with the game like everything else.

## Starting it

| Where | How |
|---|---|
| Your own game (you're the host, so you're admin) | Type `/opc_demo` in chat. It builds the demo and takes you there. |
| A dedicated server | An admin types `/opc_demo` in chat, or run it in the server console or over RCON. |
| Docker (`deploy/`) | `docker compose exec factorio rcon /opc_demo` |
| The dev server | `scripts/dev-server.sh demo` |

- **Visiting:** once the demo exists, any player can type `/opc_demo` to go
  there and `/opc_demo leave` to return to Nauvis.
- **Building and removing:** only admins, the server console and RCON can
  build the demo or delete it with `/opc_demo remove`, which also removes
  its OPC tags. It's built only once; `/opc_demo` after that just visits.

The demo uses editor-only entities (infinite power and an infinite supply
chest) so it keeps running without anyone looking after it.

## What's in it

Tags are listed with the OPC UA node to use (see
[address-space.md](address-space.md)).

**Clock, lamps and echo** (top):

| Tag | Node | What it does |
|---|---|---|
| `demo_clock` | `Readers/demo_clock/Red/virtual/signal-T` | Counts up by one every tick (60 per second) |
| `demo_lamps` | `Writers/demo_lamps/Signals/virtual/signal-1` … `signal-4` | Each signal lights one of four lamps; write `0` or `1`. All start on. |
| `demo_echo` | `Readers/demo_echo/Red/…` | Wired to `demo_lamps`, so it shows back what you wrote |

**Production line** (bottom): an infinite chest of iron plates feeds an
input belt, an assembling machine makes gears, and an output belt carries
them to a chest that empties itself.

| Tag | Node | What it does |
|---|---|---|
| `line_switch` | `Writers/line_switch/Signals/virtual/signal-R` | `1` runs the line, `0` stops it. The same as the LINE switch in game: change either and the other follows. |
| `line_input_count` | `Readers/line_input_count/Red/item/iron-plate` | Plates put on the input belt so far |
| `line_output_count` | `Readers/line_output_count/Red/item/iron-gear-wheel` | Gears taken off the output belt so far |
| `line_status` | `Readers/line_status/Red/virtual/signal-E` | The line's status code, below |

The status code is also shown in game, under the status combinator.

| Code | Status | Cause |
|---|---|---|
| 1 | Running | The machine has made something in the last 3 seconds |
| 2 | Stopped | The line switch is off |
| 3 | No power | The POWER switch is off |
| 4 | No input | The machine is out of plates, for example with SUPPLY off |
| 5 | Output blocked | The machine can't put out more gears, for example with COLLECTION off |
| 9 | Other | Anything else |

## Things to try in game

Each switch is labelled. Open a constant combinator and use its on/off
switch; click the power switch to toggle it.

- **LINE:** stops and resumes the line. `line_switch` follows, and
  `line_status` becomes 2.
- **POWER:** cuts the line's power. `line_status` becomes 3 at once.
- **SUPPLY:** stops plates coming in. Once the input belt runs empty,
  `line_status` becomes 4.
- **COLLECTION:** stops gears leaving. Once the output belt is full,
  `line_status` becomes 5.

You can also pick up a belt or an inserter to cause a problem. To start
again from scratch, run `/opc_demo remove` and then `/opc_demo`.
