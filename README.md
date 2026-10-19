# factorio-opcua

Connect Factorio 2.0 circuit networks to **OPC UA**, the standard protocol
of industrial automation. SCADA systems, PLCs and OPC clients such as
Ignition, Node-RED, UaExpert or FreeOpcUa's opcua-client can then read
signals from your factory and drive it.

```
                                                ┌──────────┐
                                                │ Factorio │
 ┌─────────────┐          ┌─bridge───────┐      │┌─mod────┐│
 │OPC UA client├─opc.tcp─►│factorio-opcua│─RCON─►│opcua-io││
 └─────────────┘          └──────────────┘      │└────────┘│
                                                └──────────┘
```

There are two parts:
- **opcua-io** (`mod/opcua-io`): a Factorio mod that adds two combinators.
  - **OPC Reader:** publishes the red and green signals wired to it.
  - **OPC Writer:** outputs signals set by OPC clients.

  Each has a tag name, which becomes its name in OPC.
- **factorio-opcua** (`bridge/`): an OPC UA server, written in Python with
  asyncua. It polls the mod over RCON and serves:
  - `Readers/<tag>/{Red,Green,Total}/<signal>`,
  - writable `Writers/<tag>/Signals/<signal>`,
  - `Status/` and metrics.

  It supports logins, read-only users, encryption and an audit log of every
  write.

## Install

Download the latest release from
[Releases](https://github.com/aelred/factorio-opcua/releases). The mod and the
bridge share a version number; use the same one for both.

### 1. Run Factorio with the mod and RCON

Choose either option. The bridge works the same with both.

**A. A dedicated server**
1. Copy `opcua-io_<version>.zip` into the server's `mods/` folder. Players
   need it in their own mods folder too: Factorio only downloads mods from
   the mod portal, and opcua-io isn't there.
2. Start the server with RCON:
   `factorio --start-server <save> --rcon-port 27015 --rcon-password <pw>`.
3. In its server settings, set `"auto_pause": false`. Otherwise, with no
   players online, the bridge's polling is what moves the game forward.

To run the server and the bridge together in Docker, see
[docs/docker.md](docs/docker.md).

**B. Your own game, hosted from the main menu**
1. Copy `opcua-io_<version>.zip` into your mods folder:
   - macOS: `~/Library/Application Support/factorio/mods`
   - Windows: `%APPDATA%\Factorio\mods`
   - Linux: `~/.factorio/mods`
2. Turn on RCON for games you host:
   - In the main menu, hold **Ctrl + Alt** (Ctrl + Option on a Mac) and
     click **Settings**. A **The rest** button appears; click it.
   - Set `local-rcon-socket` to `127.0.0.1:27015`. Use the IP address,
     not `localhost`. The default `0.0.0.0:0` means RCON is off.
   - Set `local-rcon-password` to a password of your choice.
   - Restart Factorio; most settings on this page only take effect after
     a restart.
3. Choose **Multiplayer → Host new game** (or Host saved game). Single
   player never runs RCON.

You're the host, so you're admin: the map editor and cheats work. With
you in the game, auto-pause doesn't apply.

### 2. Run the bridge

This needs Python 3.11 or newer.
```sh
pipx install factorio_opcua-<version>-py3-none-any.whl   # or pip install
FACTORIO_RCON_PASSWORD=<pw> factorio-opcua --rcon-host <server>   # leave out --rcon-host for your own game
```
For anything beyond a quick try, copy
[bridge/example.toml](bridge/example.toml) and run
`factorio-opcua --config my.toml`.

### 3. Connect and build

Connect your OPC UA client to `opc.tcp://127.0.0.1:4840/factorio-opcua/`.
In game, build an OPC Writer or Reader (unlocked by Circuit network), open
it to name its tag, and wire it into your circuits.

**To try it out first,** type `/opc_demo` in chat. It builds a demo on a
separate surface, with a clock, lamps and a small production line whose
switch and status codes you can read and write over OPC UA. See
[docs/demo.md](docs/demo.md).

**Security:** by default the bridge accepts connections from this machine
only, with no login. To serve other machines, set up logins or encryption
first, as in [docs/security.md](docs/security.md). The bridge refuses to
expose unencrypted anonymous access to the network.

### A desktop OPC UA client

FreeOpcUa's **opcua-client** works on macOS, Linux and Windows, with no
account needed. Use version 1.0.1, which needs Python 3.14 (in 1.0.2,
right-click Call crashes):
```sh
uv tool install --python 3.14 "opcua-client==1.0.1"
```
[docs/address-space.md](docs/address-space.md#calling-the-methods-from-common-tools)
shows how to call methods from it and from the command line.

## Documentation

| Document | Contents |
|---|---|
| [docs/demo.md](docs/demo.md) | The `/opc_demo` demo: what's in it and what to try |
| [docs/address-space.md](docs/address-space.md) | OPC UA nodes, status codes, events, polling |
| [docs/security.md](docs/security.md) | Endpoints, certificates, users and roles, audit log |
| [docs/docker.md](docs/docker.md) | Running Factorio and the bridge with Docker |
| [docs/protocol.md](docs/protocol.md) | The mod's RCON commands |
| [CHANGELOG.md](CHANGELOG.md) | Changes per version |

## Development

Requires Docker and Python 3.11+.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
scripts/dev-server.sh up          # Factorio 2.0.77 headless + opcua-io; RCON on 127.0.0.1:27015
scripts/dev-server.sh demo        # build the /opc_demo surface (docs/demo.md)
.venv/bin/pytest                  # unit + integration tests (integration is skipped without the server)
.venv/bin/pytest -m "not integration"
.venv/bin/ruff check .            # lint (rules in ruff.toml)
.venv/bin/factorio-opcua --rcon-password-file .dev/factorio/config/rconpw   # bridge on the dev server
scripts/package-mod.sh            # dist/opcua-io_<version>.zip
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

### Conventions

- **Never let a Lua error escape.** In multiplayer, an uncaught error in a
  command or event handler stops the whole server. Register RCON commands
  through `rcon_only` in `mod/opcua-io/lib/api.lua`, which turns errors into
  JSON error replies, and event handlers through `safe` in
  `mod/opcua-io/control.lua`.
- **Protocol changes:** when the RCON protocol changes, bump both
  `api.PROTO` in `mod/opcua-io/lib/api.lua` and `PROTO` in
  `bridge/factorio_opcua/game.py`. The bridge refuses to talk to a mod with
  a different protocol.
- **No certificates in tests:** tests that start a `Bridge` should pass
  `security=["none"]` or a temporary `pki_dir`. Otherwise they write a
  certificate to `~/.factorio-opcua`.

## License

MIT, see [LICENSE](LICENSE). The mod's graphics are the base game's
constant-combinator sprites, tinted. They are referenced from `__base__` at
runtime, not copied into this repository.
