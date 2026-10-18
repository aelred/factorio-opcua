# factorio-opcua bridge

OPC UA server for Factorio 2.0 circuit networks. It talks over RCON to the
**opcua-io** mod, which adds OPC Reader and OPC Writer combinators to the game.

```sh
pip install factorio_opcua-<version>-py3-none-any.whl   # from a GitHub release
FACTORIO_RCON_PASSWORD=<pw> factorio-opcua --rcon-host <server>
```

Then connect an OPC UA client to `opc.tcp://127.0.0.1:4840/factorio-opcua/`.

Full documentation, the mod, and the Docker setup are at
https://github.com/aelred/factorio-opcua.
