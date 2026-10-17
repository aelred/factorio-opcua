"""Milestone 5 load test: cost of the bridge's polling in game.

For each layout and size it:
  1. builds N readers (and writers) with K signals each over RCON,
  2. times the mod's poll path with Factorio's profiler (/opc_spike_profile),
  3. runs the game as fast as it can (game.speed = 1000) and compares ticks per
     second with no bridge against the real bridge polling at --poll-hz.

Layouts: "pairs" = each writer wired to its own reader (N separate networks),
"shared" = one writer and N readers all on one red network.

Usage: python spike/load_test.py [--sizes 100 500] [--signals 5] [--poll-hz 10] [--seconds 10]
Uses the dev server by default. Leaves game.speed at 1 and removes what it built.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import socket
import time

from factorio_opc.config import Config
from factorio_opc.rcon import RconClient
from factorio_opc.server import Bridge

CLEAR = ('/sc for _, e in pairs(game.surfaces.nauvis.find_entities_filtered{name={"opc-reader","opc-writer"}}) '
         'do e.destroy() end')

SIGNALS = ["signal-A", "signal-B", "signal-C", "signal-D", "signal-E", "signal-F", "signal-G", "signal-H"]


def build_command(layout: str, n: int, k: int) -> str:
    filters = ",".join(
        f'{{value={{type="virtual",name="{SIGNALS[i]}",quality="normal",comparator="="}},min={i + 1}}}'
        for i in range(k))
    red = "defines.wire_connector_id.circuit_red"
    if layout == "pairs":
        body = (f"for i=1,{n} do "
                f'local w=s.create_entity{{name="opc-writer",position={{(i%50)*3,300+math.floor(i/50)*3}},force="player",raise_built=true}} '
                f'local r=s.create_entity{{name="opc-reader",position={{(i%50)*3+1,300+math.floor(i/50)*3}},force="player",raise_built=true}} '
                f"w.get_wire_connector({red},true).connect_to(r.get_wire_connector({red},true),false) "
                f"w.get_control_behavior().get_section(1).filters={{{filters}}} end")
    else:
        body = (f'local w=s.create_entity{{name="opc-writer",position={{0,300}},force="player",raise_built=true}} '
                f"w.get_control_behavior().get_section(1).filters={{{filters}}} local prev=w "
                f"for i=1,{n} do "
                f'local r=s.create_entity{{name="opc-reader",position={{(i%50)*2,302+math.floor(i/50)*2}},force="player",raise_built=true}} '
                f"prev.get_wire_connector({red},true).connect_to(r.get_wire_connector({red},true),false) prev=r end")
    return "/sc local s=game.surfaces.nauvis " + body


def parse_ms(text: str, label: str) -> float:
    match = re.search(label + r" Duration: ([0-9.]+)ms", text)
    if not match:
        raise RuntimeError(f"cannot parse profiler output: {text!r}")
    return float(match.group(1))


async def tick(client: RconClient) -> int:
    return json.loads(await client.execute("/opc_hello"))["tick"]


async def ups(client: RconClient, seconds: float) -> float:
    t0, k0 = time.perf_counter(), await tick(client)
    await asyncio.sleep(seconds)
    t1, k1 = time.perf_counter(), await tick(client)
    return (k1 - k0) / (t1 - t0)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def run(args: argparse.Namespace) -> list[dict]:
    password = open(args.password_file).read().strip()
    results = []
    async with RconClient(args.host, args.port, password, timeout=120) as client:
        try:
            for layout in args.layouts:
                for n in args.sizes:
                    await client.execute(CLEAR)
                    await client.execute(build_command(layout, n, args.signals))
                    await tick(client)
                    profile = await client.execute(f"/opc_spike_profile {args.runs}")
                    row = {"layout": layout, "readers": n, "signals": args.signals,
                           "read_all_ms": parse_ms(profile, "read_all"), "poll_ms": parse_ms(profile, "poll")}

                    await client.execute("/sc game.speed = 1000")
                    row["max_ups_idle"] = round(await ups(client, args.seconds))
                    config = Config(rcon_host=args.host, rcon_port=args.port, rcon_password=password,
                                    endpoint=f"opc.tcp://127.0.0.1:{free_port()}/factorio-opc/",
                                    poll_hz=args.poll_hz, security=["none"])
                    async with Bridge(config) as bridge:
                        await asyncio.wait_for(bridge.connected.wait(), 60)
                        row["max_ups_bridge"] = round(await ups(client, args.seconds))
                    await client.execute("/sc game.speed = 1")
                    row["ups_cost_pct"] = round(100 * (1 - row["max_ups_bridge"] / row["max_ups_idle"]), 1)
                    # Share of one 60 UPS tick budget (16.67 ms) spent per second at poll_hz.
                    row["tick_budget_pct_at_60ups"] = round(100 * row["poll_ms"] * args.poll_hz / 1000, 2)
                    results.append(row)
                    print(json.dumps(row), flush=True)
        finally:
            await client.execute("/sc game.speed = 1")
            await client.execute(CLEAR)
    return results


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=27015)
    p.add_argument("--password-file", default=".dev/factorio/config/rconpw")
    p.add_argument("--layouts", nargs="+", default=["pairs", "shared"])
    p.add_argument("--sizes", nargs="+", type=int, default=[100, 500])
    p.add_argument("--signals", type=int, default=5)
    p.add_argument("--poll-hz", type=float, default=10)
    p.add_argument("--seconds", type=float, default=10)
    p.add_argument("--runs", type=int, default=20)
    asyncio.run(run(p.parse_args()))


if __name__ == "__main__":
    main()
