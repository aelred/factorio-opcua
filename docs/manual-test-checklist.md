# Manual test checklist (game client)
sd
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
      nothing. Paste from a normal constant combinator that uses a logistic
      group onto a writer detaches the group.  RESULT: I'm not sure what this last part means. When I do this it appears to update the "Signals written by OPC" to match the logistic group.
- [x] A player typing `/opc_snapshot` in chat is told it is RCON-only.
