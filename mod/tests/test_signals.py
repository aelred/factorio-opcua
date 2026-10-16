import pytest

PROTOTYPES = """
{
  item = { ["iron-plate"] = {}, ["copper-plate"] = {} },
  fluid = { water = {} },
  virtual_signal = { ["signal-A"] = {}, ["signal-each"] = { special = true } },
  entity = {}, recipe = {}, space_location = {}, asteroid_chunk = {},
  quality = { normal = {}, rare = {} },
}
"""


@pytest.fixture
def signals(lua):
    return lua.eval('require("lib.signals")')


@pytest.fixture
def protos(lua):
    return lua.eval(PROTOTYPES)


def table(lua, py):
    return lua.table_from(py, recursive=True)


@pytest.mark.parametrize(
    "signal_id, key",
    [
        ({"name": "iron-plate"}, "item/iron-plate"),
        ({"type": "item", "name": "iron-plate", "quality": "normal"}, "item/iron-plate"),
        ({"type": "virtual", "name": "signal-A"}, "virtual/signal-A"),
        ({"type": "item", "name": "iron-plate", "quality": "rare"}, "item/iron-plate/rare"),
    ],
)
def test_key(lua, signals, signal_id, key):
    assert signals.key(table(lua, signal_id)) == key


def test_parse_key_round_trip(signals, to_py):
    assert to_py(signals.parse_key("item/iron-plate")) == {"type": "item", "name": "iron-plate", "quality": "normal"}
    assert to_py(signals.parse_key("virtual/signal-A/rare")) == {"type": "virtual", "name": "signal-A", "quality": "rare"}


@pytest.mark.parametrize("key", ["iron-plate", "item/", "/iron-plate", "item//x", "item/a/b/c", "bogus/iron-plate", 5])
def test_parse_key_rejects(call, signals, key):
    result, err = call(signals.parse_key, key)
    assert result is None and err


@pytest.mark.parametrize("value, ok", [(0, True), (5, True), (-2147483648, True), (2147483647, True),
                                       (2147483648, False), (1.5, False), ("5", False), (float("nan"), False)])
def test_validate_value(call, signals, value, ok):
    assert bool(call(signals.validate_value, value)[0]) is ok


def test_from_network_sums_and_normalizes(lua, signals, to_py):
    network = table(lua, [
        {"signal": {"name": "iron-plate"}, "count": 2},
        {"signal": {"type": "item", "name": "iron-plate", "quality": "normal"}, "count": 3},
        {"signal": {"type": "virtual", "name": "signal-A"}, "count": -1},
    ])
    assert to_py(signals.from_network(network)) == {"item/iron-plate": 5, "virtual/signal-A": -1}
    assert to_py(signals.from_network(None)) == {}


def test_filters_round_trip_sorted_and_drops_zero(lua, signals, to_py):
    filters = signals.to_filters(table(lua, {"virtual/signal-A": 1, "item/iron-plate/rare": 4, "fluid/water": 0}))
    py = to_py(filters)
    assert [f["value"]["name"] for f in py] == ["iron-plate", "signal-A"]
    assert py[0] == {"value": {"type": "item", "name": "iron-plate", "quality": "rare", "comparator": "="}, "min": 4}
    assert to_py(signals.from_filters(filters)) == {"item/iron-plate/rare": 4, "virtual/signal-A": 1}


def test_from_filters_ignores_empty_slots(lua, signals, to_py):
    filters = table(lua, [{"value": {"type": "item", "name": "iron-plate"}, "min": 0}, {"min": 3}])
    assert to_py(signals.from_filters(filters)) == {}


def test_apply_merge_and_replace(lua, signals, to_py):
    current = table(lua, {"a/x": 1, "a/y": 2})
    assert to_py(signals.apply(current, table(lua, {"a/y": 0, "a/z": 3}), "merge")) == {"a/x": 1, "a/z": 3}
    assert to_py(signals.apply(current, table(lua, {"a/z": 3}), "replace")) == {"a/z": 3}


def test_validate_updates_accepts_and_canonicalizes(call, lua, signals, protos, to_py):
    (result,) = call(signals.validate_updates, table(lua, {"item/iron-plate/normal": 5, "fluid/water": -1}), protos)
    assert to_py(result) == {"item/iron-plate": 5, "fluid/water": -1}


@pytest.mark.parametrize("updates, message", [
    ({"item/unobtainium": 1}, "unknown item signal"),
    ({"virtual/signal-each": 1}, "cannot be written"),
    ({"item/iron-plate/legendary": 1}, "unknown quality"),
    ({"item/iron-plate": 1.5}, "integer"),
    ({"nonsense": 1}, "invalid signal key"),
])
def test_validate_updates_rejects(call, lua, signals, protos, updates, message):
    result, err = call(signals.validate_updates, table(lua, updates), protos)
    assert result is None and message in err


def test_validate_updates_rejects_non_table(call, signals, protos):
    result, err = call(signals.validate_updates, "x", protos)
    assert result is None and err


def test_validate_updates_limits_count(call, lua, signals):
    many = {f"item/i{i}": 1 for i in range(1001)}
    big_protos = lua.eval("{ item = setmetatable({}, { __index = function() return {} end }), quality = { normal = {} } }")
    result, err = call(signals.validate_updates, table(lua, many), big_protos)
    assert result is None and "too many" in err
