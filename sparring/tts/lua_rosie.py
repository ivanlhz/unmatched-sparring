"""Lua builder for Rosie the Riveter's four upgrade tokens (docs/heroes/rosie-the-riveter.md): the bot flips them on the table and pings each
one it flips or moves. A separate module (like `lua_search`) that uses the same guards and registry (`lua._registered`).

The tokens are double-sided Custom_Tokens (data/tts/rosie-the-riveter.json, `token_faces`): the inactive face is up at Z rotation 0 and the
active face at 180, the same convention as Abe Sapien's Intuition tokens. The row rule (deactivating sends the token to the end of the
row) means the tokens change places as well as faces: the row has four resting spots (`slots`, left to right) and the token that is
n-th in the row lies on the n-th spot."""
from __future__ import annotations

from .lua import PING_GAP, PING_LEAD, TOKEN_TYPES, _PINGER_LUA, _f, _guid, _i, _registered, _seats_lua


@_registered
def set_upgrade_tokens(faces: dict[str, tuple[float, float]], order: list[str], active: int, slots: list[tuple[float, float, float]] | None,
                       seat_colors: list[str]) -> str:
    """Puts the upgrade tokens as the engine has them: `order` is the row, left to right, as GUIDs; the first `active` of them lie on their
    active face and the rest on their inactive one (`faces`: GUID -> (active Z, inactive Z)). With `slots` (one position per token, left to
    right) each token is also moved to the spot of its place in the row; without them only the faces are set. A token already on its
    face and its spot is left alone; every token it flipped or moved is pinged, `PING_GAP` apart. Only objects of `TOKEN_TYPES` are touched.
    Returns `{found, total, before, flipped, moved, guids}`: `before` is the position of each token of `order` as it lay when the script
    began (the caller keeps them as the slots of a new game), `found` how many tokens exist."""
    if not order or len(set(order)) != len(order) or set(order) != set(faces):
        raise ValueError("order must list each token of faces once")
    if not isinstance(active, int) or isinstance(active, bool) or not 0 <= active <= len(order):
        raise ValueError(f"active 0-{len(order)} expected")
    if slots is not None and len(slots) != len(order):
        raise ValueError("one slot per token expected")
    kinds = "{" + ", ".join(f'["{t}"] = true' for t in sorted(TOKEN_TYPES)) + "}"
    rows = ", ".join(f"{{{_guid(g)}, {_f(faces[g][0])}, {_f(faces[g][1])}}}" for g in order)
    spots = "nil" if slots is None else "{" + ", ".join(f"{{{_f(s[0])}, {_f(s[1])}, {_f(s[2])}}}" for s in slots) + "}"
    return f"""-- sparring:set_upgrade_tokens
local seats = {_seats_lua(seat_colors)}
{_PINGER_LUA}local ROW = {{{rows}}}
local ACTIVE = {_i(active)}
local SLOTS = {spots}
local kinds = {kinds}
local function near(a, b)
  local d = math.abs((a - b) % 360)
  return math.min(d, 360 - d)
end
local found, flipped, moved, guids, before, pings = 0, 0, 0, {{}}, {{}}, {{}}
for i, row in ipairs(ROW) do
  local obj = getObjectFromGUID(row[1])
  if obj ~= nil and kinds[obj.type] == true then
    found = found + 1
    local p, r = obj.getPosition(), obj.getRotation()
    before[i] = {{p.x, p.y, p.z}}
    local want = (i <= ACTIVE) and row[2] or row[3]
    local changed = false
    if near(r.z, want) > 1 then
      obj.setRotation(Vector(r.x, r.y, want % 360))
      flipped = flipped + 1
      changed = true
    end
    if SLOTS ~= nil then
      local s = SLOTS[i]
      if math.abs(p.x - s[1]) > 0.3 or math.abs(p.z - s[3]) > 0.3 then
        obj.setPosition(Vector(s[1], s[2] + 0.3, s[3]))
        moved = moved + 1
        changed = true
      end
    end
    if changed then
      guids[#guids + 1] = row[1]
      local at = obj.getPosition()
      pings[#pings + 1] = at
    end
  end
end
for k, at in ipairs(pings) do
  Wait.time(function() pcall(function() pinger().pingTable(at) end) end, {_f(PING_LEAD)} + (k - 1) * {_f(PING_GAP)})
end
return JSON.encode({{found = found, total = #ROW, before = before, flipped = flipped, moved = moved, guids = guids}})
"""
