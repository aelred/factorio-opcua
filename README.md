# factorio-opc

Expose Factorio 2.0 circuit-network signals to **OPC UA** clients (UaExpert,
Ignition, KEPServerEX, Node-RED, PLCs). The project has two parts:

- `mod/opc-io`: a Factorio mod that adds **OPC Reader** and **OPC Writer**
  combinators and RCON commands for reading and writing their signals
  ([protocol](docs/protocol.md)).
- `bridge/`: a Python process that talks to the server over RCON and runs
  the OPC UA server (`asyncua`, from milestone 3).

See [PLAN.md](PLAN.md) for the design and milestones, and
[docs/spike-results.md](docs/spike-results.md) for measured RCON behaviour.

**Status:** milestone 2 (mod MVP) is done. The mod has the Reader/Writer
entities, tag names, and the `hello`/`browse`/`snapshot`/`write`
commands. The bridge has only the RCON client so far.

## Development

Requires Docker and Python 3.11+.

```sh
scripts/dev-server.sh up          # Factorio 2.0.77 headless + opc-io, RCON on 127.0.0.1:27015
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
.venv/bin/pytest                  # unit tests + integration tests (skipped if no server)
.venv/bin/pytest -m "not integration"   # unit tests only
.venv/bin/python spike/spike.py   # RCON measurements against the dev server
scripts/package-mod.sh            # dist/opc-io_<version>.zip for a game client
scripts/dev-server.sh down
```

`DLC_SPACE_AGE=true scripts/dev-server.sh up` runs the server with Space Age
and Quality, which you need to test quality signals.

Server data, including the generated RCON password in
`.dev/factorio/config/rconpw`, lives in `.dev/`, which git ignores. Run
`scripts/dev-server.sh up` again after editing the mod to reload it.

GUI, graphics and blueprint handling need a real game client; see
[docs/manual-test-checklist.md](docs/manual-test-checklist.md).

For OPC use, set `"auto_pause": false` in the server settings; the spike
results explain why.

## License

MIT, see [LICENSE](LICENSE). Graphics taken from the base game, if added
later, remain under Wube Software's terms.
