-- Minimal TTS table to run the generated scripts with lupa (tests only; see test_review9.py).
OBJECTS = {}
SENT = {}
TIMERS = {}
PENDING = {}
DEFER = false
local function vec(x, y, z) return {x = x, y = y, z = z} end
Vector = function(x, y, z) if type(x) == "table" then return vec(x[1] or x.x, x[2] or x.y, x[3] or x.z) end return vec(x, y, z) end
local serial = 0
local function customDeck(owner, cid)
  local base = "https://img.test/" .. tostring(owner)
  return {[tostring(math.floor(cid / 100))] = {FaceURL = base .. "/face", BackURL = base .. "/back"}}
end
function mkobj(o)
  serial = serial + 1
  o.pos = o.pos or vec(0, 1, 0)
  o.name = o.name or ""
  o.gm = o.gm or ""
  if o.resting == nil then o.resting = true end
  o.getGUID = function() return o.guid end
  o.getName = function() return o.name end
  o.setName = function(n) o.name = n end
  o.getGMNotes = function() return o.gm end
  o.setGMNotes = function(n) o.gm = n end
  o.getPosition = function() return vec(o.pos.x, o.pos.y, o.pos.z) end
  o.setPosition = function(p) o.pos = Vector(p); if HAND_ZONES then o.hand = nil; if o.use_hands ~= false then for _, z in ipairs(HAND_ZONES) do if math.abs(o.pos.x - z.cx) <= z.hw and math.abs(o.pos.z - z.cz) <= z.hd then o.hand = z.color end end end end; MOVES = (MOVES or 0) + 1; o.moved_count = (o.moved_count or 0) + 1 end
  o.setPositionSmooth = function(p) o.pos = Vector(p); o.moved_count = (o.moved_count or 0) + 1; if o.never_rests then o.resting = false end end
  o.setRotation = function(r) o.rot = r end
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
  o.setLock = function() end
  if not o.no_smooth then o.isSmoothMoving = function() return o.smooth == true end end
  o.getData = function()
    if o.type == "Card" then return {CardID = o.cid, CustomDeck = customDeck(o.owner, o.cid)} end
    local co = {}
    for _, c in ipairs(o.cards or {}) do
      table.insert(co, {CardID = c.cid, GUID = c.guid, CustomDeck = customDeck(c.owner, c.cid)})
    end
    return {ContainedObjects = co}
  end
  o.getQuantity = function() return #(o.cards or {}) end
  o.shuffle = function() o.shuffled = true end
  o.putObject = function(x)
    PUT_LOG = PUT_LOG or {}
    table.insert(PUT_LOG, {deck = o.guid, card = x.guid, rot_z = (o.rot or vec(0, 0, 0)).z})
    if x.type == "Card" then table.insert(o.cards, {cid = x.cid, guid = x.guid, owner = x.owner})
    else for _, c in ipairs(x.cards) do table.insert(o.cards, c) end end
    for i, y in ipairs(OBJECTS) do if y == x then table.remove(OBJECTS, i) break end end
    return o
  end
  o.getObjects = o.getObjects or function() local t = {} for _, it in ipairs(o.items or {}) do t[#t + 1] = {guid = it.guid, name = it.name} end return t end
  o.takeObject = function(t)
    if o.items then
      for i, it in ipairs(o.items) do
        if it.guid == t.guid or (t.guid == nil and i == 1) then
          if not o.infinite then table.remove(o.items, i) end
          return mkobj({guid = it.guid .. (o.infinite and "x" or ""), type = "Custom_Token", pos = Vector(t.position)})
        end
      end
      return nil
    end
    for i, c in ipairs(o.cards or {}) do
      if c.guid == t.guid or (t.guid == nil and i == 1) then
        table.remove(o.cards, i)
        local card = mkobj({guid = c.guid, type = "Card", cid = c.cid, owner = c.owner, pos = Vector(t.position)})
        return card
      end
    end
  end
  if o.type == "Zone" then
    o.getObjects = function()
      local t = {}
      for _, x in ipairs(OBJECTS) do
        if x ~= o and x.type ~= "Zone" and math.abs(x.pos.x - o.cx) <= o.hw and math.abs(x.pos.z - o.cz) <= o.hd then
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
  o.destruct = function() for i, y in ipairs(OBJECTS) do if y == o then table.remove(OBJECTS, i) break end end end
  table.insert(OBJECTS, o)
  return o
end
function getObjects() local t = {} for i, o in ipairs(OBJECTS) do t[i] = o end return t end
function getObjectFromGUID(g) for _, o in ipairs(OBJECTS) do if o.guid == g then return o end end return nil end
Player = setmetatable({}, {__index = function(_, color)
  return {seated = SEATED ~= nil and SEATED[color] == true, color = color,
          getHandObjects = function() local t = {} for _, o in ipairs(OBJECTS) do if o.hand == color then table.insert(t, o) end end return t end,
          pingTable = function(p) PINGS = PINGS or {}; table.insert(PINGS, {color = color, x = p.x, y = p.y, z = p.z}) end,
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
function spawnObject(t) return mkobj({guid = "spawn1", type = t.type}) end
Wait = {
  frames = function(f, n) f() end,
  time = function(f, s) table.insert(TIMERS, f) end,
  condition = function(f, cond, timeout, tf)
    if DEFER then table.insert(PENDING, {f = f, cond = cond, tf = tf}) return end
    if cond() then f() else tf() end
  end,
}
