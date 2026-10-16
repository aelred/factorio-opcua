"""The real bridge (RconGame over RCON) against the live dev server, driven by an OPC UA client."""

import asyncio
import socket

from asyncua import Client, ua

from factorio_opc.config import Config
from factorio_opc.server import Bridge


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def eventually(check, timeout: float = 5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            return await check()
        except (AssertionError, ua.UaStatusCodeError):
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.05)


async def test_opc_write_reaches_reader_through_the_game(factorio, rcon):
    writer = await factorio.create("writer", 110, 10)
    reader = await factorio.create("reader", 112, 10)
    await factorio.wire(writer, reader, "green")
    await factorio.lua(f'return remote.call("opc-io", "rename", "{(await factorio.tag_by_unit(writer))["name"]}", "e2e_w")')
    await factorio.lua(f'return remote.call("opc-io", "rename", "{(await factorio.tag_by_unit(reader))["name"]}", "e2e_r")')

    config = Config(rcon_host=rcon.host, rcon_port=rcon.port, rcon_password=rcon._password,
                    endpoint=f"opc.tcp://127.0.0.1:{free_port()}/factorio-opc/", poll_hz=10)
    async with Bridge(config) as bridge:
        await asyncio.wait_for(bridge.connected.wait(), 10)
        client = Client(config.endpoint, timeout=5)
        await client.connect()
        try:
            ns = await client.get_namespace_index("urn:factorio-opc")

            def node(path):
                return client.get_node(ua.NodeId(path, ns))

            # New signals are added through the method, then written as plain variables.
            await node("Writers/e2e_w").call_method(ua.NodeId("Writers/e2e_w/SetSignals", ns),
                                                    '{"virtual/signal-A": 12}', "merge")

            async def first_reading():
                assert await node("Readers/e2e_r/Green/virtual/signal-A").read_value() == 12
                assert await node("Readers/e2e_r/Total/virtual/signal-A").read_value() == 12
                assert await node("Readers/e2e_r/Red/virtual/signal-A").read_value() == 0

            await eventually(first_reading)

            await node("Writers/e2e_w/Signals/virtual/signal-A").write_value(
                ua.DataValue(ua.Variant(-7, ua.VariantType.Int32)))

            async def second_reading():
                assert await node("Readers/e2e_r/Green/virtual/signal-A").read_value() == -7

            await eventually(second_reading)
            assert await node("Status/Connected").read_value() is True
            assert (await node("Status/FactorioVersion").read_value()).startswith("2.0")

            # The game validates writes; its rejection reaches the client as a bad status.
            try:
                result = await node("Writers/e2e_w").call_method(
                    ua.NodeId("Writers/e2e_w/SetSignals", ns), '{"item/unobtainium": 1}', "merge")
            except ua.UaStatusCodeError as exc:
                assert exc.code == ua.StatusCodes.BadInvalidArgument
            else:
                raise AssertionError(f"invalid signal was accepted: {result}")
        finally:
            await client.disconnect()
