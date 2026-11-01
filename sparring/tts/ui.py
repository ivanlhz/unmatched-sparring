"""Panel de botones del humano. Vive en un objeto creado por el bot (obj.UI.setXml), no en el Global.

Tres secciones: TURNO (linea de estado y acciones), VIDA (PV por luchador) y PARTIDA (preparacion o reinicio).
Al pulsar un boton el propio script del panel pone "Procesando...", apaga los botones y envia el evento junto con la
instantanea de la mesa (ver `lua.snapshot_lua`); el bot lo reactiva con `lua.set_panel`."""
from __future__ import annotations

import re
from enum import Enum

from ..i18n import t


class Event(str, Enum):
    MANEUVER = "maneuver"
    ATTACKER = "attacker"
    ATTACK = "attack"
    SCHEME = "scheme"
    REVEAL = "reveal"
    END_ACTION = "end_action"
    VALUE = "value"
    CANCEL = "cancel"
    HP = "hp"
    REMOVE = "remove"
    UNDO_GAME_OVER = "undo_game_over"
    READY = "ready"
    MULLIGAN = "mulligan"
    RESTART = "restart"
    BOOST = "boost"            # "Continuar": lee la carta de boost que el humano puso en su descarte y resuelve
    NO_BOOST = "no_boost"      # "Sin boost": resuelve sin potenciar
    LOOK = "look_hand"         # "Mirar mano del bot": las cartas del bot boca arriba en fila (descartar una, p. ej. Confront)
    LOOK_PING = "look_ping"    # ping (Tab) del humano sobre una carta de esa fila: la que se descarta
    CHOICE = "choice"          # btn_choice_<i>: la opcion i (1..6) de la eleccion de efecto pendiente, en {"i": i}


PANEL_ROTATION = (0, 0, 270)     # confirmado en vivo: con 90 se veia boca abajo desde el asiento White
PANEL_SCALE = (6, 6, 6)          # sin escala el panel se ve diminuto sobre el objeto de 0.4
PANEL_WIDTH = 760
STATUS_ID = "status"
BUTTON_STYLE = 'textColor="#FFFFFF" colors="#2D6A9F|#3C86C8|#1F4C75|#555555" '

ROW_HEIGHT = 48
DEFAULT_ATTACKERS = ("hellboy", "lobster")      # sin heroes a mano: los de Medusa vs Hellboy

CHOICE_BUTTONS = tuple(f"btn_choice_{i}" for i in range(1, 7))     # ocultos salvo con una eleccion de efecto pendiente

# id de cada boton fijo -> (funcion del panel, evento)
FIXED_BUTTONS = {"btn_maneuver": "onManeuver", "btn_scheme": "onScheme", "btn_reveal": "onReveal",
                 "btn_cancel": "onCancel", "btn_end": "onEndAction", "btn_undo": "onUndoGameOver",
                 "btn_value": "onValueSend", "btn_mulligan": "onMulligan", "btn_ready": "onReady",
                 "btn_restart": "onRestart", "btn_boost": "onBoost", "btn_noboost": "onNoBoost",
                 "btn_look": "onLook", **dict.fromkeys(CHOICE_BUTTONS, "onChoice")}
SETUP_ONLY = ("btn_mulligan", "btn_ready")
GAME_ONLY = ("btn_restart",)


def __getattr__(name: str):
    """`END_ACTION_LABEL`: the caption of the end-of-action button in the current language."""
    if name == "END_ACTION_LABEL":
        return t("panel.end_action")
    raise AttributeError(name)


def _triple(v, name: str) -> str:
    if not isinstance(v, (tuple, list)) or len(v) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float))
                                                                for x in v):
        raise TypeError(f"{name}: tres numeros esperados, llego {v!r}")
    if not all(abs(float(x)) < 1e6 and float(x) == float(x) for x in v):
        raise ValueError(f"{name}: numero fuera de rango")
    return " ".join(f"{float(x):g}" for x in v)


def element_ids(target_ids, attacker_ids=DEFAULT_ATTACKERS, fighter_ids=None) -> list[str]:
    """Id de todos los botones del panel (los que se apagan al pulsar y el bot reactiva segun el estado)."""
    fighters = tuple(dict.fromkeys(fighter_ids if fighter_ids is not None else (*target_ids, *attacker_ids)))
    return [*FIXED_BUTTONS, *(f"att_{a}" for a in attacker_ids), *target_ids,
            *(f"{p}_{f}" for f in fighters for p in ("hpm", "hpp", "rm"))]


def handler_script(snapshot: str | None = None, ids: tuple[str, ...] | list[str] = (),
                   human_seat: str | None = None) -> str:
    """Script del objeto panel: cada boton avisa al bot con sendExternalMessage (llega como messageID 4).

    Feedback local instantaneo: antes de enviar pone "Procesando..." y apaga los botones (sin ida y vuelta). Con
    `snapshot` (el fragmento de `lua.snapshot_lua`) el mensaje lleva la instantanea de la mesa tomada en el clic.
    `busy` es global a proposito: el compuesto (`lua.composite`, tras esperar a las piezas) o `lua.set_panel` lo liberan
    con setVar; si el bot no contesta en 20 s se reactiva, pero solo el temporizador del ULTIMO clic puede hacerlo
    (`clickSeq`): uno viejo no desbloquea un clic posterior que aun se esta procesando. `wseq` es la ultima escritura de
    mesa que el bot anoto en el panel (la sella en la instantanea del clic).

    `onPlayerPing` (evento universal de TTS, valido en el script de un objeto) reconoce el ping del asiento `human_seat`
    sobre una carta de la fila de la mano del bot (`lookRow`, que escribe el bot con `lua.show_hand_row`): por el objeto
    pinchado si es de la fila y, si TTS no lo da, por la carta de la fila mas cercana a la posicion. Cualquier otro ping
    (otro asiento, otro objeto, sin fila) se ignora. Sin `human_seat` no reconoce ninguno."""
    for i in ids:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", i):
            raise ValueError(f"id de elemento no valido: {i!r}")
    all_ids = "{" + ", ".join(f'"{i}"' for i in ids) + "}"
    if human_seat is not None and not re.fullmatch(r"[A-Za-z]{3,10}", human_seat):
        raise ValueError(f"asiento no valido: {human_seat!r}")
    seat = f'"{human_seat}"' if human_seat else "nil"
    take = ("  local ok, snap = pcall(sparringSnapshot)\n  if ok then tbl.snapshot = JSON.encode(snap) end\n"
            if snapshot else "")
    return f"""{snapshot or ""}busy = false
wseq = 0
local clickSeq = 0
local ALL = {all_ids}
local function setAll(on)
  for _, id in ipairs(ALL) do UI.setAttribute(id, "interactable", on and "true" or "false") end
end
local function send(tbl)
  if busy then return end
  busy = true
  clickSeq = clickSeq + 1
  local mine = clickSeq
  UI.setValue("{STATUS_ID}", "{t("panel.processing")}")
  setAll(false)
{take}  sendExternalMessage(tbl)
  Wait.time(function()
    if busy and mine == clickSeq then
      busy = false
      setAll(true)
      UI.setValue("{STATUS_ID}", "{t("panel.no_reply")}")
    end
  end, 20)
end
function onManeuver() send({{event = "maneuver"}}) end
function onAttacker(player, btn, id) send({{event = "attacker", attacker = id}}) end
function onAttack(player, btn, id) send({{event = "attack", target = id}}) end
function onScheme() send({{event = "scheme"}}) end
function onReveal() send({{event = "reveal"}}) end
function onEndAction() send({{event = "end_action"}}) end
function onCancel() send({{event = "cancel"}}) end
function onHp(player, btn, id)
  local sign, fid = tostring(id):match("^hp([mp])_(%w+)$")
  if sign then send({{event = "hp", fighter = fid, delta = (sign == "p") and 1 or -1}}) end
end
function onRemove(player, btn, id)
  local fid = tostring(id):match("^rm_(%w+)$")
  if fid then send({{event = "remove", fighter = fid}}) end
end
function onUndoGameOver() send({{event = "undo_game_over"}}) end
function onReady() send({{event = "ready"}}) end
function onMulligan() send({{event = "mulligan"}}) end
function onRestart() send({{event = "restart"}}) end
function onBoost() send({{event = "boost"}}) end
function onNoBoost() send({{event = "no_boost"}}) end
function onLook() send({{event = "look_hand"}}) end
function onChoice(player, btn, id)
  local n = tonumber(tostring(id):match("^btn_choice_(%d)$"))
  if n then send({{event = "choice", i = n}}) end
end
lookRow = ""
botPingUntil = 0
local HUMAN_SEAT = {seat}
local PING_RADIUS = 1.6
function onPlayerPing(player, position, object)
  if lookRow == "" or HUMAN_SEAT == nil or player == nil or player.color ~= HUMAN_SEAT then return end
  if Time ~= nil and Time.time < botPingUntil then return end     -- the bot pings as the human's seat: not a pick
  local hit, best = nil, PING_RADIUS
  local pinged = nil
  if object ~= nil then pcall(function() pinged = object.getGUID() end) end
  for entry in string.gmatch(lookRow, "[^,]+") do
    local g, x, z = string.match(entry, "^([^|]+)|([^|]+)|([^|]+)$")
    x, z = tonumber(x), tonumber(z)
    if g ~= nil and x ~= nil and z ~= nil then
      if g == pinged then hit = g break end
      if position ~= nil then
        local d = math.sqrt((position.x - x) ^ 2 + (position.z - z) ^ 2)
        if d <= best then hit, best = g, d end
      end
    end
  end
  if hit ~= nil then send({{event = "look_ping", guid = hit}}) end
end
local pending = ""
function onValueEdit(player, value, id) pending = value end
function onValueSend() send({{event = "value", value = tonumber(pending)}}) end
"""


_LABEL = re.compile(r"[A-Za-z0-9 _.\-']{1,40}")


def _button(ident: str, handler: str, text: str, size: int = 18) -> str:
    return f'<Button fontSize="{size}" {BUTTON_STYLE}id="{ident}" onClick="{handler}">{text}</Button>'


def _row(*cells: str, height: int = ROW_HEIGHT) -> str:
    return f'<HorizontalLayout spacing="8" preferredHeight="{height}">{"".join(cells)}</HorizontalLayout>'


def _choice_row(ids) -> str:
    """Fila de botones de eleccion: nacen ocultos; el bot los muestra (con su texto) solo mientras hay una eleccion."""
    return _row(*(_button(i, "onChoice", t("panel.option"), 16).replace("<Button ", '<Button active="false" ') for i in ids))


def _text(text: str, size: int = 18, extra: str = "") -> str:
    return f'<Text color="#FFFFFF" fontSize="{size}" {extra}>{text}</Text>'.replace(" >", ">")


def panel_height(fighter_count: int) -> int:
    """Alto del panel en pixeles de UI (con la columna lateral de VIDA de `fighter_count` luchadores)."""
    return 40 + 40 + 7 * (ROW_HEIGHT + 8) + 40 + (60 + 48 * fighter_count) + 40


def panel_xml(target_ids: list[str], attacker_ids: tuple[str, ...] = DEFAULT_ATTACKERS,
              fighter_ids: tuple[str, ...] | None = None, rotation=PANEL_ROTATION, scale=PANEL_SCALE,
              names: dict[str, str] | None = None) -> str:
    """`fighter_ids` son todos los luchadores de ambos bandos (filas de PV y Retirar); por defecto, los dos grupos."""
    fighters = tuple(dict.fromkeys(fighter_ids if fighter_ids is not None else (*target_ids, *attacker_ids)))
    for ident in (*target_ids, *attacker_ids, *fighters):
        if not re.fullmatch(r"[A-Za-z0-9_]+", ident):
            raise ValueError(f"id de objetivo no valido: {ident!r}")
    rot, sc = _triple(rotation, "panel_rotation"), _triple(scale, "panel_scale")
    names = names or {}
    if not isinstance(names, dict) or not all(isinstance(v, str) and _LABEL.fullmatch(v) for v in names.values()):
        raise ValueError("nombres de boton no validos (letras, cifras, espacio y . _ - ')")

    def label(ident: str) -> str:
        return names.get(ident, ident)
    section = 'color="#16222FEE" padding="10 10 10 10" spacing="8"'
    who = _row(*(_button(f"att_{a}", "onAttacker", t("panel.attacker", name=label(a))) for a in attacker_ids))
    attacks = _row(*(_button(tid, "onAttack", t("panel.attack", name=label(tid)), 16) for tid in target_ids))
    turn = (f'<VerticalLayout {section} preferredHeight="{40 + 7 * (ROW_HEIGHT + 8) + 40}">'
            + _text(t("panel.turn"), 16, 'fontStyle="Bold"')
            + f'<Text id="{STATUS_ID}" color="#FFFFFF" fontSize="22" fontStyle="Bold" preferredHeight="40">{t("panel.status_init")}</Text>'
            + _row(_button("btn_maneuver", "onManeuver", t("panel.maneuver")), _button("btn_scheme", "onScheme", t("panel.scheme")))
            + who + attacks
            + _row(_button("btn_reveal", "onReveal", t("panel.reveal")), _button("btn_cancel", "onCancel", t("panel.cancel")),
                   _button("btn_boost", "onBoost", t("panel.continue")).replace("<Button ", '<Button active="false" '),
                   _button("btn_noboost", "onNoBoost", t("panel.no_boost")).replace("<Button ", '<Button active="false" '))
            + _row(_button("btn_end", "onEndAction", t("panel.end_action")),
                   _button("btn_look", "onLook", t("panel.look")).replace("<Button ", '<Button active="false" '))
            + _choice_row(CHOICE_BUTTONS[:3]) + _choice_row(CHOICE_BUTTONS[3:])
            + '</VerticalLayout>')
    hp_rows = "".join(
        _row(f'<Text color="#FFFFFF" fontSize="16" preferredWidth="150">{label(f)}</Text>',
             _button(f"hpm_{f}", "onHp", "-1", 16), _button(f"hpp_{f}", "onHp", "+1", 16),
             _button(f"rm_{f}", "onRemove", t("panel.remove"), 16), height=40) for f in fighters)
    side_h = 60 + 48 * len(fighters)
    life = (f'<VerticalLayout {section} preferredWidth="470" preferredHeight="{side_h}">'
            + _text(t("panel.life"), 16, 'fontStyle="Bold"') + hp_rows + '</VerticalLayout>')
    game = (f'<VerticalLayout {section} preferredWidth="260" preferredHeight="{side_h}">'
            + _text(t("panel.game"), 16, 'fontStyle="Bold"')
            + _row(_button("btn_mulligan", "onMulligan", t("panel.mulligan")))
            + _row(_button("btn_ready", "onReady", t("panel.ready")))
            + _row(_button("btn_restart", "onRestart", t("panel.restart")))
            + _row(_button("btn_undo", "onUndoGameOver", t("panel.undo")))
            + f'<InputField placeholder="{t("panel.value_placeholder")}" onValueChanged="onValueEdit" preferredHeight="40"/>'
            + _row(_button("btn_value", "onValueSend", t("panel.send_value"))) + '</VerticalLayout>')
    height = panel_height(len(fighters))
    return (f'<Panel position="0 0 -20" rotation="{rot}" scale="{sc}" width="{PANEL_WIDTH}" height="{height}" '
            f'color="#000000CC">\n  <VerticalLayout spacing="8" padding="8 8 8 8">\n    {turn}\n'
            f'    <HorizontalLayout spacing="8" preferredHeight="{side_h}">{life}{game}</HorizontalLayout>\n'
            '  </VerticalLayout>\n</Panel>\n')


def parse_event(custom_message: dict) -> tuple[Event, dict]:
    ev = Event(custom_message["event"])
    return ev, {k: v for k, v in custom_message.items() if k != "event"}
