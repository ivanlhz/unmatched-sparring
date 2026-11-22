"""Sherlock Holmes' plugins (docs/heroes/sherlock-holmes.md): `holmes:elementary` and `holmes:confirm_suspicion`.

Elementary: "Play this card face up. Predict the printed attack value of the opponent's card. DURING COMBAT: if you predicted the
correct value, cancel all effects on your opponent's card and ignore its attack value." Abe's Perfect Shot mirrored: the defender
predicts the attacker's printed value at the moment the card is played, before the attacker's card is revealed. The plugin asks its
owner once (an `effect` request with `op: predict`, `elementary: true`) and keeps the number in the run's `flags["prediction"]`; the
live session answers for the human with the buttons it showed at Reveal and for the bot with what it announced when it placed the
card (`session_hidden.PredictionChooser`). The test `predicted_correctly` compares it with the printed value of the rival's card.

Confirm Suspicion: the owner names a value; the rival must choose and discard a card matching it (a card with that printed value; a
versatile card matches by its value, a scheme never does); their hero takes damage equal to the BOOST of the discarded card; with no
matching card they reveal their hand instead (the DSL's `look_hand`). A bot rival (or a simulation) knows its hand, so the engine
lists the matching cards and the rival picks one. The table player's hand is placeholders: they lay a matching card on their discard
pile (or none) and the bot reads it (`pile_mode: reveal`, `confirm`); a human who says "none" has their hand read, and a matching card
found there must be discarded (`phase: recheck`)."""
from __future__ import annotations

from . import table
from .ops_core import OPS, plugin, plugin_condition
from .plugins_strange import _flow, _unplayed

DEDUCE = "holmes:deduce_strategy"
ELEMENTARY = "holmes:elementary"
CONFIRM = "holmes:confirm_suspicion"
VALUES = list(range(8))                 # any printed value can be named: the numbers of `ops_combat.PREDICT_VALUES` (Ivan, 28/10, for every prediction)


def matches(card, named: int) -> bool:
    """A card "matching that attack or defense value": its printed value is the named number. A scheme has no value and never matches;
    a card with no printed value (Stones in the Belly) counts 0."""
    return card.type != "scheme" and (card.value or 0) == named


# ---------------------------------------------------------------- Deduce Strategy

@plugin(DEDUCE)
def _deduce(run, game, spec):
    """"You may change the printed value of the opponent's card to its BOOST value (no BOOST value: 0)". The owner is asked with both numbers in the
    request (`rival_value`); the change is the engine's `set_value` of a printed value, so bonuses and a BOOST played on top still add."""
    flow = _flow(run, DEDUCE)
    attacking = run.ctx.played_as == "attack"
    card = flow.def_card if attacking else flow.atk_card
    if card is None:
        return
    boost = card.boost or 0
    if not run.ask(game, "optional", run.ctx.owner, [True, False], 1, 1, "do it?", rival_value={"now": card.value or 0, "to": boost})[0]:
        return
    OPS["set_value"](run, game, {"op": "set_value", "card": "opponent_card", "amount": boost})


# ---------------------------------------------------------------- Elementary

@plugin(ELEMENTARY)
def _elementary(run, game, spec):
    if "prediction" in run.flags:
        return
    from .ops_combat import PREDICT_OP          # not at import time: ops_combat imports ops_core, which imports this module
    from . import modifiers
    flow = getattr(run, "flow", None)
    known = None                    # an attack card that is already face up (the second part of a double attack, a card played face up) has a public printed value
    if flow is not None and flow.atk_card is not None and (flow.second is not None or modifiers.plays_face_up(flow.atk_card, game, flow.att, flow.tgt)):
        known = flow.atk_card.value or 0
    answer = run.ask(game, "effect", run.ctx.owner, VALUES, 1, 1, "predict the printed attack value of the opponent's card",
                     op=PREDICT_OP, elementary=True, attacker=None if flow is None else flow.att.fid, known_value=known)[0]
    run.flags["prediction"], run.flags["elementary"] = answer, True


@plugin_condition(ELEMENTARY)
def _elementary_hit(game, run, key: str) -> bool:
    """`predicted_correctly`: the number given at play time equals the printed value of the attacker's card (no printed value: 0)."""
    from .model import EffectError
    if key != "predicted_correctly":
        raise EffectError(f"{ELEMENTARY}: unknown key {key!r}")
    flow = getattr(run, "flow", None)
    if flow is None or flow.atk_card is None:
        return False
    first = flow.runs.get("immediately:def")
    prediction = None if first is None else first.flags.get("prediction")
    return prediction is not None and (flow.atk_card.value or 0) == prediction


# ---------------------------------------------------------------- Confirm Suspicion

@plugin(CONFIRM)
def _confirm(run, game, spec):
    owner, rival = run.ctx.owner, 1 - run.ctx.owner
    if spec.get("args", {}).get("phase") == "recheck":
        _recheck(run, game, owner, rival)
        return
    named = run.flags["named"] = run.ask(game, "amount", owner, VALUES, 1, 1, "name a value", confirm=True, name_value=True)[0]      # asked on every rerun: the answers are keyed by the order of the asks
    if not game.fx.can_force_discard(rival, owner):      # a rule that forbids forced discards: nothing is discarded, nothing is revealed
        run.flags["blocked"] = True
        return
    card = _rival_discards(run, game, rival, named)
    if card is not None:
        _discarded(run, game, rival, card)


def _rival_discards(run, game, rival: int, named: int):
    """The card the rival gives up, or None when they have no matching card (or the table player lays none)."""
    st = game.players[rival]
    if not table.physical(game, rival):
        options = [c.card_id for c in st.hand if matches(c, named)]
        if not options:
            return None
        got = run.ask(game, "cards", rival, options, 1, 1, f"discard a card of value {named}", zone="hand", purpose="discard",
                      of=rival, confirm=named)
        card = {c.card_id: c for c in st.hand}[got[0]]
        game.discard_card(rival, card)
        return card
    got = run.ask(game, "cards", rival, _unplayed(st), 0, 1, f"put a card of value {named} in your discard pile", zone="discard",
                  purpose="bonus", of=rival, table_discard=True, pile_mode="reveal", confirm=named)
    if not got:
        return None
    card = {c.card_id: c for c in st.full_set}[got[0]]
    table.make_known(game, rival, card)
    game.discard_card(rival, card)
    return card


def _discarded(run, game, rival: int, card) -> None:
    run.flags["discarded"] = True
    run.bind("cards", "confirmed", [card.card_id], owners=[rival])


def _recheck(run, game, owner: int, rival: int) -> None:
    """The table player said they hold nothing of the named value and their hand was read: a matching card in it is a card they
    must discard after all (the bot saw the whole hand through `look_hand`)."""
    named = run.flags.get("named")
    if named is None or not table.physical(game, rival):
        return
    seen = [c for c in game.players[owner].known.cards(game.players[rival]) if matches(c, named)]
    if not seen:
        return
    st = game.players[rival]
    got = run.ask(game, "cards", rival, [c.card_id for c in seen], 1, 1, f"you do hold a card of value {named}: discard it", zone="discard",
                  purpose="bonus", of=rival, table_discard=True, pile_mode="reveal", confirm=named, recheck=True)
    card = {c.card_id: c for c in st.full_set}[got[0]]
    table.make_known(game, rival, card)
    game.discard_card(rival, card)
    _discarded(run, game, rival, card)


@plugin_condition(CONFIRM)
def _confirm_test(game, run, key: str) -> bool:
    """`discarded`: a card was discarded and its BOOST is the damage; `reveal`: no card was discarded and the rival may be made to show
    their hand (a rule against forced discards leaves both false)."""
    from .model import EffectError
    if key == "discarded":
        return bool(run.flags.get("discarded"))
    if key == "reveal":
        return not run.flags.get("discarded") and not run.flags.get("blocked")
    raise EffectError(f"{CONFIRM}: unknown key {key!r}")
