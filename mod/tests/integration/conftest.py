"""Fixtures for tests against a live Factorio server running opcua-io.

Uses the dev server by default (scripts/dev-server.sh up). Override with
FACTORIO_RCON_HOST, FACTORIO_RCON_PORT and FACTORIO_RCON_PASSWORD.
Tests are skipped when no server is reachable, except in CI (the CI variable
that GitHub Actions and most CI systems set), where that is an error instead.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

from factorio_opcua.rcon import RconClient

REPO = Path(__file__).resolve().parents[3]
PASSWORD_FILE = REPO / ".dev" / "factorio" / "config" / "rconpw"


def pytest_collection_modifyitems(items):
    for item in items:
        if "integration" in item.path.parts:
            item.add_marker(pytest.mark.integration)


class Factorio:
    def __init__(self, client: RconClient):
        self.client = client
        self._where: dict[int, tuple[str, float, float]] = {}

    async def command(self, name: str, payload=None) -> dict:
        """Run an opc_* command and decode its JSON reply."""
        arg = "" if payload is None else " " + (payload if isinstance(payload, str) else json.dumps(payload))
        return json.loads(await self.client.execute(f"/{name}{arg}"))

    async def lua(self, code: str) -> str:
        """Run single-line Lua as a silent command; raises on Lua errors.

        RCON commands must be one line, so `code` may not contain newlines.
        """
        assert "\n" not in code
        wrapped = (
            "/sc local ok, r = pcall(function() " + code + " end) "
            "if ok then rcon.print(r == nil and '' or tostring(r)) else rcon.print('LUA_ERROR: ' .. tostring(r)) end"
        )
        reply = (await self.client.execute(wrapped)).rstrip("\n")
        if reply.startswith("LUA_ERROR: "):
            raise AssertionError(reply)
        return reply

    async def values(self) -> dict:
        """All current values: a full /opc_poll reply ({"readers": ..., "writers": ...})."""
        return await self.command("opc_poll", {"session": "itest-values", "full": True})

    async def ticks(self, n: int = 2) -> None:
        """Wait until at least n game ticks pass (each command also advances a paused server)."""
        start = (await self.command("opc_hello"))["tick"]
        while (await self.command("opc_hello"))["tick"] < start + n:
            await asyncio.sleep(0.02)

    async def create(self, kind: str, x: float, y: float, tags: dict | None = None) -> int:
        """Build an OPC entity (via a ghost revive when tags are given); returns its unit number."""
        name = f"opc-{kind}"
        # The map is random, so first clear the tile of trees, rocks and water:
        # a ghost revive fails if anything is in the way.
        clear = (f'local s = game.surfaces.nauvis s.set_tiles{{{{name="grass-1", position={{{x},{y}}}}}}} '
                 f'for _, o in pairs(s.find_entities{{{{{x},{y}}}, {{{x + 1},{y + 1}}}}}) do o.destroy() end ')
        if tags is None:
            code = clear + (f'local e = s.create_entity{{name="{name}", position={{{x},{y}}}, '
                            f'force="player", raise_built=true}} return e.unit_number')
        else:
            lua_tags = "{" + ", ".join(f'{k}="{v}"' for k, v in tags.items()) + "}"
            code = clear + (f'local g = s.create_entity{{name="entity-ghost", inner_name="{name}", '
                            f'position={{{x},{y}}}, force="player", tags={lua_tags}}} '
                            f'local _, e = g.revive{{raise_revive=true}} return e.unit_number')
        unit = int(await self.lua(code))
        self._where[unit] = (name, x + 0.5, y + 0.5)
        return unit

    def ref(self, unit: int) -> str:
        """Lua expression for an entity created by create().

        game.get_entity_by_unit_number returns nil for combinators (and chests)
        in 2.0.77, so entities are found by name and position instead.
        """
        name, x, y = self._where[unit]
        return f'game.surfaces.nauvis.find_entity("{name}", {{{x},{y}}})'

    async def wire(self, unit_a: int, unit_b: int, color: str = "red") -> None:
        await self.lua(
            f"local a = {self.ref(unit_a)} local b = {self.ref(unit_b)} "
            f"local id = defines.wire_connector_id.circuit_{color} "
            f"a.get_wire_connector(id, true).connect_to(b.get_wire_connector(id, true), false)"
        )

    async def destroy(self, unit: int) -> None:
        await self.lua(f"{self.ref(unit)}.destroy()")

    async def tag_by_unit(self, unit: int) -> dict | None:
        tags = (await self.command("opc_browse"))["tags"]
        return next((t for t in (tags or []) if t["unit"] == unit), None)

    async def clear(self) -> None:
        await self.lua(
            'for _, e in pairs(game.surfaces.nauvis.find_entities_filtered{name={"opc-reader","opc-writer"}}) '
            "do e.destroy() end"
        )
        for _ in range(50):
            if not (await self.command("opc_browse"))["tags"]:
                return
            await asyncio.sleep(0.02)
        raise AssertionError("OPC entities were not unregistered after destroy")


@pytest.fixture(scope="session")
async def rcon():
    host = os.environ.get("FACTORIO_RCON_HOST", "127.0.0.1")
    port = int(os.environ.get("FACTORIO_RCON_PORT", "27015"))
    password = os.environ.get("FACTORIO_RCON_PASSWORD")
    if password is None and PASSWORD_FILE.exists():
        password = PASSWORD_FILE.read_text().strip()
    unavailable = pytest.fail if os.environ.get("CI", "").lower() in ("true", "1") else pytest.skip
    if password is None:
        unavailable("no RCON password (start scripts/dev-server.sh or set FACTORIO_RCON_PASSWORD)")
    client = RconClient(host, port, password, timeout=10)
    try:
        await client.connect()
    except (TimeoutError, OSError) as exc:
        unavailable(f"Factorio RCON not reachable at {host}:{port}: {exc}")
    yield client
    await client.close()


@pytest.fixture
async def factorio(rcon):
    game = Factorio(rcon)
    await game.clear()
    yield game
    await game.clear()
