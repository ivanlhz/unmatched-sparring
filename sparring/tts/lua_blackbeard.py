"""Lua builder for Blackbeard's doubloons (docs/heroes/blackbeard.md): the bot puts the coins where the engine has them.

The three doubloons are three tokens in one stack (a Custom_Token_Stack nicknamed "Doubloon", data/tts/blackbeard.json `doubloon_stack`). The ones
Blackbeard holds lie on the stack's resting spot (`held_spot`) and the Treasury's lie on the Treasury tile (`treasury_spot`). A token taken out of
a stack gets a new GUID, so the coins are found by nickname (and by the stack's GUID while it is still one object), never by a list of GUIDs. A
separate module (like `lua_rosie`) that uses the same guards and registry (`lua._registered`)."""
from __future__ import annotations

from .lua import PANEL_NAME, PING_GAP, PING_LEAD, _PINGER_LUA, _f, _guid, _i, _registered, _seats_lua, lua_str

NEAR = 1.0               # a coin within this distance (x, z) of a spot is on it
RISE = 0.25              # each coin of a pile lies this much above the one under it


@_registered
def set_doubloons(name: str, stack_guid: str, held_spot: tuple[float, float, float], treasury_spot: tuple[float, float, float],
                  treasury: int, seat_colors: list[str]) -> str:
    """Leaves exactly `treasury` coins on `treasury_spot` and every other coin on `held_spot`. A stack of several coins (the one at `stack_guid`, or
    any object named `name`) is taken apart with `takeObject` (the coins land on `held_spot`); a coin already on the right spot is left alone;
    every coin it moves is pinged, `PING_GAP` apart. Everything that could be a Deck, a Card, a bag, a zone or the bot's panel is skipped.
    Returns `{total, treasury, held, moved, guids}`: `total` is how many coins exist on the table (0: they are not there)."""
    if not isinstance(treasury, int) or isinstance(treasury, bool) or not 0 <= treasury <= 3:
        raise ValueError("treasury 0-3 expected")
    return f"""-- sparring:set_doubloons
local seats = {_seats_lua(seat_colors)}
{_PINGER_LUA}local NAME, SRC = {lua_str(name)}, {_guid(stack_guid)}
local HELD = Vector({_f(held_spot[0])}, {_f(held_spot[1])}, {_f(held_spot[2])})
local TREASURY = Vector({_f(treasury_spot[0])}, {_f(treasury_spot[1])}, {_f(treasury_spot[2])})
local WANT = {_i(treasury)}
local skip = {{Deck = true, Card = true, Bag = true, Infinite = true, Block = true, Board = true, Hand = true, Scripting = true}}
local coins = {{}}
for _, o in ipairs(getObjects()) do
  local ok, hit = pcall(function()
    return not skip[o.type] and o.getName() ~= {lua_str(PANEL_NAME)} and (o.getGUID() == SRC or o.getName() == NAME)
  end)
  if ok and hit then
    local qty = 1
    pcall(function() local q = o.getQuantity() if q ~= nil and q > 1 then qty = q end end)
    while qty > 1 do
      local new = o.takeObject({{position = HELD, smooth = false}})
      if new == nil then break end
      coins[#coins + 1] = new
      qty = qty - 1
    end
    coins[#coins + 1] = o
  end
end
local function dist(c, spot)
  local p = c.getPosition()
  return math.sqrt((p.x - spot.x) ^ 2 + (p.z - spot.z) ^ 2)
end
local onT, onH, other = {{}}, {{}}, {{}}
for _, c in ipairs(coins) do
  if dist(c, TREASURY) <= {_f(NEAR)} then onT[#onT + 1] = c
  elseif dist(c, HELD) <= {_f(NEAR)} then onH[#onH + 1] = c
  else other[#other + 1] = c end
end
local moved, guids, pings = 0, {{}}, {{}}
local function send(c, spot, k)
  c.setPosition(Vector(spot.x, spot.y + {_f(RISE)} * k, spot.z))
  moved = moved + 1
  guids[#guids + 1] = c.getGUID()
  pings[#pings + 1] = c.getPosition()
end
while #onT > WANT do
  local c = table.remove(onT)
  onH[#onH + 1] = c
  send(c, HELD, #onH - 1)
end
while #onT < WANT and (#other > 0 or #onH > 0) do
  local c = table.remove(other) or table.remove(onH)
  onT[#onT + 1] = c
  send(c, TREASURY, #onT - 1)
end
for _, c in ipairs(other) do
  onH[#onH + 1] = c
  send(c, HELD, #onH - 1)
end
for k, at in ipairs(pings) do
  Wait.time(function() pcall(function() pinger().pingTable(at) end) end, {_f(PING_LEAD)} + (k - 1) * {_f(PING_GAP)})
end
return JSON.encode({{total = #coins, treasury = #onT, held = #onH, moved = moved, guids = guids}})
"""
