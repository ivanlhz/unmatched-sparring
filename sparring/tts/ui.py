"""Panel de botones del humano. Vive en un objeto creado por el bot (obj.UI.setXml), no en el Global.

Tres secciones: TURNO (linea de estado y acciones), VIDA (PV por luchador) y PARTIDA (preparacion o reinicio).
Al pulsar un boton el propio script del panel pone "Procesando...", apaga los botones y envia el evento junto con la
instantanea de la mesa (ver `lua.snapshot_lua`); el bot lo reactiva con `lua.set_panel`."""
from __future__ import annotations

import re
from enum import Enum


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


END_ACTION_LABEL = "Fin de accion"
PANEL_ROTATION = (0, 0, 270)     # confirmado en vivo: con 90 se veia boca abajo desde el asiento White
PANEL_SCALE = (6, 6, 6)          # sin escala el panel se ve diminuto sobre el objeto de 0.4
PANEL_WIDTH = 760
STATUS_ID = "status"
PROCESSING = "Procesando..."
BUTTON_STYLE = 'textColor="#FFFFFF" colors="#2D6A9F|#3C86C8|#1F4C75|#555555" '

ROW_HEIGHT = 48

# id de cada boton fijo -> (funcion del panel, evento)
FIXED_BUTTONS = {"btn_maneuver": "onManeuver", "btn_scheme": "onScheme", "btn_reveal": "onReveal",
                 "btn_cancel": "onCancel", "btn_end": "onEndAction", "btn_undo": "onUndoGameOver",
                 "btn_value": "onValueSend", "btn_mulligan": "onMulligan", "btn_ready": "onReady",
                 "btn_restart": "onRestart"}
SETUP_ONLY = ("btn_mulligan", "btn_ready")
GAME_ONLY = ("btn_restart",)


def _triple(v, name: str) -> str:
    if not isinstance(v, (tuple, list)) or len(v) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float))
                                                                for x in v):
        raise TypeError(f"{name}: tres numeros esperados, llego {v!r}")
    if not all(abs(float(x)) < 1e6 and float(x) == float(x) for x in v):
        raise ValueError(f"{name}: numero fuera de rango")
    return " ".join(f"{float(x):g}" for x in v)


def element_ids(target_ids, attacker_ids=("hellboy", "lobster"), fighter_ids=None) -> list[str]:
    """Id de todos los botones del panel (los que se apagan al pulsar y el bot reactiva segun el estado)."""
    fighters = tuple(dict.fromkeys(fighter_ids if fighter_ids is not None else (*target_ids, *attacker_ids)))
    return [*FIXED_BUTTONS, *(f"att_{a}" for a in attacker_ids), *target_ids,
            *(f"{p}_{f}" for f in fighters for p in ("hpm", "hpp", "rm"))]


def handler_script(snapshot: str | None = None, ids: tuple[str, ...] | list[str] = ()) -> str:
    """Script del objeto panel: cada boton avisa al bot con sendExternalMessage (llega como messageID 4).

    Feedback local instantaneo: antes de enviar pone "Procesando..." y apaga los botones (sin ida y vuelta). Con
    `snapshot` (el fragmento de `lua.snapshot_lua`) el mensaje lleva la instantanea de la mesa tomada en el clic.
    `busy` es global a proposito: `lua.set_panel` lo libera con setVar; si el bot no contesta en 20 s se reactiva."""
    for i in ids:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", i):
            raise ValueError(f"id de elemento no valido: {i!r}")
    all_ids = "{" + ", ".join(f'"{i}"' for i in ids) + "}"
    take = ("  local ok, snap = pcall(sparringSnapshot)\n  if ok then tbl.snapshot = JSON.encode(snap) end\n"
            if snapshot else "")
    return f"""{snapshot or ""}busy = false
local ALL = {all_ids}
local function setAll(on)
  for _, id in ipairs(ALL) do UI.setAttribute(id, "interactable", on and "true" or "false") end
end
local function send(tbl)
  if busy then return end
  busy = true
  UI.setValue("{STATUS_ID}", "{PROCESSING}")
  setAll(false)
{take}  sendExternalMessage(tbl)
  Wait.time(function()
    if busy then
      busy = false
      setAll(true)
      UI.setValue("{STATUS_ID}", "Sin respuesta del bot: repite el boton")
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
local pending = ""
function onValueEdit(player, value, id) pending = value end
function onValueSend() send({{event = "value", value = tonumber(pending)}}) end
"""


_LABEL = re.compile(r"[A-Za-z0-9 _.\-']{1,40}")


def _button(ident: str, handler: str, text: str, size: int = 18) -> str:
    return f'<Button fontSize="{size}" {BUTTON_STYLE}id="{ident}" onClick="{handler}">{text}</Button>'


def _row(*cells: str, height: int = ROW_HEIGHT) -> str:
    return f'<HorizontalLayout spacing="8" preferredHeight="{height}">{"".join(cells)}</HorizontalLayout>'


def _text(text: str, size: int = 18, extra: str = "") -> str:
    return f'<Text color="#FFFFFF" fontSize="{size}" {extra}>{text}</Text>'.replace(" >", ">")


def panel_xml(target_ids: list[str], attacker_ids: tuple[str, ...] = ("hellboy", "lobster"),
              fighter_ids: tuple[str, ...] | None = None, rotation=PANEL_ROTATION, scale=PANEL_SCALE,
              names: dict[str, str] | None = None) -> str:
    """`fighter_ids` son todos los luchadores de ambos bandos (filas de PV y Retirar); por defecto, los dos grupos."""
    fighters = tuple(dict.fromkeys(fighter_ids if fighter_ids is not None else (*target_ids, *attacker_ids)))
    for t in (*target_ids, *attacker_ids, *fighters):
        if not re.fullmatch(r"[A-Za-z0-9_]+", t):
            raise ValueError(f"id de objetivo no valido: {t!r}")
    rot, sc = _triple(rotation, "panel_rotation"), _triple(scale, "panel_scale")
    names = names or {}
    if not isinstance(names, dict) or not all(isinstance(v, str) and _LABEL.fullmatch(v) for v in names.values()):
        raise ValueError("nombres de boton no validos (letras, cifras, espacio y . _ - ')")

    def label(t: str) -> str:
        return names.get(t, t)
    section = 'color="#16222FEE" padding="10 10 10 10" spacing="8"'
    who = _row(*(_button(f"att_{a}", "onAttacker", f"Ataca {label(a)}") for a in attacker_ids))
    attacks = _row(*(_button(t, "onAttack", f"Atacar a {label(t)}", 16) for t in target_ids))
    turn = (f'<VerticalLayout {section} preferredHeight="{40 + 5 * (ROW_HEIGHT + 8) + 40}">'
            + _text("TURNO", 16, 'fontStyle="Bold"')
            + f'<Text id="{STATUS_ID}" color="#FFFFFF" fontSize="22" fontStyle="Bold" preferredHeight="40">Preparando...</Text>'
            + _row(_button("btn_maneuver", "onManeuver", "Maniobra"), _button("btn_scheme", "onScheme", "Plan"))
            + who + attacks
            + _row(_button("btn_reveal", "onReveal", "Revelar"), _button("btn_cancel", "onCancel", "Cancelar ataque"))
            + _row(_button("btn_end", "onEndAction", END_ACTION_LABEL)) + '</VerticalLayout>')
    hp_rows = "".join(
        _row(f'<Text color="#FFFFFF" fontSize="16" preferredWidth="150">{label(f)}</Text>',
             _button(f"hpm_{f}", "onHp", "-1", 16), _button(f"hpp_{f}", "onHp", "+1", 16),
             _button(f"rm_{f}", "onRemove", "Retirar", 16), height=40) for f in fighters)
    side_h = 60 + 48 * len(fighters)
    life = (f'<VerticalLayout {section} preferredWidth="470" preferredHeight="{side_h}">'
            + _text("VIDA", 16, 'fontStyle="Bold"') + hp_rows + '</VerticalLayout>')
    game = (f'<VerticalLayout {section} preferredWidth="260" preferredHeight="{side_h}">'
            + _text("PARTIDA", 16, 'fontStyle="Bold"')
            + _row(_button("btn_mulligan", "onMulligan", "Mulligan"))
            + _row(_button("btn_ready", "onReady", "Listo (preparacion)"))
            + _row(_button("btn_restart", "onRestart", "Reiniciar partida"))
            + _row(_button("btn_undo", "onUndoGameOver", "Deshacer fin de partida"))
            + '<InputField placeholder="valor (boost, On Earth...)" onValueChanged="onValueEdit" preferredHeight="40"/>'
            + _row(_button("btn_value", "onValueSend", "Enviar valor")) + '</VerticalLayout>')
    height = 40 + 40 + 5 * (ROW_HEIGHT + 8) + 40 + side_h + 40
    return (f'<Panel position="0 0 -20" rotation="{rot}" scale="{sc}" width="{PANEL_WIDTH}" height="{height}" '
            f'color="#000000CC">\n  <VerticalLayout spacing="8" padding="8 8 8 8">\n    {turn}\n'
            f'    <HorizontalLayout spacing="8" preferredHeight="{side_h}">{life}{game}</HorizontalLayout>\n'
            '  </VerticalLayout>\n</Panel>\n')


def parse_event(custom_message: dict) -> tuple[Event, dict]:
    ev = Event(custom_message["event"])
    return ev, {k: v for k, v in custom_message.items() if k != "event"}
