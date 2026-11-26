"""The human Pandora's Box, read and dealt by the bot (Ivan, 24/11/2026; the first reveal by itself, 26/11/2026).

When the engine asks which Misery the human revealed and the table has their Box zone and its reveal zone (`prepare_zone` in
session_pandora.py), the bot does not wait for a click: it takes the TOP card of the real Box (the shuffled order is the randomness), lays it
face up in the next place of the pile beside their deck (`lua.BoxPile`), reads its CardID from the card and answers the engine with that
Misery (`auto`, called when the question is about to be shown: the first Misery of the turn is mandatory, and "reveal another?" answered Yes
asks for the next one the same way). Only when the bot cannot read or move the real card the panel shows three buttons instead of the seven names:

  1. Reveal Misery   the same, by hand: the bot tries again to take the top card of the Box;
  2. I revealed it   the human turned the card over in the reveal zone themselves: the bot reads the zone, and the one Misery there that the
                     engine has not counted yet is the answer (what the engine has counted is its own `box_mask`, so nothing is stored and a
                     resumed game reads the same);
  3. Pick on panel   today's question with the names (also what happens when the bot saw nothing, saw several new cards, or could not read).

HOPE ("look at the top card of the Box before you reveal it"): the question "reveal another?" that follows a HOPE gets a third button, Look. The
bot reads the top card of the real Box without moving it (`lua.box_peek_top`, which finds the Box as Reveal does), names it in the chat and tells the engine (`box_top`), so the
question names it and the next Reveal takes that very card. Looking is optional; with no Box to read it says so once and the question is as before.

The chat says which Misery was dealt or read, so a misread is caught and the question still corrects it. The panel mechanics are `session_pile`'s
(a manual request with its own buttons); a table without those zones keeps the panel question as it was."""
from __future__ import annotations

from .effects import plugins_pandora as pandora
from .effects.choose import ChoiceRequest
from .i18n import t
from .session_choices import CHOICE_IDS, panel_text, prompt_text
from .session_pandora import _table_of, pile_of, say_pile
from .session_translators import ERRORS
from .tts import lua
from .tts.lua import ChatKind


def _deck(session):
    table = _table_of(session, session.human)
    return None if table is None else table.box


def _asked(session, req: ChoiceRequest) -> tuple:
    """Which question this is: the run of this turn's Box (a new one every turn, a game or a restart) and the Miseries it has counted so
    far. The request's own key is no use: it is the same every turn."""
    return session.effect_run, _mask(session)


def _mine(session, req: ChoiceRequest | None) -> bool:
    c = session.cfg
    return req is not None and req.player == session.human and bool(c.human_box_zone and c.human_reveal_zone) and _deck(session) is not None


def _is_look(session, req: ChoiceRequest) -> bool:
    """The "reveal another?" after a HOPE whose top card nobody has looked at yet."""
    fx, me = session.game.fx, session.human
    return (req.kind == "optional" and req.extra.get("box") == "open" and fx.counter_value(me, "box_current") == pandora.NAMES.index("Hope") + 1
            and not fx.counter_value(me, "box_top") and session._box_looked != _asked(session, req))


def active(session, req: ChoiceRequest | None) -> bool:
    """The question is one the bot can deal, read or look for on the human's table: "which Misery?", or "reveal another?" after HOPE."""
    if req is None or not _mine(session, req):
        return False
    if req.kind == "effect" and req.extra.get("tag") == "misery":
        return session._box_by_panel != _asked(session, req)
    return _is_look(session, req)


def instruction(session, req: ChoiceRequest) -> str:
    if req.kind == "optional":
        return t("pandora.look_instruction", prompt=prompt_text(session.game, req))
    return t("pandora.manual")


def status(session, req: ChoiceRequest) -> str:
    return panel_text(t("pandora.look_status" if req.kind == "optional" else "pandora.manual_status"))


def view(session, req: ChoiceRequest) -> tuple[dict, dict]:
    states = {ident: (False, False) for ident in CHOICE_IDS}
    labels = {}
    keys = ("choice.yes", "choice.no", "btn.pandora_look") if req.kind == "optional" else ("btn.pandora_reveal", "btn.pandora_read", "btn.pandora_pick")
    for ident, key in zip(CHOICE_IDS, keys):
        states[ident] = (True, True)
        labels[ident] = panel_text(t(key), 40)
    return states, labels


def wants(session, req: ChoiceRequest) -> bool:
    """The question "which Misery?" of the human's Box is about to be shown and the bot has not yet tried to answer it by itself."""
    return (req.kind == "effect" and req.extra.get("tag") == "misery" and active(session, req) and session._box_auto != _asked(session, req))


def auto(session, req: ChoiceRequest) -> bool:
    """The bot takes the top card of the real Box and answers the question, once per question. True when it did (nothing is shown); False
    leaves the three buttons (reveal again, I revealed it, pick on panel) for the human."""
    if not wants(session, req):
        return False
    paused = session._paused()
    if paused is None or paused[2].awaiting is not req:
        return False
    session._box_auto = _asked(session, req)
    if _deal(session, paused, req, fallback=False):
        return True
    return session._box_by_panel == _asked(session, req)       # the answer failed and the panel already showed the names: nothing more to show


def adopt(session) -> bool:
    """A resumed game (or any deal) with "which Misery?" pending: a Misery already lying face up on the pile that the engine has not counted was
    moved by a deal whose answer never got saved; it is the answer, nothing is dealt again. True when it answered."""
    run = session.effect_run
    req = None if run is None else run.awaiting
    if req is None or req.kind != "effect" or req.extra.get("tag") != "misery" or not active(session, req):
        return False
    paused = session._paused()
    new = _new(session, _deck(session))
    if paused is None or not new or len(new) != 1:
        return False
    return _answer(session, paused, req, new[0], "pandora.seen")


def press(session, paused, index) -> None:
    req = paused[2].awaiting
    if isinstance(index, float) and index.is_integer():
        index = int(index)
    if req.kind == "optional":
        if index in (1, 2):
            session._answer_choice(paused, [index == 1])
        elif index == 3:
            _look(session, req)
        else:
            session.say(t("choice.no_such_button"), ChatKind.WARNING)
    elif index == 1:
        _deal(session, paused, req)
    elif index == 2:
        _read(session, paused, req)
    elif index == 3:
        _panel(session, req)
    else:
        session.say(t("choice.no_such_button"), ChatKind.WARNING)


def _index(value) -> int | None:
    """Which Misery (0-6) the table says a card is: its place in the sheet, whatever DeckID TTS gave the deck; None for anything else."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or int(value) != value or not 0 <= value < len(pandora.NAMES):
        return None
    return int(value)


def _mask(session) -> int:
    return pandora.mask_of(session.game, session.human)


def _answer(session, paused, req: ChoiceRequest, idx: int, how: str) -> bool:
    if idx not in req.options:
        session.say(t("pandora.not_expected", misery=t("pandora.misery." + pandora.NAMES[idx].lower())) if 0 <= idx < len(pandora.NAMES)
                    else t("pandora.not_a_misery"), ChatKind.WARNING)
        _panel(session, req)
        return False
    top = pandora.top_known(session.game, session.human)
    if top is not None and top != idx:
        session.say(t("pandora.top_differs", misery=t("pandora.misery." + pandora.NAMES[top].lower())), ChatKind.WARNING)
    session.say(t(how, misery=t("pandora.misery." + pandora.NAMES[idx].lower())), ChatKind.ABILITY)
    session._answer_choice(paused, [idx])
    return True


def _look(session, req: ChoiceRequest) -> None:
    """HOPE's button: reads the top card of the real Box without moving it, names it, and tells the engine."""
    c, deck, me = session.cfg, _deck(session), session.human
    session._box_looked = _asked(session, req)
    try:
        res = session.client.call_lua(lua.box_peek_top(deck.guid, identity=deck.identity,
                                                       spot=c.human_box_spot or (0.0, 0.0), zone=c.human_box_zone))
    except ERRORS + (ValueError, TypeError):
        res = None
    idx = _index(res.get("idx") if isinstance(res, dict) and res.get("found") is True else None)
    if idx is None or idx not in pandora.unrevealed(_mask(session)):
        if not session._box_look_failed_said:
            session._box_look_failed_said = True
            session.say(t("pandora.look_failed"), ChatKind.WARNING)
        session._show_choice(req)
        return
    session.game.fx.set_counter(me, "box_top", idx + 1)
    session.say(t("pandora.looked", misery=t("pandora.misery." + pandora.NAMES[idx].lower())), ChatKind.ABILITY)
    session._persist()
    session._show_choice(req)


def _deal(session, paused, req: ChoiceRequest, fallback: bool = True) -> bool:
    """The top card of the Box, face up in the next place of the pile beside their deck. True when the engine got its answer. When it did not,
    `fallback` sends the human to the panel question with the names (the button); without it (the bot's own try) the three buttons stay."""
    c, deck = session.cfg, _deck(session)
    seen = _new(session, deck)                        # a card the table moved whose answer was lost: it is the one, a second is never drawn over it
    if seen is not None and len(seen) == 1:
        return _answer(session, paused, req, seen[0], "pandora.seen")
    slot = len(pandora.revealed(_mask(session))) + 1
    try:
        res = session.client.call_lua(lua.box_draw_top(deck.guid, slot, identity=deck.identity,
                                                       spot=c.human_box_spot or (0.0, 0.0), zone=c.human_box_zone,
                                                       reveal_zone=c.human_reveal_zone, pile=pile_of(session, human=True)))
    except ERRORS + (ValueError, TypeError):
        res = None
    if isinstance(res, dict):
        say_pile(session, res)
    idx = _index(res.get("idx") if isinstance(res, dict) and res.get("taken") is True else None)
    if idx is None:
        if not isinstance(res, dict):                 # the reply was lost: the card may have left the Box all the same
            new = _new(session, deck)
            if new is not None and len(new) == 1:
                return _answer(session, paused, req, new[0], "pandora.seen")
            session.say(t("pandora.deal_unknown" if fallback else "pandora.auto_unknown"), ChatKind.WARNING)
        else:
            session.say(t("pandora.no_top" if fallback else "pandora.auto_failed"), ChatKind.WARNING)
        if fallback:
            _panel(session, req)
        return False
    return _answer(session, paused, req, idx, "pandora.dealt")


def _new(session, deck) -> list[int] | None:
    """The Miseries face up in the reveal zone that the engine has not counted, by index; None if the zone could not be read."""
    try:
        res = session.client.call_lua(lua.box_read(session.cfg.human_reveal_zone, identity=deck.identity))
    except ERRORS + (ValueError, TypeError):
        return None
    if not isinstance(res, dict) or res.get("zone") is not True or not isinstance(res.get("cards"), list):
        return None
    counted = set(pandora.revealed(_mask(session)))
    ids = {_index(r.get("idx")) for r in res["cards"] if isinstance(r, dict)}
    return sorted(i for i in ids if i is not None and i not in counted)


def _read(session, paused, req: ChoiceRequest) -> None:
    """Button 2: the one new Misery lying face up in the reveal zone is the answer; anything else is the panel question."""
    deck, seen = _deck(session), []

    def looked() -> bool:
        seen[:] = [_new(session, deck)]
        return bool(seen[0])
    session._settle(looked)
    new = seen[0] if seen else None
    if new is None:
        session.say(t("pandora.unreadable"), ChatKind.WARNING)
    elif not new:
        session.say(t("pandora.nothing_new"), ChatKind.WARNING)
    elif len(new) > 1:
        session.say(t("pandora.several_new", n=len(new)), ChatKind.WARNING)
    else:
        _answer(session, paused, req, new[0], "pandora.seen")
        return
    _panel(session, req)


def _panel(session, req: ChoiceRequest) -> None:
    """The panel names the seven Miseries, as before the zones."""
    session._box_by_panel = _asked(session, req)
    session._show_choice(req)
