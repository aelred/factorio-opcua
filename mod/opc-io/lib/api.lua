-- RCON command API used by the factorio-opc bridge. See docs/protocol.md.
-- Every reply is one JSON object with "ok". All handlers go through rcon_only,
-- which catches errors: an uncaught error in a command stops a multiplayer server.

local poll = require("lib.poll")
local registry = require("lib.registry")
local signals = require("lib.signals")

local api = {}

api.PROTO = 1

local function reply(t)
  rcon.print(helpers.table_to_json(t))
end

local function fail(message)
  error({ opc_error = message })
end

local function rcon_only(handler)
  return function(cmd)
    if cmd.player_index then
      game.get_player(cmd.player_index).print("[opc-io] this command is for the OPC bridge (RCON) only")
      return
    end
    local ok, result = pcall(handler, cmd)
    if ok then
      result.ok = true
      reply(result)
    elseif type(result) == "table" and result.opc_error then
      reply({ ok = false, error = result.opc_error })
    else
      log("[opc-io] /" .. cmd.name .. " failed: " .. tostring(result))
      reply({ ok = false, error = "internal error: " .. tostring(result) })
    end
  end
end

local function decode(parameter)
  if not parameter or parameter == "" then
    fail("missing JSON parameter")
  end
  local request = helpers.json_to_table(parameter)
  if type(request) ~= "table" then
    fail("parameter is not valid JSON")
  end
  return request
end

-- Writers re-read per poll to catch changes made outside the mod: 1/20 of
-- them, so all are checked about every 2 seconds at 10 polls per second.
local AUDIT_FRACTION = 20

local function read_all()
  local readers, writers = {}, {}
  local writer_count = 0
  -- network_id -> values, so a network shared by many readers is read once.
  local networks = {}
  local function read(entity, wire)
    local network = entity.get_circuit_network(wire)
    if not network then
      return {}
    end
    local values = networks[network.network_id]
    if not values then
      values = signals.from_network(network.signals)
      networks[network.network_id] = values
    end
    return registry.copy(values) -- each reader gets its own table in storage
  end
  for _, entry in ipairs(registry.entries()) do
    if entry.entity.valid then
      if entry.kind == "reader" then
        readers[entry.name] = {
          red = read(entry.entity, defines.wire_connector_id.circuit_red),
          green = read(entry.entity, defines.wire_connector_id.circuit_green),
        }
      else
        writers[entry.name] = registry.copy(entry.values)
        writer_count = writer_count + 1
      end
    end
  end
  if writer_count > 0 then
    registry.audit_writers(math.ceil(writer_count / AUDIT_FRACTION))
  end
  return { readers = readers, writers = writers }
end

local handlers = {}

function handlers.opc_hello()
  return {
    proto = api.PROTO,
    mod_version = script.active_mods["opc-io"],
    factorio_version = script.active_mods["base"],
    tick = game.tick,
    tick_paused = game.tick_paused,
    speed = game.speed,
    model_version = registry.model_version(),
  }
end

function handlers.opc_browse()
  local tags = {}
  for _, entry in ipairs(registry.entries()) do
    if entry.entity.valid then
      tags[#tags + 1] = {
        name = entry.name,
        kind = entry.kind,
        unit = entry.unit,
      }
    end
  end
  return { tick = game.tick, model_version = registry.model_version(), tags = tags }
end

-- {"session": "<id>", "ack": <seq of the last reply applied>, "full": false}
-- Returns only what changed since the last reply to this session; see lib/poll.lua.
function handlers.opc_poll(cmd)
  local request = decode(cmd.parameter)
  local session, ack, force_full = poll.parse_request(request)
  if not session then
    fail(ack)
  end
  local result = poll.step(registry.sessions(), session, ack, force_full, read_all(), game.tick)
  result.tick = game.tick
  result.tick_paused = game.tick_paused
  result.speed = game.speed
  result.model_version = registry.model_version()
  return result
end

-- {"tag": "line_1", "signals": {"item/iron-plate": 5}, "mode": "merge"|"replace"}
function handlers.opc_write(cmd)
  local request = decode(cmd.parameter)
  local tag = request.tag
  if type(tag) ~= "string" then
    fail("'tag' must be a string")
  end
  local mode = request.mode or "merge"
  if mode ~= "merge" and mode ~= "replace" then
    fail("'mode' must be 'merge' or 'replace'")
  end
  local entry = registry.get(tag)
  if not entry then
    fail("unknown tag '" .. tag .. "'")
  end
  if entry.kind ~= "writer" then
    fail("tag '" .. tag .. "' is a reader and cannot be written")
  end
  local updates, err = signals.validate_updates(request.signals, prototypes)
  if not updates then
    fail(err)
  end
  local values = signals.apply(entry.values, updates, mode)
  local count = 0
  for _ in pairs(values) do
    count = count + 1
  end
  if count > signals.MAX_SIGNALS_PER_WRITE then
    fail("writer would hold more than " .. signals.MAX_SIGNALS_PER_WRITE .. " signals")
  end
  registry.set_writer_values(entry, values)
  return { tick = game.tick, tag = tag, signals = values }
end

local help = {
  opc_hello = "handshake",
  opc_browse = "list OPC tags",
  opc_poll = "read OPC tag values changed since the last poll (JSON parameter)",
  opc_write = "set OPC Writer signals (JSON parameter)",
}

function api.register_commands()
  for name, handler in pairs(handlers) do
    commands.add_command(name, "factorio-opc: " .. help[name] .. " (RCON only)", rcon_only(handler))
  end
end

return api
