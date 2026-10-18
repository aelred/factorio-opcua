import asyncio

import pytest

from factorio_opcua.game import GameError, RconGame
from factorio_opcua.rcon import (
    SERVERDATA_AUTH,
    SERVERDATA_AUTH_RESPONSE,
    SERVERDATA_EXECCOMMAND,
    SERVERDATA_RESPONSE_VALUE,
    RconAuthError,
    RconClient,
    RconError,
    encode_packet,
    read_packet,
)


class FakeFactorio:
    """Behaves like Factorio's RCON: one reply packet per command, in order."""

    def __init__(self, password="secret", replies=None, delays=None, auth_delay=0):
        self.password = password
        self.auth_delay = auth_delay
        self.replies = replies or {}
        self.delays = delays or {}
        self.server = None
        self.writers = []

    async def start(self):
        self.server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        return self.server.sockets[0].getsockname()[1]

    async def stop(self):
        for writer in self.writers:
            writer.close()
        self.server.close()
        await self.server.wait_closed()

    async def _handle(self, reader, writer):
        self.writers.append(writer)
        try:
            request_id, packet_type, body = await read_packet(reader)
            assert packet_type == SERVERDATA_AUTH
            await asyncio.sleep(self.auth_delay)
            ok = body == self.password
            writer.write(encode_packet(request_id if ok else -1, SERVERDATA_AUTH_RESPONSE, ""))
            await writer.drain()
            if not ok:
                return
            while True:
                request_id, packet_type, body = await read_packet(reader)
                assert packet_type == SERVERDATA_EXECCOMMAND
                await asyncio.sleep(self.delays.get(body, 0))
                reply = self.replies.get(body, f"unknown: {body}")
                writer.write(encode_packet(request_id, SERVERDATA_RESPONSE_VALUE, reply))
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass


@pytest.fixture
async def fake():
    server = FakeFactorio(replies={"/opc_hello": '{"proto":1}\n', "/big": "x" * 2_000_000})
    port = await server.start()
    server.port = port
    yield server
    await server.stop()


async def test_execute_returns_reply(fake):
    async with RconClient("127.0.0.1", fake.port, "secret") as client:
        assert await client.execute("/opc_hello") == '{"proto":1}\n'


async def test_large_single_packet_reply(fake):
    async with RconClient("127.0.0.1", fake.port, "secret") as client:
        assert len(await client.execute("/big")) == 2_000_000


async def test_pipelined_requests_are_matched_by_id(fake):
    async with RconClient("127.0.0.1", fake.port, "secret") as client:
        commands = [f"/cmd{i}" for i in range(20)]
        results = await asyncio.gather(*(client.execute(c) for c in commands))
        assert results == [f"unknown: {c}" for c in commands]


async def test_bad_password_raises(fake):
    with pytest.raises(RconAuthError):
        await RconClient("127.0.0.1", fake.port, "wrong").connect()


async def test_timeout_does_not_break_later_requests():
    server = FakeFactorio(replies={"/slow": "late", "/fast": "ok"}, delays={"/slow": 0.3})
    port = await server.start()
    try:
        async with RconClient("127.0.0.1", port, "secret", timeout=0.1) as client:
            with pytest.raises(asyncio.TimeoutError):
                await client.execute("/slow")
            client.timeout = 1.0
            assert await client.execute("/fast") == "ok"
    finally:
        await server.stop()


async def test_server_disconnect_fails_pending_and_later_calls():
    server = FakeFactorio(delays={"/hang": 10})
    port = await server.start()
    client = RconClient("127.0.0.1", port, "secret")
    await client.connect()
    pending = asyncio.create_task(client.execute("/hang"))
    await asyncio.sleep(0.05)
    await server.stop()
    with pytest.raises(RconError):
        await pending
    with pytest.raises(RconError):
        await client.execute("/opc_hello")
    await client.close()


async def test_failed_connect_closes_the_connection():
    server = FakeFactorio(replies={"/opc_hello": "Unknown command \"opc_hello\"."}, auth_delay=0)
    port = await server.start()
    try:
        game = RconGame("127.0.0.1", port, "secret")
        with pytest.raises(GameError):
            await game.connect()  # opcua-io not installed
        assert game._client._writer is None

        server.auth_delay = 1
        client = RconClient("127.0.0.1", port, "secret", timeout=0.1)
        with pytest.raises(TimeoutError):
            await client.connect()
        assert client._writer is None
    finally:
        await server.stop()


async def test_failed_send_leaves_no_pending_request(fake):
    async with RconClient("127.0.0.1", fake.port, "secret") as client:
        async def broken():
            raise ConnectionResetError("gone")
        client._writer.drain = broken
        with pytest.raises(ConnectionResetError):
            await client.execute("/opc_hello")
        assert client._pending == {}
