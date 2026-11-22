"""Lua builder for Little Red's Basket (docs/heroes/little-red-riding-hood.md, Table).

The Basket is a loose card of her bag that lies in her discard zone. It must NOT stack on the cards of her pile: a Deck that holds one card that is
nobody's is not "ours" to the restart (`reset_deck` skips it), and a card inside a Deck no longer answers to its GUID. `basket_aside` puts it back on its own
resting spot, taking it out of a Deck first when somebody (a hand, a merge of the stacking spot) put it in one. Same guards and registry as `lua_rosie`."""
from __future__ import annotations

from .lua import _f, _guid, _registered


@_registered
def basket_aside(guid: str, spot: tuple[float, float, float], rot: tuple[float, float, float], near: float = 0.6) -> str:
    """Leaves the Basket (`guid`) on `spot`, face up and turned `rot`. A loose Basket that is already within `near` of the spot is left alone; one that
    lies elsewhere is moved; one found inside a Deck (any Deck of the table whose contents list `guid`) is taken out with `takeObject` onto the spot.
    Returns `{found, taken, moved}`: `found` is false when the Basket is nowhere (it was lost: the caller says so)."""
    return f"""-- sparring:basket_aside
local G = {_guid(guid)}
local SPOT = Vector({_f(spot[0])}, {_f(spot[1])}, {_f(spot[2])})
local ROT = Vector({_f(rot[0])}, {_f(rot[1])}, {_f(rot[2])})
local NEAR2 = {_f(near)} ^ 2
local function lay(card)
  card.setPosition(SPOT)
  card.setRotation(ROT)
end
local card = getObjectFromGUID(G)
if card ~= nil then
  local p = card.getPosition()
  if (p.x - SPOT.x) ^ 2 + (p.z - SPOT.z) ^ 2 <= NEAR2 then return JSON.encode({{found = true, taken = false, moved = false}}) end
  lay(card)
  return JSON.encode({{found = true, taken = false, moved = true}})
end
for _, o in ipairs(getObjects()) do
  local ok, inside = pcall(function()
    if o.type ~= "Deck" then return false end
    for _, c in ipairs(o.getData().ContainedObjects or {{}}) do
      if c.GUID == G then return true end
    end
    return false
  end)
  if ok and inside then
    local taken = o.takeObject({{guid = G, position = SPOT, rotation = ROT, smooth = false}})
    return JSON.encode({{found = true, taken = taken ~= nil, moved = true}})
  end
end
return JSON.encode({{found = false, taken = false, moved = false}})
"""
