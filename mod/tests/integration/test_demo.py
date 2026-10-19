"""The /opc_demo surface: clock, lamps, echo and the production line with its status codes."""

import pytest

from helpers import eventually

TAGS = {"demo_clock", "demo_lamps", "demo_echo", "line_switch", "line_input_count", "line_output_count",
        "line_status"}
RUNNING, STOPPED, NO_POWER, NO_INPUT, OUTPUT_BLOCKED = 1, 2, 3, 4, 5


def at(name, x, y):
    return f'game.surfaces["opcua-demo"].find_entity("{name}", {{{x}, {y}}})'


SUPPLY, LINE, COLLECTION = (at("constant-combinator", x, -0.5) for x in (-11.5, -3.5, 4.5))
POWER = at("power-switch", -10, 9)


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


async def wait_for_status(factorio, code):
    async def check():
        assert (await reader(factorio, "line_status")).get("virtual/signal-E") == code

    await eventually(check, timeout=30)


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


async def test_line_counts_switch_and_problem_codes(demo):
    await wait_for_status(demo, RUNNING)

    async def counting():
        counts = await reader(demo, "line_input_count"), await reader(demo, "line_output_count")
        assert counts[0].get("item/iron-plate", 0) > 10 and counts[1].get("item/iron-gear-wheel", 0) > 2

    await eventually(counting, timeout=30)

    # The line switch, from OPC and then in game.
    await demo.command("opc_write", {"tag": "line_switch", "signals": {"virtual/signal-R": 0}, "mode": "replace"})
    await wait_for_status(demo, STOPPED)
    assert await demo.lua(f"return {LINE}.get_control_behavior().enabled") == "false"
    await demo.lua(f"{LINE}.get_control_behavior().enabled = true")

    async def switched_on_in_game():
        assert (await demo.values())["writers"]["line_switch"] == {"virtual/signal-R": 1}

    await eventually(switched_on_in_game)
    await wait_for_status(demo, RUNNING)

    await demo.lua(f"{POWER}.power_switch_state = false")
    await wait_for_status(demo, NO_POWER)
    await demo.lua(f"{POWER}.power_switch_state = true")
    await wait_for_status(demo, RUNNING)

    await demo.lua(f"{SUPPLY}.get_control_behavior().enabled = false")
    await wait_for_status(demo, NO_INPUT)
    await demo.lua(f"{SUPPLY}.get_control_behavior().enabled = true")
    await wait_for_status(demo, RUNNING)

    await demo.lua(f"{COLLECTION}.get_control_behavior().enabled = false")
    await wait_for_status(demo, OUTPUT_BLOCKED)
    await demo.lua(f"{COLLECTION}.get_control_behavior().enabled = true")
    await wait_for_status(demo, RUNNING)
