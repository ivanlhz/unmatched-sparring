"""Lua builder for a deck search (Ciri's Searching strike): the card the engine picked is taken out of the bot's real deck by CardID and goes
to the bot's hand. A separate module so `lua.py` does not grow: it uses the same guards and the same registry (`lua._registered`), so the
script is sendable and composable like any other builder."""
from __future__ import annotations

from .lua import (BOT_CARD_IDS, DECK_RADIUS, _color, _deck_finder, _guid, _i, _ours_lua, _registered)


@_registered
def deck_card_to_hand(card_id: int, deck_guid: str, seat_color: str, id_range: tuple[int, int] = BOT_CARD_IDS, *, identity,
                      spot: tuple[float, float] | None = None, zone: str | None = None, radius: float = DECK_RADIUS) -> str:
    """Takes ONE card of a deck out by CardID (not the top one: the bot's physical order is not the engine's) and puts it into the hand of
    `seat_color`, INSTANT like `return_card_to_hand` (a smooth move does not take a card into a hand zone). The card must be `ours`
    (`id_range` and the image of `identity`), so a card of another hero that shares the CardID is never taken. A deck that is a single loose
    Card is moved as it is. Returns `{taken, guid}` (`deck = false` when the deck is not there, `taken = false` when it does not hold the
    card). Verify live."""
    own = _ours_lua(identity, id_range) + _deck_finder(spot, radius, zone)
    return f"""-- sparring:deck_card_to_hand
{own}local deck = findDeck({_guid(deck_guid)})
if deck == nil then return JSON.encode({{taken = false, deck = false}}) end
local t = Player[{_color(seat_color)}].getHandTransform(1)
local function toHand(card)
  card.setRotation(Vector(0, t.rotation.y, 0))
  card.setPosition(t.position)
  return JSON.encode({{taken = true, guid = card.getGUID()}})
end
if deck.type == "Card" then
  if deck.getData().CardID ~= {_i(card_id)} then return JSON.encode({{taken = false}}) end
  return toHand(deck)
end
local data = deck.getData()
for _, entry in ipairs(data.ContainedObjects or {{}}) do
  if entry.CardID == {_i(card_id)} and cardOurs(entry, data.CustomDeck) then
    local at = deck.getPosition()
    local card = deck.takeObject({{guid = entry.GUID, position = Vector(at.x, at.y + 2, at.z), smooth = false}})
    if card == nil then return JSON.encode({{taken = false}}) end
    return toHand(card)
  end
end
return JSON.encode({{taken = false}})
"""
