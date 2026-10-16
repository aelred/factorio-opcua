"""Bridge configuration: a TOML file, then environment variables, then CLI flags.

    [factorio]
    rcon_host = "127.0.0.1"
    rcon_port = 27015
    rcon_password_file = "/factorio/config/rconpw"   # or rcon_password = "..."
    rcon_timeout = 5.0

    [opcua]
    endpoint = "opc.tcp://127.0.0.1:4840/factorio-opc/"
    server_name = "Factorio OPC UA"

    [bridge]
    poll_hz = 10        # 1-30

The RCON password can also come from FACTORIO_RCON_PASSWORD.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

MIN_POLL_HZ = 1.0
# RCON commands run once per tick, so a sequential poll tops out near 30 Hz
# (docs/spike-results.md).
MAX_POLL_HZ = 30.0


class ConfigError(Exception):
    pass


@dataclass
class Config:
    rcon_host: str = "127.0.0.1"
    rcon_port: int = 27015
    rcon_password: str = ""
    rcon_timeout: float = 5.0
    endpoint: str = "opc.tcp://127.0.0.1:4840/factorio-opc/"
    server_name: str = "Factorio OPC UA"
    poll_hz: float = 10.0

    def validate(self) -> Config:
        if not self.rcon_password:
            raise ConfigError("no RCON password: set factorio.rcon_password(_file) or FACTORIO_RCON_PASSWORD")
        if not MIN_POLL_HZ <= self.poll_hz <= MAX_POLL_HZ:
            raise ConfigError(f"poll_hz must be between {MIN_POLL_HZ:g} and {MAX_POLL_HZ:g}, got {self.poll_hz:g}")
        if not 0 < self.rcon_port < 65536:
            raise ConfigError(f"invalid rcon_port {self.rcon_port}")
        if not self.endpoint.startswith("opc.tcp://"):
            raise ConfigError(f"endpoint must start with opc.tcp://, got {self.endpoint!r}")
        return self


SECTIONS = {
    "factorio": {"rcon_host", "rcon_port", "rcon_password", "rcon_password_file", "rcon_timeout"},
    "opcua": {"endpoint", "server_name"},
    "bridge": {"poll_hz"},
}


def read_password_file(path: str | Path, base: Path | None = None) -> str:
    path = Path(path)
    if base is not None and not path.is_absolute():
        path = base / path
    try:
        return path.read_text().strip()
    except OSError as exc:
        raise ConfigError(f"cannot read RCON password file {path}: {exc}") from None


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
        types = {f.name: f.type for f in fields(Config)}
        for section, values in data.items():
            if section not in SECTIONS or not isinstance(values, dict):
                raise ConfigError(f"unknown config section [{section}]")
            for key, value in values.items():
                if key not in SECTIONS[section]:
                    raise ConfigError(f"unknown config key {section}.{key}")
                if key == "rcon_password_file":
                    config.rcon_password = read_password_file(value, path.parent)
                    continue
                expected = {"str": str, "int": int, "float": (int, float)}[types[key]]
                if not isinstance(value, expected) or isinstance(value, bool):
                    raise ConfigError(f"{section}.{key} has the wrong type: {value!r}")
                setattr(config, key, float(value) if types[key] == "float" else value)
    if env.get("FACTORIO_RCON_PASSWORD"):
        config.rcon_password = env["FACTORIO_RCON_PASSWORD"]
    return config
