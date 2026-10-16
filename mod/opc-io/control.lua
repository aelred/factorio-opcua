-- RCON command API for the factorio-opc bridge.
-- Every command replies with JSON via rcon.print and is only usable over RCON.

local PROTO = 1

local function reply(t)
  rcon.print(helpers.table_to_json(t))
end

-- Wraps a command handler so it is RCON-only and can never raise.
-- An uncaught Lua error inside a command stops a multiplayer server
-- (measured in the milestone 1 spike), so errors become a JSON error reply.
local function rcon_only(handler)
  return function(cmd)
    if cmd.player_index then
      game.get_player(cmd.player_index).print("[opc-io] this command is for the OPC bridge (RCON) only")
      return
    end
    local ok, err = pcall(handler, cmd)
    if not ok then
      log("[opc-io] /" .. cmd.name .. " failed: " .. tostring(err))
      reply { ok = false, error = tostring(err) }
    end
  end
end

commands.add_command("opc_hello", "factorio-opc: handshake (RCON only)", rcon_only(function()
  reply {
    proto = PROTO,
    mod_version = script.active_mods["opc-io"],
    factorio_version = script.active_mods["base"],
    tick = game.tick,
    tick_paused = game.tick_paused,
  }
end))

-- Milestone 1 spike helper: reply with a payload of N bytes to probe RCON reply size limits.
commands.add_command("opc_spike_payload", "factorio-opc: spike payload test (RCON only)", rcon_only(function(cmd)
  local n = math.floor(tonumber(cmd.parameter) or 0)
  rcon.print(string.rep("x", n))
end))

-- Milestone 1 spike helper: raise a Lua error inside a command to see how the server reacts.
commands.add_command("opc_spike_error", "factorio-opc: spike error test (RCON only)", rcon_only(function()
  error("opc_spike_error: deliberate error")
end))
