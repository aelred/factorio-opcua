"""Wait until the dev server answers /opc_hello over RCON (used by CI after scripts/dev-server.sh up).

Usage: python scripts/wait-for-server.py [--timeout 300] [--password-file .dev/factorio/config/rconpw]
"""

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from factorio_opc.rcon import RconClient


async def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=27015)
    p.add_argument("--password-file", default=".dev/factorio/config/rconpw")
    p.add_argument("--timeout", type=float, default=300)
    args = p.parse_args()
    deadline = time.monotonic() + args.timeout
    last_error = "no attempt"
    while time.monotonic() < deadline:
        try:
            password = Path(args.password_file).read_text().strip()
            async with RconClient(args.host, args.port, password, timeout=10) as client:
                hello = json.loads(await client.execute("/opc_hello"))
                print(f"server ready: Factorio {hello['factorio_version']}, opc-io {hello['mod_version']}")
                return 0
        except Exception as exc:  # not up yet: missing password file, refused, reset, not JSON
            last_error = f"{type(exc).__name__}: {exc}"
        await asyncio.sleep(2)
    print(f"server not ready after {args.timeout:.0f}s: {last_error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
