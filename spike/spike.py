"""Milestone 1 spike: measure RCON behaviour of a real Factorio server running opc-io.

Usage: python spike/spike.py [--host 127.0.0.1] [--port 27015] [--password-file .dev/factorio/config/rconpw]
Prints a JSON report; see docs/spike-results.md for interpretation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

from factorio_opc.rcon import RconClient, RconError


async def hello(client: RconClient) -> dict:
    return json.loads(await client.execute("/opc_hello"))


def percentiles(samples_ms: list[float]) -> dict:
    q = statistics.quantiles(samples_ms, n=100)
    return {"p50": round(q[49], 2), "p95": round(q[94], 2), "p99": round(q[98], 2),
            "max": round(max(samples_ms), 2), "n": len(samples_ms)}


async def latency(client: RconClient, command: str, n: int) -> dict:
    samples = []
    for _ in range(n):
        start = time.perf_counter()
        await client.execute(command)
        samples.append((time.perf_counter() - start) * 1000)
    return percentiles(samples)


async def pipelined(client: RconClient, n: int) -> dict:
    start = time.perf_counter()
    await asyncio.gather(*(client.execute("/opc_hello") for _ in range(n)))
    elapsed = time.perf_counter() - start
    return {"requests": n, "seconds": round(elapsed, 3), "req_per_s": round(n / elapsed, 1)}


async def tick_rate(client: RconClient, seconds: float) -> dict:
    t0, h0 = time.perf_counter(), await hello(client)
    await asyncio.sleep(seconds)
    t1, h1 = time.perf_counter(), await hello(client)
    return {"ticks": h1["tick"] - h0["tick"], "ups": round((h1["tick"] - h0["tick"]) / (t1 - t0), 1)}


async def ups_under_polling(client: RconClient, poll_hz: float, payload: int, seconds: float) -> dict:
    """Poll at poll_hz with a payload-sized reply and report the game's UPS meanwhile."""
    h0, t0 = await hello(client), time.perf_counter()
    late = 0
    interval = 1 / poll_hz
    next_at = t0
    while time.perf_counter() - t0 < seconds:
        await client.execute(f"/opc_spike_payload {payload}")
        next_at += interval
        delay = next_at - time.perf_counter()
        if delay > 0:
            await asyncio.sleep(delay)
        else:
            late += 1
    h1, t1 = await hello(client), time.perf_counter()
    return {"poll_hz": poll_hz, "payload_bytes": payload,
            "ups": round((h1["tick"] - h0["tick"]) / (t1 - t0), 1), "late_polls": late}


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=27015)
    parser.add_argument("--password-file", default=".dev/factorio/config/rconpw")
    parser.add_argument("--quick", action="store_true", help="fewer samples")
    parser.add_argument("--error-test", action="store_true",
                        help="also run a command that raises a Lua error (may stop the server)")
    args = parser.parse_args()
    password = open(args.password_file).read().strip()
    n = 50 if args.quick else 300
    report: dict = {}

    async with RconClient(args.host, args.port, password, timeout=30) as client:
        report["hello"] = await hello(client)
        report["tick_rate_2s"] = await tick_rate(client, 2.0)
        report["latency_hello_ms"] = await latency(client, "/opc_hello", n)
        report["latency_10kB_ms"] = await latency(client, "/opc_spike_payload 10000", n)
        report["pipelined_hello"] = await pipelined(client, n)
        report["reply_size_ms"] = {}
        for size in (100_000, 1_000_000, 10_000_000):
            start = time.perf_counter()
            body = await client.execute(f"/opc_spike_payload {size}")
            report["reply_size_ms"][size] = {"ms": round((time.perf_counter() - start) * 1000, 1),
                                             "received": len(body)}
        report["unknown_command_reply"] = await client.execute("/opc_does_not_exist")
        report["ups_under_polling"] = [
            await ups_under_polling(client, hz, payload, 5.0)
            for hz, payload in ((10, 10_000), (30, 10_000), (60, 10_000), (10, 1_000_000))
        ]
        if args.error_test:
            try:
                report["lua_error_reply"] = await client.execute("/opc_spike_error")
                await asyncio.sleep(1)
                report["after_lua_error_hello"] = await hello(client)
            except (RconError, asyncio.TimeoutError, ConnectionError) as exc:
                report["lua_error_reply"] = f"{type(exc).__name__}: {exc}"

    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
