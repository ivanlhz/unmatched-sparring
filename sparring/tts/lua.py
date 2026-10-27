"""Generadores de snippets Lua para TTS. Ninguno toca la UI global ni recarga la partida.

Convenciones: las casillas se identifican por el id del mapa (data/maps/*.json). El tablero es un
Custom_Board (GUID en BOARD_GUIDS); sus puntos de enganche locales (x, z) se pasan a mundo con
board.positionToWorld. Los scripts que devuelven datos terminan en `return JSON.encode(...)`.
Cada script empieza con una etiqueta `-- sparring:<nombre>`.

Seguridad: el cliente solo envia scripts cuyo hash registra `_sendable`, que solo llaman los
constructores de este modulo. Todo argumento se valida/coacciona (numeros con float()/int() y repr,
colores contra la lista de asientos, ids con regex, cadenas con lista blanca de caracteres).
"""
from __future__ import annotations

import functools
import hashlib
import math
import re
from dataclasses import dataclass

from ..board import Board
from ..cards import HELLBOY_BASE, MEDUSA_BASE
from . import ui

BOARD_GUIDS = {"bprd-hq": "ec6f27", "azuchi-castle": "e57969"}
PANEL_NAME = "SparringPanel"
MARKER = "sparring"      # GM notes de todo objeto propio: el nombre solo no basta para tocarlo
PANEL_POSITION = (2, 1.8, -24)
LIFT = 1.0
SEATS = frozenset({"White", "Brown", "Red", "Orange", "Yellow", "Green", "Teal", "Blue", "Purple", "Pink",
                   "Grey", "Black"})

_SAFE = re.compile(r"[A-Za-z0-9 _.\-!:']{0,64}")
_GUID = re.compile(r"[A-Za-z0-9]{1,16}")
_SENDABLE: set[str] = set()
BOT_CARD_IDS = (MEDUSA_BASE, MEDUSA_BASE + 29)      # rango de CardID del mazo de Medusa (30 cartas)


def _sendable(script: str) -> str:
    _SENDABLE.add(hashlib.sha256(script.encode("utf-8")).hexdigest())
    return script


_REQ = re.compile(
    r'(?P<head>-- sparring:\w+)\n'
    r'local __rid = (?P<rid>[0-9]{1,15})\n'
    r'local __enc = JSON\.encode\n'
    r'local __ok, __res = pcall\(function\(\)\n'
    r'local JSON = \{encode = function\(v\) sendExternalMessage\(\{sparring_reply = __rid, value = __enc\(v\)\}\) return "" end\}\n'
    r'(?P<body>.*)end\)\n'
    r'if not __ok then sendExternalMessage\(\{sparring_reply = __rid, err = tostring\(__res\)\}\) end\n', re.DOTALL)


def _unwrap(script: str) -> str:
    m = _REQ.fullmatch(script)
    return f"{m['head']}\n{m['body']}" if m else script


def is_sendable(script: str) -> bool:
    """Un script sale si lo genero un constructor, tal cual o envuelto por `request`."""
    return hashlib.sha256(_unwrap(script).encode("utf-8")).hexdigest() in _SENDABLE


def request(script: str, rid: int) -> str:
    """Marca un script de constructor con un id de peticion (entero).

    TTS no devuelve valores por el socket (no hay messageID 5): el resultado vuelve como
    sendExternalMessage({sparring_reply = id, value = <JSON>}) (messageID 4) y un fallo de Lua dentro de pcall
    como {sparring_reply = id, err = ...}, de modo que el cliente empareja respuesta y peticion."""
    if not is_sendable(script) or _REQ.fullmatch(script):
        raise ValueError("solo se marca un script generado por un constructor y aun sin marcar")
    if isinstance(rid, bool) or not isinstance(rid, int) or not 0 <= rid < 10 ** 15:
        raise ValueError(f"id de peticion no valido {rid!r}")
    head, _, body = script.partition("\n")
    return (f"{head}\nlocal __rid = {rid}\nlocal __enc = JSON.encode\nlocal __ok, __res = pcall(function()\n"
            'local JSON = {encode = function(v) sendExternalMessage({sparring_reply = __rid, value = __enc(v)}) '
            'return "" end}\n'
            f"{body}end)\nif not __ok then sendExternalMessage({{sparring_reply = __rid, err = tostring(__res)}}) end\n")


def _registered(fn):
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return _sendable(fn(*a, **kw))
    return wrapper


def lua_str(s: str) -> str:
    if not isinstance(s, str) or not _SAFE.fullmatch(s):
        raise ValueError(f"cadena no admitida en Lua: {s!r}")
    return '"' + s + '"'


def _f(v) -> str:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise TypeError(f"numero esperado, llego {v!r}")
    v = float(v)
    if not math.isfinite(v):
        raise ValueError("numero no finito")
    return repr(v)


def _i(v) -> str:
    if isinstance(v, bool) or not isinstance(v, int):
        raise TypeError(f"entero esperado, llego {v!r}")
    return repr(int(v))


def _color(c: str) -> str:
    if c not in SEATS:
        raise ValueError(f"asiento desconocido {c!r}")
    return f'"{c}"'


def _guid(g: str) -> str:
    if not isinstance(g, str) or not _GUID.fullmatch(g):
        raise ValueError(f"GUID no valido {g!r}")
    return f'"{g}"'


def _snaps_table(board: Board) -> str:
    rows = ", ".join(f"[{_i(sid)}]={{{_f(sp.local[0])},{_f(sp.local[1])}}}" for sid, sp in sorted(board.spaces.items()))
    return "{" + rows + "}"


def _board_prelude(board: Board, board_guid: str | None = None) -> str:
    guid = board_guid or BOARD_GUIDS[board.key]
    return (f"local board = getObjectFromGUID({_guid(guid)})\n"
            f"local snaps = {_snaps_table(board)}\n"
            "local function spaceWorld(id) local c = snaps[id]; return board.positionToWorld(Vector(c[1], 0, c[2])) end\n")


@_registered
def piece_spaces_by_guid(board: Board, guids: list[str], board_guid: str | None = None) -> str:
    """Casilla (punto de enganche mas cercano en XZ), distancia a el, tipo y nombre de cada pieza por GUID.

    `dist` permite al llamador descartar piezas lejos del tablero; un GUID que no existe sale `found = false`."""
    if not isinstance(guids, (list, tuple)):
        raise TypeError("lista de GUID esperada")
    wanted = "{" + ", ".join(_guid(g) for g in guids) + "}"
    return "-- sparring:piece_spaces_by_guid\n" + _board_prelude(board, board_guid) + f"""local wanted = {wanted}
local world = {{}}
for id, _ in pairs(snaps) do world[id] = spaceWorld(id) end
local out = {{}}
for _, g in ipairs(wanted) do
  local obj = getObjectFromGUID(g)
  if obj == nil then
    out[g] = {{found = false}}
  else
    local p = obj.getPosition()
    local best, bd = nil, 1e18
    for id, w in pairs(world) do
      local d = (w.x - p.x) ^ 2 + (w.z - p.z) ^ 2
      if d < bd then best, bd = id, d end
    end
    out[g] = {{found = true, space = best, dist = math.sqrt(bd), type = obj.type, name = obj.getName()}}
  end
end
return JSON.encode(out)
"""


def _card_ids_helper() -> str:
    return """local function cardIds(objs)
  local ids = {}
  for _, o in ipairs(objs) do
    local d = o.getData()
    if o.type == "Card" then
      table.insert(ids, {id = d.CardID, guid = o.getGUID()})
    elseif o.type == "Deck" then
      for _, c in ipairs(d.ContainedObjects or {}) do table.insert(ids, {id = c.CardID, guid = c.GUID}) end
    end
  end
  return ids
end
"""


@_registered
def read_hand(seat_color: str) -> str:
    """CardID de las cartas en la mano de un asiento."""
    return ("-- sparring:read_hand\n" + _card_ids_helper()
            + f"return JSON.encode(cardIds(Player[{_color(seat_color)}].getHandObjects(1)))\n")


@_registered
def count_hand(seat_color: str) -> str:
    """Numero de cartas en la mano de un asiento (la mano del humano es secreta: solo se cuenta)."""
    return ("-- sparring:count_hand\n"
            f"return JSON.encode({{count = #Player[{_color(seat_color)}].getHandObjects(1)}})\n")


@_registered
def read_discard(zone_guid: str, exclude_guids: list[str] | tuple[str, ...] = (),
                 exclude_spots: list[tuple[float, float]] | tuple = (), exclude_radius: float = 1.5) -> str:
    """CardID de las cartas (sueltas o dentro de un Deck) que hay dentro de una ZONA de scripting.

    Solo vale un GUID de zona (`getObjects()` de la zona); un GUID de mazo no es una zona. Los mazos de robo
    suelen estar dentro o al borde de la zona: se excluyen por GUID y todo lo que quede a menos de
    `exclude_radius` de cualquiera de los puntos `exclude_spots` (x, z) SI ESTAN BOCA ABAJO (la ultima carta suelta
    del mazo de robo); una carta boca arriba junto al mazo es descarte y se lee siempre."""
    if not isinstance(exclude_guids, (list, tuple)) or not isinstance(exclude_spots, (list, tuple)):
        raise TypeError("listas esperadas")
    skip = "{" + ", ".join(f"[{_guid(g)}]=true" for g in exclude_guids) + "}"
    spots = "{" + ", ".join("{" + ", ".join(_spot(sp, exclude_radius)[:2]) + "}" for sp in exclude_spots) + "}"
    return ("-- sparring:read_discard\n" + _card_ids_helper() + f"local z = getObjectFromGUID({_guid(zone_guid)})\n"
            f"local skip = {skip}\nlocal spots = {spots}\nlocal r2 = {_f(exclude_radius)} ^ 2\n"
            """local objs = {}
for _, o in ipairs(z.getObjects()) do
  local p = o.getPosition()
  local near = false
  for _, sp in ipairs(spots) do
    if (p.x - sp[1]) ^ 2 + (p.z - sp[2]) ^ 2 <= r2 and o.is_face_down then near = true end
  end
  if not skip[o.getGUID()] and not near then table.insert(objs, o) end
end
return JSON.encode(cardIds(objs))
""")


def _spot(spot: tuple[float, float], radius: float) -> tuple[str, str, str]:
    if not isinstance(spot, (tuple, list)) or len(spot) != 2:
        raise TypeError(f"(x, z) esperado, llego {spot!r}")
    return _f(spot[0]), _f(spot[1]), _f(radius)


def _find_deck(spot, radius, id_range) -> str:
    """Lua que, si `d` es nil, busca a `d` entre los Deck/Card a menos de `radius` del punto (x, z) cuyo
    CardID cae en `id_range` (el mazo del bot, o su ultima carta suelta). Sin punto no busca."""
    if spot is None:
        return ""
    x, z, r = _spot(spot, radius)
    if not isinstance(id_range, (tuple, list)) or len(id_range) != 2:
        raise TypeError("(minimo, maximo) de CardID esperado")
    lo, hi = _i(id_range[0]), _i(id_range[1])
    return f"""local function ours(o)
  local first
  if o.type == "Card" then first = o.getData().CardID
  elseif o.type == "Deck" then
    local c = (o.getData().ContainedObjects or {{}})[1]
    first = c and c.CardID
  end
  return first ~= nil and first >= {lo} and first <= {hi}
end
if d == nil then
  for _, o in ipairs(getObjects()) do
    if o.type == "Deck" or o.type == "Card" then
      local p = o.getPosition()
      if (p.x - {x}) ^ 2 + (p.z - {z}) ^ 2 <= {r} ^ 2 and not o.held_by_color and ours(o) then d = o; break end
    end
  end
end
"""


@_registered
def deal_cards(deck_guid: str, n: int, seat_color: str, spot: tuple[float, float] | None = None,
               radius: float = 2.0, id_range: tuple[int, int] = BOT_CARD_IDS) -> str:
    """Reparte n cartas del mazo fisico a la mano del asiento (robar de verdad).

    Con una sola carta restante TTS deja de tener un "Deck": queda una "Card" (y el GUID del mazo puede
    desaparecer). Con `spot` (x, z del mazo) se busca ese mazo o carta suelta a menos de `radius` del punto,
    y la carta suelta se lleva a la mano del asiento. Solo cuenta un objeto cuyo CardID cae en `id_range`
    (el mazo del bot): una carta ajena o una ficha cerca del punto se ignora. Mazo vacio: dealt = 0."""
    color = _color(seat_color)
    find = _find_deck(spot, radius, id_range)
    return f"""-- sparring:deal_cards
local d = getObjectFromGUID({_guid(deck_guid)})
{find}local k = 0
if d ~= nil and d.type == "Deck" then
  k = math.min({_i(n)}, d.getQuantity())
  d.deal(k, {color})
elseif d ~= nil and d.type == "Card" and {_i(n)} >= 1 then
  local t = Player[{color}].getHandTransform(1)
  d.setRotation(Vector(0, t.rotation.y, 0))
  d.setPositionSmooth(t.position, false, true)
  k = 1
end
return JSON.encode({{dealt = k}})
"""


@_registered
def return_hand_to_deck(seat_color: str, deck_guid: str, id_range: tuple[int, int] = BOT_CARD_IDS) -> str:
    """MULLIGAN, paso 1: mete en el mazo (putObject) todas las cartas de la mano del asiento cuyo CardID cae en
    `id_range` (el mazo del bot). Devuelve cuantas metio; `deck = false` si el GUID del mazo no existe.
    Comprobar siempre releyendo la mano de la mesa."""
    if not isinstance(id_range, (tuple, list)) or len(id_range) != 2:
        raise TypeError("(minimo, maximo) de CardID esperado")
    lo, hi = _i(id_range[0]), _i(id_range[1])
    return f"""-- sparring:return_hand_to_deck
local d = getObjectFromGUID({_guid(deck_guid)})
if d == nil then return JSON.encode({{returned = 0, deck = false}}) end
local cards = {{}}
for _, o in ipairs(Player[{_color(seat_color)}].getHandObjects(1)) do
  if o.type == "Card" then
    local id = o.getData().CardID
    if id >= {lo} and id <= {hi} then table.insert(cards, o) end
  end
end
for _, o in ipairs(cards) do d = d.putObject(o) or d end
return JSON.encode({{returned = #cards, deck = true}})
"""


@_registered
def shuffle_deck(deck_guid: str, spot: tuple[float, float] | None = None, radius: float = 2.0,
                 id_range: tuple[int, int] = BOT_CARD_IDS) -> str:
    """MULLIGAN, paso 2: baraja el mazo. Tras `putObject` el GUID del mazo puede cambiar: con `spot` se busca por
    posicion (como `deal_cards`). Devuelve `shuffled` y la cantidad de cartas que tiene, para verificarla."""
    find = _find_deck(spot, radius, id_range)
    return f"""-- sparring:shuffle_deck
local d = getObjectFromGUID({_guid(deck_guid)})
{find}if d ~= nil and d.type == "Deck" then
  d.shuffle()
  return JSON.encode({{shuffled = true, quantity = d.getQuantity()}})
end
return JSON.encode({{shuffled = false, quantity = 0}})
"""


@_registered
def return_card_to_hand(card_guid: str, seat_color: str) -> str:
    """Devuelve a la mano del asiento una carta que habia dejado en la mesa (cancelar un ataque). INSTANTANEO:
    un movimiento suave no saca la carta de donde esta ni la mete en la mano."""
    return f"""-- sparring:return_card_to_hand
local c = getObjectFromGUID({_guid(card_guid)})
if c == nil then return JSON.encode({{returned = false}}) end
local t = Player[{_color(seat_color)}].getHandTransform(1)
c.setRotation(Vector(0, t.rotation.y, 0))
c.setPosition(t.position)
return JSON.encode({{returned = c.getGUID()}})
"""


@_registered
def discard_cards(card_ids: list[int], spots: list[tuple[float, float, float]], rot_y: float = 0) -> str:
    """Lleva al descarte las cartas con esos CardID (de la mano, de la mesa o de dentro de un Deck).

    `spots[i]` es el sitio (x, y, z) de la carta `card_ids[i]`: el descarte se reparte en orden por la zona para
    que el rival vea lo jugado. Una Card suelta se mueve tal cual; de un Deck se saca la carta con takeObject
    (como mucho una por Deck y llamada, porque al quedar una sola carta TTS destruye el Deck). Devuelve los
    CardID movidos. Las Card se mueven al instante (setRotation/setPosition): si estan en una mano, un movimiento
    suave no las saca."""
    if not isinstance(card_ids, (list, tuple)) or not isinstance(spots, (list, tuple)) or len(card_ids) != len(spots):
        raise TypeError("lista de CardID y lista de sitios de la misma longitud esperadas")
    rows = []
    for c, sp in zip(card_ids, spots):
        if not isinstance(sp, (tuple, list)) or len(sp) != 3:
            raise TypeError(f"(x, y, z) esperado, llego {sp!r}")
        rows.append(f"[{_i(c)}]={{{_f(sp[0])}, {_f(sp[1])}, {_f(sp[2])}}}")
    wanted = "{" + ", ".join(rows) + "}"
    rot = f"Vector(0, {_f(rot_y)}, 0)"
    return f"""-- sparring:discard_cards
local wanted = {wanted}
local moved = {{}}
local done = {{}}
for _, o in ipairs(getObjects()) do
  if o.type == "Card" then
    local id = o.getData().CardID
    if wanted[id] and not done[id] then
      local at = wanted[id]
      o.setRotation({rot})
      o.setPosition(Vector(at[1], at[2], at[3]))
      done[id] = true
      table.insert(moved, id)
    end
  elseif o.type == "Deck" then
    for _, c in ipairs(o.getData().ContainedObjects or {{}}) do
      if wanted[c.CardID] and not done[c.CardID] then
        local at = wanted[c.CardID]
        o.takeObject({{guid = c.GUID, position = Vector(at[1], at[2], at[3]), rotation = {rot}, smooth = false}})
        done[c.CardID] = true
        table.insert(moved, c.CardID)
        break
      end
    end
  end
end
return JSON.encode({{moved = moved}})
"""


@_registered
def inspect_guids(guids: list[str]) -> str:
    """Solo lectura: tipo, nombre, cantidad y posicion de cada objeto (comprobar GUIDs de la configuracion)."""
    if not isinstance(guids, (list, tuple)):
        raise TypeError("lista de GUID esperada")
    wanted = "{" + ", ".join(_guid(g) for g in guids) + "}"
    return f"""-- sparring:inspect_guids
local out = {{}}
for _, g in ipairs({wanted}) do
  local o = getObjectFromGUID(g)
  if o == nil then
    out[g] = {{found = false}}
  else
    local p = o.getPosition()
    local qty = nil
    if o.type == "Deck" then qty = o.getQuantity() end
    out[g] = {{found = true, type = o.type, name = o.getName(), quantity = qty, x = p.x, y = p.y, z = p.z}}
  end
end
return JSON.encode(out)
"""


@_registered
def read_health_dials(guids: list[str]) -> str:
    """Solo lectura: valor de cada dial de vida por GUID.

    Los diales del save llevan un script con `CONFIG.VALUE` (la vida mostrada, entre MIN_VALUE y MAX_VALUE);
    se lee con getTable("CONFIG") y, por si el script cambia, tambien getValue() y la etiqueta del primer boton."""
    if not isinstance(guids, (list, tuple)):
        raise TypeError("lista de GUID esperada")
    wanted = "{" + ", ".join(_guid(g) for g in guids) + "}"
    return f"""-- sparring:read_health_dials
local out = {{}}
for _, g in ipairs({wanted}) do
  local o = getObjectFromGUID(g)
  if o == nil then
    out[g] = {{found = false}}
  else
    local ok, cfg = pcall(function() return o.getTable("CONFIG") end)
    local value, max = nil, nil
    if ok and type(cfg) == "table" then value, max = cfg.VALUE, cfg.MAX_VALUE end
    local label = nil
    local okb, buttons = pcall(function() return o.getButtons() end)
    if okb and type(buttons) == "table" and buttons[1] then label = buttons[1].label end
    out[g] = {{found = true, name = o.getName(), value = value, max = max, label = label, object_value = o.getValue()}}
  end
end
return JSON.encode(out)
"""


@_registered
def place_piece(guid: str, x: float, y: float, z: float) -> str:
    """Lleva la pieza con ese GUID a unas coordenadas del mundo (p. ej. fuera del tablero, a la zona de bajas);
    `moved = false` si el GUID no existe. Solo por GUID; las coordenadas se validan como numeros."""
    return f"""-- sparring:place_piece
local obj = getObjectFromGUID({_guid(guid)})
if obj == nil then return JSON.encode({{moved = false}}) end
obj.setPositionSmooth(Vector({_f(x)}, {_f(y)}, {_f(z)}), false, true)
return JSON.encode({{moved = obj.getGUID()}})
"""


@_registered
def name_pieces(names: dict[str, str]) -> str:
    """ESCRIBE: pone nombre (setName) a cada objeto, por GUID, para distinguirlos al pasar el raton (las tres
    Harpias se llaman igual). Solo GUID, nunca por nombre; un GUID que no existe se omite. Devuelve los nombrados."""
    if not isinstance(names, dict):
        raise TypeError("diccionario GUID -> nombre esperado")
    rows = ", ".join(f"[{_guid(g)}]={lua_str(n)}" for g, n in sorted(names.items()))
    return f"""-- sparring:name_pieces
local named = {{}}
for g, name in pairs({{{rows}}}) do
  local o = getObjectFromGUID(g)
  if o ~= nil then
    if o.getName() ~= name then o.setName(name) end
    table.insert(named, g)
  end
end
return JSON.encode({{named = named}})
"""


@_registered
def set_health_dials(values: dict[str, int]) -> str:
    """ESCRIBE: pone cada dial de vida (por GUID) al valor dado y devuelve lo que quedo.

    Los diales del save son contadores con un script propio: la vida vive en su tabla `CONFIG.VALUE` (entre
    MIN_VALUE y MAX_VALUE) y la etiqueta se redibuja con su funcion `updateVal`. Se lee la tabla con getTable,
    se cambia VALUE (acotado), se devuelve con setTable y se llama a `updateVal` para que se vea. El llamador
    debe releer con `read_health_dials` y comparar: el valor devuelto aqui no es una verificacion."""
    if not isinstance(values, dict):
        raise TypeError("diccionario GUID -> valor esperado")
    rows = ", ".join(f"[{_guid(g)}]={_i(v)}" for g, v in sorted(values.items()))
    return f"""-- sparring:set_health_dials
local out = {{}}
for g, v in pairs({{{rows}}}) do
  local o = getObjectFromGUID(g)
  if o == nil then
    out[g] = {{found = false}}
  else
    local cfg = o.getTable("CONFIG")
    if type(cfg) ~= "table" then
      out[g] = {{found = true, written = false}}
    else
      cfg.VALUE = math.max(cfg.MIN_VALUE or 0, math.min(cfg.MAX_VALUE or v, v))
      o.setTable("CONFIG", cfg)
      pcall(function() o.call("updateVal") end)
      out[g] = {{found = true, written = true, value = cfg.VALUE}}
    end
  end
end
return JSON.encode(out)
"""


@_registered
def zone_overlaps(zone_guids: list[str]) -> str:
    """Solo lectura: GUID de las zonas de mano (HandTrigger) cuya caja se solapa con cada zona dada."""
    if not isinstance(zone_guids, (list, tuple)):
        raise TypeError("lista de GUID esperada")
    wanted = "{" + ", ".join(_guid(g) for g in zone_guids) + "}"
    return f"""-- sparring:zone_overlaps
local out = {{}}
for _, g in ipairs({wanted}) do
  local z = getObjectFromGUID(g)
  if z == nil then
    out[g] = {{found = false}}
  else
    local b = z.getBounds()
    local hands = {{}}
    for _, o in ipairs(getObjects()) do
      if o.type == "Hand" or o.name == "HandTrigger" then
        local h = o.getBounds()
        if math.abs(b.center.x - h.center.x) <= (b.size.x + h.size.x) / 2
           and math.abs(b.center.z - h.center.z) <= (b.size.z + h.size.z) / 2 then
          table.insert(hands, o.getGUID())
        end
      end
    end
    out[g] = {{found = true, hands = hands}}
  end
end
return JSON.encode(out)
"""


def ascii_text(text: str, limit: int = 64) -> list[str]:
    """Texto libre -> trozos que `lua_str` admite (ASCII sin acentos, caracteres de la lista blanca, <= limit)."""
    import unicodedata
    plain = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    plain = re.sub(r"[^A-Za-z0-9 _.\-!:']", " ", plain)
    words, chunks, cur = plain.split(), [], ""
    for w in words:
        w = w[:limit]
        if cur and len(cur) + 1 + len(w) > limit:
            chunks.append(cur)
            cur = w
        else:
            cur = f"{cur} {w}".strip()
    if cur:
        chunks.append(cur)
    return chunks


@_registered
def broadcast(text: str) -> str:
    """Muestra un mensaje en pantalla a todos (no toca la mesa). Solo caracteres de la lista blanca, <= 64."""
    return f"""-- sparring:broadcast
broadcastToAll({lua_str(text)}, {{1, 1, 1}})
return JSON.encode({{shown = true}})
"""


@_registered
def move_piece(board: Board, guid: str, space: int, board_guid: str | None = None) -> str:
    """Lleva la pieza con ese GUID a una casilla; `moved = false` si el GUID no existe."""
    if space not in board.spaces:
        raise ValueError(f"casilla desconocida {space}")
    return "-- sparring:move_piece\n" + _board_prelude(board, board_guid) + f"""local target = spaceWorld({_i(space)})
local obj = getObjectFromGUID({_guid(guid)})
if obj == nil then return JSON.encode({{moved = false}}) end
obj.setPositionSmooth(Vector(target.x, target.y + {_f(LIFT)}, target.z), false, true)
return JSON.encode({{moved = obj.getGUID()}})
"""


@_registered
def play_card_face_down(card_id: int, seat_color: str, x: float, y: float, z: float, rot_y: float = 0) -> str:
    """Saca la carta con ese CardID de la mano del asiento y la deja boca abajo; played=false si no esta.

    El movimiento es INSTANTANEO (setRotation y luego setPosition): en TTS real, `setPositionSmooth` sobre una carta
    que esta en una zona de mano no la saca, la mano la vuelve a tirar. El resultado hay que comprobarlo leyendo la mesa."""
    return f"""-- sparring:play_card_face_down
for _, o in ipairs(Player[{_color(seat_color)}].getHandObjects(1)) do
  if o.type == "Card" and o.getData().CardID == {_i(card_id)} then
    o.setRotation(Vector(0, {_f(rot_y)}, 180))
    o.setPosition(Vector({_f(x)}, {_f(y)}, {_f(z)}))
    return JSON.encode({{played = o.getGUID()}})
  end
end
return JSON.encode({{played = false}})
"""


@_registered
def read_face_down_cards(x: float, z: float, radius: float = 2.0) -> str:
    """Lee (sin girar) las cartas boca abajo a menos de `radius` del punto (x, z): CardID y GUID."""
    return f"""-- sparring:read_face_down_cards
local out = {{}}
for _, o in ipairs(getObjects()) do
  if o.type == "Card" and o.is_face_down then
    local p = o.getPosition()
    if (p.x - {_f(x)}) ^ 2 + (p.z - {_f(z)}) ^ 2 <= {_f(radius)} ^ 2 then
      table.insert(out, {{id = o.getData().CardID, guid = o.getGUID()}})
    end
  end
end
return JSON.encode(out)
"""


@_registered
def flip_card(card_guid: str, rot_y: float = 0, face_up: bool = True) -> str:
    """Gira una carta ya jugada (revelar o volver a ocultar)."""
    z = 0 if face_up else 180
    return f"""-- sparring:flip_card
local c = getObjectFromGUID({_guid(card_guid)})
c.setRotationSmooth(Vector(0, {_f(rot_y)}, {_f(z)}), false, true)
return JSON.encode({{flipped = c.getGUID()}})
"""


MARK_PREFIX = "SparringLabel"
MARK_LINE_Y = 1.7
CARD_SIZE = (2.2, 3.2)
MARK_COLORS = {"discard": (1.0, 1.0, 1.0), "combat": (1.0, 0.45, 0.0)}
# Etiquetas del suelo (3DText). White se sienta en x = -30 mirando hacia +x: el texto se lee a lo largo de -z con la
# parte alta hacia +x, que es girar el texto plano 90 grados sobre Y (el panel usa 0 0 270 por lo mismo).
LABEL_FONT = 30.0                    # un tercio del 90 anterior
LABEL_ROTATION = (90.0, 90.0, 0.0)
LABEL_CHAR_W = 0.012                 # ancho de un caracter por punto de fuente, en unidades del mundo (estimado)
LABEL_CHAR_H = 0.02                  # alto del texto por punto de fuente
LABEL_MARGIN = 0.4                   # separacion entre el borde de la caja y la etiqueta


def label_position(cx: float, cz: float, w: float, d: float, rot_y: float, text: str,
                   font: float = LABEL_FONT) -> tuple[float, float, float, float]:
    """(x, z, ancho en x, largo en z) de la etiqueta de una caja: justo FUERA de ella, en el borde que mira a White
    (el lado -x de su caja envolvente) y centrada en z. Es el espejo en Python de la formula que usa el script Lua."""
    t = math.radians(rot_y)
    half_x = abs(math.cos(t)) * w / 2 + abs(math.sin(t)) * d / 2
    ext_x, ext_z = font * LABEL_CHAR_H, len(text) * font * LABEL_CHAR_W
    return cx - half_x - LABEL_MARGIN - ext_x / 2, cz, ext_x, ext_z


def _mark_rows(rows, fields: int) -> list:
    if not isinstance(rows, (list, tuple)):
        raise TypeError("lista esperada")
    for r in rows:
        if not isinstance(r, (tuple, list)) or len(r) != fields:
            raise TypeError(f"fila de {fields} campos esperada, llego {r!r}")
    return list(rows)


@_registered
def draw_markings(zones: list[tuple[str, str]], cards: list[tuple[str, float, float]],
                  card_size: tuple[float, float] = CARD_SIZE, label_font: float = LABEL_FONT,
                  label_rotation: tuple[float, float, float] = LABEL_ROTATION) -> str:
    """Marca en el suelo las zonas de descarte (rectangulo blanco) y los puntos de carta de combate
    (rectangulo naranja), con una etiqueta de texto cada uno.

    Las lineas van en el objeto PROPIO del bot (SparringPanel) con setVectorLines, convertidas con
    positionToLocal: nunca se toca el Global ni las decals. Cada zona se lee en vivo (posicion, escala y rotY).
    Las etiquetas son objetos 3DText llamados "SparringLabel <texto>": si ya existen se reutilizan, asi que
    repetir la llamada no duplica nada; `clear_markings` los borra. zones: [(etiqueta, guid)];
    cards: [(etiqueta, x, z)]."""
    zrows, crows = _mark_rows(zones, 2), _mark_rows(cards, 3)
    font, lrot = _f(label_font), ", ".join(_f(v) for v in label_rotation)
    if not isinstance(label_rotation, (tuple, list)) or len(label_rotation) != 3 or not 1 <= float(label_font) <= 200:
        raise ValueError("etiquetas: fuente entre 1 y 200 y rotacion de tres numeros")
    if not isinstance(card_size, (tuple, list)) or len(card_size) != 2:
        raise TypeError("(ancho, fondo) esperado")
    zlua = "{" + ", ".join(f"{{{lua_str(lab)}, {_guid(g)}}}" for lab, g in zrows) + "}"
    clua = "{" + ", ".join(f"{{{lua_str(lab)}, {_f(x)}, {_f(z)}}}" for lab, x, z in crows) + "}"
    dc, cc = (", ".join(_f(v) for v in MARK_COLORS[k]) for k in ("discard", "combat"))
    return f"""-- sparring:draw_markings
local panel
for _, o in ipairs(getObjects()) do
  if o.getName() == {lua_str(PANEL_NAME)} and o.getGMNotes() == {lua_str(MARKER)} then panel = o end
end
if panel == nil then return JSON.encode({{drawn = 0, labels = 0, panel = false}}) end
local rects = {{}}
local function rect(label, cx, cz, w, d, rotY, color)
  local t = math.rad(rotY)
  local c, s = math.cos(t), math.sin(t)
  local pts = {{}}
  for _, k in ipairs({{{{-1, -1}}, {{1, -1}}, {{1, 1}}, {{-1, 1}}, {{-1, -1}}}}) do
    local lx, lz = k[1] * w / 2, k[2] * d / 2
    local wp = Vector(cx + lx * c + lz * s, {_f(MARK_LINE_Y)}, cz - lx * s + lz * c)
    local lp = panel.positionToLocal(wp)
    table.insert(pts, {{lp.x, lp.y, lp.z}})
  end
  local ht = math.rad(rotY)
  local half = math.abs(math.cos(ht)) * w / 2 + math.abs(math.sin(ht)) * d / 2
  local lx = cx - half - {_f(LABEL_MARGIN)} - {font} * {_f(LABEL_CHAR_H)} / 2
  table.insert(rects, {{points = pts, color = color, thickness = 0.12, label = label, x = lx, z = cz}})
end
for _, z in ipairs({zlua}) do
  local obj = getObjectFromGUID(z[2])
  if obj ~= nil then
    local p, sc, r = obj.getPosition(), obj.getScale(), obj.getRotation()
    rect(z[1], p.x, p.z, sc.x, sc.z, r.y, {{{dc}}})
  end
end
for _, c in ipairs({clua}) do
  rect(c[1], c[2], c[3], {_f(card_size[0])}, {_f(card_size[1])}, 0, {{{cc}}})
end
local lines = {{}}
for _, r in ipairs(rects) do table.insert(lines, {{points = r.points, color = r.color, thickness = r.thickness}}) end
panel.setVectorLines(lines)
local made = 0
local function setText(o, text)
  local ok = pcall(function() o.TextTool.setValue(text) end)
  if not ok then pcall(function() o.setValue(text) end) end
  pcall(function() o.TextTool.setFontSize({font}) end)
end
for _, r in ipairs(rects) do
  local name = {lua_str(MARK_PREFIX)} .. " " .. r.label
  local found
  for _, o in ipairs(getObjects()) do
    if o.getName() == name and o.getGMNotes() == {lua_str(MARKER)} then found = o end
  end
  if found ~= nil then
    local usable = pcall(function()
      if found.setPosition == nil then error("sin setPosition") end
      found.setPosition({{r.x, 2.0, r.z}})
      found.setRotation({{{lrot}}})
    end)
    if usable then
      setText(found, r.label)
    else
      pcall(function() found.destruct() end)
      found = nil
    end
  end
  if found == nil then
    spawnObject({{type = "3DText", position = {{r.x, 2.0, r.z}}, rotation = {{{lrot}}},
      callback_function = function(o)
        o.setName(name)
        o.setGMNotes({lua_str(MARKER)})
        o.setLock(true)
        setText(o, r.label)
      end}})
    made = made + 1
  end
end
return JSON.encode({{drawn = #rects, labels = made, panel = true}})
"""


@_registered
def clear_markings(remove_panel: bool = False) -> str:
    """Quita lo que dibujo `draw_markings`: las lineas del panel propio y las etiquetas "SparringLabel ...".

    Con `remove_panel` quita tambien el propio panel (al salir, o al empezar si una ejecucion anterior murio sin
    limpiar). Solo toca objetos cuyo nombre Y cuyas notas de GM (`MARKER`) son nuestros: un objeto del usuario
    que solo comparta el nombre se deja en paz. El panel se renombra antes de destruirse para que ninguna
    lectura posterior en la misma pasada lo vuelva a encontrar. Nunca toca el Global."""
    if not isinstance(remove_panel, bool):
        raise TypeError("remove_panel debe ser un booleano")
    drop_panel = ("    o.setName(\"\")\n    o.setGMNotes(\"\")\n    o.destruct()\n    removed = removed + 1\n"
                  if remove_panel else "")
    return f"""-- sparring:clear_markings
local removed = 0
for _, o in ipairs(getObjects()) do
  local name = o.getName()
  local ours = o.getGMNotes() == {lua_str(MARKER)}
  if ours and o.getName() == {lua_str(PANEL_NAME)} then
    o.setVectorLines({{}})
{drop_panel}  elseif ours and string.sub(name, 1, {len(MARK_PREFIX)}) == {lua_str(MARK_PREFIX)} then
    o.destruct()
    removed = removed + 1
  end
end
return JSON.encode({{removed = removed}})
"""


@_registered
def create_panel(target_ids: list[str], position: tuple[float, float, float] = PANEL_POSITION,
                 rotation=ui.PANEL_ROTATION, scale=ui.PANEL_SCALE, names: dict[str, str] | None = None,
                 snapshot: "SnapSpec | None" = None) -> str:
    """Crea (o reutiliza) un objeto propio y le pone el panel de botones con obj.UI.setXml (nunca el Global).

    Solo se reutiliza un panel con nuestro nombre Y nuestras notas de GM; la posicion por defecto queda encima de
    los tapetes (que estan a y 1.0 y los objetos reposan a ~1.57)."""
    x, y, z = (_f(v) for v in position)
    xml = ui.panel_xml(target_ids, rotation=rotation, scale=scale, names=names)
    handler_script = ui.handler_script(snapshot_lua(snapshot) if snapshot is not None else None,
                                       ui.element_ids(target_ids))
    return f"""-- sparring:create_panel
local panel
for _, o in ipairs(getObjects()) do
  if o.getName() == {lua_str(PANEL_NAME)} and o.getGMNotes() == {lua_str(MARKER)} then panel = o end
end
if panel == nil then
  panel = spawnObject({{type = "BlockSquare", position = {{{x}, {y}, {z}}}, scale = {{0.4, 0.1, 0.4}}}})
end
panel.setName({lua_str(PANEL_NAME)})
panel.setGMNotes({lua_str(MARKER)})
panel.setLock(true)
panel.setLuaScript([==[{handler_script}]==])
local guid = panel.getGUID()
Wait.time(function()
  local p = getObjectFromGUID(guid)
  p.UI.setXml([==[{xml}]==])
end, 0.5)
return JSON.encode({{panel = guid}})
"""


# ---------- instantanea de la mesa y script compuesto (un mensaje por boton) ----------
@dataclass(frozen=True)
class SnapSpec:
    """Que se lee de la mesa en una instantanea: todo lo que la sesion necesita para decidir sin preguntar."""
    board: Board
    bot_seat: str
    human_seat: str
    bot_zone: str
    bot_skip: tuple[str, ...]
    bot_spots: tuple[tuple[float, float], ...]
    human_zone: str
    human_skip: tuple[str, ...]
    human_spots: tuple[tuple[float, float], ...]
    exclude_radius: float
    bot_card_spot: tuple[float, float]
    human_card_spot: tuple[float, float]
    reveal_radius: float
    pieces: tuple[str, ...]
    dials: tuple[str, ...]
    board_guid: str | None = None
    human_deck: str | None = None          # mazo de robo del humano: solo se mira cuantas cartas tiene


def _pairs(spots) -> str:
    return "{" + ", ".join("{" + ", ".join(_spot(sp, 1.0)[:2]) + "}" for sp in spots) + "}"


def _guid_list(guids) -> str:
    return "{" + ", ".join(_guid(g) for g in guids) + "}"


def snapshot_lua(spec: SnapSpec) -> str:
    """Fragmento Lua que define `sparringSnapshot()`: la mano del bot (CardID), el conteo de la mano del humano
    (secreta: solo se cuenta), los descartes de ambas zonas (sin los mazos de robo), las cartas boca abajo en los dos
    puntos de combate, la casilla mas cercana y la distancia de cada pieza por GUID y los diales. Lo usan el script de
    lectura `snapshot`, el compuesto `composite` (estado resultante) y el script del panel (al pulsar un boton)."""
    return f"""local function sparringSnapshot()
{_card_ids_helper()}{_board_prelude(spec.board, spec.board_guid)}local function zoneCards(guid, skip, spots, r2)
  local z = getObjectFromGUID(guid)
  local objs = {{}}
  if z == nil then return {{}} end
  for _, o in ipairs(z.getObjects()) do
    local p = o.getPosition()
    local near = false
    for _, sp in ipairs(spots) do
      if (p.x - sp[1]) ^ 2 + (p.z - sp[2]) ^ 2 <= r2 and o.is_face_down then near = true end
    end
    if not skip[o.getGUID()] and not near then table.insert(objs, o) end
  end
  return cardIds(objs)
end
local function faceDown(x, z, r)
  local out = {{}}
  for _, o in ipairs(getObjects()) do
    if o.type == "Card" and o.is_face_down then
      local p = o.getPosition()
      if (p.x - x) ^ 2 + (p.z - z) ^ 2 <= r ^ 2 then table.insert(out, {{id = o.getData().CardID, guid = o.getGUID()}}) end
    end
  end
  return out
end
local function skipSet(list)
  local t = {{}}
  for _, g in ipairs(list) do t[g] = true end
  return t
end
local snap = {{}}
snap.bot_hand = cardIds(Player[{_color(spec.bot_seat)}].getHandObjects(1))
snap.human_count = #Player[{_color(spec.human_seat)}].getHandObjects(1)
local r2 = {_f(spec.exclude_radius)} ^ 2
snap.bot_discard = zoneCards({_guid(spec.bot_zone)}, skipSet({_guid_list(spec.bot_skip)}), {_pairs(spec.bot_spots)}, r2)
snap.human_discard = zoneCards({_guid(spec.human_zone)}, skipSet({_guid_list(spec.human_skip)}), {_pairs(spec.human_spots)}, r2)
snap.face_bot = faceDown({_f(spec.bot_card_spot[0])}, {_f(spec.bot_card_spot[1])}, {_f(spec.reveal_radius)})
snap.face_human = faceDown({_f(spec.human_card_spot[0])}, {_f(spec.human_card_spot[1])}, {_f(spec.reveal_radius)})
local world = {{}}
for id, _ in pairs(snaps) do world[id] = spaceWorld(id) end
snap.pieces = {{}}
for _, g in ipairs({_guid_list(spec.pieces)}) do
  local obj = getObjectFromGUID(g)
  if obj == nil then
    snap.pieces[g] = {{found = false}}
  else
    local p = obj.getPosition()
    local best, bd = nil, 1e18
    for id, w in pairs(world) do
      local d = (w.x - p.x) ^ 2 + (w.z - p.z) ^ 2
      if d < bd then best, bd = id, d end
    end
    snap.pieces[g] = {{found = true, space = best, dist = math.sqrt(bd), type = obj.type, name = obj.getName()}}
  end
end
snap.human_deck_qty = -1
local hd = {_guid(spec.human_deck) if spec.human_deck else "nil"} and getObjectFromGUID({_guid(spec.human_deck) if spec.human_deck else '"-"'})
if hd ~= nil then snap.human_deck_qty = (hd.type == "Deck") and hd.getQuantity() or 1 end
snap.dials = {{}}
for _, g in ipairs({_guid_list(spec.dials)}) do
  local o = getObjectFromGUID(g)
  if o == nil then
    snap.dials[g] = {{found = false}}
  else
    local ok, cfg = pcall(function() return o.getTable("CONFIG") end)
    local value, max = nil, nil
    if ok and type(cfg) == "table" then value, max = cfg.VALUE, cfg.MAX_VALUE end
    snap.dials[g] = {{found = true, name = o.getName(), value = value, max = max}}
  end
end
return snap
end
"""


@_registered
def snapshot(spec: SnapSpec) -> str:
    """Solo lectura: la instantanea completa de la mesa en UN mensaje (ver `snapshot_lua`)."""
    return "-- sparring:snapshot\n" + snapshot_lua(spec) + "return JSON.encode(sparringSnapshot())\n"


MAX_OPS = 64
_OP_HEAD = re.compile(r"-- sparring:(\w+)\n")


def _check_op(op) -> str:
    if not isinstance(op, str) or not is_sendable(op) or _REQ.fullmatch(op):
        raise ValueError("solo se componen scripts generados por un constructor y aun sin marcar")
    tag = _OP_HEAD.match(op)
    if tag is None or tag.group(1) in ("composite", "snapshot"):
        raise ValueError("operacion no componible")
    if len(re.findall(r"^-- sparring:", op, re.M)) != 1:
        raise ValueError("operacion con mas de una cabecera")
    return op


@_registered
def composite(ops: list[str], spec: SnapSpec | None = None, expect_hand: tuple[str, int] | None = None) -> str:
    """UN script con varias operaciones ya validadas (cada una la genero un constructor) y el estado resultante.

    Las operaciones se ejecutan en orden, cada una dentro de pcall (un fallo de una no frena a las demas: su
    resultado es `{__err = ...}`). Al terminar, con `spec`, se lee la mesa de nuevo y se devuelve
    `{ops = [resultados], state = instantanea}`. Si alguna operacion movio una pieza (suave) o repartio cartas, o
    se pide `expect_hand` = (asiento, n), se espera dentro de TTS a que las piezas esten quietas y la mano del
    asiento tenga n cartas (maximo 2.5 s) antes de leer: asi la verificacion cabe en el mismo mensaje."""
    if not isinstance(ops, (list, tuple)) or not 1 <= len(ops) <= MAX_OPS:
        raise ValueError(f"se esperan entre 1 y {MAX_OPS} operaciones")
    body = []
    for i, op in enumerate(_check_op(o) for o in ops):
        body.append(f"results[{i + 1}] = run(function()\n{op}end) or {{}}\n")
    if expect_hand is not None:
        seat, n = expect_hand
        expect = f"local expectSeat, expectN = {_color(seat)}, {_i(n)}\n"
    else:
        expect = "local expectSeat, expectN = nil, nil\n"
    snap = snapshot_lua(spec) if spec is not None else ""
    read = "local ok, st = pcall(sparringSnapshot)" if spec is not None else "local ok, st = true, nil"
    return ("-- sparring:composite\nlocal __J = JSON\nlocal JSON = {encode = function(v) return v end}\n"
            "local results = {}\n"
            "local function run(f) local ok, r = pcall(f); if ok then return r end return {__err = tostring(r)} end\n"
            + "".join(body) + snap + expect + f"""local function finish()
  {read}
  __J.encode({{ops = results, state = ok and st or nil, state_err = (not ok) and tostring(st) or nil}})
end
local function ready()
  if expectSeat ~= nil and #Player[expectSeat].getHandObjects(1) ~= expectN then return false end
  for _, r in ipairs(results) do
    if type(r.moved) == "string" then
      local o = getObjectFromGUID(r.moved)
      if o ~= nil and not o.resting then return false end
    end
  end
  return true
end
local slow = expectSeat ~= nil
for _, r in ipairs(results) do
  if type(r.moved) == "string" or r.dealt ~= nil then slow = true end
end
if slow then
  Wait.frames(function()
    Wait.condition(function() pcall(finish) end, ready, 2.5, function() pcall(finish) end)
  end, 3)
else
  finish()
end
return ""
""")


PANEL_ID = re.compile(r"[A-Za-z0-9_]{1,40}")
_STATUS = re.compile(r"[A-Za-z0-9 _.\-!:',·]{0,90}")


@_registered
def set_panel(status: str, states: dict[str, tuple[bool, bool]]) -> str:
    """ESCRIBE en la UI del panel PROPIO del bot (nunca el Global): la linea de estado y, por id de elemento, si se
    puede pulsar (`interactable`) y si se ve (`active`). Tambien libera el "Procesando..." del panel."""
    if not isinstance(status, str) or not _STATUS.fullmatch(status):
        raise ValueError(f"texto de estado no admitido: {status!r}")
    if not isinstance(states, dict) or len(states) > 80:
        raise TypeError("diccionario id -> (interactable, active) esperado")
    rows = []
    for ident, st in sorted(states.items()):
        if not isinstance(ident, str) or not PANEL_ID.fullmatch(ident) or not isinstance(st, (tuple, list)) \
                or len(st) != 2 or not all(isinstance(b, bool) for b in st):
            raise ValueError(f"estado de elemento no valido: {ident!r}")
        rows.append(f'["{ident}"]={{{str(st[0]).lower()}, {str(st[1]).lower()}}}')
    return f"""-- sparring:set_panel
local panel
for _, o in ipairs(getObjects()) do
  if o.getName() == {lua_str(PANEL_NAME)} and o.getGMNotes() == {lua_str(MARKER)} then panel = o end
end
if panel == nil then return JSON.encode({{panel = false}}) end
panel.setVar("busy", false)
panel.UI.setValue("status", "{status}")
for id, st in pairs({{{", ".join(rows)}}}) do
  panel.UI.setAttribute(id, "interactable", tostring(st[1]))
  panel.UI.setAttribute(id, "active", tostring(st[2]))
end
return JSON.encode({{panel = true}})
"""


HUMAN_CARD_IDS = (HELLBOY_BASE, HELLBOY_BASE + 29)      # rango de CardID del mazo de Hellboy (30 cartas)


@_registered
def reset_deck(deck_guid: str, spot: tuple[float, float], id_range: tuple[int, int], radius: float = 2.0) -> str:
    """REINICIO: mete en el mazo de robo TODAS las cartas de un bando (las de las manos, los descartes, las que estan
    boca abajo en la mesa y los Deck sueltos) y lo baraja. Solo cuenta lo que tiene un CardID de `id_range` (el mazo
    de ese bando) y no esta cogido por nadie. El mazo se halla por GUID o, si TTS lo destruyo al quedar vacio, por
    posicion `spot`; sin mazo, se agrupan las cartas sueltas (`group`). Devuelve cuantas cartas hay en el mazo."""
    if not isinstance(id_range, (tuple, list)) or len(id_range) != 2:
        raise TypeError("(minimo, maximo) de CardID esperado")
    lo, hi = _i(id_range[0]), _i(id_range[1])
    find = _find_deck(spot, radius, id_range)
    return f"""-- sparring:reset_deck
local d = getObjectFromGUID({_guid(deck_guid)})
{find}local function ours(o)
  local first
  if o.type == "Card" then first = o.getData().CardID
  elseif o.type == "Deck" then
    local c = (o.getData().ContainedObjects or {{}})[1]
    first = c and c.CardID
  end
  return first ~= nil and first >= {lo} and first <= {hi}
end
local others = {{}}
for _, o in ipairs(getObjects()) do
  if (o.type == "Card" or o.type == "Deck") and o ~= d and not o.held_by_color and ours(o) then
    table.insert(others, o)
  end
end
if d == nil then
  if #others >= 2 then
    local made = group(others)
    d = made and made[1]
    others = {{}}
  elseif #others == 1 then
    return JSON.encode({{deck = false, quantity = 1}})
  end
end
if d == nil then return JSON.encode({{deck = false, quantity = 0}}) end
for _, o in ipairs(others) do d = d.putObject(o) or d end
if d.type == "Deck" then
  d.shuffle()
  return JSON.encode({{deck = true, quantity = d.getQuantity()}})
end
return JSON.encode({{deck = true, quantity = 1}})
"""
