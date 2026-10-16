import pytest

from factorio_opc.__main__ import main
from factorio_opc.config import Config, ConfigError, load_config


def write(tmp_path, text):
    path = tmp_path / "bridge.toml"
    path.write_text(text)
    return path


def test_defaults_and_env_password():
    config = load_config(None, env={"FACTORIO_RCON_PASSWORD": "pw"})
    assert config.rcon_password == "pw" and config.poll_hz == 10.0
    config.validate()


def test_file_values_and_relative_password_file(tmp_path):
    (tmp_path / "rconpw").write_text("secret\n")
    path = write(tmp_path, '[factorio]\nrcon_host = "game"\nrcon_port = 27016\nrcon_password_file = "rconpw"\n'
                           '[opcua]\nendpoint = "opc.tcp://0.0.0.0:4841/x/"\n[bridge]\npoll_hz = 5\n')
    config = load_config(path, env={})
    assert (config.rcon_host, config.rcon_port, config.rcon_password) == ("game", 27016, "secret")
    assert config.endpoint == "opc.tcp://0.0.0.0:4841/x/" and config.poll_hz == 5.0


@pytest.mark.parametrize("text, message", [
    ("[factorio]\nrcon_hots = 'x'\n", "unknown config key"),
    ("[opc]\nendpoint = 'x'\n", "unknown config section"),
    ("[bridge]\npoll_hz = 'fast'\n", "wrong type"),
    ("[factorio]\nrcon_password_file = 'missing'\n", "cannot read"),
    ("not toml = = =", "cannot load"),
])
def test_bad_files(tmp_path, text, message):
    with pytest.raises(ConfigError, match=message):
        load_config(write(tmp_path, text), env={})


@pytest.mark.parametrize("changes, message", [
    ({"rcon_password": ""}, "no RCON password"),
    ({"poll_hz": 31}, "between 1 and 30"),
    ({"poll_hz": 0.5}, "between 1 and 30"),
    ({"endpoint": "http://x"}, "opc.tcp://"),
])
def test_validate(changes, message):
    config = Config(rcon_password="pw")
    for k, v in changes.items():
        setattr(config, k, v)
    with pytest.raises(ConfigError, match=message):
        config.validate()


def test_cli_reports_config_errors(capsys, monkeypatch):
    monkeypatch.delenv("FACTORIO_RCON_PASSWORD", raising=False)
    assert main(["--poll-hz", "100"]) == 2
    assert "no RCON password" in capsys.readouterr().err
