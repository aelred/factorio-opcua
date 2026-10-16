import pytest


@pytest.fixture
def names(lua):
    return lua.eval('require("lib.names")')


@pytest.mark.parametrize("name, ok", [
    ("line_1", True), ("smelter-2.out", True), ("a" * 64, True),
    ("", False), ("a" * 65, False), ("has space", False), ("a/b", False), (None, False), (5, False),
])
def test_validate(call, names, name, ok):
    assert bool(call(names.validate, name)[0]) is ok


def test_unique_suffixes_until_free(lua, names):
    taken = lua.eval("function(n) return n == 'x' or n == 'x-2' end")
    assert names.unique("free", taken) == "free"
    assert names.unique("x", taken) == "x-3"


def test_unique_keeps_length_limit(lua, names):
    long = "a" * 64
    taken = lua.eval(f"function(n) return n == '{long}' end")
    result = names.unique(long, taken)
    assert result == "a" * 62 + "-2" and len(result) == 64
