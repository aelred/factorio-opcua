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
them to a chest that empties itself. It's all ordinary circuits: once the
demo is built, no script runs.

| Tag | Node | What it does |
|---|---|---|
| `line_input_count` | `Readers/line_input_count/Red/item/iron-plate` | Plates put on the input belt so far |
| `line_output_count` | `Readers/line_output_count/Red/item/iron-gear-wheel` | Gears taken off the output belt so far |
| `line_status` | `Readers/line_status/Red/virtual/signal-…` | Status signals, below |

`line_status` reads the line's control network. Each status signal is `1`
while it applies and `0` otherwise. (Its OPC node appears the first time it
is `1`; B, for example, only once the output has been blocked.)

| Signal | Means | Comes from |
|---|---|---|
| `virtual/signal-R` | The line is switched on | The LINE combinator |
| `virtual/signal-P` | Power is on | The POWER combinator, which also opens and closes the power switch |
| `virtual/signal-W` | The machine is working | The assembling machine (its "read working state" setting) |
| `virtual/signal-I` | No input: no plates on the belt at the machine | A decider combinator reading that belt |
| `virtual/signal-B` | Output blocked: gears backed up at the machine | A decider combinator reading that belt |

When everything runs, R, P and W are `1`. A client can work out the state
from them, as a PLC or SCADA system would: R = 0 means stopped, P = 0 no
power, I = 1 no input, B = 1 output blocked. Without power the belt
sensors stop updating, so check P first.

## Things to try in game

Each switch is a labelled constant combinator: open it and use its on/off
switch.

- **LINE:** stops and resumes the line. R and W go to 0.
- **POWER:** opens the power switch, cutting the line's power. P and W go to
  0 at once.
- **SUPPLY:** stops plates coming in. Once the input belt has run empty at
  the machine, which takes a little while, I becomes 1 and W 0.
- **COLLECTION:** stops gears leaving. Once gears have backed up to the
  machine, which takes a little longer, B becomes 1 and W 0.

You can also pick up a belt or an inserter to cause a problem. To start
again from scratch, run `/opc_demo remove` and then `/opc_demo`.
