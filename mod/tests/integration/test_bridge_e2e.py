"""The real bridge (RconGame over RCON) against the live dev server, driven by an OPC UA client."""

import asyncio

from asyncua import Client, ua

from factorio_opcua.config import Config
from factorio_opcua.server import Bridge

from helpers import eventually, free_port


async def test_opc_write_reaches_reader_through_the_game(factorio, rcon):
    writer = await factorio.create("writer", 110, 10)
    reader = await factorio.create("reader", 112, 10)
    await factorio.wire(writer, reader, "green")
    await factorio.lua(f'return remote.call("opcua-io", "rename", "{(await factorio.tag_by_unit(writer))["name"]}", "e2e_w")')
    await factorio.lua(f'return remote.call("opcua-io", "rename", "{(await factorio.tag_by_unit(reader))["name"]}", "e2e_r")')

    config = Config(rcon_host=rcon.host, rcon_port=rcon.port, rcon_password=rcon._password,
                    endpoint=f"opc.tcp://127.0.0.1:{free_port()}/factorio-opcua/", poll_hz=10, security=["none"])
    async with Bridge(config) as bridge:
        await asyncio.wait_for(bridge.connected.wait(), 10)
        client = Client(config.endpoint, timeout=5)
        await client.connect()
        try:
            ns = await client.get_namespace_index("urn:factorio-opcua")

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


async def test_rename_in_game_moves_nodes_and_emits_model_change(factorio, rcon):
    writer = await factorio.create("writer", 130, 10)
    old = (await factorio.tag_by_unit(writer))["name"]
    await factorio.command("opc_write", {"tag": old, "signals": {"virtual/signal-R": 9}})

    config = Config(rcon_host=rcon.host, rcon_port=rcon.port, rcon_password=rcon._password,
                    endpoint=f"opc.tcp://127.0.0.1:{free_port()}/factorio-opcua/", poll_hz=10, security=["none"])
    async with Bridge(config) as bridge:
        await asyncio.wait_for(bridge.connected.wait(), 10)
        client = Client(config.endpoint, timeout=5)
        await client.connect()
        try:
            ns = await client.get_namespace_index("urn:factorio-opcua")
            events = asyncio.Queue()

            class Handler:
                def event_notification(self, event):
                    events.put_nowait(event)

            sub = await client.create_subscription(50, Handler())
            await sub.subscribe_events(client.nodes.server,
                                       client.get_node(ua.ObjectIds.GeneralModelChangeEventType))
            assert await client.get_node(ua.NodeId(f"Writers/{old}/Signals/virtual/signal-R", ns)).read_value() == 9

            await factorio.lua(f'return remote.call("opcua-io", "rename", "{old}", "e2e_renamed")')
            changes = set()
            while ("Writers/e2e_renamed", 5) not in changes:
                event = await asyncio.wait_for(events.get(), 5)
                changes |= {(c.Affected.Identifier, c.Verb) for c in event.Changes}
            assert (f"Writers/{old}", 10) in changes
            new_value = client.get_node(ua.NodeId("Writers/e2e_renamed/Signals/virtual/signal-R", ns))
            assert await new_value.read_value() == 9
        finally:
            await client.disconnect()
