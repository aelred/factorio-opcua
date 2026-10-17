"""Helpers shared by the bridge tests and the end-to-end integration tests."""

import asyncio
import socket

from asyncua import ua


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def eventually(check, timeout: float = 5.0):
    """Retry an async check until it stops failing (assertion or bad OPC status)."""
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        try:
            return await check()
        except (AssertionError, ua.UaStatusCodeError):
            if asyncio.get_running_loop().time() > deadline:
                raise
            await asyncio.sleep(0.05)
