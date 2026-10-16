"""Bridge + asyncua client tests against an in-memory fake game."""

import asyncio
import json
import socket

import pytest
from asyncua import Client, ua

from factorio_opc import server as server_module
from factorio_opc.config import Config
from factorio_opc.server import Bridge

from fake_game import FakeGame, FakeWorld

NS = "urn:factorio-opc"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def eventually(check, timeout: float = 3.0):
    """Retry an async check until it stops failing (assertion or bad OPC status)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            return await check()
        except (AssertionError, ua.UaStatusCodeError):
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.05)


@pytest.fixture
def world():
    w = FakeWorld()
    w.add("reader", "line_1")
    w.add("writer", "press")
    w.set_reader("line_1", red={"item/iron-plate": 5}, green={"item/iron-plate": 2, "virtual/signal-A": -1})
    w.writers["press"] = {"virtual/signal-B": 3}
    return w


@pytest.fixture
async def bridge(world, monkeypatch):
    monkeypatch.setattr(server_module, "BACKOFF_START", 0.05)
    monkeypatch.setattr(server_module, "BACKOFF_MAX", 0.1)
    config = Config(rcon_password="x", endpoint=f"opc.tcp://127.0.0.1:{free_port()}/factorio-opc/", poll_hz=30)
    b = Bridge(config, game_factory=lambda: FakeGame(world))
    await b.start()
    await asyncio.wait_for(b.connected.wait(), 3)
    yield b
    await b.stop()


@pytest.fixture
async def client(bridge):
    c = Client(bridge.config.endpoint, timeout=5)
    await c.connect()
    c.ns = await c.get_namespace_index(NS)
    yield c
    await c.disconnect()


def node(client, path):
    return client.get_node(ua.NodeId(path, client.ns))


async def value(client, path):
    return await node(client, path).read_value()


async def test_browse_structure(client):
    factorio = await client.nodes.objects.get_child(f"{client.ns}:Factorio")
    names = {(await c.read_browse_name()).Name for c in await factorio.get_children()}
    assert names == {"Status", "Readers", "Writers"}

    async def readers_ready():
        reader = node(client, "Readers/line_1")
        channels = {(await c.read_browse_name()).Name for c in await reader.get_children()}
        assert channels == {"Red", "Green", "Total"}
        red = {(await c.read_browse_name()).Name for c in await node(client, "Readers/line_1/Red").get_children()}
        assert red == {"item/iron-plate", "virtual/signal-A"}  # signal-A is only on green

    await eventually(readers_ready)
    writer_children = {(await c.read_browse_name()).Name for c in await node(client, "Writers/press").get_children()}
    assert writer_children == {"Signals", "SetSignals", "ClearAll"}


async def test_reader_values_and_total(client, world):
    async def check():
        assert await value(client, "Readers/line_1/Red/item/iron-plate") == 5
        assert await value(client, "Readers/line_1/Green/item/iron-plate") == 2
        assert await value(client, "Readers/line_1/Total/item/iron-plate") == 7
        assert await value(client, "Readers/line_1/Total/virtual/signal-A") == -1
        assert await value(client, "Readers/line_1/Red/virtual/signal-A") == 0

    await eventually(check)
    world.set_reader("line_1", red={"item/iron-plate": 9})

    async def updated():
        assert await value(client, "Readers/line_1/Red/item/iron-plate") == 9
        # Signals that disappear stay as nodes with value 0.
        assert await value(client, "Readers/line_1/Green/virtual/signal-A") == 0
        assert await value(client, "Readers/line_1/Total/item/iron-plate") == 9

    await eventually(updated)


async def test_total_wraps_like_circuit_arithmetic(client, world):
    world.set_reader("line_1", red={"virtual/signal-A": 2**31 - 1}, green={"virtual/signal-A": 1})

    async def check():
        assert await value(client, "Readers/line_1/Total/virtual/signal-A") == -(2**31)

    await eventually(check)


async def test_status_nodes(client, world):
    async def check():
        assert await value(client, "Status/Connected") is True
        assert await value(client, "Status/FactorioVersion") == "2.0.77"
        assert await value(client, "Status/ModVersion") == "0.2.0"
        assert await value(client, "Status/GameTick") > 0
        assert await value(client, "Status/ModelVersion") == world.model_version

    await eventually(check)


async def test_subscription_gets_reader_changes(client, world):
    await eventually(lambda: value(client, "Readers/line_1/Red/item/iron-plate"))
    changes = asyncio.Queue()

    class Handler:
        def datachange_notification(self, n, val, data):
            changes.put_nowait(val)

    sub = await client.create_subscription(50, Handler())
    await sub.subscribe_data_change(node(client, "Readers/line_1/Red/item/iron-plate"))
    assert await asyncio.wait_for(changes.get(), 3) == 5
    world.set_reader("line_1", red={"item/iron-plate": 11})
    assert await asyncio.wait_for(changes.get(), 3) == 11
    await sub.delete()


async def test_write_signal_node_goes_to_game(client, world):
    target = node(client, "Writers/press/Signals/virtual/signal-B")
    await eventually(lambda: target.read_value())
    await target.write_value(ua.DataValue(ua.Variant(42, ua.VariantType.Int32)))
    assert world.writes[-1] == ("press", {"virtual/signal-B": 42}, "merge")
    assert world.writers["press"] == {"virtual/signal-B": 42}
    assert await target.read_value() == 42


async def test_write_accepts_integral_numbers_of_other_types(client, world):
    target = node(client, "Writers/press/Signals/virtual/signal-B")
    await eventually(lambda: target.read_value())
    await target.write_value(ua.DataValue(ua.Variant(7.0, ua.VariantType.Double)))
    assert world.writers["press"]["virtual/signal-B"] == 7
    with pytest.raises(ua.UaStatusCodeError) as err:
        await target.write_value(ua.DataValue(ua.Variant(7.5, ua.VariantType.Double)))
    assert err.value.code == ua.StatusCodes.BadTypeMismatch
    with pytest.raises(ua.UaStatusCodeError) as err:
        await target.write_value(ua.DataValue(ua.Variant(2**31, ua.VariantType.Int64)))
    assert err.value.code == ua.StatusCodes.BadOutOfRange


async def test_reader_nodes_are_read_only(client):
    target = node(client, "Readers/line_1/Red/item/iron-plate")
    await eventually(lambda: target.read_value())
    with pytest.raises(ua.UaStatusCodeError) as err:
        await target.write_value(ua.DataValue(ua.Variant(1, ua.VariantType.Int32)))
    assert err.value.code in (ua.StatusCodes.BadUserAccessDenied, ua.StatusCodes.BadNotWritable)


async def test_game_rejection_maps_to_bad_status(client, world):
    target = node(client, "Writers/press/Signals/virtual/signal-B")
    await eventually(lambda: target.read_value())
    world.reject_writes = "signal value out of int32 range"
    with pytest.raises(ua.UaStatusCodeError) as err:
        await target.write_value(ua.DataValue(ua.Variant(1, ua.VariantType.Int32)))
    assert err.value.code == ua.StatusCodes.BadInvalidArgument


async def test_set_signals_and_clear_all_methods(client, world):
    press = node(client, "Writers/press")
    await eventually(lambda: node(client, "Writers/press/Signals/virtual/signal-B").read_value())
    result = await press.call_method(ua.NodeId("Writers/press/SetSignals", client.ns),
                                     json.dumps({"item/iron-plate": 4}), "merge")
    assert json.loads(result) == {"item/iron-plate": 4, "virtual/signal-B": 3}
    assert await value(client, "Writers/press/Signals/item/iron-plate") == 4

    await press.call_method(ua.NodeId("Writers/press/ClearAll", client.ns))
    assert world.writers["press"] == {}
    assert await value(client, "Writers/press/Signals/item/iron-plate") == 0

    with pytest.raises(ua.UaStatusCodeError) as err:
        await press.call_method(ua.NodeId("Writers/press/SetSignals", client.ns), "not json", "merge")
    assert err.value.code == ua.StatusCodes.BadInvalidArgument
    with pytest.raises(ua.UaStatusCodeError) as err:
        await press.call_method(ua.NodeId("Writers/press/SetSignals", client.ns), "{}", "append")
    assert err.value.code == ua.StatusCodes.BadInvalidArgument


async def test_tags_added_and_removed_follow_model_version(client, world):
    world.add("writer", "new_one")

    async def added():
        children = {(await c.read_browse_name()).Name for c in await node(client, "Writers").get_children()}
        assert children == {"press", "new_one"}

    await eventually(added)
    world.remove("line_1")

    async def removed():
        assert await node(client, "Readers").get_children() == []

    await eventually(removed)


async def test_disconnect_marks_values_stale_then_recovers(client, world, bridge):
    path = "Readers/line_1/Red/item/iron-plate"
    await eventually(lambda: value(client, path))
    world.reachable = False

    async def stale():
        dv = await node(client, path).read_data_value(raise_on_bad_status=False)
        assert dv.StatusCode.value == ua.StatusCodes.UncertainNoCommunicationLastUsableValue
        assert dv.Value.Value == 5
        assert await value(client, "Status/Connected") is False

    await eventually(stale)
    target = node(client, "Writers/press/Signals/virtual/signal-B")
    with pytest.raises(ua.UaStatusCodeError) as err:
        await target.write_value(ua.DataValue(ua.Variant(1, ua.VariantType.Int32)))
    assert err.value.code == ua.StatusCodes.BadNoCommunication

    world.reachable = True

    async def recovered():
        dv = await node(client, path).read_data_value()
        assert dv.StatusCode.is_good()
        assert await value(client, "Status/Connected") is True

    await eventually(recovered)
    assert world.connections >= 2


async def test_non_signal_writes_pass_through(client):
    # Writing a read-only status variable is still refused by asyncua's own checks.
    with pytest.raises(ua.UaStatusCodeError):
        await node(client, "Status/GameTick").write_value(ua.DataValue(ua.Variant(1, ua.VariantType.UInt64)))


async def test_admin_username_does_not_bypass_access_levels(bridge):
    c = Client(bridge.config.endpoint, timeout=5)
    c.set_user("admin")
    c.set_password("anything")
    await c.connect()
    try:
        ns = await c.get_namespace_index(NS)
        target = c.get_node(ua.NodeId("Status/GameTick", ns))
        with pytest.raises(ua.UaStatusCodeError):
            await target.write_value(ua.DataValue(ua.Variant(1, ua.VariantType.UInt64)))
    finally:
        await c.disconnect()
