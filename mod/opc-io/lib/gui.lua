-- Small custom panel that replaces the combinator GUI for OPC entities.
-- It lets the player set the tag name and shows the current signals.
-- Writers can't be edited by hand: their values belong to OPC clients.

local registry = require("lib.registry")
local signals = require("lib.signals")

local gui = {}

local FRAME = "opc_io_frame"

local function signal_text(map)
  local keys = signals.sorted_keys(map)
  if #keys == 0 then
    return { "opc-io.no-signals" }
  end
  local lines = {}
  for _, key in ipairs(keys) do
    lines[#lines + 1] = key .. " = " .. map[key]
  end
  return table.concat(lines, "\n")
end

local function network_section(parent, entity, wire, caption)
  parent.add({ type = "label", caption = { caption }, style = "caption_label" })
  local network = entity.get_circuit_network(wire)
  local text = network and signal_text(signals.from_network(network.signals)) or { "opc-io.not-connected" }
  parent.add({ type = "label", caption = text }).style.single_line = false
end

function gui.close(player)
  local frame = player.gui.screen[FRAME]
  if frame then
    frame.destroy()
  end
end

function gui.open(player, entry)
  gui.close(player)
  local frame = player.gui.screen.add({
    type = "frame",
    name = FRAME,
    direction = "vertical",
    caption = { "opc-io." .. entry.kind },
    tags = { unit = entry.unit },
  })
  frame.auto_center = true

  local row = frame.add({ type = "flow", direction = "horizontal" })
  row.style.vertical_align = "center"
  row.add({ type = "label", caption = { "opc-io.tag-name" } })
  row.add({ type = "textfield", name = "opc_io_name", text = entry.name, tags = { unit = entry.unit } })
  row.add({ type = "button", name = "opc_io_apply", caption = { "opc-io.apply" }, tags = { unit = entry.unit } })
  frame.add({ type = "label", name = "opc_io_error", caption = "" }).style.font_color = { r = 1, g = 0.3, b = 0.3 }

  frame.add({ type = "line" })
  if entry.kind == "writer" then
    frame.add({ type = "label", caption = { "opc-io.signals-written" }, style = "caption_label" })
    frame.add({ type = "label", caption = signal_text(registry.read_writer(entry.entity)) }).style.single_line = false
  else
    network_section(frame, entry.entity, defines.wire_connector_id.circuit_red, "opc-io.signals-red")
    network_section(frame, entry.entity, defines.wire_connector_id.circuit_green, "opc-io.signals-green")
  end

  player.opened = frame
end

local function apply(player, element)
  local frame = player.gui.screen[FRAME]
  local entry = frame and registry.get_by_unit(element.tags.unit)
  if not entry then
    return
  end
  local field = element.parent["opc_io_name"]
  local ok, err = registry.rename(entry, field.text)
  if ok then
    gui.close(player)
  else
    frame["opc_io_error"].caption = err
  end
end

function gui.on_opened(event)
  local entity = event.entity
  if not (entity and entity.valid and registry.KIND_BY_ENTITY[entity.name]) then
    return
  end
  local entry = registry.get_by_unit(entity.unit_number) or registry.add(entity)
  if entry then
    gui.open(game.get_player(event.player_index), entry)
  end
end

function gui.on_closed(event)
  if event.element and event.element.valid and event.element.name == FRAME then
    event.element.destroy()
  end
end

function gui.on_click(event)
  if event.element.valid and event.element.name == "opc_io_apply" then
    apply(game.get_player(event.player_index), event.element)
  end
end

function gui.on_confirmed(event)
  if event.element.valid and event.element.name == "opc_io_name" then
    apply(game.get_player(event.player_index), event.element)
  end
end

-- Close any open panel whose entity was removed.
function gui.on_removed(unit)
  for _, player in pairs(game.players) do
    local frame = player.gui.screen[FRAME]
    if frame and frame.tags.unit == unit then
      frame.destroy()
    end
  end
end

return gui
