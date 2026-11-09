"""The draw deck that is not there, for the Lua builders that put cards INTO a deck.

TTS destroys a Deck object when its last card is drawn: an empty draw deck is nothing on the table, so `findDeck` finds
nothing and a writer that needs the deck has nowhere to put the cards (Devil of Hell's Kitchen's AFTER only ever runs with the
deck empty when it was worth 8). The cards then stay where they are while the engine counts them in the deck, and the table
deck runs dry while the engine still sees cards in it. The fix is the one a player makes by hand: the first card goes face
down where the deck lay and IS the deck again; the rest are put into it.

`home_lua` defines `home` (where the deck lay: the centre of its Scripting zone, else its spot, else nil: no place to lay it,
and then the writer refuses as before). `DECK_FUNCS` defines `layFirst(card, home)` and `qty(deck)`."""
from __future__ import annotations

DECK_FUNCS = """local function layFirst(card, home)
  -- an empty draw deck is no object in TTS: this card, face down where the deck lay, IS the deck again
  local r = card.getRotation()
  card.setRotation(Vector(0, r.y, 180))
  card.setPosition(Vector(home.x, home.y, home.z))
  return card
end
local function qty(d)
  if d.type == "Deck" then return d.getQuantity() end
  return 1      -- getQuantity() of a lone Card is -1 in TTS
end
"""


def home_lua(spot, zone) -> str:
    from . import lua                 # lua.py imports this module for its builders: resolved at call time
    if zone is not None:
        return f"""local home = nil
do
  local z = getObjectFromGUID({lua._guid(zone)})
  if isZone(z) then local p = z.getPosition(); home = {{x = p.x, y = 1.5, z = p.z}} end
end
"""
    if spot is not None:
        x, z, _ = lua._spot(spot, 0)
        return f"local home = {{x = {x}, y = 1.5, z = {z}}}\n"
    return "local home = nil\n"
