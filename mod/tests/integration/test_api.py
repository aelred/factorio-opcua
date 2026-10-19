"""End-to-end tests of the opcua-io RCON API against a live Factorio server."""

import pytest


async def test_hello(factorio):
    hello = await factorio.command("opc_hello")
    assert hello["ok"] is True
    assert hello["proto"] == 1
    assert hello["factorio_version"].startswith("2.0")
    assert isinstance(hello["model_version"], int)


async def test_built_entities_get_default_names_and_appear_in_browse(factorio):
    before = (await factorio.command("opc_hello"))["model_version"]
    reader = await factorio.create("reader", 10, 10)
    writer = await factorio.create("writer", 12, 10)
    browse = await factorio.command("opc_browse")
    by_unit = {t["unit"]: t for t in browse["tags"]}
    assert by_unit[reader]["kind"] == "reader" and by_unit[reader]["name"].startswith("reader-")
    assert by_unit[writer]["kind"] == "writer" and by_unit[writer]["name"].startswith("writer-")
    assert browse["model_version"] >= before + 2
    assert [t["name"] for t in browse["tags"]] == sorted(t["name"] for t in browse["tags"])


async def test_write_reaches_wired_reader(factorio):
    writer = await factorio.create("writer", 10, 12)
    reader = await factorio.create("reader", 12, 12)
    await factorio.wire(writer, reader, "red")
    w = (await factorio.tag_by_unit(writer))["name"]
    r = (await factorio.tag_by_unit(reader))["name"]

    reply = await factorio.command("opc_write", {"tag": w, "signals": {"item/iron-plate": 5, "virtual/signal-A": -3}})
    assert reply == {"ok": True, "tick": reply["tick"], "tag": w,
                     "signals": {"item/iron-plate": 5, "virtual/signal-A": -3}}
    await factorio.ticks(2)

    snap = await factorio.values()
    assert snap["writers"][w] == {"item/iron-plate": 5, "virtual/signal-A": -3}
    assert snap["readers"][r]["red"] == {"item/iron-plate": 5, "virtual/signal-A": -3}
    assert not snap["readers"][r]["green"]  # empty map encodes as {} (or [])


async def test_reader_sums_and_separates_wire_colours(factorio):
    w1 = await factorio.create("writer", 20, 10)
    w2 = await factorio.create("writer", 20, 12)
    reader = await factorio.create("reader", 22, 11)
    await factorio.wire(w1, reader, "red")
    await factorio.wire(w2, reader, "red")
    await factorio.wire(w2, reader, "green")
    n1 = (await factorio.tag_by_unit(w1))["name"]
    n2 = (await factorio.tag_by_unit(w2))["name"]
    r = (await factorio.tag_by_unit(reader))["name"]
    await factorio.command("opc_write", {"tag": n1, "signals": {"virtual/signal-A": 2}})
    await factorio.command("opc_write", {"tag": n2, "signals": {"virtual/signal-A": 3, "fluid/water": 1}})
    await factorio.ticks(2)
    readings = (await factorio.values())["readers"][r]
    assert readings["red"] == {"virtual/signal-A": 5, "fluid/water": 1}
    assert readings["green"] == {"virtual/signal-A": 3, "fluid/water": 1}


async def test_merge_replace_and_zero_removes(factorio):
    unit = await factorio.create("writer", 30, 10)
    w = (await factorio.tag_by_unit(unit))["name"]
    await factorio.command("opc_write", {"tag": w, "signals": {"item/iron-plate": 1, "item/copper-plate": 2}})
    merged = await factorio.command("opc_write", {"tag": w, "signals": {"item/iron-plate": 0, "fluid/water": 9}})
    assert merged["signals"] == {"item/copper-plate": 2, "fluid/water": 9}
    replaced = await factorio.command("opc_write", {"tag": w, "signals": {"virtual/signal-B": 4}, "mode": "replace"})
    assert replaced["signals"] == {"virtual/signal-B": 4}
    cleared = await factorio.command("opc_write", {"tag": w, "signals": {}, "mode": "replace"})
    assert not cleared["signals"]
    assert not (await factorio.values())["writers"][w]


async def test_reader_emits_nothing_and_writer_keeps_one_ungrouped_section(factorio):
    reader = await factorio.create("reader", 40, 10)
    writer = await factorio.create("writer", 42, 10)
    state = await factorio.lua(
        f"local r = {factorio.ref(reader)}.get_control_behavior() "
        f"local w = {factorio.ref(writer)}.get_control_behavior() "
        "return r.sections_count .. ',' .. tostring(r.enabled) .. ',' .. w.sections_count .. ',' "
        ".. tostring(w.enabled) .. ',' .. w.get_section(1).group"
    )
    assert state == "0,false,1,true,"
    # Not operable: the game doesn't open its own combinator window (the mod opens its panel).
    operable = f"return tostring({factorio.ref(reader)}.operable) .. ',' .. tostring({factorio.ref(writer)}.operable)"
    assert await factorio.lua(operable) == "false,false"


@pytest.mark.parametrize("payload, message", [
    ("", "missing JSON parameter"),
    ("{not json", "not valid JSON"),
    ({"signals": {}}, "'tag' must be a string"),
    ({"tag": "does-not-exist", "signals": {}}, "unknown tag"),
    ({"tag": "WRITER", "signals": {"item/iron-plate": 1}, "mode": "add"}, "'mode' must be"),
    ({"tag": "WRITER", "signals": {"item/unobtainium": 1}}, "unknown item signal"),
    ({"tag": "WRITER", "signals": {"virtual/signal-everything": 1}}, "cannot be written"),
    ({"tag": "WRITER", "signals": {"item/iron-plate": 2147483648}}, "int32"),
    ({"tag": "WRITER", "signals": {"item/iron-plate": 1.5}}, "integer"),
    ({"tag": "WRITER", "signals": {"iron-plate": 1}}, "invalid signal key"),
    ({"tag": "WRITER", "signals": [1, 2]}, "signal key must be a string"),
    ({"tag": "READER", "signals": {"item/iron-plate": 1}}, "is a reader"),
])
async def test_write_errors_are_reported_and_server_survives(factorio, payload, message):
    names = {}
    for kind, x in (("writer", 50), ("reader", 52)):
        names[kind.upper()] = (await factorio.tag_by_unit(await factorio.create(kind, x, 10)))["name"]
    if isinstance(payload, dict) and payload.get("tag") in names:
        payload = {**payload, "tag": names[payload["tag"]]}
    reply = await factorio.command("opc_write", payload)
    assert reply["ok"] is False
    assert message in reply["error"]
    assert (await factorio.command("opc_hello"))["ok"] is True


async def test_destroyed_entity_is_removed(factorio):
    unit = await factorio.create("writer", 60, 10)
    before = (await factorio.command("opc_hello"))["model_version"]
    await factorio.destroy(unit)
    await factorio.ticks(2)
    assert await factorio.tag_by_unit(unit) is None
    assert (await factorio.command("opc_hello"))["model_version"] > before


async def test_blueprint_tag_sets_name_and_collisions_get_suffix(factorio):
    first = await factorio.create("writer", 70, 10, tags={"opc_name": "press_line"})
    second = await factorio.create("writer", 72, 10, tags={"opc_name": "press_line"})
    bad = await factorio.create("reader", 74, 10, tags={"opc_name": "not valid!"})
    assert (await factorio.tag_by_unit(first))["name"] == "press_line"
    assert (await factorio.tag_by_unit(second))["name"] == "press_line-2"
    assert (await factorio.tag_by_unit(bad))["name"].startswith("reader-")



@pytest.mark.parametrize("kind", ["reader", "writer"])
async def test_name_survives_death_and_rebuild_from_ghost(factorio, kind):
    unit = await factorio.create(kind, 76, 10, tags={"opc_name": f"{kind}_survivor"})
    await factorio.lua("game.forces.player.create_ghost_on_entity_death = true")
    await factorio.lua(f'{factorio.ref(unit)}.die("enemy")')
    rebuilt = await factorio.lua(
        'local g = game.surfaces.nauvis.find_entity("entity-ghost", {76.5, 10.5}) '
        "local _, e = g.revive{raise_revive=true} return e.unit_number")
    await factorio.ticks()
    assert (await factorio.tag_by_unit(int(rebuilt)))["name"] == f"{kind}_survivor"


async def test_write_repairs_a_writer_whose_section_was_removed(factorio):
    unit = await factorio.create("writer", 78, 10)
    name = (await factorio.tag_by_unit(unit))["name"]
    await factorio.lua(f"{factorio.ref(unit)}.get_control_behavior().remove_section(1)")
    write = await factorio.command("opc_write", {"tag": name, "signals": {"virtual/signal-A": 4}})
    assert write["ok"] is True
    assert (await factorio.values())["writers"][name] == {"virtual/signal-A": 4}

async def test_rename_via_remote_interface(factorio):
    a = await factorio.create("writer", 80, 10)
    b = await factorio.create("writer", 82, 10)
    name_a = (await factorio.tag_by_unit(a))["name"]
    name_b = (await factorio.tag_by_unit(b))["name"]
    before = (await factorio.command("opc_hello"))["model_version"]

    assert await factorio.lua(f'return remote.call("opcua-io", "rename", "{name_a}", "boiler_feed")') == ""
    assert (await factorio.tag_by_unit(a))["name"] == "boiler_feed"
    assert (await factorio.command("opc_hello"))["model_version"] == before + 1
    clash = await factorio.lua(f'return remote.call("opcua-io", "rename", "{name_b}", "boiler_feed")')
    assert "already used" in clash
    invalid = await factorio.lua(f'return remote.call("opcua-io", "rename", "{name_b}", "has space")')
    assert "may only contain" in invalid
    assert await factorio.lua(f"return remote.call('opcua-io', 'get_name', {factorio.ref(a)})") \
        == "boiler_feed"
    write = await factorio.command("opc_write", {"tag": "boiler_feed", "signals": {"virtual/signal-A": 1}})
    assert write["ok"] is True


async def test_poll_full_then_deltas(factorio):
    writer = await factorio.create("writer", 120, 10)
    reader = await factorio.create("reader", 122, 10)
    await factorio.wire(writer, reader, "red")
    w = (await factorio.tag_by_unit(writer))["name"]
    r = (await factorio.tag_by_unit(reader))["name"]
    session = "itest-poll"

    first = await factorio.command("opc_poll", {"session": session, "full": True})
    assert first["ok"] and first["full"] is True
    assert {"tick_paused", "speed", "model_version", "tick", "seq"} <= set(first)
    assert r in first["readers"] and w in first["writers"]

    quiet = await factorio.command("opc_poll", {"session": session, "ack": first["seq"]})
    assert quiet["full"] is False and quiet["seq"] == first["seq"] + 1
    assert not quiet["readers"] and not quiet["writers"] and not quiet["removed"]

    await factorio.command("opc_write", {"tag": w, "signals": {"virtual/signal-A": 4}})
    await factorio.ticks(2)
    changed = await factorio.command("opc_poll", {"session": session, "ack": quiet["seq"]})
    assert changed["writers"] == {w: {"virtual/signal-A": 4}}
    assert changed["readers"] == {r: {"red": {"virtual/signal-A": 4}, "green": {}}}

    # A stale ack (e.g. the bridge missed a reply) gets a full resync.
    resync = await factorio.command("opc_poll", {"session": session, "ack": quiet["seq"]})
    assert resync["full"] is True and resync["writers"][w] == {"virtual/signal-A": 4}

    await factorio.destroy(reader)
    await factorio.ticks(2)
    gone = await factorio.command("opc_poll", {"session": session, "ack": resync["seq"]})
    assert gone["removed"] == [r]


@pytest.mark.parametrize("payload, message", [
    ("", "missing JSON parameter"),
    ({}, "'session' must be"),
    ({"session": "a b"}, "'session' must be"),
    ({"session": "ok", "ack": "1"}, "'ack' must be an integer"),
])
async def test_poll_rejects_bad_requests(factorio, payload, message):
    reply = await factorio.command("opc_poll", payload)
    assert reply["ok"] is False and message in reply["error"]
