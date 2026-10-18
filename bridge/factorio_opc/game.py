"""Typed wrapper over the opc-io mod's RCON commands (see docs/protocol.md)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Literal, Protocol

from .rcon import RconClient

PROTO = 1

SignalMap = dict[str, int]
Kind = Literal["reader", "writer"]


class GameError(Exception):
    """The mod answered with ok=false, or with something that isn't protocol JSON."""


@dataclass(frozen=True)
class Hello:
    proto: int
    mod_version: str
    factorio_version: str
    tick: int
    tick_paused: bool
    speed: float
    model_version: int


@dataclass(frozen=True)
class Tag:
    name: str
    kind: Kind


@dataclass(frozen=True)
class ReaderValues:
    red: SignalMap = field(default_factory=dict)
    green: SignalMap = field(default_factory=dict)


@dataclass(frozen=True)
class Poll:
    """One /opc_poll reply: everything (full) or only what changed since the acked reply.

    In a delta, a reader lists only the changed keys of each wire, a key that
    went away has value 0, and `removed` names tags that are gone.
    """

    seq: int
    full: bool
    tick: int
    tick_paused: bool
    speed: float
    model_version: int
    readers: dict[str, ReaderValues]
    writers: dict[str, SignalMap]
    removed: list[str]


class GameApi(Protocol):
    """What the bridge needs from the game; RconGame implements it over RCON."""

    async def connect(self) -> Hello: ...
    async def close(self) -> None: ...
    async def browse(self) -> list[Tag]: ...
    async def poll(self, session: str, ack: int | None) -> Poll: ...
    async def write(self, tag: str, signals: SignalMap, mode: str = "merge") -> SignalMap: ...


def _as_map(value: object) -> dict:
    # table_to_json writes every empty table as {} and the bridge treats [] the same.
    if value in (None, [], {}):
        return {}
    if not isinstance(value, dict):
        raise GameError(f"expected a JSON object, got {value!r}")
    return value


def _as_list(value: object) -> list:
    if value in (None, [], {}):
        return []
    if not isinstance(value, list):
        raise GameError(f"expected a JSON array, got {value!r}")
    return value


def _signals(value: object) -> SignalMap:
    return {str(k): int(v) for k, v in _as_map(value).items()}


def parse_reply(text: str) -> dict:
    try:
        reply = json.loads(text)
    except json.JSONDecodeError:
        raise GameError(f"reply is not JSON (is opc-io installed?): {text.strip()[:200]}") from None
    if not isinstance(reply, dict) or "ok" not in reply:
        raise GameError(f"unexpected reply: {text.strip()[:200]}")
    if not reply["ok"]:
        raise GameError(str(reply.get("error", "unknown error")))
    return reply


def parse_hello(reply: dict) -> Hello:
    return Hello(
        proto=int(reply["proto"]),
        mod_version=str(reply["mod_version"]),
        factorio_version=str(reply["factorio_version"]),
        tick=int(reply["tick"]),
        tick_paused=bool(reply["tick_paused"]),
        speed=float(reply["speed"]),
        model_version=int(reply["model_version"]),
    )


def parse_browse(reply: dict) -> list[Tag]:
    return [
        Tag(name=str(t["name"]), kind=t["kind"])
        for t in _as_list(reply.get("tags"))
    ]


def parse_poll(reply: dict) -> Poll:
    readers = {
        str(name): ReaderValues(red=_signals(_as_map(v).get("red")), green=_signals(_as_map(v).get("green")))
        for name, v in _as_map(reply.get("readers")).items()
    }
    writers = {str(name): _signals(v) for name, v in _as_map(reply.get("writers")).items()}
    return Poll(
        seq=int(reply["seq"]),
        full=bool(reply["full"]),
        tick=int(reply["tick"]),
        tick_paused=bool(reply["tick_paused"]),
        speed=float(reply["speed"]),
        model_version=int(reply["model_version"]),
        readers=readers,
        writers=writers,
        removed=[str(n) for n in _as_list(reply.get("removed"))],
    )


class RconGame:
    """GameApi over one RCON connection. Reconnecting is the caller's job."""

    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0) -> None:
        self._client = RconClient(host, port, password, timeout=timeout)

    async def _call(self, command: str, payload: dict | None = None) -> dict:
        line = f"/{command}" if payload is None else f"/{command} {json.dumps(payload, separators=(',', ':'))}"
        return parse_reply(await self._client.execute(line))

    async def connect(self) -> Hello:
        await self._client.connect()
        hello = await self.hello()
        if hello.proto != PROTO:
            await self.close()
            raise GameError(f"opc-io speaks protocol {hello.proto}, this bridge needs {PROTO}")
        return hello

    async def close(self) -> None:
        await self._client.close()

    async def hello(self) -> Hello:
        return parse_hello(await self._call("opc_hello"))

    async def browse(self) -> list[Tag]:
        return parse_browse(await self._call("opc_browse"))

    async def poll(self, session: str, ack: int | None) -> Poll:
        request: dict = {"session": session}
        if ack is not None:
            request["ack"] = ack
        return parse_poll(await self._call("opc_poll", request))

    async def write(self, tag: str, signals: SignalMap, mode: str = "merge") -> SignalMap:
        reply = await self._call("opc_write", {"tag": tag, "signals": signals, "mode": mode})
        return _signals(reply.get("signals"))
