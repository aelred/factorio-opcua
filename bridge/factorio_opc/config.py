"""Bridge configuration: a TOML file, then environment variables, then CLI flags.

    [factorio]
    rcon_host = "127.0.0.1"
    rcon_port = 27015
    rcon_password_file = "/factorio/config/rconpw"   # or rcon_password = "..."
    rcon_timeout = 5.0

    [opcua]
    endpoint = "opc.tcp://127.0.0.1:4840/factorio-opc/"
    server_name = "Factorio OPC UA"
    security = ["none", "sign_encrypt"]   # endpoint modes offered: none, sign, sign_encrypt
    anonymous = "write"                   # anonymous access: none, read or write
    pki_dir = "~/.factorio-opc/pki"       # where the self-signed server certificate is kept
    # certificate = "server_cert.der"     # use your own instead (DER or PEM) ...
    # private_key = "server_key.pem"      # ... with its PEM private key
    allow_insecure = false                # see Config.validate

    [[opcua.users]]
    name = "operator"
    password_hash = "scrypt$..."          # from: factorio-opc hash-password
    role = "write"                        # read or write

    [bridge]
    poll_hz = 10        # 1-30
    log_format = "text" # text or json

The RCON password can also come from FACTORIO_RCON_PASSWORD.
"""

from __future__ import annotations

import ipaddress
import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

MIN_POLL_HZ = 1.0
# RCON commands run once per tick, so a sequential poll tops out near 30 Hz.
MAX_POLL_HZ = 30.0

SECURITY_MODES = ("none", "sign", "sign_encrypt")
ACCESS_LEVELS = ("none", "read", "write")
ROLES = ("read", "write")
LOG_FORMATS = ("text", "json")


class ConfigError(Exception):
    pass


@dataclass
class UserConfig:
    name: str
    role: str
    password_hash: str


@dataclass
class Config:
    rcon_host: str = "127.0.0.1"
    rcon_port: int = 27015
    rcon_password: str = ""
    rcon_timeout: float = 5.0
    endpoint: str = "opc.tcp://127.0.0.1:4840/factorio-opc/"
    server_name: str = "Factorio OPC UA"
    security: list[str] = field(default_factory=lambda: ["none", "sign_encrypt"])
    anonymous: str = "write"
    users: list[UserConfig] = field(default_factory=list)
    pki_dir: str = "~/.factorio-opc/pki"
    certificate: str | None = None
    private_key: str | None = None
    allow_insecure: bool = False
    poll_hz: float = 10.0
    log_format: str = "text"

    @property
    def endpoint_is_local(self) -> bool:
        host = urlparse(self.endpoint).hostname or ""
        if host == "localhost":
            return True
        try:
            return ipaddress.ip_address(host).is_loopback
        except ValueError:
            return False

    def validate(self) -> Config:
        if not self.rcon_password:
            raise ConfigError("no RCON password: set factorio.rcon_password(_file) or FACTORIO_RCON_PASSWORD")
        if not MIN_POLL_HZ <= self.poll_hz <= MAX_POLL_HZ:
            raise ConfigError(f"poll_hz must be between {MIN_POLL_HZ:g} and {MAX_POLL_HZ:g}, got {self.poll_hz:g}")
        if not 0 < self.rcon_port < 65536:
            raise ConfigError(f"invalid rcon_port {self.rcon_port}")
        if not self.endpoint.startswith("opc.tcp://"):
            raise ConfigError(f"endpoint must start with opc.tcp://, got {self.endpoint!r}")
        if not self.security or any(m not in SECURITY_MODES for m in self.security):
            raise ConfigError(f"opcua.security must be a non-empty list of {', '.join(SECURITY_MODES)}")
        if self.anonymous not in ACCESS_LEVELS:
            raise ConfigError(f"opcua.anonymous must be one of {', '.join(ACCESS_LEVELS)}")
        if self.anonymous == "none" and not self.users:
            raise ConfigError("opcua.anonymous is 'none' but no [[opcua.users]] are configured: nobody could log in")
        if (self.certificate is None) != (self.private_key is None):
            raise ConfigError("set both opcua.certificate and opcua.private_key, or neither")
        if self.log_format not in LOG_FORMATS:
            raise ConfigError(f"bridge.log_format must be one of {', '.join(LOG_FORMATS)}")
        # Anyone on the network could read (and maybe write) the factory over a
        # connection nobody can verify. Make that a deliberate choice.
        if (not self.endpoint_is_local and "none" in self.security and self.anonymous != "none"
                and not self.allow_insecure):
            raise ConfigError(
                f"endpoint {self.endpoint} is reachable from the network with security 'none' and anonymous "
                f"'{self.anonymous}' access. Remove 'none' from opcua.security, set opcua.anonymous = \"none\" "
                "and add users, or set opcua.allow_insecure = true to accept the risk")
        return self


# key -> (expected TOML type(s), section)
KEYS: dict[str, tuple[type | tuple[type, ...], str]] = {
    "rcon_host": (str, "factorio"),
    "rcon_port": (int, "factorio"),
    "rcon_password": (str, "factorio"),
    "rcon_password_file": (str, "factorio"),
    "rcon_timeout": ((int, float), "factorio"),
    "endpoint": (str, "opcua"),
    "server_name": (str, "opcua"),
    "security": (list, "opcua"),
    "anonymous": (str, "opcua"),
    "users": (list, "opcua"),
    "pki_dir": (str, "opcua"),
    "certificate": (str, "opcua"),
    "private_key": (str, "opcua"),
    "allow_insecure": (bool, "opcua"),
    "poll_hz": ((int, float), "bridge"),
    "log_format": (str, "bridge"),
}
SECTIONS = {s for _, s in KEYS.values()}


def read_password_file(path: str | Path, base: Path | None = None) -> str:
    path = Path(path)
    if base is not None and not path.is_absolute():
        path = base / path
    try:
        return path.read_text().strip()
    except OSError as exc:
        raise ConfigError(f"cannot read RCON password file {path}: {exc}") from None


def _parse_users(raw: list, base: Path) -> list[UserConfig]:
    from .auth import hash_password  # imported lazily: only needed for plain-text passwords

    users, seen = [], set()
    for i, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise ConfigError(f"opcua.users[{i}] must be a table")
        unknown = set(entry) - {"name", "role", "password", "password_hash"}
        if unknown:
            raise ConfigError(f"unknown key(s) in opcua.users[{i}]: {', '.join(sorted(unknown))}")
        name, role = entry.get("name"), entry.get("role", "read")
        if not isinstance(name, str) or not name:
            raise ConfigError(f"opcua.users[{i}] needs a name")
        if name in seen:
            raise ConfigError(f"user {name!r} is configured twice")
        seen.add(name)
        if role not in ROLES:
            raise ConfigError(f"user {name!r}: role must be 'read' or 'write'")
        if ("password" in entry) == ("password_hash" in entry):
            raise ConfigError(f"user {name!r}: set exactly one of password_hash (recommended) or password")
        if "password" in entry:
            password_hash = hash_password(str(entry["password"]))
        else:
            password_hash = str(entry["password_hash"])
            if not password_hash.startswith("scrypt$"):
                raise ConfigError(f"user {name!r}: password_hash must come from 'factorio-opc hash-password'")
        users.append(UserConfig(name=name, role=role, password_hash=password_hash))
    return users


def _resolve(path: str, base: Path) -> str:
    p = Path(path).expanduser()
    return str(p if p.is_absolute() else base / p)


def load_config(path: str | Path | None = None, env: dict[str, str] | None = None) -> Config:
    """Load a config file (optional) and apply environment overrides. Call validate() after CLI overrides."""
    env = os.environ if env is None else env
    config = Config()
    if path is not None:
        path = Path(path)
        try:
            data = tomllib.loads(path.read_text())
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ConfigError(f"cannot load config {path}: {exc}") from None
        base = path.parent
        for section, values in data.items():
            if section not in SECTIONS or not isinstance(values, dict):
                raise ConfigError(f"unknown config section [{section}]")
            for key, value in values.items():
                expected, key_section = KEYS.get(key, (None, None))
                if key_section != section:
                    raise ConfigError(f"unknown config key {section}.{key}")
                bool_ok = expected is bool
                if not isinstance(value, expected) or (isinstance(value, bool) and not bool_ok):
                    raise ConfigError(f"{section}.{key} has the wrong type: {value!r}")
                if key == "rcon_password_file":
                    config.rcon_password = read_password_file(value, base)
                elif key == "users":
                    config.users = _parse_users(value, base)
                elif key == "security":
                    if not all(isinstance(m, str) for m in value):
                        raise ConfigError("opcua.security must be a list of strings")
                    config.security = list(value)
                elif key in ("certificate", "private_key", "pki_dir"):
                    setattr(config, key, _resolve(value, base))
                elif expected == (int, float):
                    setattr(config, key, float(value))
                else:
                    setattr(config, key, value)
    if env.get("FACTORIO_RCON_PASSWORD"):
        config.rcon_password = env["FACTORIO_RCON_PASSWORD"]
    return config
