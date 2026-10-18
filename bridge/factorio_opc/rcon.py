"""Minimal asyncio Source-RCON client tuned for Factorio.

Factorio specifics (measured against 2.0.77):
- Each command reply arrives as exactly one packet, however large (1 MB tested),
  so there is no multi-packet reassembly.
- Empty "sentinel" packets are not echoed, so the usual end-of-reply trick
  does not work and is not used.
- Replies come back in request order, so requests can be pipelined and are
  matched to callers by request id.
"""

from __future__ import annotations

import asyncio
import contextlib
import itertools
import struct
from typing import Self

SERVERDATA_AUTH = 3
SERVERDATA_AUTH_RESPONSE = 2
SERVERDATA_EXECCOMMAND = 2
SERVERDATA_RESPONSE_VALUE = 0

# Guard against a corrupt length prefix making us allocate unbounded memory.
MAX_PACKET_SIZE = 64 * 1024 * 1024

_HEADER = struct.Struct("<iii")  # size, request id, type


class RconError(Exception):
    """Connection-level RCON failure."""


class RconAuthError(RconError):
    """The server rejected the RCON password."""


def encode_packet(request_id: int, packet_type: int, body: str) -> bytes:
    payload = body.encode("utf-8") + b"\x00\x00"
    return _HEADER.pack(len(payload) + 8, request_id, packet_type) + payload


async def read_packet(reader: asyncio.StreamReader) -> tuple[int, int, str]:
    (size,) = struct.unpack("<i", await reader.readexactly(4))
    if not 10 <= size <= MAX_PACKET_SIZE:
        raise RconError(f"invalid RCON packet size {size}")
    data = await reader.readexactly(size)
    request_id, packet_type = struct.unpack("<ii", data[:8])
    return request_id, packet_type, data[8:-2].decode("utf-8", errors="replace")


class RconClient:
    """One authenticated RCON connection. Not reconnecting; callers own retries."""

    def __init__(self, host: str, port: int, password: str, timeout: float = 5.0) -> None:
        self.host = host
        self.port = port
        self._password = password
        self.timeout = timeout
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._ids = itertools.count(1)
        self._pending: dict[int, asyncio.Future[str]] = {}
        self._read_task: asyncio.Task[None] | None = None

    @property
    def connected(self) -> bool:
        return self._read_task is not None and not self._read_task.done()

    async def connect(self) -> None:
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(self.host, self.port), self.timeout
        )
        try:
            await self._authenticate()
        except BaseException:
            await self.close()
            raise
        self._read_task = asyncio.create_task(self._read_loop())

    async def _authenticate(self) -> None:
        assert self._reader is not None and self._writer is not None
        auth_id = next(self._ids)
        self._writer.write(encode_packet(auth_id, SERVERDATA_AUTH, self._password))
        await self._writer.drain()
        while True:
            request_id, packet_type, _ = await asyncio.wait_for(
                read_packet(self._reader), self.timeout
            )
            if packet_type != SERVERDATA_AUTH_RESPONSE:
                continue  # some servers send an empty RESPONSE_VALUE first
            if request_id == -1:
                raise RconAuthError("RCON authentication failed")
            if request_id == auth_id:
                return

    async def _read_loop(self) -> None:
        assert self._reader is not None
        error: Exception = RconError("connection closed")
        try:
            while True:
                request_id, _, body = await read_packet(self._reader)
                future = self._pending.pop(request_id, None)
                if future is not None and not future.done():
                    future.set_result(body)
        except (asyncio.IncompleteReadError, ConnectionError, RconError) as exc:
            error = exc if isinstance(exc, RconError) else RconError(str(exc) or "connection closed")
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(error)
            self._pending.clear()

    async def execute(self, command: str) -> str:
        """Run a console command (e.g. "/opc_hello") and return its reply text."""
        if not self.connected or self._writer is None:
            raise RconError("not connected")
        request_id = next(self._ids)
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        try:
            self._writer.write(encode_packet(request_id, SERVERDATA_EXECCOMMAND, command))
            await self._writer.drain()
            return await asyncio.wait_for(future, self.timeout)
        finally:
            self._pending.pop(request_id, None)

    async def close(self) -> None:
        if self._read_task is not None:
            self._read_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._read_task
            self._read_task = None
        if self._writer is not None:
            self._writer.close()
            with contextlib.suppress(ConnectionError):
                await self._writer.wait_closed()
            self._writer = None

    async def __aenter__(self) -> Self:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()
