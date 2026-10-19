-- Small custom panel shown instead of the combinator GUI for OPC entities.
-- It lets the player set the tag name and shows the current signals, kept up
-- to date by gui.refresh. Writers can't be edited by hand: their values belong
-- to OPC clients.

local registry = require("lib.registry")
local signals = require("lib.signals")

local gui = {}

local FRAME = "opcua_io_frame"

local function signal_text(map)
  local keys = signals.sorted_keys(map)
  if #keys == 0 then
    return { "opcua-io.no-signals" }
  end
  local lines = {}
  for _, key in ipairs(keys) do
    lines[#lines + 1] = key .. " = " .. map[key]
  end
  return table.concat(lines, "\n")
end

local function network_text(entity, wire)
  local network = entity.get_circuit_network(wire)
  return network and signal_text(signals.from_network(network.signals)) or { "opcua-io.not-connected" }
end

local function fill(frame, entry)
  if entry.kind == "writer" then
    frame["opcua_io_written"].caption = signal_text(registry.read_writer(entry.entity))
  else
    frame["opcua_io_red"].caption = network_text(entry.entity, defines.wire_connector_id.circuit_red)
    frame["opcua_io_green"].caption = network_text(entry.entity, defines.wire_connector_id.circuit_green)
  end
end

local function signal_section(frame, name, caption)
  frame.add({ type = "label", caption = { caption }, style = "caption_label" })
  frame.add({ type = "label", name = name, caption = "" }).style.single_line = false
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
    caption = { "opcua-io." .. entry.kind },
    tags = { unit = entry.unit },
  })
  frame.auto_center = true

  local row = frame.add({ type = "flow", direction = "horizontal" })
  row.style.vertical_align = "center"
  row.add({ type = "label", caption = { "opcua-io.tag-name" } })
  row.add({ type = "textfield", name = "opcua_io_name", text = entry.name, tags = { unit = entry.unit } })
  row.add({ type = "button", name = "opcua_io_apply", caption = { "opcua-io.apply" }, tags = { unit = entry.unit } })
  frame.add({ type = "label", name = "opcua_io_error", caption = "" }).style.font_color = { r = 1, g = 0.3, b = 0.3 }

  frame.add({ type = "line" })
  if entry.kind == "writer" then
    signal_section(frame, "opcua_io_written", "opcua-io.signals-written")
  else
    signal_section(frame, "opcua_io_red", "opcua-io.signals-red")
    signal_section(frame, "opcua_io_green", "opcua-io.signals-green")
  end
  fill(frame, entry)

  player.opened = frame
end

-- Updates the signals in every open panel, closing panels whose entity is gone.
function gui.refresh()
  for _, player in pairs(game.connected_players) do
    local frame = player.gui.screen[FRAME]
    if frame then
      local entry = registry.get_by_unit(frame.tags.unit)
      if entry and entry.entity.valid then
        fill(frame, entry)
      else
        frame.destroy()
      end
    end
  end
end

local function apply(player, element)
  local frame = player.gui.screen[FRAME]
  local entry = frame and registry.get_by_unit(element.tags.unit)
  if not entry then
    return
  end
  local field = element.parent["opcua_io_name"]
  local ok, err = registry.rename(entry, field.text)
  if ok then
    gui.close(player)
  else
    frame["opcua_io_error"].caption = err
  end
end

local function is_opc(entity)
  return entity and entity.valid and registry.KIND_BY_ENTITY[entity.name] ~= nil
end

local function open_for(player, entity)
  if not is_opc(entity) then
    return
  end
  local entry = registry.get_by_unit(entity.unit_number) or registry.add(entity)
  if entry then
    gui.open(player, entry)
  end
end

-- OPC entities aren't operable, so the game doesn't open its combinator
-- window for them (opening it and then replacing it made it flash). The panel
-- opens on the "open" control instead, unless the player holds something
-- (e.g. a wire to connect).
function gui.on_open_input(event)
  local player = game.get_player(event.player_index)
  if (player.cursor_stack and player.cursor_stack.valid_for_read) or player.cursor_ghost then
    return
  end
  open_for(player, player.selected)
end

-- Fallback for OPC entities from saves made before they were made
-- non-operable: the game still opens its window once, which this replaces.
-- Any other entity's window is left alone.
function gui.on_opened(event)
  if is_opc(event.entity) then
    event.entity.operable = false
    open_for(game.get_player(event.player_index), event.entity)
  end
end

function gui.on_closed(event)
  if event.element and event.element.valid and event.element.name == FRAME then
    event.element.destroy()
  end
end

function gui.on_click(event)
  if event.element.valid and event.element.name == "opcua_io_apply" then
    apply(game.get_player(event.player_index), event.element)
  end
end

function gui.on_confirmed(event)
  if event.element.valid and event.element.name == "opcua_io_name" then
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
