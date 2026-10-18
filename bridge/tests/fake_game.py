"""In-memory stand-in for the opcua-io mod, implementing GameApi."""

from __future__ import annotations

from factorio_opcua.game import GameError, Hello, Poll, ReaderValues, Tag
from factorio_opcua.rcon import RconError


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
        self.poll_timeouts = 0  # polls that raise TimeoutError, as when the game is busy saving
        self.reject_writes: str | None = None
        self.connections = 0
        self.polls: list[Poll] = []          # every poll reply, for assertions
        self.sessions: dict[str, dict] = {}  # session -> {"seq": int, "values": {"readers", "writers"}}

    def add(self, kind: str, name: str) -> None:
        self.tags[name] = Tag(name=name, kind=kind)
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


def _diff(prev: dict[str, int], cur: dict[str, int]) -> dict[str, int]:
    changes = {k: v for k, v in cur.items() if prev.get(k) != v}
    changes.update({k: 0 for k in prev if k not in cur})
    return changes


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
        return Hello(proto=1, mod_version="0.6.0", factorio_version="2.0.77", tick=self.world.tick,
                     tick_paused=False, speed=1.0, model_version=self.world.model_version)

    async def browse(self) -> list[Tag]:
        self._check()
        return sorted(self.world.tags.values(), key=lambda t: t.name)

    async def poll(self, session: str, ack: int | None) -> Poll:
        """Same semantics as the mod's lib/poll.lua."""
        self._check()
        if self.world.poll_timeouts:
            self.world.poll_timeouts -= 1
            raise TimeoutError
        w = self.world
        current = {"readers": {k: ReaderValues(dict(v.red), dict(v.green)) for k, v in w.readers.items()},
                   "writers": {k: dict(v) for k, v in w.writers.items()}}
        s = w.sessions.get(session)
        full = s is None or ack != s["seq"]
        if s is None:
            s = w.sessions[session] = {"seq": 0}
        if full:
            readers, writers, removed = current["readers"], current["writers"], []
        else:
            prev = s["values"]
            readers, writers = {}, {}
            for name, r in current["readers"].items():
                p = prev["readers"].get(name)
                if p is None:
                    readers[name] = r
                else:
                    red, green = _diff(p.red, r.red), _diff(p.green, r.green)
                    if red or green:
                        readers[name] = ReaderValues(red, green)
            for name, v in current["writers"].items():
                p = prev["writers"].get(name)
                if p is None:
                    writers[name] = v
                elif d := _diff(p, v):
                    writers[name] = d
            removed = sorted(n for kind in ("readers", "writers") for n in prev[kind] if n not in current[kind])
        s["values"] = current
        s["seq"] += 1
        reply = Poll(seq=s["seq"], full=full, tick=w.tick, tick_paused=False, speed=1.0,
                     model_version=w.model_version, readers=readers, writers=writers, removed=removed)
        w.polls.append(reply)
        return reply

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
