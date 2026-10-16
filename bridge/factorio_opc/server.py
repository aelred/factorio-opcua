"""The bridge: an asyncua OPC UA server fed by polling the game over RCON."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Callable
from urllib.parse import urlparse

from asyncua import Server, ua
from asyncua.crypto.permission_rules import User

from .config import Config
from .game import GameApi, GameError, RconGame
from .model import NAMESPACE_URI, AddressSpace, now
from .rcon import RconError

log = logging.getLogger("factorio_opc")

BACKOFF_START = 1.0
BACKOFF_MAX = 30.0

INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1
NUMERIC_TYPES = {
    ua.VariantType.SByte, ua.VariantType.Byte, ua.VariantType.Int16, ua.VariantType.UInt16,
    ua.VariantType.Int32, ua.VariantType.UInt32, ua.VariantType.Int64, ua.VariantType.UInt64,
    ua.VariantType.Float, ua.VariantType.Double,
}


def status(code: int) -> ua.StatusCode:
    return ua.StatusCode(code)


def signal_value(variant: ua.Variant | None) -> int | None:
    """Accept any numeric variant holding an int32-range integer (clients differ in what they send)."""
    if variant is None or variant.VariantType not in NUMERIC_TYPES or isinstance(variant.Value, list):
        return None
    value = variant.Value
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    return value


class Bridge:
    def __init__(self, config: Config, game_factory: Callable[[], GameApi] | None = None) -> None:
        self.config = config
        self._game_factory = game_factory or (
            lambda: RconGame(config.rcon_host, config.rcon_port, config.rcon_password, config.rcon_timeout)
        )
        self.server = Server()
        self.model: AddressSpace | None = None
        self.game: GameApi | None = None  # set while connected
        self.connected = asyncio.Event()  # set once tags are synced, cleared on disconnect
        self._model_version: int | None = None
        self._task: asyncio.Task | None = None
        self._original_write = None

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        await self.server.init()
        self.server.set_endpoint(self.config.endpoint)
        self.server.set_server_name(self.config.server_name)
        await self.server.set_application_uri("urn:factorio-opc:bridge")
        self.server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        # Never grant the admin role (which skips access-level checks) to remote users.
        self.server.iserver.allow_remote_admin = False
        ns = await self.server.register_namespace(NAMESPACE_URI)
        self.model = AddressSpace(self.server, ns)
        await self.model.build()
        self._install_write_hook()
        host = urlparse(self.config.endpoint).hostname or ""
        if host not in ("127.0.0.1", "localhost", "::1"):
            log.warning("OPC UA endpoint %s is reachable from the network without security or login "
                        "(security arrives in milestone 5)", self.config.endpoint)
        await self.server.start()
        log.info("OPC UA server listening on %s", self.config.endpoint)
        self._task = asyncio.create_task(self._run_game(), name="factorio-game")

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        await self._disconnect()
        await self.server.stop()

    async def __aenter__(self) -> Bridge:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # -- game connection and polling --------------------------------------------

    async def _disconnect(self) -> None:
        game, self.game = self.game, None
        self.connected.clear()
        if game is not None:
            try:
                await game.close()
            except Exception:  # closing a broken connection may fail; nothing to do about it
                pass

    async def _run_game(self) -> None:
        assert self.model is not None
        backoff = BACKOFF_START
        rcon = f"{self.config.rcon_host}:{self.config.rcon_port}"
        while True:
            game = self._game_factory()
            try:
                hello = await game.connect()
                log.info("connected to Factorio %s (opc-io %s) at %s", hello.factorio_version, hello.mod_version, rcon)
                self.game = game
                self._model_version = None
                await self.model.set_connected(hello)
                backoff = BACKOFF_START
                await self._poll(game)
            except (RconError, GameError, OSError, asyncio.TimeoutError) as exc:
                was_connected = self.game is not None
                await self._disconnect()
                await self.model.mark_stale()
                if was_connected:
                    log.warning("lost connection to Factorio at %s: %s", rcon, exc)
                else:
                    log.info("cannot reach Factorio at %s (%s); retrying in %.0fs", rcon, exc, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("unexpected error in game loop; reconnecting")
                await self._disconnect()
                await self.model.mark_stale()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)

    async def _poll(self, game: GameApi) -> None:
        assert self.model is not None
        loop = asyncio.get_running_loop()
        interval = 1.0 / self.config.poll_hz
        next_at = loop.time()
        while True:
            start = time.perf_counter()
            # Pipelined: both commands normally run in the same game tick.
            hello, snapshot = await asyncio.gather(game.hello(), game.snapshot())
            received = now()
            latency_ms = (time.perf_counter() - start) * 1000
            if snapshot.model_version != self._model_version:
                await self.model.sync_tags(await game.browse(), self._method_write)
                self._model_version = snapshot.model_version
            await self.model.apply_snapshot(snapshot, received)
            await self.model.set_status(hello, latency_ms)
            # Only after the first full sync, so every tag's nodes exist once this is set.
            self.connected.set()
            next_at += interval
            delay = next_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                next_at = loop.time()  # running late: skip ahead instead of bursting

    # -- writes from OPC clients -------------------------------------------------

    def _install_write_hook(self) -> None:
        service = self.server.iserver.attribute_service
        self._original_write = service.write
        service.write = self._write

    async def _write(self, params: ua.WriteParameters, user: User = User()) -> list[ua.StatusCode]:
        """Intercepts session writes: writer signal nodes go to the game, the rest to asyncua."""
        assert self.model is not None
        results: list[ua.StatusCode | None] = [None] * len(params.NodesToWrite)
        passthrough: list[int] = []
        by_tag: dict[str, list[tuple[int, str, int]]] = {}
        for i, wv in enumerate(params.NodesToWrite):
            target = self.model.writer_signal_nodes.get(wv.NodeId)
            if target is None:
                passthrough.append(i)
            elif wv.AttributeId != ua.AttributeIds.Value or wv.IndexRange:
                results[i] = status(ua.StatusCodes.BadNotWritable)
            else:
                value = signal_value(wv.Value.Value if wv.Value else None)
                if value is None:
                    results[i] = status(ua.StatusCodes.BadTypeMismatch)
                elif not INT32_MIN <= value <= INT32_MAX:
                    results[i] = status(ua.StatusCodes.BadOutOfRange)
                else:
                    by_tag.setdefault(target[0], []).append((i, target[1], value))

        if passthrough:
            sub = ua.WriteParameters(NodesToWrite=[params.NodesToWrite[i] for i in passthrough])
            for i, result in zip(passthrough, await self._original_write(sub, user=user)):
                results[i] = result

        for tag, items in by_tag.items():
            code = await self._write_tag(tag, {key: value for _, key, value in items})
            for i, _, _ in items:
                results[i] = status(code)
        return results  # type: ignore[return-value]

    async def _game_write(self, tag: str, signals: dict[str, int], mode: str) -> dict[str, int]:
        """Write through to the game and update the writer's nodes from its reply."""
        assert self.model is not None
        game = self.game
        if game is None:
            raise ua.UaStatusCodeError(ua.StatusCodes.BadNoCommunication)
        try:
            result = await game.write(tag, signals, mode)
        except GameError as exc:
            log.warning("write to %s rejected by the game: %s", tag, exc)
            raise ua.UaStatusCodeError(ua.StatusCodes.BadInvalidArgument) from exc
        except (RconError, OSError, asyncio.TimeoutError) as exc:
            log.warning("write to %s failed: %s", tag, exc)
            raise ua.UaStatusCodeError(ua.StatusCodes.BadCommunicationError) from exc
        await self.model.apply_writer(tag, result)
        return result

    async def _write_tag(self, tag: str, signals: dict[str, int]) -> int:
        try:
            await self._game_write(tag, signals, "merge")
        except ua.UaStatusCodeError as exc:
            return exc.code
        return ua.StatusCodes.Good

    async def _method_write(self, tag: str, signals_json: str, mode: str) -> str:
        """Backs the SetSignals and ClearAll methods."""
        if mode not in ("merge", "replace"):
            raise ua.UaStatusCodeError(ua.StatusCodes.BadInvalidArgument)
        try:
            signals = json.loads(signals_json)
        except json.JSONDecodeError:
            raise ua.UaStatusCodeError(ua.StatusCodes.BadInvalidArgument) from None
        if not isinstance(signals, dict):
            raise ua.UaStatusCodeError(ua.StatusCodes.BadInvalidArgument)
        result = await self._game_write(tag, signals, mode)
        return json.dumps(result, sort_keys=True)
