# factorio-opc

Connect Factorio 2.0 circuit networks to **OPC UA**, the standard protocol
of industrial automation. SCADA systems, PLCs and OPC clients such as
Ignition, Node-RED, UaExpert or FreeOpcUa's opcua-client can then read
signals from your factory and drive it.

```
OPC UA client ──opc.tcp──▶ factorio-opc bridge ──RCON──▶ Factorio server + opc-io mod
```

There are two parts:
- **opc-io** (`mod/opc-io`): a Factorio mod that adds two combinators.
  - **OPC Reader:** publishes the red and green signals wired to it.
  - **OPC Writer:** outputs signals set by OPC clients.

  Each has a tag name, which becomes its name in OPC.
- **factorio-opc** (`bridge/`): an OPC UA server, written in Python with
  asyncua. It polls the mod over RCON and serves:
  - `Readers/<tag>/{Red,Green,Total}/<signal>`,
  - writable `Writers/<tag>/Signals/<signal>`,
  - `Status/` and metrics.

  It supports logins, read-only users, encryption and an audit log of every
  write.

## Install

Download the latest release from
[Releases](https://github.com/aelred/factorio-opc/releases). The mod and the
bridge share a version number; use the same one for both.

1. **Mod:** copy `opc-io_<version>.zip` into the server's `mods/` folder.
   Players joining the server download it automatically.
2. **Server:** run Factorio 2.0 headless with RCON:
   `factorio --start-server <save> --rcon-port 27015 --rcon-password <pw>`.
   In its server settings, set `"auto_pause": false`.
3. **Bridge:** this needs Python 3.11 or newer.
   ```sh
   pipx install factorio_opc-<version>-py3-none-any.whl   # or pip install
   FACTORIO_RCON_PASSWORD=<pw> factorio-opc --rcon-host <server>
   ```
   For anything beyond a quick try, copy
   [bridge/example.toml](bridge/example.toml) and run
   `factorio-opc --config my.toml`.
4. **Client:** connect your OPC UA client to
   `opc.tcp://127.0.0.1:4840/factorio-opc/`.

In game, build an OPC Writer or Reader (unlocked by Circuit network), open
it to name its tag, and wire it into your circuits.

**Docker:** [deploy/compose.yml](deploy/compose.yml) runs a Factorio server
and the bridge together; see [docs/docker.md](docs/docker.md).

**Security:** by default the bridge accepts connections from this machine
only, with no login. To serve other machines, set up logins or encryption
first, as in [docs/security.md](docs/security.md). The bridge refuses to
expose unencrypted anonymous access to the network.

### Hosting from your own game instead of a server

A multiplayer game hosted from Factorio's menu can run RCON too, and you
are admin there, so the map editor and cheats are available. The
`--rcon-*` command-line flags don't apply to it. It uses two settings in
`config.ini` instead. Single player never runs RCON.

1. Copy `opc-io_<version>.zip` into your mods folder
   (macOS: `~/Library/Application Support/factorio/mods`).
2. **Quit Factorio**, then edit `config.ini`:
   - macOS: `~/Library/Application Support/factorio/config/config.ini`
   - Windows: `%APPDATA%\Factorio\config\config.ini`
   - Linux: `~/.factorio/config/config.ini`

   In its `[other]` section, uncomment and set:
   ```ini
   local-rcon-socket=127.0.0.1:27015
   local-rcon-password=<pw>
   ```
   The default `0.0.0.0:0` means RCON is off. `127.0.0.1` keeps RCON to
   your own machine. Edit the file with the game closed, because Factorio
   can overwrite `config.ini` when it exits.
3. Start Factorio, then choose Multiplayer → Host new game.
   `factorio-current.log` (in the folder above `config/`) should show
   `Starting RCON interface at IP ADDR:({127.0.0.1:27015})`.
4. Run `FACTORIO_RCON_PASSWORD=<pw> factorio-opc`.

### A desktop OPC UA client

FreeOpcUa's **opcua-client** works on macOS, Linux and Windows, with no
account needed. Use version 1.0.1:
```sh
uv tool install --python 3.14 "opcua-client==1.0.1"
```
Newer releases need Python 3.14, and on an older Python, pip installs the
buggy 0.8.4. 1.0.2's Call menu is broken.
[docs/address-space.md](docs/address-space.md#calling-the-methods-from-common-tools)
shows how to call methods from it and from the command line.

## Documentation

| Document | Contents |
|---|---|
| [docs/address-space.md](docs/address-space.md) | OPC UA nodes, status codes, events, polling |
| [docs/security.md](docs/security.md) | Endpoints, certificates, users and roles, audit log |
| [docs/docker.md](docs/docker.md) | Running Factorio and the bridge with Docker |
| [docs/protocol.md](docs/protocol.md) | The mod's RCON commands |
| [CHANGELOG.md](CHANGELOG.md) | Changes per version |

## Development

Requires Docker and Python 3.11+.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
scripts/dev-server.sh up          # Factorio 2.0.77 headless + opc-io; RCON on 127.0.0.1:27015
.venv/bin/pytest                  # unit + integration tests (integration is skipped without the server)
.venv/bin/pytest -m "not integration"
.venv/bin/factorio-opc --rcon-password-file .dev/factorio/config/rconpw   # bridge on the dev server
scripts/package-mod.sh            # dist/opc-io_<version>.zip
scripts/dev-server.sh down
```

- **Space Age:** `DLC_SPACE_AGE=true scripts/dev-server.sh up` adds Space
  Age and Quality, for testing quality signals.
- **Admin rights:** `FACTORIO_ADMINS=yourname scripts/dev-server.sh up`
  makes you admin when you join (at `localhost:34197`), so `/c`, `/editor`
  and `/cheat` work.
- **Server data:** this lives in `.dev/`, including the RCON password in
  `.dev/factorio/config/rconpw`. Run `scripts/dev-server.sh up` again after
  editing the mod.
- **CI:** GitHub Actions runs the unit tests on Python 3.11 and 3.13, the
  integration tests against a real headless server, and the package builds.

## License

MIT, see [LICENSE](LICENSE). The mod's graphics are the base game's
constant-combinator sprites, tinted. They are referenced from `__base__` at
runtime, not copied into this repository.
