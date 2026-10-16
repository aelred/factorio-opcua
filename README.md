# factorio-opc

Expose Factorio 2.0 circuit-network signals to **OPC UA** clients (UaExpert,
Ignition, KEPServerEX, Node-RED, PLCs). The project has two parts:

- `mod/opc-io`: a Factorio mod that adds **OPC Reader** and **OPC Writer**
  combinators and RCON commands for reading and writing their signals
  ([protocol](docs/protocol.md)).
- `bridge/`: a Python process (`factorio-opc`) that polls the game over
  RCON and serves it as an OPC UA server, using `asyncua`
  ([address space](docs/address-space.md)).

See [PLAN.md](PLAN.md) for the design and milestones, and
[docs/spike-results.md](docs/spike-results.md) for measured RCON behaviour.

**Status:** milestone 3 (bridge MVP) is done. OPC UA clients can browse
readers and writers, read and subscribe to signals, and write writer signals.
There is no OPC security or login yet (milestone 5), so keep the endpoint on
localhost or a trusted network.

## Quick start

1. Install the mod: `scripts/package-mod.sh`, then copy
   `dist/opc-io_<version>.zip` into the server's `mods/` folder.
2. Run the server with RCON enabled, for example
   `--rcon-port 27015 --rcon-password <pw>`, and set
   `"auto_pause": false`.
3. Install and start the bridge:
   ```sh
   pip install ./bridge
   FACTORIO_RCON_PASSWORD=<pw> factorio-opc --rcon-host <server> --poll-hz 10
   ```
   Alternatively, copy `bridge/example.toml` and run
   `factorio-opc --config my.toml`.
4. Connect your OPC UA client to `opc.tcp://127.0.0.1:4840/factorio-opc/`
   with security None. Use `--endpoint opc.tcp://0.0.0.0:4840/factorio-opc/`
   to accept connections from other machines.

## Development

Requires Docker and Python 3.11+.

```sh
scripts/dev-server.sh up          # Factorio 2.0.77 headless + opc-io, RCON on 127.0.0.1:27015
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest                  # unit tests + integration tests (skipped if no server)
.venv/bin/pytest -m "not integration"   # unit tests only
.venv/bin/python spike/spike.py   # RCON measurements against the dev server
scripts/package-mod.sh            # dist/opc-io_<version>.zip for a game client
.venv/bin/factorio-opc --rcon-password-file .dev/factorio/config/rconpw   # bridge on the dev server
scripts/dev-server.sh down
```

`DLC_SPACE_AGE=true scripts/dev-server.sh up` runs the server with Space Age
and Quality, which you need to test quality signals.

Server data, including the generated RCON password in
`.dev/factorio/config/rconpw`, lives in `.dev/`, which git ignores. Run
`scripts/dev-server.sh up` again after editing the mod to reload it.

GUI, graphics, blueprint handling and the UaExpert walkthrough need a real
client; see
[docs/manual-test-checklist.md](docs/manual-test-checklist.md).

For OPC use, set `"auto_pause": false` in the server settings; the spike
results explain why.

## License

MIT, see [LICENSE](LICENSE). Graphics taken from the base game, if added
later, remain under Wube Software's terms.
