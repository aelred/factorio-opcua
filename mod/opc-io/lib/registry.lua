-- Registry of OPC Reader/Writer entities, keyed by unit number and by tag name.
-- Lives in storage.opc so it is saved with the map:
--   by_unit[unit_number] = { entity, unit, kind, name, values }  (values: a writer's cached output)
--   by_name[name]        = same entry
--   model_version        bumped on every add, remove or rename
--   next_index[kind]     counter for default names ("reader-1", ...)
--   sessions             bridge poll sessions (lib/poll.lua)
--   audit_index          round-robin position of audit_writers

local names = require("lib.names")
local signals = require("lib.signals")

local registry = {}

registry.KIND_BY_ENTITY = { ["opc-reader"] = "reader", ["opc-writer"] = "writer" }
registry.ENTITY_NAMES = { "opc-reader", "opc-writer" }

function registry.init()
  storage.opc = storage.opc or {}
  local s = storage.opc
  s.by_unit = s.by_unit or {}
  s.by_name = s.by_name or {}
  s.model_version = s.model_version or 0
  s.next_index = s.next_index or { reader = 1, writer = 1 }
  s.sessions = s.sessions or {}
  s.audit_index = s.audit_index or 0
end

function registry.sessions()
  return storage.opc.sessions
end

local function state()
  return storage.opc
end

local function bump()
  state().model_version = state().model_version + 1
end

function registry.model_version()
  return state().model_version
end

function registry.get(name)
  local entry = state().by_name[name]
  if entry and entry.entity.valid then
    return entry
  end
  return nil
end

function registry.get_by_unit(unit)
  return state().by_unit[unit]
end

-- All entries sorted by name, cached until model_version changes. A plain
-- local is fine as a cache: it only speeds up producing the same result,
-- which comes from storage. Callers must skip entries whose entity is no
-- longer valid.
local sorted_entries, sorted_version

function registry.entries()
  local s = state()
  if sorted_entries == nil or sorted_version ~= s.model_version then
    sorted_entries = {}
    for _, entry in pairs(s.by_name) do
      sorted_entries[#sorted_entries + 1] = entry
    end
    table.sort(sorted_entries, function(a, b) return a.name < b.name end)
    sorted_version = s.model_version
  end
  return sorted_entries
end

local function control(entity)
  return entity.get_or_create_control_behavior()
end

local function copy(map)
  local result = {}
  for k, v in pairs(map) do
    result[k] = v
  end
  return result
end
registry.copy = copy

-- A writer's actual output, read from its sections. Comparatively expensive.
function registry.read_writer(entity)
  local cb = control(entity)
  local map = {}
  for i = 1, cb.sections_count do
    local section = cb.get_section(i)
    for k, v in pairs(signals.from_filters(section.filters)) do
      map[k] = (map[k] or 0) + v
    end
  end
  return map
end

-- Writers' output is cached in entry.values: the mod is the only thing that
-- changes it (pastes are normalized), and audit_writers catches anything else.
function registry.set_writer_values(entry, map)
  local cb = control(entry.entity)
  if cb.sections_count ~= 1 then -- e.g. another mod's script removed the section
    registry.normalize(entry.entity, "writer")
  end
  cb.get_section(1).filters = signals.to_filters(map)
  entry.values = copy(map)
end

-- Re-reads `count` writers (round robin) and fixes their cached values if
-- something outside the mod changed them, e.g. another mod's script.
function registry.audit_writers(count)
  local s = state()
  local writers = {}
  for _, entry in ipairs(registry.entries()) do
    if entry.kind == "writer" and entry.entity.valid then
      writers[#writers + 1] = entry
    end
  end
  if #writers == 0 then
    return
  end
  for _ = 1, math.min(count, #writers) do
    s.audit_index = s.audit_index % #writers + 1
    local entry = writers[s.audit_index]
    entry.values = registry.read_writer(entry.entity)
  end
end

-- Enforces the invariants script relies on, whatever a blueprint, paste or
-- player did to the combinator:
--   writer: enabled, exactly one section with no logistic group (a group would
--           share values with other combinators). Existing values are kept.
--   reader: disabled and no sections, so it never adds to the networks it reads.
function registry.normalize(entity, kind)
  local cb = control(entity)
  local keep = {}
  if kind == "writer" then
    keep = registry.read_writer(entity)
  end
  for i = cb.sections_count, 1, -1 do
    cb.remove_section(i)
  end
  if kind == "writer" then
    cb.add_section()
    cb.get_section(1).filters = signals.to_filters(keep)
    cb.enabled = true
    local entry = state().by_unit[entity.unit_number]
    if entry then
      entry.values = keep
    end
  else
    cb.enabled = false
  end
end

-- Registers a newly built entity. `wanted` is an optional preferred name
-- (from blueprint tags); taken names get a "-2", "-3" ... suffix.
function registry.add(entity, wanted)
  local s = state()
  local kind = registry.KIND_BY_ENTITY[entity.name]
  if not kind or not entity.unit_number then
    return nil
  end
  local existing = s.by_unit[entity.unit_number]
  if existing then
    return existing
  end
  local base = wanted
  if not (base and names.validate(base)) then
    base = kind .. "-" .. s.next_index[kind]
    s.next_index[kind] = s.next_index[kind] + 1
  end
  local name = names.unique(base, function(n) return s.by_name[n] ~= nil end)
  local entry = { entity = entity, unit = entity.unit_number, kind = kind, name = name }
  s.by_unit[entry.unit] = entry
  s.by_name[name] = entry
  script.register_on_object_destroyed(entity)
  registry.normalize(entity, kind)
  bump()
  return entry
end

function registry.remove_unit(unit)
  local s = state()
  local entry = s.by_unit[unit]
  if not entry then
    return nil
  end
  s.by_unit[unit] = nil
  if s.by_name[entry.name] == entry then
    s.by_name[entry.name] = nil
  end
  bump()
  return entry
end

function registry.rename(entry, new_name)
  local s = state()
  if new_name == entry.name then
    return true
  end
  local ok, err = names.validate(new_name)
  if not ok then
    return false, err
  end
  if s.by_name[new_name] then
    return false, "name '" .. new_name .. "' is already used"
  end
  s.by_name[entry.name] = nil
  entry.name = new_name
  s.by_name[new_name] = entry
  bump()
  return true
end

-- Rebuilds the registry against the actual map: drops entries whose entity is
-- gone and registers any OPC entities that are missing (e.g. after a mod update).
function registry.rescan()
  local s = state()
  for unit, entry in pairs(s.by_unit) do
    if not entry.entity.valid then
      registry.remove_unit(unit)
    end
  end
  for _, surface in pairs(game.surfaces) do
    for _, entity in pairs(surface.find_entities_filtered({ name = registry.ENTITY_NAMES })) do
      if s.by_unit[entity.unit_number] then
        registry.normalize(entity, registry.KIND_BY_ENTITY[entity.name])
      else
        registry.add(entity)
      end
    end
  end
end

return registry
