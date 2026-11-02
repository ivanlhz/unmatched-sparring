"""The human's cards on the interpreter, at the real table (E2).

The human's box hero is in `fx.dsl_heroes` like the bot's, so their combat cards resolve inside the `CombatFlow`
the session already drives (E1) and their schemes run here (`play_scheme`), with the same split of work:

  * the engine does what it can see and own: damage and heals (the dials follow), statuses and rules on the bot
    (Cold Iron, Counterhex, Burning Barrier, the Pacts), values and cancellations, the bot's discards the bot
    chooses, the bot's hand and deck moves (projected through `session_bot_effects`), the bot's pieces the human
    relocates (chosen on the panel buttons, projected like any bot move);
  * the bot deals the human's draws from their deck to their hand (`Session._deal_owed_draws`);
  * the human does by hand what only they hold: picks out of their own hand, the order of their deck, where their
    own miniatures go (`effects/table.py` leaves a note per op; the chat says it); the table sync reconciles.

Buttons appear only while a card asks (Posthumous Power, Pancakes!, FATEFUL BARGAINS when the bot's effect damage
reaches Baba Yaga with Koschei beside her); nothing is greyed, the rest of the panel waits (E1).

`human_chooser` is the hook E3 (hidden-information cards, `session_hidden.py`) wraps to answer or stage the picks
the human makes over the bot's revealed hand."""
from __future__ import annotations

from .cards import Card
from .effects import narrate, ongoing, table
from .effects.choose import PanelChooser
from .effects.model import EffectError, load_effects, walk_ops
from .effects.run import Ctx, EffectRun
from .effects.select import condition
from .i18n import has, t
from .tts.lua import ChatKind
from . import session_bot_effects as bot_effects
from . import session_translators as translators

STEP = "step"       # run.flags key: what a human scheme's step needs at its end (JSON-safe, survives a pause)


def human_chooser(session) -> PanelChooser:
    """Who answers the human's effect decisions: the panel buttons."""
    return PanelChooser()


# ---------------------------------------------------------------- schemes

def is_ongoing(game, player: int, card: Card) -> bool:
    try:
        return load_effects(game.players[player].hero.slug).card(card.title).ongoing is not None
    except EffectError:
        return False


def recognize_scheme(session, base: set) -> list[Card]:
    """The scheme(s) the human just played: an ONGOING one lies face up on their ONGOING spot (Ivan, 29/10), any
    other face up on their discard pile; a non-ONGOING scheme left on the spot is ignored and the human is told. Without `human_ongoing_spot` in the configuration the pile is read for
    both (said once)."""
    g, human = session.game, session.human
    st = g.players[human]
    found = [c for c in st.discard if c.card_id not in base and c.is_scheme]
    if session.cfg.human_ongoing_spot is None:
        if any(is_ongoing(g, human, c) for c in found):
            session._warn("ongoing", "spot", t("fx.no_spot"))
        return found
    by_id = {c.card_id: c for c in st.full_set}
    in_play = g.fx.ongoing_card_id(human)
    on_spot = [by_id[r["id"]] for r in session._rd_ongoing("human")
               if isinstance(r, dict) and r.get("id") in by_id and r["id"] != in_play and by_id[r["id"]].is_scheme]
    spot = [c for c in on_spot if is_ongoing(g, human, c)]        # only ONGOING cards count there (Ivan, 29/10)
    for c in on_spot:
        if c not in spot:
            session._warn("ongoing", f"not-ongoing-{c.card_id}", t("fx.not_ongoing", title=c.title))
    for c in spot:                                # it left your hand for the spot: the engine's copy follows
        for zone in (st.deck, st.discard):
            if c in zone:
                zone.remove(c)
        if c not in st.hand:
            st.hand.append(c)
    return spot + [c for c in found if c not in spot]


def play_scheme(session, card: Card) -> None:
    """The scheme the human put face up in their discard: its ops run now (the action was spent at the button). A
    decision of theirs stops the run on the panel (`ongoing.resolve_scheme` parks it, `Session._choice` finishes it);
    otherwise the step closes here."""
    g = session.game
    step = {"bot": session._snapshot_bot(), "fx": bot_effects.snapshot(session), "alive": session._alive_map(),
            "narrate": narrate.snapshot(g), "seen": len(g.players[session.bot].discard),
            "in_play": g.fx.ongoing_card_id(session.human)}
    run, pending = ongoing.resolve_scheme(g, session.human, g.hero(session.human), card, session._choosers())
    run.flags[STEP] = step
    if pending is not None:
        session.say(t("fx.detected", title=card.title), ChatKind.SCHEME)
        session._show_choice(run.awaiting)
        return
    finish(session, run)


def maneuver_boost(session, card: Card) -> None:
    """The card the human spent as a BOOST in their Maneuver (it lies in their discard pile): its `boost` moment runs now,
    with the same step as a scheme (what the engine applied, what they do by hand, the bot's side projected, the dials)."""
    g = session.game
    ops = load_effects(g.players[session.human].hero.slug).moment_ops(card.title, "boost")
    step = {"bot": session._snapshot_bot(), "fx": bot_effects.snapshot(session), "alive": session._alive_map(),
            "narrate": narrate.snapshot(g), "seen": len(g.players[session.bot].discard),
            "in_play": g.fx.ongoing_card_id(session.human)}
    run = EffectRun(ops, Ctx(owner=session.human, this_fid=g.hero(session.human).fid, card_id=card.card_id, moment="boost"),
                    label="boost")
    run.flags[STEP] = step
    g.fx.emit("card_boosted", session.human, card)
    pending = run.run(g, session._choosers())
    if pending is not None:
        g.fx.parked.append(run)
        session.say(t("fx.detected", title=card.title), ChatKind.SCHEME)
        session._show_choice(run.awaiting)
        return
    finish(session, run)
    session._deal_owed_draws(card.title)


def finish(session, run: EffectRun) -> None:
    """The human's scheme is done (now, or after their answer): says what the engine applied and what they do on the
    table, projects the bot's side of it and the dials."""
    g, human = session.game, session.human
    step = run.flags.pop(STEP, None)
    if step is None:
        return
    session.say(t("fx.applied", line=narrate.describe(g, step['narrate'], run)), ChatKind.SCHEME)
    if not g.fx.can_gain_actions(human) and any(o["op"] == "gain_action" for o in walk_ops(run.ops)):
        session.say(t("fx.no_actions", title=_card_title(g, run), left=g.actions_left), ChatKind.WARNING)
    now = g.fx.ongoing_card_id(human)
    if now == run.ctx.card_id:
        translators.translate(session, {"op": "ongoing", "player": human, "card": now, "replaces": step["in_play"]},
                              translators.Ctx())
    listed = session._discard_list(step["seen"], {}, t("fx.cause_default"))
    if listed:
        session.say(t("fx.bot_discards", listed=listed))
    session._mark_dirty({fid: (v[0], v[1]) for fid, v in step["bot"].items()})
    fin_fx = session._project_effects(step["fx"], frozenset(), cause=t("fx.cause_of", card=_card_title(g, run)))
    session._announce_human_falls(step["alive"])
    fin_table = session._try_flush_stage()
    fin_dials = session._write_dials(defer=True)
    fin_table()
    fin_fx()
    fin_dials()
    if g.winner is not None:
        session.say(t("fx.game_over", winner=g.winner))


def _card_title(game, run: EffectRun) -> str:
    card = None if run.ctx.card_id is None else game.card_of(run.ctx.card_id, run.ctx.owner)
    return card.title if card else t("fx.the_card")


# ---------------------------------------------------------------- combat

def stage_bottom_card(session, card: Card) -> None:
    """Flame Lash: the human put the real bottom card of their deck in the discard; the engine's copy of the deck
    is placeholders, so that card goes to the bottom of the virtual deck for the card's own `discard` op to take."""
    st = session.game.players[session.human]
    if card in st.hand:                           # a placeholder of the hand stands for it: the hand did not shrink
        st.hand.remove(card)
        spare = next((c for c in st.deck if c.card_id not in session.game.players[session.bot].known.seen), None)
        if spare is not None:
            st.deck.remove(spare)
            st.hand.append(spare)
    elif card in st.discard:
        st.discard.remove(card)
    elif card in st.deck:
        st.deck.remove(card)
    st.deck.append(card)


def human_ran(flow) -> bool:
    """A run of the human's own card happened in this combat (its lines are in `result.human_effects`)."""
    return any(r.ctx.owner != flow.game.bot_player for r in flow.runs.values())


# ---------------------------------------------------------------- the panel

def decline(session, paused) -> bool:
    """"Cancel" while a card asks: the answer that does nothing when the request allows one ("No" to an optional,
    nothing picked when none is required). A forced pick cannot be cancelled: the card is played."""
    kind, holder, run = paused
    req = run.awaiting
    if req.kind == "optional":
        answer = [False]
    elif req.min == 0:
        answer = []
    else:
        session.say(t("fx.mandatory"), ChatKind.WARNING)
        return False
    session.say(t("fx.cancelled"), ChatKind.NEUTRAL)
    session._answer_choice(paused, answer)
    return True


ABILITY_NAME = {"detective_draw": "OCCULT DETECTIVE"}      # trigger id -> the ability as the chat names it


class _AbilityText:
    """trigger id -> the ability's prompt in the current language, with `{hero}` still to fill (a mapping view over
    the catalog tags `fx.ability.<id>`, so callers that `.get` a template keep working)."""

    def get(self, trigger_id: str, default=None):
        tag = f"fx.ability.{trigger_id}"
        return t(tag, hero="{hero}") if has(tag) else default


ABILITY_TEXT = _AbilityText()


def start_of_turn_ability(session) -> str | None:
    """What the human's start-of-turn ability asks of them right now, or None: the triggers the engine leaves to the
    table (`table.start_of_turn_is_physical`) whose condition holds (Ivan, 29/10: the panel waits for it)."""
    g, human = session.game, session.human
    hero = g.hero(human)
    try:
        triggers = load_effects(g.players[human].hero.slug).triggers
    except EffectError:
        return None
    texts = []
    for trig in triggers:
        if not table.start_of_turn_is_physical(g, human, trig):
            continue
        run = EffectRun(trig["ops"], Ctx(owner=human, this_fid=hero.fid), label=trig["id"])
        if "condition" in trig and not condition(g, run, trig["condition"]):
            continue
        texts.append(ABILITY_TEXT.get(trig["id"], trig["id"]).format(hero=session._name(hero)))
    return " ".join(texts) if texts else None
