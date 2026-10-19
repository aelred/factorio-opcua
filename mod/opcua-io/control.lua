-- opcua-io runtime: tracks OPC Reader/Writer entities and serves the RCON API.

local api = require("lib.api")
local demo = require("lib.demo")
local gui = require("lib.gui")
local registry = require("lib.registry")

local BLUEPRINT_TAG = "opc_name"

-- An uncaught error in an event handler would stop a multiplayer server, which
-- is far worse than a skipped update for one entity. Log it and carry on.
local function safe(handler)
  return function(event)
    local ok, err = pcall(handler, event)
    if not ok then
      log("[opcua-io] event " .. tostring(event.name) .. " failed: " .. tostring(err))
      game.print("[opcua-io] internal error, see factorio-current.log: " .. tostring(err))
    end
  end
end

local function on_built(event)
  local entity = event.entity or event.destination
  if not (entity and entity.valid and registry.KIND_BY_ENTITY[entity.name]) then
    return
  end
  local tags = event.tags
  registry.add(entity, tags and tags[BLUEPRINT_TAG])
end

local function on_destroyed(event)
  if event.useful_id and registry.remove_unit(event.useful_id) then
    gui.on_removed(event.useful_id)
  end
end

-- A combinator that dies leaves a ghost (when the force has ghosts on death);
-- store the tag name on it so the rebuilt entity keeps its name. The registry
-- entry is still there: on_object_destroyed only fires at the end of the tick.
local function on_post_entity_died(event)
  local ghost = event.ghost
  local entry = event.unit_number and registry.get_by_unit(event.unit_number)
  if ghost and ghost.valid and entry then
    local tags = ghost.tags or {}
    tags[BLUEPRINT_TAG] = entry.name
    ghost.tags = tags
  end
end

local function on_settings_pasted(event)
  local entity = event.destination
  local kind = entity and entity.valid and registry.KIND_BY_ENTITY[entity.name]
  if kind then
    registry.normalize(entity, kind)
  end
end

-- Store tag names in blueprints so pasted copies keep them (suffixed if taken).
local function on_setup_blueprint(event)
  local blueprint = event.stack
  if not (blueprint and blueprint.valid_for_read and blueprint.is_blueprint) then
    blueprint = event.record
  end
  if not blueprint or not event.mapping then
    return
  end
  for index, entity in pairs(event.mapping.get()) do
    if entity.valid and registry.KIND_BY_ENTITY[entity.name] then
      local entry = registry.get_by_unit(entity.unit_number)
      if entry then
        blueprint.set_blueprint_entity_tag(index, BLUEPRINT_TAG, entry.name)
      end
    end
  end
end

local filters = {}
for _, name in pairs(registry.ENTITY_NAMES) do
  filters[#filters + 1] = { filter = "name", name = name }
end

for _, id in pairs({
  defines.events.on_built_entity,
  defines.events.on_robot_built_entity,
  defines.events.on_space_platform_built_entity,
  defines.events.script_raised_built,
  defines.events.script_raised_revive,
  defines.events.on_entity_cloned,
}) do
  script.on_event(id, safe(on_built), filters)
end

script.on_event(defines.events.on_object_destroyed, safe(on_destroyed))
script.on_event(defines.events.on_post_entity_died, safe(on_post_entity_died),
  { { filter = "type", type = "constant-combinator" } })
script.on_event(defines.events.on_entity_settings_pasted, safe(on_settings_pasted))
script.on_event(defines.events.on_player_setup_blueprint, safe(on_setup_blueprint))
script.on_event("opcua-io-open", safe(gui.on_open_input))
script.on_event(defines.events.on_gui_opened, safe(gui.on_opened))
script.on_event(defines.events.on_gui_closed, safe(gui.on_closed))
script.on_event(defines.events.on_gui_click, safe(gui.on_click))
script.on_event(defines.events.on_gui_confirmed, safe(gui.on_confirmed))

-- Six times a second: open panels show live values, and the demo (if built)
-- updates its switch and status.
local refresh_panels, update_demo = safe(gui.refresh), safe(demo.update)
script.on_nth_tick(10, function(event)
  refresh_panels(event)
  update_demo(event)
end)

script.on_init(function()
  registry.init()
end)

script.on_configuration_changed(function()
  registry.init()
  registry.rescan()
end)

-- /opc_demo [leave|remove]: takes the player to the demo surface, which
-- admins, the server console and RCON can build (once) and remove; `leave`
-- returns to Nauvis. Anyone may visit and leave.
local function say(cmd, message)
  if cmd.player_index then
    game.get_player(cmd.player_index).print(message)
  else
    rcon.print(message)
  end
end

local function demo_command(cmd)
  local player = cmd.player_index and game.get_player(cmd.player_index)
  local admin = not player or player.admin
  local action = cmd.parameter or ""
  if action == "leave" then
    if player then
      demo.leave(player)
    end
  elseif action == "remove" then
    if not admin then
      say(cmd, "[opcua-io] only admins can remove the demo")
      return
    end
    demo.remove()
    say(cmd, "[opcua-io] demo removed")
  elseif action == "" then
    if not demo.exists() then
      if not admin then
        say(cmd, "[opcua-io] there is no demo yet; an admin can build it with /opc_demo")
        return
      end
      if game.surfaces[demo.SURFACE] then
        say(cmd, "[opcua-io] a surface named " .. demo.SURFACE .. " already exists; delete it with /opc_demo remove")
        return
      end
      local names = demo.build()
      say(cmd, "[opcua-io] demo built with OPC tags: " .. table.concat(names, ", "))
    elseif not player then
      say(cmd, "[opcua-io] the demo already exists")
    end
    if player then
      demo.visit(player)
    end
  else
    say(cmd, "[opcua-io] usage: /opc_demo [leave|remove]")
  end
end

commands.add_command("opc_demo", "factorio-opcua: build and visit the demo surface; /opc_demo leave|remove",
  function(cmd)
    local ok, err = pcall(demo_command, cmd)
    if not ok then
      log("[opcua-io] /opc_demo failed: " .. tostring(err))
      say(cmd, "[opcua-io] /opc_demo failed: " .. tostring(err))
    end
  end)

api.register_commands()

-- For other mods and scripts. Functions return nil on success or an error string.
remote.add_interface("opcua-io", {
  get_name = function(entity)
    local entry = entity and entity.valid and registry.get_by_unit(entity.unit_number)
    return entry and entry.name or nil
  end,
  rename = function(old_name, new_name)
    local entry = registry.get(old_name)
    if not entry then
      return "unknown tag '" .. tostring(old_name) .. "'"
    end
    local ok, err = registry.rename(entry, new_name)
    return (not ok) and err or nil
  end,
})
