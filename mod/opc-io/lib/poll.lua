-- Change-only polling for the bridge (/opc_poll). Pure logic over plain
-- tables, so it can be unit tested outside Factorio.
--
-- Each bridge connection is a session holding the values last sent to it.
-- The mod numbers its replies (seq) and the bridge sends back the seq of the
-- last reply it applied (ack). Any mismatch (lost reply, unknown or expired
-- session, or a save loaded from before the last reply) gets a full reply
-- instead of a delta, so the two sides can't drift apart.
--
-- Values tables have the snapshot shape:
--   { readers = { [tag] = { red = map, green = map } }, writers = { [tag] = map } }

local poll = {}

-- Sessions not polled for this many ticks are dropped (5 minutes at 60 UPS).
poll.SESSION_TTL = 5 * 60 * 60
poll.MAX_SESSIONS = 16

-- Keys whose value differs between two {key = value} maps; removed keys map to 0.
-- Returns nil when nothing changed.
function poll.diff(prev, cur)
  local changes, any = {}, false
  for k, v in pairs(cur) do
    if prev[k] ~= v then
      changes[k] = v
      any = true
    end
  end
  for k in pairs(prev) do
    if cur[k] == nil then
      changes[k] = 0
      any = true
    end
  end
  return any and changes or nil
end

local function expire(sessions, tick)
  local count, oldest_id, oldest_tick = 0, nil, nil
  for id, s in pairs(sessions) do
    if tick - s.last_tick > poll.SESSION_TTL then
      sessions[id] = nil
    else
      count = count + 1
      if not oldest_tick or s.last_tick < oldest_tick then
        oldest_id, oldest_tick = id, s.last_tick
      end
    end
  end
  return count, oldest_id
end

-- Validates a decoded request. Returns session id, ack (or nil), force_full; or nil, error.
function poll.parse_request(request)
  local session = request.session
  if type(session) ~= "string" or not string.match(session, "^[%w_%-]+$") or #session > 64 then
    return nil, "'session' must be 1-64 characters of letters, digits, '_' or '-'"
  end
  local ack = request.ack
  if ack ~= nil and (type(ack) ~= "number" or math.floor(ack) ~= ack) then
    return nil, "'ack' must be an integer"
  end
  if request.full ~= nil and type(request.full) ~= "boolean" then
    return nil, "'full' must be a boolean"
  end
  return session, ack, request.full == true
end

-- Computes the reply body for one poll and updates `sessions` in place.
-- Returns { seq, full, readers, writers, removed } where readers/writers hold
-- only changed tags and keys (everything when full), and removed lists tags
-- that disappeared since the last reply.
function poll.step(sessions, session_id, ack, force_full, current, tick)
  local count, oldest = expire(sessions, tick)
  local s = sessions[session_id]
  local full = force_full or s == nil or ack ~= s.seq
  if s == nil then
    if count >= poll.MAX_SESSIONS and oldest then
      sessions[oldest] = nil
    end
    s = { seq = 0 }
    sessions[session_id] = s
  end

  local readers, writers, removed = {}, {}, {}
  if full then
    readers, writers = current.readers, current.writers
  else
    for name, r in pairs(current.readers) do
      local prev = s.values.readers[name]
      if prev == nil then
        readers[name] = r
      else
        local red, green = poll.diff(prev.red, r.red), poll.diff(prev.green, r.green)
        if red or green then
          readers[name] = { red = red or {}, green = green or {} }
        end
      end
    end
    for name, w in pairs(current.writers) do
      local prev = s.values.writers[name]
      if prev == nil then
        writers[name] = w
      else
        writers[name] = poll.diff(prev, w)
      end
    end
    for _, kind in ipairs({ "readers", "writers" }) do
      for name in pairs(s.values[kind]) do
        if current[kind][name] == nil then
          removed[#removed + 1] = name
        end
      end
    end
    table.sort(removed)
  end

  s.values = current
  s.seq = s.seq + 1
  s.last_tick = tick
  return { seq = s.seq, full = full, readers = readers, writers = writers, removed = removed }
end

return poll
