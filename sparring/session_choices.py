"""Effect choices and rule restrictions at the panel (phase E1). Pure helpers: the Session owns the state.

Choice buttons: `btn_choice_1..6` exist only while the human has a pending effect choice (`PendingChoice` of kind
"effect" inside a `Session.effect_run`); the rest of the time they are HIDDEN, never greyed. `layout` turns the
ChoiceRequest into the six slots (options, a "More" page button when there are too many, a "Confirm" button for
multi-pick answers) and `ChoiceUI` keeps the page and the picks made so far. Labels and prompts are Spanish (they are
shown to the human); card texts keep the card data's own wording.

Restrictions: rules that forbid a human action (Pact Of Freedom, Cold Iron And Holy Water, a pinned fighter) are asked
to the engine each time the panel is drawn (`fx_query`: `game.fx.<name>(player)`, read with `getattr` and a permissive
default so a missing query allows the action). A forbidden button is hidden, the chat says why once, and the session
refuses the action if it arrives anyway (an attack), skips its blocked part (the Maneuver draw, a scheme's actions) or
keeps the engine's position (a fighter that cannot leave its space).

The look at the bot's hand (`btn_look`) is granted by a card, never by default: `grants_look` reads the card's DSL
effects and says whether any moment has a `look_hand` op on the opponent.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Callable

from .effects.choose import ChoiceRequest
from .effects.model import EffectError, load_effects, walk_ops

MAX_CHOICE_BUTTONS = 6
CHOICE_IDS = tuple(f"btn_choice_{i}" for i in range(1, MAX_CHOICE_BUTTONS + 1))
LABEL_MAX = 40
_UNSAFE = re.compile(r"[^A-Za-z0-9 _.\-!:',]")

NO_DRAW_REASON = "un efecto en juego te impide robar cartas, asi que no robas"

PROMPTS = {"fighter": "Elige un luchador", "space": "Elige una casilla", "cards": "Elige carta(s)",
           "effect": "Elige un efecto", "optional": "Quieres hacerlo?", "order": "Elige el orden",
           "amount": "Elige una cantidad"}


def safe_label(text: str, fallback: str = "Opcion", limit: int = LABEL_MAX) -> str:
    """ASCII text the panel accepts as a button label (accents dropped, odd characters removed, `limit` characters)."""
    plain = unicodedata.normalize("NFKD", str(text)).encode("ascii", "ignore").decode("ascii")
    plain = " ".join(_UNSAFE.sub(" ", plain).split())
    return plain[:limit].rstrip() or fallback


@dataclass
class Slot:
    label: str
    action: str                 # "pick" | "page" | "confirm"
    value: object = None
    enabled: bool = True


@dataclass
class ChoiceUI:
    """What the human has done on the current request: the page shown and the options toggled so far."""
    key: str = ""
    page: int = 0
    selected: list = field(default_factory=list)

    def sync(self, req: ChoiceRequest) -> None:
        if req.key != self.key:
            self.key, self.page, self.selected = req.key, 0, []


def card_titles(game, ids) -> str:
    titles = []
    for i in ids:
        titles.append(next((c.title for p in game.players for c in p.full_set if c.card_id == i), f"Carta {i}"))
    return ", ".join(titles)


def option_label(game, req: ChoiceRequest, option) -> str:
    kind = req.kind
    if kind == "effect":
        if req.extra.get("op") == "predict":                 # Perfect Shot: a printed value, or face down
            return "Boca abajo" if option == req.extra.get("face_down") else f"Valor {option}"
        labels = req.extra.get("labels") or []
        return safe_label(labels[option] if isinstance(option, int) and 0 <= option < len(labels) else option)
    if kind == "optional":
        # what each answer means, when the op said so (Remove A Painful Memory: discard it, or take 2)
        if option is True and req.extra.get("discards"):
            return safe_label("Descartar " + card_titles(game, req.extra["discards"]))
        if option is False and "else_damage" in req.extra:
            return safe_label(f"Coger {req.extra['else_damage']}")
        return "Si" if option is True else "No"
    if kind == "amount":
        return str(option)
    if kind == "space":
        return f"Casilla {option}"
    if kind in ("cards", "order"):
        owner = req.extra.get("of", req.player)
        for p in ([game.players[owner]] if isinstance(owner, int) else []) + list(game.players):
            for c in p.full_set:
                if c.card_id == option:
                    return safe_label(c.title)
        return safe_label(f"Carta {option}")
    fighter = game.fighters.get(option) if isinstance(option, str) else None
    return safe_label(fighter.name if fighter is not None else option)


def options_text(game, req: ChoiceRequest, limit: int = 6) -> str:
    """'1: Si, 2: No': the options in button order for the chat, so the human knows each button even if its caption
    did not change on the table."""
    opts = list(req.options)
    shown = [f"{i}: {option_label(game, req, o)}" for i, o in enumerate(opts[:limit], 1)]
    return ", ".join(shown) + (", ..." if len(opts) > limit else "")


def card_text_hint(game, req: ChoiceRequest) -> str:
    """' Carta: <printed text>' for a plain yes/no (Pyrotechnics: the question alone did not say what the card does), else ''."""
    if req.kind != "optional" or req.extra.get("discards") or "to" in req.extra:
        return ""
    card = next((c for p in game.players for c in p.full_set if c.card_id == req.card_id), None)
    text = getattr(card, "text", "") if card is not None else ""
    return f" Carta: {text}" if text else ""


def prompt_text(game, req: ChoiceRequest) -> str:
    """Spanish chat line for the request: what is asked and, for the card that asks, its title."""
    base = PROMPTS.get(req.kind, "Elige")
    if req.kind == "effect" and req.extra.get("op") == "predict":
        base = "Predice el valor impreso de la carta rival, o juega boca abajo"
    elif req.kind == "optional" and req.extra.get("discards"):
        base = f"Descartas {card_titles(game, req.extra['discards'])}"
        if "else_damage" in req.extra:
            base += f" o coges {req.extra['else_damage']} de dano"
    elif req.kind == "optional" and "to" in req.extra and "fighter" in req.extra:     # a damage redirection (FATEFUL BARGAINS)
        names = {fid: f.name for fid, f in game.fighters.items()}
        base = (f"{names.get(req.extra['to'], req.extra['to'])} recibe el dano ({req.extra.get('amount', '?')}) en lugar de "
                f"{names.get(req.extra['fighter'], req.extra['fighter'])}?")
    title = None
    for p in game.players:
        for c in p.full_set:
            if c.card_id == req.card_id:
                title = c.title
    if req.kind == "optional" and base == PROMPTS["optional"] and title:
        return f"Usas el efecto de {title}?"              # the question names the card: "Quieres hacerlo?" did not
    if req.max > 1 or req.min != 1:
        lo, hi = req.min, req.max
        base += f" ({lo} a {hi})" if lo != hi else f" ({hi})"
    return f"{base}" + (f" - {title}" if title else "")


def layout(game, req: ChoiceRequest, ui: ChoiceUI) -> list[Slot]:
    """The slots of `btn_choice_1..6` for `req`, given the page and picks held in `ui`."""
    ui.sync(req)
    options = list(req.options)
    single = req.min == 1 and req.max == 1
    n = len(options)
    reserved = 0 if single else 1                    # the multi-pick answer needs its Confirm button
    room = MAX_CHOICE_BUTTONS - reserved
    paged = n > room
    per_page = room - 1 if paged else room
    pages = max(1, -(-n // per_page))
    ui.page %= pages
    shown = options[ui.page * per_page:(ui.page + 1) * per_page]
    slots = []
    for opt in shown:
        label = option_label(game, req, opt)
        if opt in ui.selected:
            label = safe_label(f"{ui.selected.index(opt) + 1}. {label}")
        slots.append(Slot(label, "pick", opt))
    if paged:
        slots.append(Slot(f"Mas {ui.page + 1} de {pages}", "page"))
    if not single:
        ready = req.min <= len(ui.selected) <= req.max
        label = "Confirmar" if ui.selected else ("Ninguna" if req.min == 0 else "Confirmar")
        slots.append(Slot(label, "confirm", None, ready))
    return slots


def panel_choice_view(game, req: ChoiceRequest | None, ui: ChoiceUI) -> tuple[dict, dict]:
    """({button id: (interactable, active)}, {button id: label}) for the six choice buttons. Without a request every
    button is hidden and no label is sent."""
    if req is None:
        return {i: (False, False) for i in CHOICE_IDS}, {}
    slots = layout(game, req, ui)
    states, labels = {}, {}
    for ident, slot in zip(CHOICE_IDS, slots):
        states[ident], labels[ident] = (slot.enabled, True), slot.label
    for ident in CHOICE_IDS[len(slots):]:
        states[ident] = (False, False)
    return states, labels


def press(game, req: ChoiceRequest, ui: ChoiceUI, index) -> tuple[str, object]:
    """What a click on `btn_choice_<index>` does: ("answer", values) | ("update", None) | ("error", message)."""
    if isinstance(index, bool) or not isinstance(index, int) or not 1 <= index <= MAX_CHOICE_BUTTONS:
        return "error", f"Boton de eleccion no valido: {index!r}."
    slots = layout(game, req, ui)
    if index > len(slots):
        return "error", "Ese boton no corresponde a ninguna opcion."
    slot = slots[index - 1]
    if slot.action == "page":
        ui.page += 1
        return "update", None
    if slot.action == "confirm":
        if not slot.enabled:
            return "error", f"Elige entre {req.min} y {req.max} opciones y confirma."
        return "answer", list(ui.selected)
    if req.max == 1:                             # one pick answers at once; "Ninguna" (the confirm slot) picks none
        return "answer", [slot.value]
    if slot.value in ui.selected:
        ui.selected.remove(slot.value)
    elif len(ui.selected) >= req.max:
        return "error", f"Solo puedes elegir {req.max}: quita una antes."
    else:
        ui.selected.append(slot.value)
    if req.min == req.max and len(ui.selected) == req.max:
        return "answer", list(ui.selected)
    return "update", None


# ---------------------------------------------------------------- restrictions

@dataclass(frozen=True)
class Restriction:
    name: str
    allowed: Callable[[object, int], bool]       # (game, player) -> False while the rule forbids it
    reason: str                                  # Spanish chat line
    buttons: Callable[[object], list[str]] = lambda session: []     # session -> ids of the buttons it hides


def fx_query(name: str) -> Callable[[object, int], bool]:
    """`game.fx.<name>(player)`; an engine without that query allows the action."""
    def check(game, player: int) -> bool:
        fn = getattr(game.fx, name, None)
        return True if fn is None else bool(fn(player))
    return check


def _attack_buttons(session) -> list[str]:
    return [f"att_{f.fid}" for f in session.game.own(session.human, alive_only=False)]


def pinned(game, player: int) -> list:
    """The fighters of `player` an effect keeps on their space (their own maneuver cannot move them)."""
    return [f for f in game.own(player) if not game.fx.can_move(f)]


RESTRICTIONS = (
    Restriction("attack", fx_query("may_attack"),
                "Un efecto en juego te impide atacar ahora (por ejemplo, un ataque como primera accion del turno): "
                "los botones de ataque estan ocultos.", _attack_buttons),
    Restriction("draw", fx_query("can_draw"),
                f"Un efecto en juego te impide robar cartas (Cold Iron And Holy Water): la Maniobra solo mueve, {NO_DRAW_REASON}."),
    Restriction("gain_actions", fx_query("can_gain_actions"),
                "Un efecto en juego te impide ganar acciones: los planes que dan acciones no te las dan este turno."),
    Restriction("move", lambda game, player: not pinned(game, player),
                "Un efecto en juego impide que alguna de tus miniaturas deje su casilla: si la mueves, la devuelvo."),
)


def allowed(game, query: str, player: int) -> bool:
    return fx_query(query)(game, player)


def active_restrictions(session) -> list[Restriction]:
    """The restrictions that forbid something to the human right now (only on the human's own turn)."""
    g = session.game
    if g.turn != session.human or g.winner is not None:
        return []
    return [r for r in RESTRICTIONS if not r.allowed(g, session.human)]


# ---------------------------------------------------------------- the look at the bot's hand

def grants_look(game, player: int, card) -> bool:
    """True when `card` (of `player`'s hero) has, in any moment, a `look_hand` op on the opponent's hand: playing it
    is what lets the human see the bot's hand (Confront Any Demon or God, Every Possible Angle...). Conditions
    around the op are not evaluated: the human knows whether they held."""
    try:
        effects = load_effects(game.players[player].hero.slug).card(card.title)
    except EffectError:                          # a hero without effects file (Medusa) or a card it does not list
        return False
    return any(o["op"] == "look_hand" and o.get("player") == "opponent" for o in walk_ops(effects.moments))
