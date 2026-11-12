"""The draw deck that is not there, for the Lua builders that put cards INTO a deck.

TTS destroys a Deck object when its last card is drawn: an empty draw deck is nothing on the table, so `findDeck` finds
nothing and a writer that needs the deck has nowhere to put the cards (Devil of Hell's Kitchen's AFTER only ever runs with the
deck empty when it was worth 8). The cards then stay where they are while the engine counts them in the deck, and the table
deck runs dry while the engine still sees cards in it. The fix is the one a player makes by hand: the first card goes face
down where the deck lay and IS the deck again; the rest are put into it.

`home_lua` defines `home` (where the deck lay: the centre of its Scripting zone, else its spot, else nil: no place to lay it,
and then the writer refuses as before). `DECK_FUNCS` defines `layFirst(card, home)` and `qty(deck)`.

The BOTTOM of a deck (`BURY_LUA`, live 12/11). `putObject` lays a card on the draw top; turning the deck over with
`setRotation` for the put, in the same frame, did not send it to the bottom on the real table (DARK PACT's card lay on top and
the pact's own draw took it back). So nothing is put: the deck is spawned again from its data with the cards appended at the end
of `ContainedObjects` (entry 1 is the draw top, the last one the bottom), and the old deck and the loose cards are destroyed.
That happens on a LATER frame, once the deck has kept its size for `BURY_QUIET_FRAMES` frames: a draw queued after the move in
the same script (the session sends one composite) deals from the untouched deck, and a deck destroyed and one spawned are never
asked for anything in the frame they change. `sparringBury` (a global of the table's script) keeps the cards waiting for each
deck, so several moves end in ONE rebuild, and counts the rebuilds under way: `composite` reads the table only at zero."""
from __future__ import annotations

BURY_QUIET_FRAMES = 15      # frames the deck must keep its size before it is rebuilt (a deal in flight takes cards out over frames)

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


BURY_LUA = f"""local function sink(guid, home, job)
  local deck = findDeck(guid)
  local live = {{}}
  for _, rec in ipairs(job) do
    for i, card in ipairs(rec.cards) do
      local ok, data = pcall(function() return card.getData() end)
      if not ok or type(data) ~= "table" then
        rec.lost[i] = true                       -- destroyed meanwhile
      elseif card ~= deck then
        table.insert(live, {{rec = rec, i = i, card = card, data = data}})
      end
    end
  end
  if #live == 0 then return deck end
  local function lose()
    for _, l in ipairs(live) do l.rec.lost[l.i] = true end
  end
  if deck == nil and home == nil then lose() return nil end
  if deck == nil and #live == 1 then return layFirst(live[1].card, home) end
  local seed = deck ~= nil and deck.getData() or live[1].data
  local pos, rot
  if deck ~= nil then
    pos, rot = deck.getPosition(), deck.getRotation()
  else
    pos, rot = Vector(home.x, home.y, home.z), Vector(0, live[1].card.getRotation().y, 180)
  end
  local data = seed
  if deck == nil or deck.type ~= "Deck" then
    -- no Deck object to copy (a last card, or nothing): the deck is made around the card that is on top
    data = {{Name = "Deck", Transform = seed.Transform, Nickname = "", Description = "", ColorDiffuse = seed.ColorDiffuse,
            Hands = false, HideWhenFaceDown = true, SidewaysCard = seed.SidewaysCard, CustomDeck = {{}},
            ContainedObjects = deck ~= nil and {{seed}} or {{}}}}
  end
  for _, l in ipairs(live) do
    local t = l.data.Transform or {{}}
    l.data.Locked = false             -- a card lifted and locked while it waited must not come out locked when drawn
    l.data.Transform = {{posX = pos.x, posY = pos.y, posZ = pos.z, rotX = rot.x, rotY = rot.y, rotZ = rot.z,
                        scaleX = t.scaleX or 1, scaleY = t.scaleY or 1, scaleZ = t.scaleZ or 1}}
    table.insert(data.ContainedObjects, l.data)
  end
  data.DeckIDs, data.CustomDeck = {{}}, data.CustomDeck or {{}}
  for i, entry in ipairs(data.ContainedObjects) do
    data.DeckIDs[i] = entry.CardID
    for k, image in pairs(entry.CustomDeck or {{}}) do
      if data.CustomDeck[k] == nil and data.CustomDeck[tostring(k)] == nil and data.CustomDeck[tonumber(k) or k] == nil then
        data.CustomDeck[k] = image
      end
    end
  end
  -- the new deck first: if the table refuses it nothing has been destroyed
  local ok, made = pcall(spawnObjectData, {{data = data, position = pos, rotation = rot}})
  if not ok or made == nil then lose() return deck end
  if deck ~= nil then deck.destruct() end
  for _, l in ipairs(live) do l.card.destruct() end
  return made
end
local function bury(guid, home, cards, settle)
  -- `cards` go under the deck on a later frame, in that order (the last one is the very bottom card). When the deck is
  -- rebuilt `settle(new, lost)` is called: `new` is the deck there is now (nil: none) and `lost[i]` is true for each card
  -- that did not get into it. An op uses it to set its reply right: inside a composite the reply is the very table the
  -- composite sends later. Returns how many cards are waiting for that deck.
  sparringBury = sparringBury or {{jobs = {{}}, busy = 0}}
  local S = sparringBury
  local rec = {{cards = cards, settle = settle, lost = {{}}}}
  local job = S.jobs[guid]
  if job ~= nil then
    table.insert(job, rec)
  else
    job = {{rec}}
    S.jobs[guid] = job
    S.busy = S.busy + 1
    local size, still = nil, 0
    local function quiet()
      local okd, n = pcall(function()
        local d = findDeck(guid)
        return d ~= nil and qty(d) or 0
      end)
      if not okd then n = 0 end
      if n == size then still = still + 1 else size, still = n, 0 end
      return still >= {BURY_QUIET_FRAMES}
    end
    local function go()
      S.jobs[guid] = nil
      local ok, new = pcall(sink, guid, home, job)
      local function done()
        for _, r in ipairs(job) do
          if not ok then
            for i = 1, #r.cards do r.lost[i] = true end
          end
          pcall(r.settle, ok and new or nil, r.lost)
        end
        S.busy = S.busy - 1
      end
      local function spawned()
        if not ok or new == nil then return true end
        local oks, spawning = pcall(function() return new.spawning end)
        return not oks or not spawning
      end
      Wait.condition(done, spawned, 1, done)
    end
    Wait.condition(go, quiet, 1, go)
  end
  local n = 0
  for _, r in ipairs(job) do n = n + #r.cards end
  return n
end
"""
