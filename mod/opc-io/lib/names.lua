-- Pure helpers for OPC tag names. Names become OPC UA browse names, so they
-- are restricted to letters, digits, '_', '-' and '.', 1 to 64 characters.

local names = {}

names.MAX_LENGTH = 64

function names.validate(name)
  if type(name) ~= "string" or name == "" then
    return false, "name must not be empty"
  end
  if #name > names.MAX_LENGTH then
    return false, "name must be at most " .. names.MAX_LENGTH .. " characters"
  end
  if not string.match(name, "^[%w_%-%.]+$") then
    return false, "name may only contain letters, digits, '_', '-' and '.'"
  end
  return true
end

-- Returns `name` if free, otherwise the first free "name-2", "name-3", ...
-- `taken(n)` must return true when n is already used.
function names.unique(name, taken)
  if not taken(name) then
    return name
  end
  local i = 2
  while true do
    local suffix = "-" .. i
    local candidate = string.sub(name, 1, names.MAX_LENGTH - #suffix) .. suffix
    if not taken(candidate) then
      return candidate
    end
    i = i + 1
  end
end

return names
