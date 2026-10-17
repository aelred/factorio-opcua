# factorio-opc bridge

OPC UA server for Factorio 2.0 circuit networks. It talks over RCON to the
**opc-io** mod, which adds OPC Reader and OPC Writer combinators to the game.

```sh
pip install factorio-opc-<version>-py3-none-any.whl   # from a GitHub release
FACTORIO_RCON_PASSWORD=<pw> factorio-opc --rcon-host <server>
```

Then connect an OPC UA client to `opc.tcp://127.0.0.1:4840/factorio-opc/`.

Full documentation, the mod, and the Docker setup are at
https://github.com/aelred/factorio-opc.
