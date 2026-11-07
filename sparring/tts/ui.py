"""The human's button panel. It lives in an object created by the bot (obj.UI.setXml), not in the Global.

Three sections: TURN (status line and actions), LIFE (HP per fighter) and GAME (setup or restart).
When a button is pressed the panel's own script sets "Processing...", turns the buttons off and sends the event together with the
table snapshot (see `lua.snapshot_lua`); the bot re-enables it with `lua.set_panel`."""
from __future__ import annotations

import re
from enum import Enum
from xml.sax.saxutils import escape

from ..i18n import t as _tag_text


def t(tag: str, **kwargs) -> str:
    """Catalog text, escaped for XML text and double-quoted attributes (& < > and the double quote)."""
    return escape(_tag_text(tag, **kwargs), {'"': "&quot;"})


def lua_text(tag: str) -> str:
    """Catalog text for a double-quoted Lua string: backslash, quote and line breaks escaped, other controls dropped."""
    text = _tag_text(tag).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return "".join(c for c in text if c >= " ")


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
    BOOST = "boost"            # "Continue": reads the boost card the human put in their discard and resolves
    NO_BOOST = "no_boost"      # "No boost": resolves without boosting
    MANEUVER_BOOST = "maneuver_boost"   # "Boost": reads the boost card in the discard pile during the human's Maneuver
    LOOK = "look_hand"         # "Look at bot's hand": the bot's cards face up in a row (discard one, e.g. Confront)
    LOOK_PING = "look_ping"    # the human's ping (Tab) on a card of that row: the one that is discarded
    CHOICE = "choice"          # btn_choice_<i>: option i (1..6) of the pending effect choice, in {"i": i}
    CLEAN = "clean_table"      # "Clean table": removes every hero and map (the pre-game gate, `sparring/table_reset.py`)
    PREPARE = "prepare_table"  # "Prepare": reads the map and the two heroes the player dropped and lays them out
    START = "start_game"       # "Start game": ends the gate and lets the normal start flow run


PANEL_ROTATION = (0, 0, 270)     # confirmed live: with 90 it looked upside down from the White seat
PANEL_SCALE = (6, 6, 6)          # without scale the panel looks tiny on the 0.4 object
PANEL_WIDTH = 760
STATUS_ID = "status"
BUTTON_STYLE = 'textColor="#FFFFFF" colors="#2D6A9F|#3C86C8|#1F4C75|#555555" '

ROW_HEIGHT = 48
DEFAULT_ATTACKERS = ("hellboy", "lobster")      # without heroes at hand: those of Medusa vs Hellboy

CHOICE_BUTTONS = tuple(f"btn_choice_{i}" for i in range(1, 7))     # hidden except with an effect choice pending

# id of each fixed button -> (panel function, event)
FIXED_BUTTONS = {"btn_maneuver": "onManeuver", "btn_scheme": "onScheme", "btn_reveal": "onReveal",
                 "btn_cancel": "onCancel", "btn_end": "onEndAction", "btn_undo": "onUndoGameOver",
                 "btn_value": "onValueSend", "btn_mulligan": "onMulligan", "btn_ready": "onReady",
                 "btn_restart": "onRestart", "btn_boost": "onBoost", "btn_noboost": "onNoBoost", "btn_mboost": "onManeuverBoost",
                 "btn_look": "onLook", **dict.fromkeys(CHOICE_BUTTONS, "onChoice")}
GATE_BUTTONS = ("btn_clean", "btn_prep", "btn_start")     # born hidden; only the pre-game gate shows them (never part of a game's panel states)
SETUP_ONLY = ("btn_mulligan", "btn_ready")
GAME_ONLY = ("btn_restart",)


def __getattr__(name: str):
    """`END_ACTION_LABEL`: the caption of the end-of-action button in the current language."""
    if name == "END_ACTION_LABEL":
        return _tag_text("panel.end_action")
    raise AttributeError(name)


def _triple(v, name: str) -> str:
    if not isinstance(v, (tuple, list)) or len(v) != 3 or any(isinstance(x, bool) or not isinstance(x, (int, float))
                                                                for x in v):
        raise TypeError(f"{name}: three numbers expected, got {v!r}")
    if not all(abs(float(x)) < 1e6 and float(x) == float(x) for x in v):
        raise ValueError(f"{name}: number out of range")
    return " ".join(f"{float(x):g}" for x in v)


def element_ids(target_ids, attacker_ids=DEFAULT_ATTACKERS, fighter_ids=None) -> list[str]:
    """Id of every button on the panel (those turned off on press and re-enabled by the bot according to the state)."""
    fighters = tuple(dict.fromkeys(fighter_ids if fighter_ids is not None else (*target_ids, *attacker_ids)))
    return [*FIXED_BUTTONS, *(f"att_{a}" for a in attacker_ids), *target_ids,
            *(f"{p}_{f}" for f in fighters for p in ("hpm", "hpp", "rm"))]


def handler_script(snapshot: str | None = None, ids: tuple[str, ...] | list[str] = (),
                   human_seat: str | None = None) -> str:
    """Script of the panel object: each button notifies the bot with sendExternalMessage (it arrives as messageID 4).

    Instant local feedback: before sending it sets "Processing..." and turns the buttons off (no round trip). With
    `snapshot` (the fragment of `lua.snapshot_lua`) the message carries the table snapshot taken at the click.
    `busy` is global on purpose: the composite (`lua.composite`, after waiting for the pieces) or `lua.set_panel` release it
    with setVar; if the bot does not answer within 20 s it is re-enabled, but only the timer of the LAST click can do it
    (`clickSeq`): an old one does not unblock a later click that is still being processed. `wseq` is the last table
    write the bot noted on the panel (it seals it into the click's snapshot).

    `onPlayerPing` (a universal TTS event, valid in an object's script) recognizes the ping of seat `human_seat`
    on a card of the row of the bot's hand (`lookRow`, which the bot writes with `lua.show_hand_row`): by the object
    pinged if it is in the row and, if TTS does not give it, by the row card closest to the position. Any other ping
    (another seat, another object, no row) is ignored. Without `human_seat` it recognizes none."""
    for i in ids:
        if not re.fullmatch(r"[A-Za-z0-9_]{1,40}", i):
            raise ValueError(f"invalid element id: {i!r}")
    all_ids = "{" + ", ".join(f'"{i}"' for i in ids) + "}"
    if human_seat is not None and not re.fullmatch(r"[A-Za-z]{3,10}", human_seat):
        raise ValueError(f"invalid seat: {human_seat!r}")
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
  UI.setValue("{STATUS_ID}", "{lua_text("panel.processing")}")
  setAll(false)
{take}  sendExternalMessage(tbl)
  Wait.time(function()
    if busy and mine == clickSeq then
      busy = false
      setAll(true)
      UI.setValue("{STATUS_ID}", "{lua_text("panel.no_reply")}")
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
function onManeuverBoost() send({{event = "maneuver_boost"}}) end
function onLook() send({{event = "look_hand"}}) end
function onClean() send({{event = "clean_table"}}) end
function onPrepare() send({{event = "prepare_table"}}) end
function onStart() send({{event = "start_game"}}) end
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
    """Row of choice buttons: they are born hidden; the bot shows them (with their text) only while there is a choice."""
    return _row(*(_button(i, "onChoice", t("panel.option"), 16).replace("<Button ", '<Button active="false" ') for i in ids))


def _text(text: str, size: int = 18, extra: str = "") -> str:
    return f'<Text color="#FFFFFF" fontSize="{size}" {extra}>{text}</Text>'.replace(" >", ">")


# the GAME column (title, 5 button rows and the value field) must fit even with two lone heroes:
# with only the LIFE rows sizing it, Liz vs Bullseye squashed Mulligan and Ready into blank slivers (7/11)
# 348 is the height the default table (Medusa and 3 harpies vs Hellboy and the lobster) always had and rendered
# well; a taller panel would cover the HELLBOY label of the real table
GAME_COLUMN_MIN = 60 + 48 * 6


def side_height(fighter_count: int) -> int:
    """Height of the LIFE / GAME row: the LIFE rows of `fighter_count` fighters, never less than the GAME column."""
    return max(60 + 48 * fighter_count, GAME_COLUMN_MIN)


def panel_height(fighter_count: int) -> int:
    """Height of the panel in UI pixels (with the LIFE side column of `fighter_count` fighters)."""
    return 40 + 40 + 7 * (ROW_HEIGHT + 8) + 40 + side_height(fighter_count) + 40


def panel_xml(target_ids: list[str], attacker_ids: tuple[str, ...] = DEFAULT_ATTACKERS,
              fighter_ids: tuple[str, ...] | None = None, rotation=PANEL_ROTATION, scale=PANEL_SCALE,
              names: dict[str, str] | None = None) -> str:
    """`fighter_ids` are all the fighters of both sides (HP and Remove rows); by default, the two groups."""
    fighters = tuple(dict.fromkeys(fighter_ids if fighter_ids is not None else (*target_ids, *attacker_ids)))
    for ident in (*target_ids, *attacker_ids, *fighters):
        if not re.fullmatch(r"[A-Za-z0-9_]+", ident):
            raise ValueError(f"invalid target id: {ident!r}")
    rot, sc = _triple(rotation, "panel_rotation"), _triple(scale, "panel_scale")
    names = names or {}
    if not isinstance(names, dict) or not all(isinstance(v, str) and _LABEL.fullmatch(v) for v in names.values()):
        raise ValueError("invalid button names (letters, digits, space and . _ - ')")

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
                   _button("btn_mboost", "onManeuverBoost", t("panel.maneuver_boost")).replace("<Button ", '<Button active="false" '),
                   _button("btn_look", "onLook", t("panel.look")).replace("<Button ", '<Button active="false" '))
            + _choice_row(CHOICE_BUTTONS[:3]) + _choice_row(CHOICE_BUTTONS[3:])
            + '</VerticalLayout>')
    hp_rows = "".join(
        _row(f'<Text color="#FFFFFF" fontSize="16" preferredWidth="150">{label(f)}</Text>',
             _button(f"hpm_{f}", "onHp", "-1", 16), _button(f"hpp_{f}", "onHp", "+1", 16),
             _button(f"rm_{f}", "onRemove", t("panel.remove"), 16), height=40) for f in fighters)
    side_h = side_height(len(fighters))
    life = (f'<VerticalLayout {section} preferredWidth="470" preferredHeight="{side_h}">'
            + _text(t("panel.life"), 16, 'fontStyle="Bold"') + hp_rows + '</VerticalLayout>')
    game = (f'<VerticalLayout {section} preferredWidth="260" preferredHeight="{side_h}">'
            + _text(t("panel.game"), 16, 'fontStyle="Bold"')
            + _row(_button("btn_mulligan", "onMulligan", t("panel.mulligan")),   # the gate buttons share the rows of the setup
                   _button("btn_prep", "onPrepare", t("panel.prep"), 16).replace("<Button ", '<Button active="false" '))
            + _row(_button("btn_ready", "onReady", t("panel.ready")),            # ones: the gate precedes the setup, never overlaps it
                   _button("btn_start", "onStart", t("panel.start"), 16).replace("<Button ", '<Button active="false" '))
            + _row(_button("btn_restart", "onRestart", t("panel.restart")),
                   _button("btn_clean", "onClean", t("panel.clean"), 16).replace("<Button ", '<Button active="false" '))
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
