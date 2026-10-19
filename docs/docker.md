# Running with Docker

`deploy/compose.yml` runs a Factorio 2.0 headless server
(`factoriotools/factorio`) and the bridge side by side. RCON stays on the
compose network. The OPC UA port is published on this machine only.

## Start

From a clone of this repository:

```sh
cd deploy
docker compose up -d --wait   # returns once both are running
```

Then connect an OPC UA client to `opc.tcp://127.0.0.1:4840/factorio-opcua/`.

- **Data:** the Factorio server keeps its saves and config in
  `deploy/factorio/`. On first start it creates a map and an RCON password
  (`factorio/config/rconpw`), which the bridge reads.
- **The mod:** on every start, the short-lived `setup` service copies
  opcua-io from this checkout into `factorio/mods/`, so the mod always
  matches the bridge. Don't add an opcua-io zip there yourself; it's removed.
- **Startup order:** the bridge starts only once the Factorio service is
  healthy, meaning RCON answers and opcua-io replies to `/opc_hello`.
  `docker compose ps` shows this.
- **Updating:** after `git pull`, run
  `docker compose up -d --build --force-recreate --wait`. That rebuilds the
  bridge, reinstalls the mod and restarts both.

## Server settings

On first start, `deploy/server-settings.json` is copied to
`factorio/config/server-settings.json`. It differs from Factorio's defaults
in three ways:
- **Not published:** the server is visible on your LAN only.
- **No account check:** players don't need a factorio.com login, so the
  server needs no factorio.com credentials. Set
  `"require_user_verification": true` to check accounts.
- **No auto-pause:** the game keeps running with no players online.
  Otherwise the bridge's polling is what advances the game: each RCON
  command moves a paused game on by one tick.

To change settings, edit `factorio/config/server-settings.json` (not the
copy in `deploy/`, which is only used on first start), then
`docker compose restart factorio`. To publish the server on the public
server list, set `"visibility": {"public": true, "lan": true}` and add your
factorio.com `username` and `token`.

## Bridge settings

Bridge settings are in `deploy/bridge.toml`; restart with
`docker compose restart bridge`.
- **Network access:** the bridge listens on all interfaces *inside* its
  container, and the port mapping in `compose.yml` decides who can reach it.
  It is `127.0.0.1:4840`, this machine only, which is why the example sets
  `allow_insecure = true`.
- **Before publishing the port to your network**, change it to `4840:4840`,
  then set up logins or encryption as in [security.md](security.md), and
  remove `allow_insecure`.
- **Password hashes:** `docker compose run --rm bridge hash-password` makes
  one.
- **Certificate:** the server certificate is kept in the `bridge-data`
  volume, so clients only need to trust it once.

## Build and run the image by itself

```sh
docker build -t factorio-opcua bridge
docker run --rm -p 127.0.0.1:4840:4840 -v "$PWD/my-bridge.toml:/config/bridge.toml:ro" factorio-opcua
```

The image's command is `factorio-opcua --config /config/bridge.toml`. Any
other arguments replace that, for example
`docker run --rm factorio-opcua --version`.
