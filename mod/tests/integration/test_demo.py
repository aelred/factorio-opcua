"""The /opc_demo surface: clock, lamps, echo and the production line with its status signals."""

import pytest

from helpers import eventually

TAGS = {"demo_clock", "demo_lamps", "demo_echo", "line_input_count", "line_output_count", "line_status"}
RUNNING = {"R", "P", "W"}  # line on, power on, machine working


def at(name, x, y):
    return f'game.surfaces["opcua-demo"].find_entity("{name}", {{{x}, {y}}})'


SUPPLY, LINE, COLLECTION = (at("constant-combinator", x, -0.5) for x in (-11.5, -3.5, 4.5))
POWER = at("constant-combinator", -12.5, 6.5)
POWER_SWITCH = at("power-switch", -10, 9)


@pytest.fixture
async def demo(factorio):
    assert "demo built" in await factorio.client.execute("/opc_demo")
    await factorio.lua("game.speed = 10")  # the line takes a while to fill and drain
    yield factorio
    await factorio.lua("game.speed = 1")
    await factorio.client.execute("/opc_demo remove")

    async def removed():
        tags = (await factorio.command("opc_browse"))["tags"] or []
        assert not TAGS & {t["name"] for t in tags}

    await eventually(removed)


async def reader(factorio, name):
    return (await factorio.values())["readers"][name]["red"]


async def wait_for_status(factorio, expected):
    """Waits until line_status shows exactly these signals (virtual signal-X, value 1)."""
    async def check():
        status = await reader(factorio, "line_status")
        assert {key.removeprefix("virtual/signal-") for key, value in status.items() if value} == expected

    await eventually(check, timeout=30)


def toggle(combinator, on):
    return f"{combinator}.get_control_behavior().enabled = {'true' if on else 'false'}"


async def test_demo_has_tags_clock_lamps_and_echo(demo):
    assert {t["name"] for t in (await demo.command("opc_browse"))["tags"]} >= TAGS
    assert "already exists" in await demo.client.execute("/opc_demo")

    async def clock():
        values = await reader(demo, "demo_clock")
        assert "virtual/signal-T" in values
        return values["virtual/signal-T"]

    first = await eventually(clock)

    async def ticking():
        assert await clock() > first

    await eventually(ticking)

    def lamp_on(i):
        return demo.lua(f"return {at('small-lamp', -6.5 + i, -7.5)}.status == defines.entity_status.working")

    assert [await lamp_on(i) for i in range(1, 5)] == ["true"] * 4  # all on to start
    await demo.command("opc_write", {"tag": "demo_lamps", "signals": {"virtual/signal-2": 0}})
    await demo.ticks()
    assert [await lamp_on(i) for i in range(1, 5)] == ["true", "false", "true", "true"]
    assert await reader(demo, "demo_echo") == {"virtual/signal-1": 1, "virtual/signal-3": 1, "virtual/signal-4": 1}


async def test_line_counts_and_status_signals(demo):
    await wait_for_status(demo, RUNNING)

    async def counting():
        counts = await reader(demo, "line_input_count"), await reader(demo, "line_output_count")
        assert counts[0].get("item/iron-plate", 0) > 10 and counts[1].get("item/iron-gear-wheel", 0) > 2

    await eventually(counting, timeout=30)

    await demo.lua(toggle(LINE, False))
    await wait_for_status(demo, {"P"})
    await demo.lua(toggle(LINE, True))
    await wait_for_status(demo, RUNNING)

    await demo.lua(toggle(POWER, False))
    await wait_for_status(demo, {"R"})
    assert await demo.lua(f"return {POWER_SWITCH}.power_switch_state") == "false"
    await demo.lua(toggle(POWER, True))
    await wait_for_status(demo, RUNNING)

    await demo.lua(toggle(SUPPLY, False))
    await wait_for_status(demo, {"R", "P", "I"})  # input belt empty at the machine
    await demo.lua(toggle(SUPPLY, True))
    await wait_for_status(demo, RUNNING)

    await demo.lua(toggle(COLLECTION, False))
    await wait_for_status(demo, {"R", "P", "B"})  # gears backed up at the machine
    await demo.lua(toggle(COLLECTION, True))
    await wait_for_status(demo, RUNNING)
