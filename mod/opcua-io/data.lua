-- OPC Reader and OPC Writer: constant combinators recoloured and driven by script.
-- Both reuse the base game's constant-combinator prototype and graphics
-- (referenced from __base__, not copied).
--   Writer: its output signals are set by the OPC bridge.
--   Reader: kept empty (no signal sections) by control.lua, so it emits
--           nothing and only reads the red/green networks it is wired to.

local base_entity = data.raw["constant-combinator"]["constant-combinator"]
local base_item = data.raw["item"]["constant-combinator"]
local base_recipe = data.raw["recipe"]["constant-combinator"]

local variants = {
  { name = "opc-writer", tint = { r = 1.0, g = 0.55, b = 0.2, a = 1 }, order = "e[opc]-a[writer]" },
  { name = "opc-reader", tint = { r = 0.3, g = 0.65, b = 1.0, a = 1 }, order = "e[opc]-b[reader]" },
}

-- Tints every non-shadow sprite layer found anywhere inside a sprite definition.
local function tint_sprites(node, tint)
  if type(node) ~= "table" then
    return
  end
  if node.filename or node.filenames then
    if not node.draw_as_shadow and not node.draw_as_glow and not node.draw_as_light then
      node.tint = tint
    end
  end
  for _, child in pairs(node) do
    tint_sprites(child, tint)
  end
end

local function tinted_icons(proto, tint)
  if proto.icons then
    local icons = table.deepcopy(proto.icons)
    for _, icon in pairs(icons) do
      icon.tint = tint
    end
    return icons
  end
  return { { icon = proto.icon, icon_size = proto.icon_size, tint = tint } }
end

-- The game's "open" control (left click), used to open the OPC panel: the
-- entities aren't operable, so the game doesn't open anything itself.
data:extend({ { type = "custom-input", name = "opcua-io-open", key_sequence = "", linked_game_control = "open-gui" } })

local technology_effects = data.raw["technology"]["circuit-network"].effects

for _, v in pairs(variants) do
  local entity = table.deepcopy(base_entity)
  entity.name = v.name
  entity.icon = nil
  entity.icons = tinted_icons(base_entity, v.tint)
  entity.minable = { mining_time = 0.1, result = v.name }
  entity.fast_replaceable_group = nil
  entity.next_upgrade = nil
  tint_sprites(entity.sprites, v.tint)

  local item = table.deepcopy(base_item)
  item.name = v.name
  item.icon = nil
  item.icons = tinted_icons(base_item, v.tint)
  item.place_result = v.name
  item.order = v.order

  local recipe = table.deepcopy(base_recipe)
  recipe.name = v.name
  recipe.enabled = false
  recipe.results = { { type = "item", name = v.name, amount = 1 } }

  data:extend({ entity, item, recipe })
  table.insert(technology_effects, { type = "unlock-recipe", recipe = v.name })
end
