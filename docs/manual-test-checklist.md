# Manual test checklist (game client)

A headless server can't exercise GUI, graphics or player-only events, and
scripts aren't allowed to raise `on_entity_settings_pasted`. Check these in
a real Factorio 2.0 client after changes to `data.lua`, `lib/gui.lua` or
the blueprint/paste handlers.

Setup: run `scripts/package-mod.sh`, copy `dist/opc-io_<version>.zip` into
your Factorio `mods/` folder, and start a new game (the editor or cheat
mode is convenient).

- [x] The game loads without prototype errors.
- [x] OPC Writer looks orange and OPC Reader looks blue, in the world, as
      icons, and in the crafting menu.
- [x] Both recipes unlock with the Circuit network technology.
- [x] Opening either entity shows the OPC panel (not the combinator panel),
      with its name, a text field and an Apply button.
- [x] Renaming with Apply or Enter works. An invalid or duplicate name shows
      a red error and the panel stays open. E and Esc close the panel.
- [x] The reader panel lists red and green network signals; the writer panel
      lists signals written over RCON.
- [x] Mining an entity while its panel is open closes the panel.
- [x] A blueprint of a named writer, placed twice, gives `name` and
      `name-2`. Also check robot-built ghosts.
- [x] Shift-click paste from writer to reader leaves the reader outputting
      nothing.
- [x] Shift-click paste from a normal constant combinator that uses a
      logistic group onto a writer: the writer takes a copy of the group's
      values (they appear under "Signals written by OPC"). Then **edit the
      group** on the original combinator: the writer's signals must not
      change, because it should no longer be linked to the group.
- [x] A player typing `/opc_snapshot` in chat is told it is RCON-only.

Last full pass: 2026-10-16, opc-io 0.2.0, all items passed.

## Bridge in UaExpert (or another OPC UA client)

Setup: `scripts/dev-server.sh up` (or your own server with RCON), then
`factorio-opc --rcon-password-file .dev/factorio/config/rconpw` (or
`--config bridge/example.toml`). Connect UaExpert to
`opc.tcp://127.0.0.1:4840/factorio-opc/` with security None and anonymous
login. Building entities needs a game client connected to the server, or
`/sc` commands over RCON.

- [x] Factorio/Status shows Connected = true, plus the game tick, versions
      and latency.
- [x] Readers and Writers list your in-game tags; renaming a tag in game
      updates the tree within a second (you may need to refresh the browse
      view).
- [x] Reader values update live in the Data Access view as the circuit
      changes, and Total = Red + Green.
- [x] Calling `SetSignals` on a writer with `{"virtual/signal-A": 5}` and
      `merge` makes the signal appear in game and under `Signals/`.
- [x] Writing a writer's signal node changes the in-game output; writing a
      reader node is refused.
- [x] Stopping the Factorio server makes values go Uncertain and Connected
      false; starting it again brings them back to Good.

## Model changes in a client (milestone 4)

- [ ] Renaming a tag in game: the old node goes Bad (`BadNodeIdUnknown`) in
      the Data Access view, and the new name appears under Readers/Writers.
      Note whether your client refreshes the tree by itself (from the model
      change event) or needs a manual refresh.
- [ ] Mining a reader that you're monitoring: its items go Bad, and the tag
      disappears from the tree.
- [ ] In UaExpert's Event View, add the Server object with event type
      GeneralModelChangeEventType, then place a new writer in game: one event
      appears listing the new node.
