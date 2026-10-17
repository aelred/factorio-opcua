import pytest


@pytest.fixture
def poll(lua):
    return lua.eval('require("lib.poll")')


@pytest.fixture
def values(lua):
    """Build a values table: values(readers={...}, writers={...})."""

    def make(readers=None, writers=None):
        return lua.table_from({"readers": readers or {}, "writers": writers or {}}, recursive=True)

    return make


def test_diff(lua, poll, to_py):
    t = lambda d: lua.table_from(d)
    assert to_py(poll.diff(t({"a": 1, "b": 2}), t({"a": 1, "b": 3, "c": 4}))) == {"b": 3, "c": 4}
    assert to_py(poll.diff(t({"a": 1, "b": 2}), t({"a": 1}))) == {"b": 0}
    assert poll.diff(t({"a": 1}), t({"a": 1})) is None


def test_first_poll_is_full_then_deltas(lua, poll, values, to_py):
    sessions = lua.table()
    v1 = values(readers={"r": {"red": {"x": 1}, "green": {}}}, writers={"w": {"y": 2}})
    first = to_py(poll.step(sessions, "s1", None, False, v1, 100))
    assert first["full"] is True and first["seq"] == 1
    assert first["readers"] == {"r": {"red": {"x": 1}, "green": {}}} and first["writers"] == {"w": {"y": 2}}

    unchanged = to_py(poll.step(sessions, "s1", 1, False, values(
        readers={"r": {"red": {"x": 1}, "green": {}}}, writers={"w": {"y": 2}}), 101))
    assert unchanged["full"] is False and unchanged["seq"] == 2
    assert unchanged["readers"] == {} and unchanged["writers"] == {} and unchanged["removed"] == {}

    changed = to_py(poll.step(sessions, "s1", 2, False, values(
        readers={"r": {"red": {"x": 5}, "green": {"z": 1}}}, writers={"w": {}}), 102))
    assert changed["readers"] == {"r": {"red": {"x": 5}, "green": {"z": 1}}}
    assert changed["writers"] == {"w": {"y": 0}}


def test_only_the_changed_wire_is_reported(lua, poll, values, to_py):
    sessions = lua.table()
    poll.step(sessions, "s", None, False, values(readers={"r": {"red": {"x": 1}, "green": {"g": 1}}}), 1)
    delta = to_py(poll.step(sessions, "s", 1, False, values(readers={"r": {"red": {"x": 2}, "green": {"g": 1}}}), 2))
    assert delta["readers"] == {"r": {"red": {"x": 2}, "green": {}}}


def test_new_and_removed_tags(lua, poll, values, to_py):
    sessions = lua.table()
    poll.step(sessions, "s", None, False, values(readers={"old": {"red": {"x": 1}, "green": {}}}, writers={"w": {}}), 1)
    delta = to_py(poll.step(sessions, "s", 1, False, values(
        readers={"new": {"red": {"x": 1}, "green": {}}}, writers={"w": {}, "w2": {"k": 3}}), 2))
    assert delta["readers"] == {"new": {"red": {"x": 1}, "green": {}}}
    assert delta["writers"] == {"w2": {"k": 3}}
    assert delta["removed"] == ["old"]


@pytest.mark.parametrize("ack", [None, 0, 5])
def test_ack_mismatch_forces_full(lua, poll, values, to_py, ack):
    sessions = lua.table()
    poll.step(sessions, "s", None, False, values(writers={"w": {"y": 1}}), 1)
    poll.step(sessions, "s", 1, False, values(writers={"w": {"y": 1}}), 2)  # seq is now 2
    reply = to_py(poll.step(sessions, "s", ack, False, values(writers={"w": {"y": 1}}), 3))
    assert reply["full"] is True and reply["writers"] == {"w": {"y": 1}}


def test_forced_full(lua, poll, values, to_py):
    sessions = lua.table()
    poll.step(sessions, "s", None, False, values(writers={"w": {"y": 1}}), 1)
    assert to_py(poll.step(sessions, "s", 1, True, values(writers={"w": {"y": 1}}), 2))["full"] is True


def test_sessions_are_independent(lua, poll, values, to_py):
    sessions = lua.table()
    v = lambda y: values(writers={"w": {"y": y}})
    poll.step(sessions, "a", None, False, v(1), 1)
    poll.step(sessions, "b", None, False, v(1), 1)
    assert to_py(poll.step(sessions, "a", 1, False, v(2), 2))["writers"] == {"w": {"y": 2}}
    assert to_py(poll.step(sessions, "b", 1, False, v(2), 2))["writers"] == {"w": {"y": 2}}


def test_idle_sessions_expire_and_count_is_capped(lua, poll, values, to_py):
    sessions = lua.table()
    ttl = poll.SESSION_TTL
    poll.step(sessions, "idle", None, False, values(), 0)
    poll.step(sessions, "busy", None, False, values(), ttl)
    poll.step(sessions, "busy", 1, False, values(), ttl + 1)
    assert set(to_py(sessions)) == {"busy"}  # "idle" was last polled more than SESSION_TTL ago

    for i in range(poll.MAX_SESSIONS + 3):
        poll.step(sessions, f"s{i}", None, False, values(), ttl + 2 + i)
    assert len(to_py(sessions)) == poll.MAX_SESSIONS
    assert "busy" not in to_py(sessions)  # oldest evicted first


@pytest.mark.parametrize("request_, ok", [
    ({"session": "abc-1_2"}, True),
    ({"session": "abc", "ack": 3, "full": True}, True),
    ({}, False),
    ({"session": ""}, False),
    ({"session": "has space"}, False),
    ({"session": "x" * 65}, False),
    ({"session": "abc", "ack": 1.5}, False),
    ({"session": "abc", "full": "yes"}, False),
])
def test_parse_request(lua, call, poll, request_, ok):
    result = call(poll.parse_request, lua.table_from(request_))
    assert (result[0] is not None) is ok
