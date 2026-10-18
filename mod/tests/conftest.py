from pathlib import Path

import pytest
from lupa import lua52

MOD_DIR = Path(__file__).resolve().parents[1] / "opcua-io"


@pytest.fixture
def lua():
    """A Lua 5.2 runtime (Factorio's version) that can require the mod's lib/ modules."""
    runtime = lua52.LuaRuntime()
    runtime.execute(f'package.path = "{MOD_DIR.as_posix()}/?.lua;" .. package.path')
    return runtime


def _to_py(value):
    if hasattr(value, "items"):
        items = {k: _to_py(v) for k, v in value.items()}
        if items and all(isinstance(k, int) for k in items) and sorted(items) == list(range(1, len(items) + 1)):
            return [items[i] for i in range(1, len(items) + 1)]
        return items
    return value


@pytest.fixture
def to_py():
    """Convert Lua tables to dicts (or lists when keyed 1..n) recursively."""
    return _to_py


@pytest.fixture
def call(lua):
    """Call a Lua function and always get its return values as a list (lupa drops singletons)."""
    pack = lua.eval("function(f, ...) local r = table.pack(f(...)) return r end")

    def invoke(fn, *args):
        packed = pack(fn, *args)
        return [packed[i] for i in range(1, packed["n"] + 1)]

    return invoke
