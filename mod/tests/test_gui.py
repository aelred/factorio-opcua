"""gui.refresh keeps open panels up to date, with stand-ins for Factorio's objects."""

SETUP = """
defines = { wire_connector_id = { circuit_red = 1, circuit_green = 2 } }
storage = { opc = { by_unit = {}, by_name = {} } }
red = { signals = { { signal = { type = "item", name = "iron-plate" }, count = 3 } } }
entity = { valid = true, get_circuit_network = function(wire) if wire == 1 then return red end end }
storage.opc.by_unit[7] = { entity = entity, unit = 7, kind = "reader", name = "r" }
frame = {
  tags = { unit = 7 },
  opcua_io_red = { caption = "" },
  opcua_io_green = { caption = "" },
  destroy = function() frame.destroyed = true end,
}
game = { connected_players = { { gui = { screen = { opcua_io_frame = frame } } } } }
gui = require("lib.gui")
"""


def test_refresh_shows_current_reader_signals(lua, to_py):
    lua.execute(SETUP)
    g = lua.globals()
    g.gui.refresh()
    assert g.frame.opcua_io_red.caption == "item/iron-plate = 3"
    assert to_py(g.frame.opcua_io_green.caption) == ["opcua-io.not-connected"]

    lua.execute("red.signals[1].count = 5")
    g.gui.refresh()
    assert g.frame.opcua_io_red.caption == "item/iron-plate = 5"


def test_refresh_closes_panels_whose_entity_is_gone(lua):
    lua.execute(SETUP)
    lua.execute("entity.valid = false")
    lua.globals().gui.refresh()
    assert lua.globals().frame.destroyed is True
