-- Pure helpers for circuit signals: keys, values and conversion between
-- Factorio's signal lists, logistic filters and plain {key = value} maps.
-- No game globals are used here so the module can be unit tested outside Factorio.
--
-- A signal key is "type/name" or "type/name/quality", e.g. "item/iron-plate",
-- "virtual/signal-A", "item/iron-plate/rare". Normal quality is never written
-- in a key; type defaults to "item" as it does in Factorio's SignalID.

local signals = {}

signals.INT32_MIN = -2147483648
signals.INT32_MAX = 2147483647
signals.MAX_SIGNALS_PER_WRITE = 1000

-- SignalID type -> name of the LuaPrototypes collection holding its prototypes.
signals.PROTOTYPE_COLLECTIONS = {
  ["item"] = "item",
  ["fluid"] = "fluid",
  ["virtual"] = "virtual_signal",
  ["entity"] = "entity",
  ["recipe"] = "recipe",
  ["space-location"] = "space_location",
  ["asteroid-chunk"] = "asteroid_chunk",
  ["quality"] = "quality",
}

-- type -> name -> quality -> key. A pure memo (same result with or without it)
-- that saves building the same strings on every poll.
local key_cache = {}

function signals.key(id)
  local t, name, quality = id.type or "item", id.name, id.quality or "normal"
  local by_name = key_cache[t]
  if not by_name then
    by_name = {}
    key_cache[t] = by_name
  end
  local by_quality = by_name[name]
  if not by_quality then
    by_quality = {}
    by_name[name] = by_quality
  end
  local key = by_quality[quality]
  if not key then
    key = t .. "/" .. name
    if quality ~= "normal" then
      key = key .. "/" .. quality
    end
    by_quality[quality] = key
  end
  return key
end

-- Returns a SignalID table {type, name, quality} or nil and an error message.
function signals.parse_key(key)
  if type(key) ~= "string" then
    return nil, "signal key must be a string"
  end
  local parts = {}
  for part in string.gmatch(key, "[^/]+") do
    parts[#parts + 1] = part
  end
  if #parts < 2 or #parts > 3 or string.find(key, "//", 1, true) or string.sub(key, -1) == "/" then
    return nil, "invalid signal key '" .. key .. "' (expected type/name or type/name/quality)"
  end
  if not signals.PROTOTYPE_COLLECTIONS[parts[1]] then
    return nil, "unknown signal type '" .. parts[1] .. "' in '" .. key .. "'"
  end
  return { type = parts[1], name = parts[2], quality = parts[3] or "normal" }
end

-- Checks that a SignalID refers to existing prototypes and may be set on a
-- constant combinator. `protos` is the game's `prototypes` global (injected for tests).
function signals.validate_id(id, protos)
  local collection = protos[signals.PROTOTYPE_COLLECTIONS[id.type]]
  local proto = collection and collection[id.name]
  if not proto then
    return false, "unknown " .. id.type .. " signal '" .. id.name .. "'"
  end
  if id.type == "virtual" and proto.special then
    return false, "special signal '" .. id.name .. "' cannot be written"
  end
  if not protos.quality[id.quality] then
    return false, "unknown quality '" .. id.quality .. "'"
  end
  return true
end

function signals.validate_value(value)
  if type(value) ~= "number" or value ~= value or math.floor(value) ~= value then
    return false, "signal value must be an integer"
  end
  if value < signals.INT32_MIN or value > signals.INT32_MAX then
    return false, "signal value out of int32 range"
  end
  return true
end

-- Circuit network `signals` array (may be nil) -> {key = count}.
function signals.from_network(list)
  local map = {}
  for _, s in pairs(list or {}) do
    local key = signals.key(s.signal)
    map[key] = (map[key] or 0) + s.count
  end
  return map
end

-- Logistic section `filters` array -> {key = value}.
function signals.from_filters(filters)
  local map = {}
  for _, f in pairs(filters or {}) do
    if f.value and f.value.name and f.min and f.min ~= 0 then
      local key = signals.key(f.value)
      map[key] = (map[key] or 0) + f.min
    end
  end
  return map
end

local function sorted_keys(map)
  local keys = {}
  for k in pairs(map) do
    keys[#keys + 1] = k
  end
  table.sort(keys)
  return keys
end
signals.sorted_keys = sorted_keys

-- {key = value} -> logistic section filters, sorted by key so slot order is stable.
-- Zero values are dropped. Keys must already be valid.
function signals.to_filters(map)
  local filters = {}
  for _, key in ipairs(sorted_keys(map)) do
    local value = map[key]
    if value ~= 0 then
      local id = assert(signals.parse_key(key))
      filters[#filters + 1] = {
        value = { type = id.type, name = id.name, quality = id.quality, comparator = "=" },
        min = value,
      }
    end
  end
  return filters
end

-- Applies a write. mode "replace" starts from empty, "merge" starts from current.
-- A value of 0 removes the signal. Returns the new map.
function signals.apply(current, updates, mode)
  local result = {}
  if mode == "merge" then
    for k, v in pairs(current) do
      result[k] = v
    end
  end
  for k, v in pairs(updates) do
    if v == 0 then
      result[k] = nil
    else
      result[k] = v
    end
  end
  return result
end

-- Validates a decoded write request's `signals` table against `protos`.
-- Returns a normalized {key = value} map (keys re-encoded canonically) or nil, error.
function signals.validate_updates(updates, protos)
  if type(updates) ~= "table" then
    return nil, "'signals' must be an object of signal key -> integer"
  end
  local result, count = {}, 0
  for key, value in pairs(updates) do
    local id, err = signals.parse_key(key)
    if not id then
      return nil, err
    end
    local ok, verr = signals.validate_id(id, protos)
    if not ok then
      return nil, verr
    end
    ok, verr = signals.validate_value(value)
    if not ok then
      return nil, verr .. " for '" .. key .. "'"
    end
    result[signals.key(id)] = value
    count = count + 1
  end
  if count > signals.MAX_SIGNALS_PER_WRITE then
    return nil, "too many signals in one write (max " .. signals.MAX_SIGNALS_PER_WRITE .. ")"
  end
  return result
end

return signals
