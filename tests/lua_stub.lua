-- Minimal TTS table to run the generated scripts with lupa (tests only; see test_review9.py).
OBJECTS = {}
SENT = {}
TIMERS = {}
PENDING = {}
DEFER = false
-- Frame mode (a test sets FRAME_MODE = true): like live TTS, `Wait.frames` / `Wait.condition` run on a later frame, a
-- destructed object is still on the table until the frame ends and a spawned one is `spawning` for a frame. `tick(n)`
-- advances n frames. Without it everything deferred runs at once (the old behaviour most tests rely on).
FRAME_MODE = false
NOW = 0
WAITS = {}
DYING = {}
local function vec(x, y, z) return {x = x, y = y, z = z} end
Vector = function(x, y, z) if type(x) == "table" then return vec(x[1] or x.x, x[2] or x.y, x[3] or x.z) end return vec(x, y, z) end
local serial = 0
local function customDeck(owner, cid, key)
  local base = "https://img.test/" .. tostring(owner)
  return {[key or tostring(math.floor(cid / 100))] = {FaceURL = base .. "/face", BackURL = base .. "/back"}}
end
function mkobj(o)
  serial = serial + 1
  o.pos = o.pos or vec(0, 1, 0)
  o.name = o.name or ""
  o.gm = o.gm or ""
  if o.resting == nil then o.resting = true end
  if o.type == "Deck" and o.is_face_down == nil then o.is_face_down = true end   -- decks lie face down unless a test says otherwise
  o.getGUID = function() return o.guid end
  o.getName = function() return o.name end
  o.setName = function(n) o.name = n end
  o.getGMNotes = function() return o.gm end
  o.setGMNotes = function(n) o.gm = n end
  o.getPosition = function() return vec(o.pos.x, o.pos.y, o.pos.z) end
  o.setPosition = function(p) o.pos = Vector(p); if HAND_ZONES then o.hand = nil; if o.use_hands ~= false then for _, z in ipairs(HAND_ZONES) do if math.abs(o.pos.x - z.cx) <= z.hw and math.abs(o.pos.z - z.cz) <= z.hd then o.hand = z.color end end end end; MOVES = (MOVES or 0) + 1; o.moved_count = (o.moved_count or 0) + 1 end
  o.setPositionSmooth = function(p) o.pos = Vector(p); o.moved_count = (o.moved_count or 0) + 1; if o.never_rests then o.resting = false end end
  -- an object that declares a side keeps it true to its turn: turned to z = 180 it is face down, otherwise face up
  o.setRotation = function(r) o.rot = r; if o.is_face_down ~= nil then o.is_face_down = (math.floor((r.z or 0) + 0.5) % 360 == 180) end end
  o.setRotationSmooth = function(r) o.rot = r end
  o.getRotation = function() local r = o.rot or vec(0, 0, 0); return vec(r.x, r.y, r.z) end
  o.getAttachments = function() return o.attached or {} end
  o.getStateId = function() return o.state_id or 1 end
  o.getStates = function()
    local t = {}
    for id, g in pairs(o.states or {}) do table.insert(t, {id = id, guid = g, name = "state" .. id}) end
    return t
  end
  o.setState = function(i)
    if o.state_id == i then return o end
    local g = o.states[i]
    local n = mkobj({guid = g, type = o.type, pos = o.pos, rot = o.rot, states = o.states, state_id = i})
    o.destruct()
    return n
  end
  o.clone = function(t)
    local c = mkobj({guid = "clone" .. serial, type = o.type, pos = Vector(t.position)})
    CLONES = (CLONES or 0) + 1
    return c
  end
  o.setLock = function(v) o.locked = v end
  if not o.no_smooth then o.isSmoothMoving = function() return o.smooth == true end end
  o.setScale = function(v) o.scale = v end
  o.getScale = function() local s = o.scale or vec(1, 1, 1); return vec(s.x, s.y, s.z) end
  o.getData = function()
    if o.data then return o.data end
    local r = o.rot or vec(0, 0, 0)
    local tr = {posX = o.pos.x, posY = o.pos.y, posZ = o.pos.z, rotX = r.x, rotY = r.y, rotZ = r.z, scaleX = 1, scaleY = 1, scaleZ = 1}
    if o.type == "Card" then
      return {Name = "Card", GUID = o.guid, Transform = tr, CardID = o.cid, CustomDeck = o.custom or customDeck(o.owner, o.cid, o.deck_key)}
    end
    local co, ids = {}, {}
    for _, c in ipairs(o.cards or {}) do
      table.insert(co, {Name = "Card", CardID = c.cid, GUID = c.guid, CustomDeck = c.custom or customDeck(c.owner, c.cid, c.deck_key)})
      table.insert(ids, c.cid)
    end
    return {Name = "Deck", GUID = o.guid, Transform = tr, DeckIDs = ids, CustomDeck = o.custom_deck, ContainedObjects = co}
  end
  o.getQuantity = function() return #(o.cards or {}) end
  o.shuffle = function() o.shuffled = true end
  -- like live TTS (seen 12/11, DARK PACT): a card put into a deck lies on its draw top (cards[1]) WHATEVER the deck's facing;
  -- turning the deck over with setRotation in the same frame does not send the card to the bottom. A single Card becomes a
  -- Deck with a new GUID
  o.putObject = function(x)
    PUT_LOG = PUT_LOG or {}
    table.insert(PUT_LOG, {deck = o.guid, card = x.guid, rot_z = (o.rot or vec(0, 0, 0)).z})
    if o.type == "Card" then
      o.cards = {{cid = o.cid, guid = o.guid, owner = o.owner, deck_key = o.deck_key, custom = o.custom}}
      o.type, o.guid, o.cid = "Deck", "deck" .. serial .. "x" .. #PUT_LOG, nil
    end
    local at = 1
    local added = {}
    if x.type == "Card" then added = {{cid = x.cid, guid = x.guid, owner = x.owner, deck_key = x.deck_key, custom = x.custom}} else added = x.cards end
    for k, c in ipairs(added) do table.insert(o.cards, at + k - 1, c) end
    for i, y in ipairs(OBJECTS) do if y == x then table.remove(OBJECTS, i) break end end
    return o
  end
  -- like live TTS: an infinite bag does not list its content (it always gives a copy of its single object)
  o.getObjects = o.getObjects or function() local t = {} if o.infinite then return t end for _, it in ipairs(o.items or {}) do t[#t + 1] = {guid = it.guid, name = it.name} end return t end
  o.takeObject = function(t)
    if o.items then
      for i, it in ipairs(o.items) do
        if it.guid == t.guid or (t.guid == nil and i == 1) then
          if not o.infinite then table.remove(o.items, i) end
          local made = mkobj({guid = it.guid .. (o.infinite and "x" or ""), type = it.type or "Custom_Token", pos = Vector(t.position)})
          if t.callback_function then t.callback_function(made) end
          return made
        end
      end
      return nil
    end
    for i, c in ipairs(o.cards or {}) do
      if c.guid == t.guid or (t.guid == nil and i == 1) then
        table.remove(o.cards, i)
        local card = mkobj({guid = c.guid, type = "Card", cid = c.cid, owner = c.owner, deck_key = c.deck_key, custom = c.custom, pos = Vector(t.position),
                            rot = o.rot, is_face_down = o.is_face_down})
        if #o.cards == 1 then          -- like live TTS: the last card of a deck is a loose Card with a GUID of its own
          local last = o.cards[1]
          o.type, o.guid, o.cid, o.owner, o.deck_key, o.custom, o.cards = "Card", last.guid, last.cid, last.owner, last.deck_key, last.custom, nil
        end
        return card
      end
    end
  end
  if o.type == "Scripting" then
    o.getBounds = o.getBounds or function() return {center = vec(o.cx, 1, o.cz), size = vec(o.hw * 2, 1, o.hd * 2)} end
    o.getObjects = function()
      local t = {}
      for _, x in ipairs(OBJECTS) do
        if x ~= o and x.type ~= "Scripting" and math.abs(x.pos.x - o.cx) <= o.hw and math.abs(x.pos.z - o.cz) <= o.hd then
          table.insert(t, x)
        end
      end
      return t
    end
  end
  o.UI = {setValue = function(id, v) o.ui = o.ui or {}; o.ui[id] = v end,
          setAttribute = function(id, k, v) o.attrs = o.attrs or {}; o.attrs[id .. "." .. k] = v end,
          setXml = function() end}
  o.setVar = function(k, v) o.vars = o.vars or {}; o.vars[k] = v end
  o.setLuaScript = function(s) o.script = s end
  o.positionToWorld = function(v) return vec(v.x, 1, v.z) end
  o.getTable = function(k) return o.tbl end
  o.setTable = function(k, t) o.tbl = t end
  o.call = function() end
  o.destruct = function()
    if FRAME_MODE then table.insert(DYING, o) return end       -- still on the table (getObjects, its GUID) until the frame ends
    for i, y in ipairs(OBJECTS) do if y == o then table.remove(OBJECTS, i) break end end
  end
  -- a real draw: the top cards leave the deck for the seat's hand, face up
  o.deal = o.deal or function(k, color)
    for _ = 1, k do
      local c = o                                   -- the last card of a deck is the deck
      if o.type == "Deck" then c = o.takeObject({position = o.pos}) end
      c.hand, c.is_face_down, c.rot = color, false, vec(0, 0, 0)
    end
  end
  table.insert(OBJECTS, o)
  return o
end
function getObjects() local t = {} for i, o in ipairs(OBJECTS) do t[i] = o end return t end
function getObjectFromGUID(g) for _, o in ipairs(OBJECTS) do if o.guid == g then return o end end return nil end
Player = setmetatable({}, {__index = function(_, color)
  return {seated = SEATED ~= nil and SEATED[color] == true, color = color,
          getHandObjects = function() local t = {} for _, o in ipairs(OBJECTS) do if o.hand == color then table.insert(t, o) end end return t end,
          pingTable = function(p) PINGS = PINGS or {}; table.insert(PINGS, {color = color, x = p.x, y = p.y, z = p.z}) end,
          showInfoDialog = (not NO_DIALOG) and function(text) DIALOGS = DIALOGS or {}; table.insert(DIALOGS, {color = color, text = text}) end or nil,
          getHandTransform = function() return {position = vec(0, 1, 0), rotation = vec(0, 0, 0)} end}
end})
function Player.getPlayers()
  local t = {}
  for _, c in ipairs(PLAYERS or {}) do t[#t + 1] = Player[c] end
  return t
end
function group(objs)
  local d = mkobj({guid = "grp001", type = "Deck", cards = {}})
  for _, x in ipairs(objs) do d.putObject(x) end
  return {d}
end
function sendExternalMessage(t) table.insert(SENT, t) end
BROADCASTS = {}
function broadcastToAll(text, color) table.insert(BROADCASTS, {text = text, r = color[1], g = color[2], b = color[3]}) end
SPAWNS = {}
function spawnObject(t)
  if t.type == "ScriptingTrigger" then       -- a Scripting zone: TTS gives it a fresh GUID and reports it as "Scripting"
    local p, sc, r = t.position, t.scale, t.rotation
    local z = mkobj({guid = "zone" .. (#SPAWNS + 1), type = "Scripting", pos = vec(p.x, p.y, p.z), rot = vec(r.x, r.y, r.z),
                     scale = vec(sc.x, sc.y, sc.z), cx = p.x, cz = p.z, hw = sc.x / 2, hd = sc.z / 2})
    table.insert(SPAWNS, z)
    return z
  end
  return mkobj({guid = "spawn1", type = t.type})
end
function spawnObjectData(t)
  local d = t.data
  SPAWNED = (SPAWNED or 0) + 1
  if d.ContainedObjects ~= nil then
    -- a deck by data: ContainedObjects[1] is the draw top. Live TTS wants DeckIDs in step with the cards and an image for each
    assert(d.Name == "Deck" or d.Name == "DeckCustom", "deck data needs the Name of a deck")
    assert(#d.ContainedObjects >= 2, "a deck has two cards or more")
    assert(type(d.DeckIDs) == "table" and #d.DeckIDs == #d.ContainedObjects, "DeckIDs out of step with ContainedObjects")
    local cards = {}
    for i, c in ipairs(d.ContainedObjects) do
      assert(d.DeckIDs[i] == c.CardID, "DeckIDs out of step with ContainedObjects")
      local key = math.floor(c.CardID / 100)
      assert(type(d.CustomDeck) == "table" and (d.CustomDeck[tostring(key)] or d.CustomDeck[key]), "no CustomDeck image for card " .. c.CardID)
      local owner = nil      -- the stub's images name the owner (customDeck): kept so a test still tells whose card it is
      for _, image in pairs(c.CustomDeck or {}) do owner = tostring(image.FaceURL):match("^https://img%.test/(.-)/face$") end
      cards[i] = {cid = c.CardID, guid = c.GUID or ("card" .. SPAWNED .. "x" .. i), custom = c.CustomDeck, owner = owner}
    end
    local guid, rot = d.GUID, Vector(t.rotation)
    if guid == nil or getObjectFromGUID(guid) ~= nil then guid = "spawned" .. SPAWNED end     -- a GUID in use is never given twice
    local deck = mkobj({guid = guid, type = "Deck", cards = cards, custom_deck = d.CustomDeck, pos = Vector(t.position), rot = rot,
                        is_face_down = math.floor((rot.z or 0) + 0.5) % 360 == 180, spawning = FRAME_MODE or nil})
    if t.callback_function then Wait.frames(function() t.callback_function(deck) end, 1) end
    return deck
  end
  return mkobj({guid = "spawned" .. SPAWNED, type = "Card", cid = d.CardID, name = d.Nickname, gm = d.GMNotes,
                tags = d.Tags, locked = d.Locked, data = d, pos = Vector(t.position), rot = Vector(t.rotation)})
end
Wait = {
  frames = function(f, n)
    if FRAME_MODE then table.insert(WAITS, {f = f, at = NOW + (n or 1)}) return end
    f()
  end,
  time = function(f, s) table.insert(TIMERS, f) end,
  condition = function(f, cond, timeout, tf)
    if FRAME_MODE then table.insert(WAITS, {f = f, cond = cond, tf = tf, at = NOW + math.ceil((timeout or 1e9) * 60)}) return end
    if DEFER then table.insert(PENDING, {f = f, cond = cond, tf = tf}) return end
    if cond() then f() else tf() end
  end,
}
function tick(n)
  for _ = 1, n or 1 do
    for _, o in ipairs(DYING) do
      for i, y in ipairs(OBJECTS) do if y == o then table.remove(OBJECTS, i) break end end
    end
    DYING = {}
    for _, o in ipairs(OBJECTS) do o.spawning = nil end
    NOW = NOW + 1
    local due = WAITS
    WAITS = {}
    for _, w in ipairs(due) do
      if w.cond == nil then
        if w.at <= NOW then w.f() else table.insert(WAITS, w) end
      elseif w.cond() then w.f()
      elseif w.at <= NOW then if w.tf then w.tf() end
      else table.insert(WAITS, w) end
    end
  end
end
