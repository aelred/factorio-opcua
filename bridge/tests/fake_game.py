"""In-memory stand-in for the opc-io mod, implementing GameApi."""

from __future__ import annotations

from factorio_opc.game import GameError, Hello, ReaderValues, Snapshot, Tag
from factorio_opc.rcon import RconError


class FakeWorld:
    """Game state shared by every FakeGame connection; tests poke it directly."""

    def __init__(self) -> None:
        self.tick = 0
        self.model_version = 0
        self.tags: dict[str, Tag] = {}
        self.readers: dict[str, ReaderValues] = {}
        self.writers: dict[str, dict[str, int]] = {}
        self.writes: list[tuple[str, dict[str, int], str]] = []
        self.reachable = True
        self.reject_writes: str | None = None
        self.connections = 0
        self._unit = 0

    def add(self, kind: str, name: str) -> None:
        self._unit += 1
        self.tags[name] = Tag(name=name, kind=kind, unit=self._unit, surface="nauvis", position=(0.0, 0.0))
        if kind == "reader":
            self.readers[name] = ReaderValues()
        else:
            self.writers[name] = {}
        self.model_version += 1

    def remove(self, name: str) -> None:
        del self.tags[name]
        self.readers.pop(name, None)
        self.writers.pop(name, None)
        self.model_version += 1

    def set_reader(self, name: str, red: dict[str, int] | None = None, green: dict[str, int] | None = None) -> None:
        self.readers[name] = ReaderValues(red=red or {}, green=green or {})


class FakeGame:
    def __init__(self, world: FakeWorld) -> None:
        self.world = world
        self.open = False

    def _check(self) -> None:
        if not (self.open and self.world.reachable):
            raise RconError("connection closed")
        self.world.tick += 1

    async def connect(self) -> Hello:
        if not self.world.reachable:
            raise OSError("connection refused")
        self.open = True
        self.world.connections += 1
        return await self.hello()

    async def close(self) -> None:
        self.open = False

    async def hello(self) -> Hello:
        self._check()
        return Hello(proto=1, mod_version="0.2.0", factorio_version="2.0.77", tick=self.world.tick,
                     tick_paused=False, speed=1.0, model_version=self.world.model_version)

    async def browse(self) -> list[Tag]:
        self._check()
        return sorted(self.world.tags.values(), key=lambda t: t.name)

    async def snapshot(self) -> Snapshot:
        self._check()
        return Snapshot(tick=self.world.tick, model_version=self.world.model_version,
                        readers=dict(self.world.readers),
                        writers={k: dict(v) for k, v in self.world.writers.items()})

    async def write(self, tag: str, signals: dict[str, int], mode: str = "merge") -> dict[str, int]:
        self._check()
        if self.world.reject_writes:
            raise GameError(self.world.reject_writes)
        if tag not in self.world.writers:
            raise GameError(f"unknown tag '{tag}'")
        self.world.writes.append((tag, dict(signals), mode))
        current = {} if mode == "replace" else dict(self.world.writers[tag])
        for key, value in signals.items():
            if value == 0:
                current.pop(key, None)
            else:
                current[key] = value
        self.world.writers[tag] = current
        return dict(current)
