"""The bridge: an asyncua OPC UA server fed by polling the game over RCON."""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import ipaddress
import json
import logging
import os
import socket
import time
import uuid
import warnings
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Self
from urllib.parse import urlparse

from asyncua import Server, ua
from asyncua.crypto import cert_gen
from asyncua.crypto.permission_rules import User
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import ExtendedKeyUsageOID

from .auth import Ruleset, UserManager
from .config import Config
from .game import GameApi, GameError, RconGame
from .model import NAMESPACE_URI, AddressSpace, now
from .rcon import RconError

log = logging.getLogger("factorio_opcua")

# asyncua's delete_nodes calls an async monitored-item callback without awaiting
# it. The bridge notifies subscribers itself before deleting (model.py), so the
# resulting warning is noise.
warnings.filterwarnings("ignore", message="coroutine 'MonitoredItemService.datachange_callback' was never awaited")

BACKOFF_START = 1.0
BACKOFF_MAX = 30.0
# Polls in a row that may time out before the bridge reconnects. The game
# doesn't answer while it saves, which on a big map can take longer than
# rcon_timeout.
MAX_POLL_TIMEOUTS = 3

INT32_MIN, INT32_MAX = -(2**31), 2**31 - 1
NUMERIC_TYPES = {
    ua.VariantType.SByte, ua.VariantType.Byte, ua.VariantType.Int16, ua.VariantType.UInt16,
    ua.VariantType.Int32, ua.VariantType.UInt32, ua.VariantType.Int64, ua.VariantType.UInt64,
    ua.VariantType.Float, ua.VariantType.Double,
}


def status(code: int) -> ua.StatusCode:
    return ua.StatusCode(code)


def signal_value(variant: ua.Variant | None) -> int | None:
    """The whole number held by any numeric variant, else None. Clients differ in the type they send;
    the int32 range is checked by the caller."""
    if variant is None or variant.VariantType not in NUMERIC_TYPES or isinstance(variant.Value, list):
        return None
    value = variant.Value
    if isinstance(value, float):
        if not value.is_integer():
            return None
        value = int(value)
    return value


APPLICATION_URI = "urn:factorio-opcua:bridge"

# The user behind the method call being handled (asyncua doesn't pass it to methods).
CALLING_USER: contextvars.ContextVar[User | None] = contextvars.ContextVar("calling_user", default=None)

# opcua.security modes -> endpoints offered. Basic256Sha256 is what most clients
# support; Aes256-Sha256-RsaPss is the current recommended profile.
SECURITY_POLICIES = {
    "none": [ua.SecurityPolicyType.NoSecurity],
    "sign": [ua.SecurityPolicyType.Basic256Sha256_Sign, ua.SecurityPolicyType.Aes256Sha256RsaPss_Sign],
    "sign_encrypt": [ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt,
                     ua.SecurityPolicyType.Aes256Sha256RsaPss_SignAndEncrypt],
}


def _certificate_names(config: Config) -> tuple[list[str], list[str]]:
    """DNS names and IP addresses the server certificate should cover."""
    dns, ips = {socket.gethostname(), "localhost"}, {"127.0.0.1"}
    host = urlparse(config.endpoint).hostname or ""
    if host and host not in ("0.0.0.0", "::"):
        try:
            ipaddress.ip_address(host)
            ips.add(host)
        except ValueError:
            dns.add(host)
    return sorted(dns), sorted(ips)


def _needs_new_certificate(cert_file: Path, dns: list[str], ips: list[str]) -> bool:
    try:
        cert = x509.load_der_x509_certificate(cert_file.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    except (OSError, ValueError, x509.ExtensionNotFound):
        return True
    if cert.not_valid_after_utc - datetime.now(UTC) < timedelta(days=7):
        return True
    have_ips = {str(i) for i in san.get_values_for_type(x509.IPAddress)}
    return (APPLICATION_URI not in san.get_values_for_type(x509.UniformResourceIdentifier)
            or not set(dns) <= set(san.get_values_for_type(x509.DNSName)) or not set(ips) <= have_ips)


async def ensure_certificate(config: Config) -> tuple[Path, Path]:
    """The configured certificate, or a self-signed one kept in pki_dir.

    The self-signed certificate is created on first use and replaced when it is
    about to expire or no longer covers this machine's names, so clients that
    check host names (e.g. UaExpert) accept it.
    """
    if config.certificate and config.private_key:
        return Path(config.certificate), Path(config.private_key)
    pki = Path(config.pki_dir).expanduser()
    pki.mkdir(mode=0o700, parents=True, exist_ok=True)
    cert_file, key_file = pki / "server_cert.der", pki / "server_key.pem"
    dns, ips = _certificate_names(config)
    if not key_file.is_file():
        pem = cert_gen.dump_private_key_as_pem(cert_gen.generate_private_key())
        with os.fdopen(os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "wb") as f:
            f.write(pem)
        cert_file.unlink(missing_ok=True)
    key_file.chmod(0o600)
    if _needs_new_certificate(cert_file, dns, ips):
        key = await cert_gen.load_private_key(key_file)
        names = [x509.UniformResourceIdentifier(APPLICATION_URI)] + [x509.DNSName(d) for d in dns] + [
            x509.IPAddress(ipaddress.ip_address(i)) for i in ips]
        cert = cert_gen.generate_self_signed_app_certificate(
            key, "factorio-opcua bridge", {"organizationName": "factorio-opcua"}, names,
            extended=[ExtendedKeyUsageOID.SERVER_AUTH, ExtendedKeyUsageOID.CLIENT_AUTH], days=365)
        cert_file.write_bytes(cert.public_bytes(serialization.Encoding.DER))
        log.info("created self-signed OPC UA server certificate %s for %s", cert_file, ", ".join(dns + ips))
    return cert_file, key_file


class Bridge:
    def __init__(self, config: Config, game_factory: Callable[[], GameApi] | None = None) -> None:
        self.config = config
        self._game_factory = game_factory or (
            lambda: RconGame(config.rcon_host, config.rcon_port, config.rcon_password, config.rcon_timeout)
        )
        self.server = Server(user_manager=UserManager(config))
        self.model: AddressSpace | None = None
        self.game: GameApi | None = None  # set while connected
        self.connected = asyncio.Event()  # set once tags are synced, cleared on disconnect
        self._model_version: int | None = None
        self._task: asyncio.Task | None = None
        self._original_write = None
        # Counters published under Status/ (see model.STATUS_TYPES).
        self.metrics: dict = {"Polls": 0, "LatePolls": 0, "Reconnects": 0, "Writes": 0, "WriteErrors": 0,
                              "ConnectedSince": None}
        self._ever_connected = False

    # -- lifecycle -------------------------------------------------------------

    async def start(self) -> None:
        await self.server.init()
        self.server.set_endpoint(self.config.endpoint)
        self.server.set_server_name(self.config.server_name)
        await self.server.set_application_uri(APPLICATION_URI)
        await self._setup_security()
        # Never grant the admin role (which skips access-level checks) to remote users.
        self.server.iserver.allow_remote_admin = False
        ns = await self.server.register_namespace(NAMESPACE_URI)
        self.model = AddressSpace(self.server, ns)
        await self.model.build()
        self._install_write_hook()
        await self.server.start()
        log.info("OPC UA server listening on %s (security: %s; anonymous: %s; %d user(s))", self.config.endpoint,
                 ", ".join(self.config.security), self.config.anonymous, len(self.config.users))
        self._task = asyncio.create_task(self._run_game(), name="factorio-game")

    async def _setup_security(self) -> None:
        config = self.config
        policies = [policy for mode in config.security for policy in SECURITY_POLICIES[mode]]
        if any(mode != "none" for mode in config.security):
            cert, key = await ensure_certificate(config)
            await self.server.load_certificate(str(cert))
            await self.server.load_private_key(str(key))
        self.server.set_security_policy(policies, permission_ruleset=Ruleset())
        tokens = []
        if config.anonymous != "none":
            tokens.append(ua.AnonymousIdentityToken)
        if config.users:
            tokens.append(ua.UserNameIdentityToken)
        self.server.set_identity_tokens(tokens)
        if config.allow_insecure and not config.endpoint_is_local and "none" in config.security \
                and config.anonymous != "none":
            log.warning("allow_insecure: anyone who can reach %s gets %s access without encryption",
                        config.endpoint, config.anonymous)
        if config.allow_insecure and not config.endpoint_is_local and "none" in config.security \
                and config.users and "sign_encrypt" not in config.security:
            log.warning("allow_insecure: passwords sent to %s on the 'none' endpoint are not encrypted",
                        config.endpoint)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self._disconnect()
        await self.server.stop()

    async def __aenter__(self) -> Self:
        await self.start()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.stop()

    # -- game connection and polling --------------------------------------------

    async def _disconnect(self) -> None:
        game, self.game = self.game, None
        self.connected.clear()
        if game is not None:
            with contextlib.suppress(Exception):  # closing a broken connection may fail; nothing to do about it
                await game.close()

    async def _run_game(self) -> None:
        assert self.model is not None
        backoff = BACKOFF_START
        rcon = f"{self.config.rcon_host}:{self.config.rcon_port}"
        while True:
            game = self._game_factory()
            try:
                hello = await game.connect()
                log.info("connected to Factorio %s (opcua-io %s) at %s", hello.factorio_version, hello.mod_version, rcon)
                self.game = game
                self._model_version = None
                if self._ever_connected:
                    self.metrics["Reconnects"] += 1
                self._ever_connected = True
                self.metrics["ConnectedSince"] = now()
                await self.model.set_connected(hello)
                backoff = BACKOFF_START
                await self._poll(game)
            except Exception as exc:  # CancelledError is not an Exception, so stop() still works
                if not isinstance(exc, (RconError, GameError, OSError, asyncio.TimeoutError)):
                    log.exception("unexpected error in game loop; reconnecting")
                elif self.game is not None:
                    log.warning("lost connection to Factorio at %s: %s", rcon, exc)
                else:
                    log.info("cannot reach Factorio at %s (%s); retrying in %.0fs", rcon, exc, backoff)
                await self._disconnect()
                try:
                    await self.model.mark_stale()
                except Exception:
                    log.exception("cannot mark values stale")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)

    async def _poll(self, game: GameApi) -> None:
        """Poll changes until the connection fails.

        Each connection is a new poll session, so its first reply is full; after
        that the mod sends only changes since the reply we acknowledge.
        """
        assert self.model is not None
        loop = asyncio.get_running_loop()
        interval = 1.0 / self.config.poll_hz
        next_at = loop.time()
        session = uuid.uuid4().hex
        ack: int | None = None
        timeouts = 0
        while True:
            start = time.perf_counter()
            try:
                poll = await game.poll(session, ack)
            except TimeoutError:
                timeouts += 1
                if timeouts >= MAX_POLL_TIMEOUTS:
                    raise
                log.warning("Factorio did not answer a poll within %gs (saving?); waiting", self.config.rcon_timeout)
                continue
            timeouts = 0
            received = now()
            latency_ms = (time.perf_counter() - start) * 1000
            if poll.full or poll.model_version != self._model_version:
                await self.model.sync_tags(await game.browse(), self._method_write)
                self._model_version = poll.model_version
            await self.model.apply_poll(poll, received)
            ack = poll.seq
            await self.model.set_status(GameTick=poll.tick, TickPaused=poll.tick_paused, GameSpeed=poll.speed,
                                        ModelVersion=poll.model_version, LastPollLatencyMs=latency_ms)
            await self.model.emit_model_changes()
            self.metrics["Polls"] += 1
            await self.model.set_metrics(self.metrics)
            # Only after the first full sync, so every tag's nodes exist once this is set.
            self.connected.set()
            next_at += interval
            delay = next_at - loop.time()
            if delay > 0:
                await asyncio.sleep(delay)
            else:
                self.metrics["LatePolls"] += 1
                next_at = loop.time()  # running late: skip ahead instead of bursting

    # -- writes from OPC clients -------------------------------------------------

    def _install_write_hook(self) -> None:
        service = self.server.iserver.attribute_service
        self._original_write = service.write
        service.write = self._write

        # Record who is calling each method, for the audit log. Wraps the
        # sessions of this server only.
        iserver = self.server.iserver
        create_session = iserver.create_session

        def create_tracked_session(*args, **kwargs):
            session = create_session(*args, **kwargs)
            call = session.call

            async def tracked_call(params):
                token = CALLING_USER.set(session.user)
                try:
                    return await call(params)
                finally:
                    CALLING_USER.reset(token)

            session.call = tracked_call
            return session

        iserver.create_session = create_tracked_session

    async def _write(
        self, params: ua.WriteParameters, user: User = User()  # noqa: B008 (asyncua's signature)
    ) -> list[ua.StatusCode]:
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
            for i, result in zip(passthrough, await self._original_write(sub, user=user), strict=True):
                results[i] = result

        for tag, items in by_tag.items():
            code = await self._write_tag(tag, {key: value for _, key, value in items}, user)
            for i, _, _ in items:
                results[i] = status(code)
        return results  # type: ignore[return-value]

    async def _game_write(self, tag: str, signals: dict[str, int], mode: str, user: User | None,
                          via: str) -> dict[str, int]:
        """Write through to the game, update the writer's nodes from its reply, and audit-log it."""
        assert self.model is not None
        audit = {"tag": tag, "signals": signals, "mode": mode, "via": via,
                 "user": getattr(user, "name", None) or "anonymous"}
        game = self.game
        if game is None:
            self.metrics["WriteErrors"] += 1
            log.warning("write to %s refused: not connected to the game", tag, extra={**audit, "result": "offline"})
            raise ua.UaStatusCodeError(ua.StatusCodes.BadNoCommunication)
        try:
            result = await game.write(tag, signals, mode)
        except GameError as exc:
            self.metrics["WriteErrors"] += 1
            log.warning("write to %s rejected by the game: %s", tag, exc, extra={**audit, "result": "rejected"})
            raise ua.UaStatusCodeError(ua.StatusCodes.BadInvalidArgument) from exc
        except (TimeoutError, RconError, OSError) as exc:
            self.metrics["WriteErrors"] += 1
            log.warning("write to %s failed: %s", tag, exc, extra={**audit, "result": "failed"})
            raise ua.UaStatusCodeError(ua.StatusCodes.BadCommunicationError) from exc
        self.metrics["Writes"] += 1
        log.info("write %s %s by %s", tag, json.dumps(signals, sort_keys=True), audit["user"],
                 extra={**audit, "result": "ok"})
        await self.model.apply_writer(tag, result)
        return result

    async def _write_tag(self, tag: str, signals: dict[str, int], user: User | None) -> int:
        try:
            await self._game_write(tag, signals, "merge", user, "write")
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
        result = await self._game_write(tag, signals, mode, CALLING_USER.get(), "method")
        return json.dumps(result, sort_keys=True)
