-- A demo of OPC Readers and Writers on its own surface, built by /opc_demo.
-- It never touches the player's own map. See docs/demo.md for what it contains.
--
-- storage.demo (nil until built):
--   on           whether the production line runs (the LINE combinator, kept
--                in sync with the line_switch writer)
--   switch       the LINE constant combinator players toggle
--   writer_unit  unit number of the line_switch writer
--   status       constant combinator holding the status code, read by line_status
--   status_text  render object showing the status in game
--   code         the status code last set
--   assembler    the line's assembling machine
--   last_working tick the assembler last worked

local registry = require("lib.registry")

local demo = {}

demo.SURFACE = "opcua-demo"
demo.UPDATE_TICKS = 10

local RUN = "virtual/signal-R"
local STATUS_SIGNAL = { type = "virtual", name = "signal-E", quality = "normal" }

-- line_status codes. Short gaps in production (an inserter catching up) are
-- not faults: the line counts as running for GRACE_TICKS after it last worked.
demo.STATUS = { running = 1, stopped = 2, no_power = 3, no_input = 4, output_blocked = 5, other = 9 }
local STATUS_TEXT = {
  [1] = "1: running",
  [2] = "2: stopped by switch",
  [3] = "3: no power",
  [4] = "4: no input",
  [5] = "5: output blocked",
  [9] = "9: other problem",
}
local GRACE_TICKS = 180

local WIDTH, HEIGHT = 48, 32
local SPAWN = { -4, 12 }

local red = defines.wire_connector_id.circuit_red
local green = defines.wire_connector_id.circuit_green

-- Connects a circuit or copper wire.
local function wire(a, a_id, b, b_id)
  a.get_wire_connector(a_id, true).connect_to(b.get_wire_connector(b_id, true), false)
end

local function create_surface()
  local surface = game.create_surface(demo.SURFACE, {
    width = WIDTH,
    height = HEIGHT,
    default_enable_all_autoplace_controls = false,
    no_enemies_mode = true,
  })
  surface.always_day = true
  surface.request_to_generate_chunks({ 0, 0 }, 2)
  surface.force_generate_chunk_requests()
  local tiles = {}
  for x = -WIDTH / 2, WIDTH / 2 - 1 do
    for y = -HEIGHT / 2, HEIGHT / 2 - 1 do
      tiles[#tiles + 1] = { name = (x + y) % 2 == 0 and "lab-dark-1" or "lab-dark-2", position = { x, y } }
    end
  end
  surface.set_tiles(tiles)
  for _, entity in pairs(surface.find_entities()) do
    entity.destroy()
  end
  return surface
end

local function builder(surface)
  local b = { names = {} }

  function b.entity(name, position, direction)
    local entity = surface.create_entity({ name = name, position = position, direction = direction, force = "player" })
    if not entity then
      error("cannot place " .. name .. " at " .. serpent.line(position))
    end
    return entity
  end

  -- Editor-only entities (infinite power and items) that players can't mine.
  function b.fixed(name, position)
    local entity = b.entity(name, position)
    entity.minable = false
    return entity
  end

  -- An OPC Reader or Writer registered under `wanted` (suffixed if taken).
  function b.opc(kind, wanted, position)
    local entity = b.entity("opc-" .. kind, position)
    local entry = registry.add(entity, wanted)
    b.names[#b.names + 1] = entry.name
    return entity, entry
  end

  function b.label(text, position, scale)
    return rendering.draw_text({
      text = text,
      surface = surface,
      target = position,
      color = { 1, 1, 1 },
      scale = scale or 1,
      alignment = "center",
    })
  end

  -- A constant combinator outputting one signal; players toggle it on and off.
  function b.toggle(position, signal)
    local entity = b.entity("constant-combinator", position)
    local section = entity.get_or_create_control_behavior().add_section()
    section.set_slot(1, { value = { type = "virtual", name = signal, quality = "normal" }, min = 1 })
    return entity
  end

  function b.enable_when(entity, signal)
    local cb = entity.get_or_create_control_behavior()
    cb.circuit_enable_disable = true
    cb.circuit_condition = { first_signal = { type = "virtual", name = signal }, comparator = ">", constant = 0 }
  end

  -- An arithmetic combinator that adds `step` and its input to its own output
  -- every tick.
  function b.counter(position, signal, step)
    local entity = b.entity("arithmetic-combinator", position, defines.direction.east)
    entity.get_or_create_control_behavior().parameters = {
      first_signal = signal, second_constant = step, operation = "+", output_signal = signal,
    }
    local ids = defines.wire_connector_id
    wire(entity, ids.combinator_output_red, entity, ids.combinator_input_red)
    return entity
  end

  -- Medium poles connected only as listed, so nothing bypasses the power switch.
  function b.poles(positions)
    local poles = {}
    for i, position in ipairs(positions) do
      poles[i] = b.entity("medium-electric-pole", position)
      poles[i].get_wire_connector(defines.wire_connector_id.pole_copper, true).disconnect_all()
    end
    for i = 2, #poles do
      wire(poles[i - 1], defines.wire_connector_id.pole_copper, poles[i], defines.wire_connector_id.pole_copper)
    end
    return poles
  end

  return b
end

local function build_clock_lamps_echo(b)
  b.label("Clock", { -11, -10 }, 1.5)
  local clock = b.counter({ -12, -7.5 }, { type = "virtual", name = "signal-T" }, 1)
  local reader = b.opc("reader", "demo_clock", { -9.5, -7.5 })
  wire(clock, defines.wire_connector_id.combinator_output_red, reader, red)

  b.label("Lamps and echo", { -4, -10 }, 1.5)
  -- All four lamps start on, so each has an OPC node to write 0 or 1 to.
  local writer, lamps_entry = b.opc("writer", "demo_lamps", { -7.5, -7.5 })
  local previous = writer
  local all_on = {}
  for i = 1, 4 do
    all_on["virtual/signal-" .. i] = 1
    local lamp = b.entity("small-lamp", { -6.5 + i, -7.5 })
    lamp.always_on = true
    b.enable_when(lamp, "signal-" .. i)
    wire(previous, red, lamp, red)
    previous = lamp
  end
  registry.set_writer_values(lamps_entry, all_on)
  local echo = b.opc("reader", "demo_echo", { -7.5, -5.5 })
  wire(writer, red, echo, red)
  b.fixed("electric-energy-interface", { 0, -5 })
  b.poles({ { -9.5, -5.5 }, { -2.5, -5.5 } }) -- combinators need power too
  b.label("demo_clock", { -9.5, -6.6 }, 0.7)
  b.label("demo_lamps: signal-1..4", { -5, -6.6 }, 0.7)
  b.label("demo_echo", { -7.5, -4.6 }, 0.7)
end

local function build_line(b)
  b.label("Production line: iron plates -> gears", { -4, -3 }, 1.5)

  -- Supply chest -> input belt -> assembler -> output belt -> collection chest.
  local source = b.fixed("infinity-chest", { -12.5, 2.5 })
  source.set_infinity_container_filter(1, { name = "iron-plate", count = 100, mode = "exactly" })
  local west = defines.direction.west -- inserters face where they pick up from
  local feed = b.entity("fast-inserter", { -11.5, 2.5 }, west)
  for x = -10.5, -6.5 do
    b.entity("transport-belt", { x, 2.5 }, defines.direction.east)
  end
  local load = b.entity("fast-inserter", { -5.5, 2.5 }, west)
  local assembler = b.entity("assembling-machine-1", { -3.5, 2.5 })
  assembler.set_recipe("iron-gear-wheel")
  local unload = b.entity("fast-inserter", { -1.5, 2.5 }, west)
  for x = -0.5, 3.5 do
    b.entity("transport-belt", { x, 2.5 }, defines.direction.east)
  end
  local collect = b.entity("fast-inserter", { 4.5, 2.5 }, west)
  local sink = b.fixed("infinity-chest", { 5.5, 2.5 })
  sink.remove_unfiltered_items = true

  -- On/off combinators: SUPPLY feeds the input belt, LINE runs the machine and
  -- its inserters, COLLECTION empties the output belt.
  local supply = b.toggle({ -11.5, -0.5 }, "signal-S")
  b.enable_when(feed, "signal-S")
  wire(supply, red, feed, red)
  local switch = b.toggle({ -3.5, -0.5 }, "signal-R")
  for _, entity in ipairs({ load, assembler, unload }) do
    b.enable_when(entity, "signal-R")
    wire(switch, red, entity, red)
  end
  local collection = b.toggle({ 4.5, -0.5 }, "signal-K")
  b.enable_when(collect, "signal-K")
  wire(collection, red, collect, red)
  local _, switch_entry = b.opc("writer", "line_switch", { -1.5, -0.5 })
  registry.set_writer_values(switch_entry, { [RUN] = 1 })
  b.label("SUPPLY on/off", { -11.5, -1.6 }, 0.8)
  b.label("LINE on/off = line_switch", { -2.5, -1.6 }, 0.8)
  b.label("COLLECTION on/off", { 4.5, -1.6 }, 0.8)

  -- Counters: the inserters putting plates on the line and taking gears off it
  -- pulse once per item they move. (A belt's pulse reading overcounts once
  -- items queue on it.)
  local function count(inserter, position, item, wanted, reader_position)
    local cb = inserter.get_or_create_control_behavior()
    cb.circuit_read_hand_contents = true
    cb.circuit_hand_read_mode = defines.control_behavior.inserter.hand_read_mode.pulse
    local counter = b.counter(position, { type = "item", name = item }, 0)
    wire(inserter, green, counter, defines.wire_connector_id.combinator_input_green)
    local reader = b.opc("reader", wanted, reader_position)
    wire(counter, defines.wire_connector_id.combinator_output_red, reader, red)
    b.label(wanted, { reader_position[1], reader_position[2] + 0.9 }, 0.7)
  end
  count(feed, { -8, 5.5 }, "iron-plate", "line_input_count", { -5.5, 5.5 })
  count(collect, { 1, 5.5 }, "iron-gear-wheel", "line_output_count", { 3.5, 5.5 })

  -- Power: interface -> pole -> power switch -> poles along the line.
  b.fixed("electric-energy-interface", { -14, 9 })
  local before = b.poles({ { -12.5, 8.5 } })[1]
  local power_switch = b.entity("power-switch", { -10, 9 })
  power_switch.power_switch_state = true
  local after = b.poles({ { -7.5, 8.5 }, { -8.5, 4.5 }, { -2.5, 4.5 }, { 3.5, 4.5 } })
  local pole_copper = defines.wire_connector_id.pole_copper
  wire(before, pole_copper, power_switch, defines.wire_connector_id.power_switch_left_copper)
  wire(power_switch, defines.wire_connector_id.power_switch_right_copper, after[1], pole_copper)
  b.label("POWER switch", { -10, 10.4 }, 0.8)

  -- Status code, set by demo.update and read by line_status.
  local status = b.entity("constant-combinator", { -3.5, 9.5 })
  status.get_or_create_control_behavior().add_section()
  local status_reader = b.opc("reader", "line_status", { -1.5, 9.5 })
  wire(status, red, status_reader, red)
  local status_text = b.label("", { -2.5, 10.6 }, 1)

  storage.demo = {
    on = true,
    switch = switch,
    writer_unit = switch_entry.unit,
    status = status,
    status_text = status_text,
    assembler = assembler,
    last_working = game.tick,
  }
end

function demo.exists()
  return storage.demo ~= nil
end

-- Builds the demo surface. Returns the OPC tag names it registered.
function demo.build()
  local surface = create_surface()
  local b = builder(surface)
  build_clock_lamps_echo(b)
  build_line(b)
  demo.update()
  return b.names
end

local function set_status(code)
  local d = storage.demo
  if d.code == code then
    return
  end
  d.code = code
  d.status.get_control_behavior().get_section(1).set_slot(1, { value = STATUS_SIGNAL, min = code })
  d.status_text.text = "line_status = " .. STATUS_TEXT[code]
end

local function line_status(d)
  if not d.on then
    return demo.STATUS.stopped
  end
  local status, s = d.assembler.status, defines.entity_status
  if status == s.no_power or status == s.low_power then
    return demo.STATUS.no_power
  end
  if status == s.working then
    d.last_working = game.tick
  end
  if game.tick - d.last_working <= GRACE_TICKS then
    return demo.STATUS.running
  end
  if status == s.no_ingredients or status == s.item_ingredient_shortage then
    return demo.STATUS.no_input
  end
  if status == s.full_output then
    return demo.STATUS.output_blocked
  end
  return demo.STATUS.other
end

-- Keeps the LINE combinator and the line_switch writer in sync (whichever
-- changed last wins) and updates the status code.
function demo.update()
  local d = storage.demo
  if not (d and d.switch.valid and d.status.valid and d.assembler.valid) then
    return
  end
  local entry = registry.get_by_unit(d.writer_unit)
  local cb = d.switch.get_control_behavior()
  if cb.enabled ~= d.on then -- toggled in game
    d.on = cb.enabled
    if entry then
      registry.set_writer_values(entry, d.on and { [RUN] = 1 } or {})
    end
  elseif entry and ((entry.values[RUN] or 0) > 0) ~= d.on then -- written by OPC
    d.on = not d.on
    cb.enabled = d.on
  end
  set_status(line_status(d))
end

function demo.remove()
  local surface = game.surfaces[demo.SURFACE]
  if surface then
    for _, player in pairs(game.players) do
      if player.surface == surface then
        demo.leave(player)
      end
    end
    game.delete_surface(surface)
  end
  storage.demo = nil
end

function demo.visit(player)
  player.teleport(SPAWN, demo.SURFACE)
end

function demo.leave(player)
  local nauvis = game.surfaces.nauvis
  player.teleport(player.force.get_spawn_position(nauvis), nauvis)
end

return demo
