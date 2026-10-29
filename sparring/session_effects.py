"""The human's cards on the interpreter, at the real table (E2).

The human's box hero is in `fx.dsl_heroes` like the bot's, so their combat cards resolve inside the `CombatFlow`
the session already drives (E1) and their schemes run here (`play_scheme`), with the same split of work:

  * the engine does what it can see and own: damage and heals (the dials follow), statuses and rules on the bot
    (Cold Iron, Counterhex, Burning Barrier, the Pacts), values and cancellations, the bot's discards the bot
    chooses, the bot's hand and deck moves (projected through `session_bot_effects`), the bot's pieces the human
    relocates (chosen on the panel buttons, projected like any bot move);
  * the human does by hand what only they hold: picks out of their own hand, the order of their deck, where their
    own miniatures go (`effects/table.py` leaves a note per op; the chat says it); the table sync reconciles.

Buttons appear only while a card asks (Posthumous Power, Pancakes!, FATEFUL BARGAINS when the bot's effect damage
reaches Baba Yaga with Koschei beside her); nothing is greyed, the rest of the panel waits (E1).

`human_chooser` is the hook E3 (hidden-information cards, `session_hidden.py`) wraps to answer or stage the picks
the human makes over the bot's revealed hand."""
from __future__ import annotations

from .cards import Card
from .effects import narrate, ongoing
from .effects.choose import PanelChooser
from .effects.model import walk_ops
from .effects.run import EffectRun
from .tts.lua import ChatKind
from . import session_bot_effects as bot_effects

STEP = "step"       # run.flags key: what a human scheme's step needs at its end (JSON-safe, survives a pause)


def human_chooser(session) -> PanelChooser:
    """Who answers the human's effect decisions: the panel buttons."""
    return PanelChooser()


# ---------------------------------------------------------------- schemes

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
        session.say(f"Detecto {card.title}: la carta te pide una eleccion.", ChatKind.SCHEME)
        session._show_choice(run.awaiting)
        return
    finish(session, run)


def finish(session, run: EffectRun) -> None:
    """The human's scheme is done (now, or after their answer): says what the engine applied and what they do on the
    table, projects the bot's side of it and the dials."""
    g, human = session.game, session.human
    step = run.flags.pop(STEP, None)
    if step is None:
        return
    session.say(f"Aplico {narrate.describe(g, step['narrate'], run)}.", ChatKind.SCHEME)
    if not g.fx.can_gain_actions(human) and any(o["op"] == "gain_action" for o in walk_ops(run.ops)):
        session.say(f"{_card_title(g, run)}: no ganas sus acciones (un efecto en juego lo impide), te quedan "
                    f"{g.actions_left}.", ChatKind.WARNING)
    now = g.fx.ongoing_card_id(human)
    if now == run.ctx.card_id:
        was = step["in_play"]
        by_id = {c.card_id: c for c in g.players[human].full_set}
        replaced = f" y reemplaza a {by_id[was].title} (un solo ONGOING por jugador)" if was is not None and was in by_id else ""
        session.say(f"{by_id[now].title} queda en juego{replaced}: dejala a la vista en tu descarte, la tengo en "
                    "cuenta hasta que caduque.", ChatKind.SCHEME)
    listed = session._discard_list(step["seen"], {}, "efecto")
    if listed:
        session.say(f"El bot descarta {listed}.")
    session._mark_dirty({fid: (v[0], v[1]) for fid, v in step["bot"].items()})
    fin_fx = session._project_effects(step["fx"], frozenset(), cause=f"efecto de {_card_title(g, run)}")
    session._announce_human_falls(step["alive"])
    fin_table = session._try_flush_stage()
    fin_dials = session._write_dials(defer=True)
    fin_table()
    fin_fx()
    fin_dials()
    if g.winner is not None:
        session.say(f"Fin de partida: gana el jugador {g.winner}.")


def _card_title(game, run: EffectRun) -> str:
    card = next((c for p in game.players for c in p.full_set if c.card_id == run.ctx.card_id), None)
    return card.title if card else "la carta"


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
    """"Cancelar" while a card asks: the answer that does nothing when the request allows one ("No" to an optional,
    nothing picked when none is required). A forced pick cannot be cancelled: the card is played."""
    kind, holder, run = paused
    req = run.awaiting
    if req.kind == "optional":
        answer = [False]
    elif req.min == 0:
        answer = []
    else:
        session.say("Esta eleccion es obligatoria (la carta ya esta jugada): elige una de las opciones del panel.",
                    ChatKind.WARNING)
        return False
    session.say("Eleccion cancelada: se resuelve sin hacer nada.", ChatKind.NEUTRAL)
    session._answer_choice(paused, answer)
    return True


def start_of_turn_text(session) -> str | None:
    """The human's start-of-turn ability the engine leaves to the table (effects/table.py): Wildfire's bottom card."""
    g = session.game
    if g.hero_def(session.human).slug != "liz-sherman":
        return None
    liz = session._name(g.hero(session.human))
    return (f"WILDFIRE: descarta la carta del fondo de tu mazo. Si es ardiente, 1 de dano a otro luchador de la zona "
            f"de {liz} (usa -1 sobre el; la ardiente vuelve a tu mano); si no, mueve a {liz} hasta 2 casillas. Hazlo en la mesa.")
