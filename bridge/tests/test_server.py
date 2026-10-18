"""Bridge + asyncua client tests against an in-memory fake game."""

import asyncio
import json

import pytest
from asyncua import Client, ua

from factorio_opc import server as server_module
from factorio_opc.config import Config
from factorio_opc.server import Bridge

from fake_game import FakeGame, FakeWorld
from helpers import eventually, free_port

NS = "urn:factorio-opc"


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
    config = Config(rcon_password="x", endpoint=f"opc.tcp://127.0.0.1:{free_port()}/factorio-opc/", poll_hz=30,
                    security=["none"])
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
        assert await value(client, "Status/ModVersion") == "0.6.0"
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


async def test_set_signals_argument_handling(client, world):
    press = node(client, "Writers/press")
    method = ua.NodeId("Writers/press/SetSignals", client.ns)
    await eventually(lambda: node(client, "Writers/press/Signals/virtual/signal-B").read_value())
    # Mode is optional and defaults to merge.
    result = await press.call_method(method, json.dumps({"item/iron-plate": 1}))
    assert json.loads(result) == {"item/iron-plate": 1, "virtual/signal-B": 3}
    for args, code in (
        ((), ua.StatusCodes.BadArgumentsMissing),
        (("{}", "merge", "extra"), ua.StatusCodes.BadTooManyArguments),
        ((ua.Variant(5, ua.VariantType.Int32),), ua.StatusCodes.BadTypeMismatch),
    ):
        with pytest.raises(ua.UaStatusCodeError) as err:
            await press.call_method(method, *args)
        assert err.value.code == code, args
    with pytest.raises(ua.UaStatusCodeError) as err:
        await press.call_method(ua.NodeId("Writers/press/ClearAll", client.ns), "unexpected")
    assert err.value.code == ua.StatusCodes.BadTooManyArguments


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


async def test_unconfigured_user_names_are_refused(bridge):
    # Including "admin", which asyncua would otherwise grant the Admin role.
    c = Client(bridge.config.endpoint, timeout=5)
    c.set_user("admin")
    c.set_password("anything")
    with pytest.raises(ua.UaStatusCodeError):
        await c.connect()


async def test_first_poll_is_full_then_deltas(client, world):
    await eventually(lambda: value(client, "Readers/line_1/Red/item/iron-plate"))
    assert world.polls[0].full is True
    world.set_reader("line_1", red={"item/iron-plate": 6}, green={"item/iron-plate": 2})

    async def updated():
        assert await value(client, "Readers/line_1/Red/item/iron-plate") == 6
        assert await value(client, "Readers/line_1/Total/item/iron-plate") == 8
        # signal-A left the green wire: the delta carries it as 0.
        assert await value(client, "Readers/line_1/Green/virtual/signal-A") == 0
        assert await value(client, "Readers/line_1/Total/virtual/signal-A") == 0

    await eventually(updated)

    async def quiet_poll_seen():
        # Once values settle, polls carry no values at all.
        assert any(not p.readers and not p.writers for p in world.polls[1:])

    await eventually(quiet_poll_seen)
    assert not any(p.full for p in world.polls[1:])


async def test_mod_losing_session_state_triggers_full_resync(client, world):
    """E.g. the server reloaded an older save: its session state no longer matches our ack."""
    await eventually(lambda: value(client, "Readers/line_1/Red/item/iron-plate"))
    world.sessions.clear()
    world.set_reader("line_1", red={"item/iron-plate": 42})

    async def resynced():
        assert await value(client, "Readers/line_1/Red/item/iron-plate") == 42
        assert await value(client, "Readers/line_1/Green/item/iron-plate") == 0

    await eventually(resynced)
    assert sum(p.full for p in world.polls) == 2


async def test_model_change_events_for_added_and_removed_tags(client, world):
    await eventually(lambda: value(client, "Readers/line_1/Red/item/iron-plate"))
    events = asyncio.Queue()

    class Handler:
        def event_notification(self, event):
            events.put_nowait(event)

    sub = await client.create_subscription(50, Handler())
    await sub.subscribe_events(client.nodes.server, client.get_node(ua.ObjectIds.GeneralModelChangeEventType))

    async def next_changes():
        event = await asyncio.wait_for(events.get(), 3)
        return {(c.Affected.Identifier, c.Verb) for c in event.Changes}

    world.add("writer", "added_w")
    world.writers["added_w"] = {"virtual/signal-Z": 1}
    changes = await next_changes()
    assert ("Writers/added_w", 5) in changes                          # NodeAdded | ReferenceAdded
    assert ("Writers/added_w/Signals/virtual/signal-Z", 5) in changes

    world.remove("line_1")
    assert ("Readers/line_1", 10) in await next_changes()             # NodeDeleted | ReferenceDeleted
    await sub.delete()


def test_model_change_message_names_tags():
    from factorio_opc.model import VERB_ADDED, VERB_DELETED, describe_changes

    def change(path, type_id, verb):
        return ua.ModelChangeStructureDataType(Affected=ua.NodeId(path, 2), AffectedType=ua.NodeId(type_id), Verb=verb)

    tag, var = ua.ObjectIds.BaseObjectType, ua.ObjectIds.BaseDataVariableType
    message = describe_changes([change("Writers/press_2", tag, VERB_ADDED), change("Writers/press", tag, VERB_DELETED),
                                change("Writers/press_2/Signals/item/iron-plate", var, VERB_ADDED)])
    assert message == "Added Writers/press_2; removed Writers/press; 1 new signal node"
    many = describe_changes([change(f"Readers/r{i}", tag, VERB_ADDED) for i in range(7)])
    assert many == "Added Readers/r0, Readers/r1, Readers/r2, Readers/r3, Readers/r4 and 2 more"


async def test_subscribers_of_a_removed_tag_get_a_bad_status(client, world):
    await eventually(lambda: value(client, "Readers/line_1/Red/item/iron-plate"))
    updates = asyncio.Queue()

    class Handler:
        def datachange_notification(self, n, val, data):
            updates.put_nowait(data.monitored_item.Value.StatusCode)

    sub = await client.create_subscription(50, Handler())
    await sub.subscribe_data_change(node(client, "Readers/line_1/Red/item/iron-plate"))
    assert (await asyncio.wait_for(updates.get(), 3)).is_good()
    world.remove("line_1")
    status = await asyncio.wait_for(updates.get(), 3)
    assert status.value == ua.StatusCodes.BadNodeIdUnknown


async def test_rename_moves_values_to_new_nodes(client, world):
    await eventually(lambda: value(client, "Writers/press/Signals/virtual/signal-B"))
    values = world.writers["press"]
    world.remove("press")
    world.add("writer", "press_renamed")
    world.writers["press_renamed"] = values

    async def moved():
        assert await value(client, "Writers/press_renamed/Signals/virtual/signal-B") == 3
        with pytest.raises(ua.UaStatusCodeError):
            await value(client, "Writers/press/Signals/virtual/signal-B")

    await eventually(moved)


async def test_metrics(client, world):
    target = node(client, "Writers/press/Signals/virtual/signal-B")
    await eventually(lambda: target.read_value())
    await target.write_value(ua.DataValue(ua.Variant(5, ua.VariantType.Int32)))
    world.reject_writes = "nope"
    with pytest.raises(ua.UaStatusCodeError):
        await target.write_value(ua.DataValue(ua.Variant(6, ua.VariantType.Int32)))
    world.reject_writes = None

    async def counted():
        assert await value(client, "Status/Polls") > 1
        assert await value(client, "Status/Writes") == 1
        assert await value(client, "Status/WriteErrors") == 1
        assert await value(client, "Status/Tags") == 2
        assert await value(client, "Status/SignalNodes") >= 7  # 2 reader signals x 3 channels + 1 writer signal
        assert await value(client, "Status/ConnectedSince") is not None
        assert await value(client, "Status/Reconnects") == 0

    await eventually(counted)
    world.reachable = False

    async def disconnected():
        assert await value(client, "Status/Connected") is False

    await eventually(disconnected)
    world.reachable = True

    async def reconnected():
        assert await value(client, "Status/Reconnects") == 1

    await eventually(reconnected)


async def test_writes_are_audit_logged(client, world, caplog):
    target = node(client, "Writers/press/Signals/virtual/signal-B")
    await eventually(lambda: target.read_value())
    with caplog.at_level("INFO", logger="factorio_opc"):
        await target.write_value(ua.DataValue(ua.Variant(9, ua.VariantType.Int32)))
        await node(client, "Writers/press").call_method(ua.NodeId("Writers/press/SetSignals", client.ns),
                                                       '{"item/iron-plate": 2}')
    audits = [r for r in caplog.records if getattr(r, "tag", None) == "press"]
    assert [(r.via, r.result, r.user, r.signals) for r in audits] == [
        ("write", "ok", "anonymous", {"virtual/signal-B": 9}),
        ("method", "ok", "anonymous", {"item/iron-plate": 2}),
    ]


def test_json_log_format():
    import logging

    from factorio_opc.logs import JsonFormatter

    record = logging.LogRecord("factorio_opc", logging.INFO, __file__, 1, "write %s", ("press",), None)
    record.tag, record.user = "press", "alice"
    entry = json.loads(JsonFormatter().format(record))
    assert entry["message"] == "write press" and entry["level"] == "INFO"
    assert entry["tag"] == "press" and entry["user"] == "alice" and "time" in entry


async def test_a_few_poll_timeouts_do_not_reconnect(bridge, world, monkeypatch):
    monkeypatch.setattr(server_module, "MAX_POLL_TIMEOUTS", 3)
    world.poll_timeouts = 2  # the game is busy, e.g. saving
    polls = len(world.polls)

    async def polled_again():
        assert len(world.polls) > polls + 2

    await eventually(polled_again)
    assert world.connections == 1

    world.poll_timeouts = 3

    async def reconnected():
        assert world.connections == 2

    await eventually(reconnected)


async def test_game_loop_survives_errors_while_marking_stale(bridge, world, monkeypatch):
    async def broken():
        raise RuntimeError("boom")

    monkeypatch.setattr(bridge.model, "mark_stale", broken)
    world.reachable = False

    async def disconnected():
        assert not bridge.connected.is_set()

    await eventually(disconnected)
    world.reachable = True

    async def reconnected():
        assert bridge.connected.is_set() and world.connections >= 2

    await eventually(reconnected)
