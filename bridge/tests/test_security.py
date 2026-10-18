"""OPC UA security: endpoints, certificates, users and roles."""

import asyncio
import os
import stat

import pytest
from asyncua import Client, ua
from asyncua.crypto.cert_gen import setup_self_signed_certificate
from asyncua.crypto.security_policies import SecurityPolicyBasic256Sha256
from cryptography.x509.oid import ExtendedKeyUsageOID

from factorio_opc import server as server_module
from factorio_opc.__main__ import main
from factorio_opc.auth import hash_password, verify_password
from factorio_opc.config import Config, ConfigError, UserConfig, load_config
from factorio_opc.server import Bridge

from fake_game import FakeGame, FakeWorld
from helpers import eventually, free_port

NS = "urn:factorio-opc"
USERS = [UserConfig("alice", "write", hash_password("alice-pw")), UserConfig("bob", "read", hash_password("bob-pw"))]


@pytest.fixture
def world():
    w = FakeWorld()
    w.add("writer", "press")
    w.writers["press"] = {"virtual/signal-B": 3}
    return w


@pytest.fixture
async def make_bridge(world, tmp_path, monkeypatch):
    monkeypatch.setattr(server_module, "BACKOFF_START", 0.05)
    bridges = []

    async def make(**overrides):
        config = Config(rcon_password="x", endpoint=f"opc.tcp://127.0.0.1:{free_port()}/factorio-opc/",
                        poll_hz=30, pki_dir=str(tmp_path / "pki"), users=USERS, **overrides)
        bridge = Bridge(config.validate(), game_factory=lambda: FakeGame(world))
        await bridge.start()
        bridges.append(bridge)
        await asyncio.wait_for(bridge.connected.wait(), 5)
        return bridge

    yield make
    for b in bridges:
        await b.stop()


async def connect(bridge, user=None, password=None, security=None):
    client = Client(bridge.config.endpoint, timeout=5)
    if user:
        client.set_user(user)
        client.set_password(password)
    if security:
        await client.set_security(SecurityPolicyBasic256Sha256, certificate=str(security[0]),
                                  private_key=str(security[1]), mode=ua.MessageSecurityMode.SignAndEncrypt)
    await client.connect()
    return client


async def try_write_and_call(client):
    """Returns (write status, call status) for the writer's signal node and SetSignals."""
    ns = await client.get_namespace_index(NS)
    signal = client.get_node(ua.NodeId("Writers/press/Signals/virtual/signal-B", ns))
    await eventually(lambda: signal.read_value())
    results = []
    for action in (
        lambda: signal.write_value(ua.DataValue(ua.Variant(7, ua.VariantType.Int32))),
        lambda: client.get_node(ua.NodeId("Writers/press", ns)).call_method(
            ua.NodeId("Writers/press/SetSignals", ns), '{"item/iron-plate": 1}'),
    ):
        try:
            await action()
            results.append(ua.StatusCodes.Good)
        except ua.UaStatusCodeError as exc:
            results.append(exc.code)
    return tuple(results)


@pytest.fixture
def client_cert(tmp_path):
    cert, key = tmp_path / "client_cert.der", tmp_path / "client_key.pem"
    asyncio.run(setup_self_signed_certificate(
        key, cert, "urn:factorio-opc:test-client", "localhost", [ExtendedKeyUsageOID.CLIENT_AUTH],
        {"commonName": "test client"}))
    return cert, key


async def test_anonymous_write_can_write_and_call(make_bridge, world):
    bridge = await make_bridge(security=["none"], anonymous="write")
    client = await connect(bridge)
    try:
        assert await try_write_and_call(client) == (ua.StatusCodes.Good, ua.StatusCodes.Good)
        assert world.writers["press"]["virtual/signal-B"] == 7
    finally:
        await client.disconnect()


async def test_anonymous_read_only(make_bridge, world):
    bridge = await make_bridge(security=["none"], anonymous="read")
    client = await connect(bridge)
    try:
        denied = ua.StatusCodes.BadUserAccessDenied
        assert await try_write_and_call(client) == (denied, denied)
        assert world.writes == []
    finally:
        await client.disconnect()


async def test_users_and_roles(make_bridge, world, caplog):
    bridge = await make_bridge(security=["none"], anonymous="none")
    with pytest.raises(ua.UaStatusCodeError):
        await connect(bridge)  # anonymous refused
    with pytest.raises(ua.UaStatusCodeError):
        await connect(bridge, "alice", "wrong")

    bob = await connect(bridge, "bob", "bob-pw")
    try:
        denied = ua.StatusCodes.BadUserAccessDenied
        assert await try_write_and_call(bob) == (denied, denied)
    finally:
        await bob.disconnect()

    alice = await connect(bridge, "alice", "alice-pw")
    try:
        with caplog.at_level("INFO", logger="factorio_opc"):
            assert await try_write_and_call(alice) == (ua.StatusCodes.Good, ua.StatusCodes.Good)
    finally:
        await alice.disconnect()
    # The audit log names the user for value writes and method calls alike.
    assert {(r.via, r.user) for r in caplog.records if getattr(r, "tag", None)} == {("write", "alice"),
                                                                                   ("method", "alice")}


async def test_encrypted_endpoint_with_generated_certificate(make_bridge, client_cert, tmp_path):
    bridge = await make_bridge(security=["sign_encrypt"], anonymous="none")
    pki = tmp_path / "pki"
    assert (pki / "server_cert.der").is_file()
    assert stat.S_IMODE(os.stat(pki / "server_key.pem").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(pki).st_mode) == 0o700

    endpoints = await Client(bridge.config.endpoint).connect_and_get_server_endpoints()
    modes = {e.SecurityMode for e in endpoints}
    assert modes == {ua.MessageSecurityMode.SignAndEncrypt}

    with pytest.raises(Exception):  # noqa: B017 (asyncua raises different errors here)
        await connect(bridge, "alice", "alice-pw")  # no unencrypted endpoint any more
    client = await connect(bridge, "alice", "alice-pw", security=client_cert)
    try:
        ns = await client.get_namespace_index(NS)
        assert await client.get_node(ua.NodeId("Status/Connected", ns)).read_value() is True
        assert await try_write_and_call(client) == (ua.StatusCodes.Good, ua.StatusCodes.Good)
    finally:
        await client.disconnect()


async def test_certificate_is_reused_across_restarts(make_bridge, tmp_path):
    await make_bridge(security=["sign"])
    first = (tmp_path / "pki" / "server_cert.der").read_bytes()
    await make_bridge(security=["sign"])
    assert (tmp_path / "pki" / "server_cert.der").read_bytes() == first


async def test_certificate_covers_machine_names(tmp_path):
    import socket

    from cryptography import x509

    from factorio_opc.server import ensure_certificate

    config = Config(rcon_password="x", endpoint="opc.tcp://192.0.2.7:4840/x/", pki_dir=str(tmp_path / "pki"))
    cert_file, _ = await ensure_certificate(config)
    san = x509.load_der_x509_certificate(cert_file.read_bytes()).extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value
    assert {socket.gethostname(), "localhost"} <= set(san.get_values_for_type(x509.DNSName))
    assert {"127.0.0.1", "192.0.2.7"} <= {str(i) for i in san.get_values_for_type(x509.IPAddress)}
    assert "urn:factorio-opc:bridge" in san.get_values_for_type(x509.UniformResourceIdentifier)
    # A new endpoint address that the certificate doesn't cover gets a new certificate (same key).
    before = cert_file.read_bytes()
    config.endpoint = "opc.tcp://192.0.2.8:4840/x/"
    await ensure_certificate(config)
    assert cert_file.read_bytes() != before


def test_password_hashing():
    encoded = hash_password("pw")
    assert encoded.startswith("scrypt$") and verify_password("pw", encoded)
    assert not verify_password("other", encoded)
    assert not verify_password("pw", "scrypt$not$valid")
    assert hash_password("pw") != encoded  # salted


def test_config_users_and_security(tmp_path):
    path = tmp_path / "bridge.toml"
    path.write_text(f'''
[opcua]
security = ["sign_encrypt"]
anonymous = "none"
pki_dir = "pki"
[[opcua.users]]
name = "ops"
password = "plain-pw"
role = "write"
[[opcua.users]]
name = "viewer"
password_hash = "{hash_password("v")}"
''')
    config = load_config(path, env={"FACTORIO_RCON_PASSWORD": "x"}).validate()
    assert config.security == ["sign_encrypt"] and config.anonymous == "none"
    assert config.pki_dir == str(tmp_path / "pki")
    ops, viewer = config.users
    assert ops.role == "write" and verify_password("plain-pw", ops.password_hash)  # plain passwords get hashed
    assert viewer.role == "read"  # default role


@pytest.mark.parametrize("text, message", [
    ('[opcua]\nsecurity = ["tls"]\n', "opcua.security must be"),
    ('[opcua]\nanonymous = "admin"\n', "opcua.anonymous must be"),
    ('[opcua]\nanonymous = "none"\n', "nobody could log in"),
    ('[[opcua.users]]\nname = "a"\nrole = "admin"\npassword = "x"\n', "role must be"),
    ('[[opcua.users]]\nname = "a"\n', "exactly one of"),
    ('[[opcua.users]]\nname = "a"\npassword_hash = "md5$x"\n', "hash-password"),
    ('[[opcua.users]]\nname = "a"\npassword = "x"\n[[opcua.users]]\nname = "a"\npassword = "y"\n', "twice"),
    ('[opcua]\ncertificate = "c.der"\n', "both"),
    ('[opcua]\nendpoint = "opc.tcp://0.0.0.0:4840/x/"\n', "reachable from the network"),
    (('[opcua]\nendpoint = "opc.tcp://0.0.0.0:4840/x/"\nanonymous = "none"\nsecurity = ["none", "sign"]\n'
      '[[opcua.users]]\nname = "a"\npassword = "x"\n'), "passwords would be sent unencrypted"),
])
def test_config_validation(tmp_path, text, message):
    path = tmp_path / "bridge.toml"
    path.write_text(text)
    with pytest.raises(ConfigError, match=message):
        load_config(path, env={"FACTORIO_RCON_PASSWORD": "x"}).validate()


@pytest.mark.parametrize("extra", [
    'allow_insecure = true',                  # accepted explicitly
    'security = ["sign_encrypt"]',            # encrypted only
    'anonymous = "none"\n[[opcua.users]]\nname = "a"\npassword = "x"',  # users; logins encrypted by default
])
def test_network_endpoint_allowed_when_safe_or_explicit(tmp_path, extra):
    path = tmp_path / "bridge.toml"
    path.write_text(f'[opcua]\nendpoint = "opc.tcp://0.0.0.0:4840/x/"\n{extra}\n')
    load_config(path, env={"FACTORIO_RCON_PASSWORD": "x"}).validate()


def test_hash_password_command(capsys, monkeypatch):
    monkeypatch.setattr("getpass.getpass", lambda prompt="": "typed-pw")
    assert main(["hash-password"]) == 0
    encoded = capsys.readouterr().out.strip()
    assert verify_password("typed-pw", encoded)


def test_hash_password_command_without_input(capsys, monkeypatch):
    def no_input(prompt=""):
        raise EOFError
    monkeypatch.setattr("getpass.getpass", no_input)
    assert main(["hash-password"]) == 1
    assert "no password entered" in capsys.readouterr().err


@pytest.mark.parametrize("security, encrypted", [
    (["none", "sign_encrypt"], True),
    (["none", "sign"], False),  # why config validation insists on sign_encrypt for users on the network
])
async def test_password_policy_on_the_none_endpoint(make_bridge, security, encrypted):
    bridge = await make_bridge(security=security)
    endpoints = await Client(bridge.config.endpoint).connect_and_get_server_endpoints()
    none = next(e for e in endpoints if e.SecurityMode == ua.MessageSecurityMode.None_)
    token = next(t for t in none.UserIdentityTokens if t.TokenType == ua.UserTokenType.UserName)
    plain = (token.SecurityPolicyUri or "#None").endswith("#None")
    assert plain is not encrypted
