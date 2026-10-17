# Running with Docker

`deploy/compose.yml` runs a Factorio 2.0 headless server
(`factoriotools/factorio`) and the bridge side by side. RCON stays on the
compose network. The OPC UA port is published on this machine only.

## Start

From a clone of this repository:

```sh
cd deploy
mkdir -p factorio/mods
cp /path/to/opc-io_<version>.zip factorio/mods/   # from a GitHub release, or scripts/package-mod.sh
docker compose up -d
docker compose logs -f bridge                     # wait for "connected to Factorio"
```

Then connect an OPC UA client to `opc.tcp://127.0.0.1:4840/factorio-opc/`.

- **Data:** the Factorio server keeps its saves and config in
  `deploy/factorio/`. On first start it creates a map and an RCON password
  (`factorio/config/rconpw`), which the bridge reads.
- **Startup order:** if the bridge starts before that file exists, it exits
  and Docker restarts it.

## Server settings

On first start the Factorio image copies its default
`factorio/config/server-settings.json`. Edit it, then
`docker compose restart factorio`:
- **Auto-pause:** set `"auto_pause": false`. Otherwise, with no players, the
  bridge's polling is what advances the game (see `docs/spike-results.md`).
- **Server visibility and login:** the defaults publish the server and check
  players' factorio.com accounts. That needs your factorio.com username and
  token in the file. For a private server, set
  `"visibility": {"public": false, "lan": true}` and
  `"require_user_verification": false`.

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
docker build -t factorio-opc bridge
docker run --rm -p 127.0.0.1:4840:4840 -v "$PWD/my-bridge.toml:/config/bridge.toml:ro" factorio-opc
```

The image's command is `factorio-opc --config /config/bridge.toml`. Any
other arguments replace that, for example
`docker run --rm factorio-opc --version`.
