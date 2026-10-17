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

## Using opcua-client

Every client step in this checklist uses FreeOpcUa **`opcua-client` 1.0.1**,
which works on macOS without an account. To install it:
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

The terms below are its UI:

- **Connect:** enter `opc.tcp://127.0.0.1:4840/factorio-opc/` in the
  address box and press **Connect**. The **Connect to server** dialog
  opens:
  - Pick a security mode (**None**, **Sign** or **SignAndEncrypt**).
  - Pick an endpoint from the list. Entries read like
    `Basic256Sha256 | SignAndEncrypt | opc.tcp://...`.
  - Pick a login: **Anonymous**, or **Username** with User and Password.
  - Press **Connect**.
  The defaults are None and Anonymous.
- **Tree:** the browse tree on the left. Children load when you first
  expand a node and are then cached, so the tree doesn't show tags added or
  renamed later. To refresh it, press **Disconnect** then **Connect**.
- **Watch a value:** right-click a variable and choose **Subscribe to data
  change**. It appears in the **Subscriptions** pane with live value and
  status.
- **Write a value:** select a variable, then in the **Attributes** pane
  double-click its Value, type the new number and press Enter.
- **Call a method:** right-click it and choose **Call**. Each argument has
  its own box; press **Call Method**, and the status and output appear in
  the dialog.
- **Watch events:** right-click `Objects/Server` and choose **Subscribe to
  events**. Events appear in the **Events** pane, and the Message column
  carries the useful text. It doesn't show event-specific fields such as a
  model change's `Changes` list.

## Bridge in an OPC UA client

Setup: `scripts/dev-server.sh up` (or your own server with RCON), then
`factorio-opc --rcon-password-file .dev/factorio/config/rconpw` (or
`--config bridge/example.toml`). Connect opcua-client as above. Building
entities needs a game client connected to the server, or `/sc` commands
over RCON.

- [x] Under `Objects/Factorio/Status`, Connected is true, and GameTick,
      versions and LastPollLatencyMs are filled in.
- [x] `Readers` and `Writers` list your in-game tags.
- [x] Subscribed reader values (Red, Green, Total) update live in the
      Subscriptions pane as the circuit changes, and Total = Red + Green.
- [x] Calling `Writers/<tag>/SetSignals` with `{"virtual/signal-A": 5}` and
      `merge` returns Good, the signal appears in game, and it appears under
      `Signals/` after a reconnect.
- [x] Writing a writer signal's Value in the Attributes pane changes the
      in-game output; the same edit on a reader signal is refused.
- [x] Stopping the Factorio server turns subscribed values' status
      Uncertain (`UncertainNoCommunicationLastUsableValue`) and Connected
      false; starting it again brings them back to Good.

## Model changes in a client (milestone 4)

- [x] Subscribe to data change on one of a tag's signals, then rename the
      tag in game. Within a second the subscription's status turns
      `BadNodeIdUnknown`. After Disconnect and Connect, the tree shows the
      tag under its new name, with current values.
- [x] Subscribe to a reader signal, then mine that reader: its status turns
      `BadNodeIdUnknown`, and after a reconnect the tag is gone from the
      tree.
- [x] Subscribe to events on `Objects/Server`, then place a new writer in
      game: one event appears in the Events pane, with a Message like
      `Added Writers/writer-12`. Renaming a tag gives
      `Added Writers/<new>; removed Writers/<old>`.

## Security and metrics (milestone 5)

Setup: make a password hash with `factorio-opc hash-password`.
- **Client certificate:** once, in opcua-client, open **Settings → Client
  Application Certificate**, press **Generate self-signed certificate**, then
  OK. opcua-client 1.0.1 refuses encrypted endpoints until it has one.
- **The bridge's certificate:** the bridge creates its own server
  certificate in `~/.factorio-opc/pki/` when it starts.
- **Access:** the bridge accepts any client certificate, using it only to
  encrypt. The login decides what you can do.

Then put
this in a config file in the repo root (for example `secure.toml`;
relative paths are resolved from the config file's folder) and run
`factorio-opc --config secure.toml`:
```toml
[factorio]
rcon_password_file = ".dev/factorio/config/rconpw"   # adjust to your setup
[opcua]
security = ["none", "sign_encrypt"]
anonymous = "read"
[[opcua.users]]
name = "operator"
password_hash = "scrypt$..."   # your hash
role = "write"
```

- [ ] Connecting with no login works, and values can be read and
      subscribed. Writing a writer signal's Value in the Attributes pane
      fails, and calling `SetSignals` fails with `BadUserAccessDenied`.
- [ ] Connecting with **Username** `operator` and your password allows the
      write and the method call. A wrong password refuses the connection.
- [ ] Encrypted connection: in the Connect dialog choose
      **SignAndEncrypt**, try both endpoints (Basic256Sha256 and
      Aes256_Sha256_RsaPss), and log in as operator. On first use,
      opcua-client may ask you to trust the bridge's certificate. The
      connection works, and so do writes.
- [ ] The bridge's log shows a line like
      `write press {"virtual/signal-A": 5} by operator` for each write.
      With `--log-format json`, the same line is JSON with `user` and
      `result` fields.
- [ ] Under `Objects/Factorio/Status`, the new counters move as you'd
      expect: Polls rises steadily, Writes and WriteErrors count your
      writes, Tags and SignalNodes match the tree, and Reconnects
      increases after you stop and start the Factorio server.
- [ ] Network safety check: add `endpoint = "opc.tcp://0.0.0.0:4840/factorio-opc/"`
      under `[opcua]` in that config (`0.0.0.0` means "reachable from other
      machines", while `127.0.0.1` means this computer only). With
      `security` still including "none" and `anonymous = "read"`, running
      the bridge exits immediately with
      `factorio-opc: endpoint ... is reachable from the network with security 'none' and anonymous 'read' access ...`,
      listing the three ways to fix it. Remove the line again afterwards.
