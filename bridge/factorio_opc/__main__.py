"""factorio-opc: run the OPC UA bridge.  `python -m factorio_opc --help`"""

from __future__ import annotations

import argparse
import asyncio
import logging
import signal
import sys

from . import __version__
from .config import ConfigError, load_config, read_password_file
from .server import Bridge


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="factorio-opc", description="OPC UA server for Factorio circuit networks")
    p.add_argument("--config", help="TOML config file")
    p.add_argument("--rcon-host")
    p.add_argument("--rcon-port", type=int)
    p.add_argument("--rcon-password-file", help="file containing the RCON password")
    p.add_argument("--endpoint", help="OPC UA endpoint URL, e.g. opc.tcp://127.0.0.1:4840/factorio-opc/")
    p.add_argument("--poll-hz", type=float, help="game polls per second (1-30, default 10)")
    p.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p.parse_args(argv)


async def run(bridge: Bridge) -> None:
    """Serve until SIGINT or SIGTERM (as sent by Ctrl-C, docker stop or systemd)."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:  # Windows: Ctrl-C still raises KeyboardInterrupt
            pass
    async with bridge:
        await stop.wait()
        logging.getLogger("factorio_opc").info("shutting down")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.log_level != "DEBUG":
        logging.getLogger("asyncua").setLevel(logging.WARNING)
    try:
        config = load_config(args.config)
        for attr in ("rcon_host", "rcon_port", "endpoint", "poll_hz"):
            if getattr(args, attr) is not None:
                setattr(config, attr, getattr(args, attr))
        if args.rcon_password_file:
            config.rcon_password = read_password_file(args.rcon_password_file)
        config.validate()
    except ConfigError as exc:
        print(f"factorio-opc: {exc}", file=sys.stderr)
        return 2
    try:
        asyncio.run(run(Bridge(config)))
    except KeyboardInterrupt:
        pass
    except OSError as exc:  # most often: the OPC UA port is already in use
        print(f"factorio-opc: cannot start OPC UA server on {config.endpoint}: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
