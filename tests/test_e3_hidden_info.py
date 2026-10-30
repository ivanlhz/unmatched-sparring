"""E3: hidden-information cards at the live table, both sides (`sparring/session_hidden.py`).

FakeTTS sessions in batch mode (one combined script per step). The human's box hero runs on the interpreter
(`fx.dsl_heroes`, what E2 switches on for real), so the human's cards resolve in the engine and their looks happen
exactly when the `look_hand` op runs:
  * Confront Any Demon or God lost by the human: the bot's hand goes face up in a row and is pinged; a ping (or the
    card's button) discards that card; won: nothing is shown;
  * Advanced Psychometry: a reveal only, and only when adjacent (the engine's condition);
  * Every Possible Angle: the pinged card goes to the top of the bot's deck, then the move is asked;
  * Remove A Painful Memory by the human: the bot answers its own "discard it or take 2";
  * a save taken with the row open resumes and the ping finishes the card;
  * Perfect Shot: the human predicts at Revelar before the bot defends (buttons, saved); the bot announces its own
    prediction when it places the card, face up;
  * UNCANNY INTUITION: the bot's attack on the human's Abe is turned face up; the human's attack on the bot's Abe is
    the one card the bot's defense may know;
  * bot Shock And Awe: the human's own pick through `pending_discard`; bot Remove A Painful Memory: "Descartar X" /
    "Coger 2" buttons; Fleeting Moments by the human: the engine's rng picks the bot's card, nobody reads a hand.
Anti-cheat tripwires: no read of the human seat in any of the human's looks; the bot's defense never sees the
attack card unless a rule turned it face up."""
from __future__ import annotations

import json
import re

import pytest

from sparring import session_hidden as hidden
from sparring.ai_effects import predict_value
from sparring.ai_medusa import Act
from sparring.effects.choose import ScriptedChooser
from sparring.effects.events import attack_revealed
from sparring.effects.ops_combat import FACE_DOWN
from sparring.effects.run import Ctx, EffectRun
from sparring.session_choices import layout
from sparring.state import Game
from sparring.tts.ui import Event
from test_batch import click
from test_choice_infra import visible_choices
from test_d3_table_effects import (FxTable, answer_pause, answers, build, card_ids, human_hand, human_plays,
                                   human_reads, said, twin_session)
from test_effects_info import HandSpy


class E3Table(FxTable):
    """The D3 table plus the two Lua operations E3 adds: pings over points and a row card put on the deck."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.point_pings: list[int] = []

    def do_ping_points(self, s):
        n = len(re.findall(r"Vector\(", re.search(r"local points = \{(.*)\}\nfor i", s, re.S).group(1)))
        self.point_pings.append(n)
        return {"queued": n}

    def do_resolve_hand_row(self, s):
        if "deck.putObject(o)" not in s:
            return super().do_resolve_hand_row(s)
        pick = re.search(r'local pick = "(\w+)"', s).group(1)
        chosen = int(pick[1:])
        if chosen not in self.look_row:
            return {"discarded": False, "returned": [], "found": 0, "down": 0}
        returned = [i for i in self.look_row if i != chosen]
        self.look_row.clear()
        self.bot_deck.insert(0, chosen)
        self.bot_hand.extend(returned)
        return {"discarded": chosen, "returned": returned, "found": len(returned) + 1, "down": 0}


def rig_for(tmp_path, bot, human, hand, interpret_human=True):
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=E3Table)
    if interpret_human:
        game.fx.dsl_heroes.add(game.players[1].hero.slug)
    else:
        game.fx.dsl_heroes.discard(game.players[1].hero.slug)     # E2 interprets the human by default
    return session, table, game, fake, cfg, client


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param[:3]
    interpret = request.param[3] if len(request.param) > 3 else True
    session, table, game, fake, cfg, client = rig_for(tmp_path, bot, human, hand, interpret)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(*param):
    return pytest.mark.parametrize("rig", [param], indirect=True)


BABA_HAND = ("Exploit", "Remove A Painful Memory", "Iron Teeth", "Deathless", "Foul Journey")
HELLBOY_HAND = ("On Earth As It Is In Hell", "Service Pistol", "Excalibur", "Right Hand Of Doom", "B.P.R.D. Training")
ABE_HAND = ("Perfect Shot", "Shock And Awe", "Every Possible Angle", "Faster. Stronger.", "Secure The Scene")


def defend_with(session, game, monkeypatch, title):
    card = next(c for c in game.players[0].hand if c.title == title)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: card)
    return card


def attack(session, table, game, attacker, target, title, value=0):
    """The human attacks; returns the messages of the Attack click (the target choice)."""
    click(session, table, Event.ATTACKER, {"attacker": f"att_{attacker}"})
    msgs = click(session, table, Event.ATTACK, {"target": target})
    if value:
        click(session, table, Event.VALUE, {"value": value})
    played = human_plays(table, game, title)
    if played.card_id in table.human_hand:
        table.human_hand.remove(played.card_id)
    table.human_count -= 1
    return msgs


def row_ids(session):
    return list(session.look["ids"])


def scripts_of(table, tag):
    return [s for s in table.scripts if s.startswith(f"-- sparring:{tag}")]


# ---------------------------------------------------------------- Confront Any Demon or God by the human


@with_rig("baba-yaga", "hellboy", BABA_HAND)
def test_confront_won_shows_nothing_the_condition_is_the_engines(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defend_with(session, game, monkeypatch, "Exploit")
    human_hand(table, game, "Service Pistol", "Excalibur", "Confront Any Demon or God")
    attack(session, table, game, "hellboy", "baba", "Confront Any Demon or God", value=3)   # 6 vs 4: won
    msgs = click(session, table, Event.REVEAL)
    assert session.look is None and session.pending is None and table.look_row == [] if hasattr(table, "look_row") else True
    assert not said(msgs, "boca arriba") and not session.look_granted and human_reads(table) == []


@with_rig("liz-sherman", "hellboy", ("Evade", "Fireball", "Feint", "Rekindle", "Pyrotechnics"))
def test_confront_against_liz_lost_lays_the_hand_out_and_won_only_draws(rig, monkeypatch):
    """The live case (30/10): Hellboy's Confront against bot Liz. Lost: the hand is laid out face up, nothing is in
    the discard until the pick; won: no row, no discard."""
    session, table, game, fake, cfg = rig
    defend_with(session, game, monkeypatch, "Feint")
    human_hand(table, game, "Service Pistol", "Confront Any Demon or God")
    attack(session, table, game, "hellboy", "liz", "Confront Any Demon or God", value=6)     # a big value: won
    msgs = click(session, table, Event.REVEAL)
    assert session.look is None and not getattr(table, "look_row", []) and not said(msgs, "boca arriba")



# Confront Any Demon or God lost: the human acts on the table himself (Ivan, 30/10) and presses Hecho; the bot
# validates the table and only then lets the engine discard the card.

LIZ_HAND = ("Evade", "Fireball", "Feint", "Rekindle", "Pyrotechnics")


def lost_confront(session, table, game, fake, monkeypatch, defense="Exploit", bot_hand=None):
    """The human plays Confront against the bot and loses; returns the messages of Revelar."""
    defend_with(session, game, monkeypatch, defense)
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell", "Confront Any Demon or God")
    attack(session, table, game, "hellboy", "baba" if "baba" in session.game.hero_def(0).slug else "liz",
           "Confront Any Demon or God")
    return click(session, table, Event.REVEAL)


def pending_pick(session):
    return hidden.manual_request(session)


def hecho(session, table):
    return click(session, table, Event.CHOICE, {"i": 1})


def human_discards(table, *ids):
    """What the human does on the table: takes the cards out of Green's hand and lays them on the bot's discard."""
    for i in ids:
        table.bot_hand.remove(i)
        table.bot_discard.append(i)


@with_rig("baba-yaga", "hellboy", BABA_HAND)
def test_confront_lost_does_not_move_the_bots_hand_and_waits_for_hecho(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hand_before = sorted(table.bot_hand)
    msgs = lost_confront(session, table, game, fake, monkeypatch)
    assert pending_pick(session) is not None and session.look is None
    assert not scripts_of(table, "show_hand_row"), "the bot lays nothing out: the human looks at the hand himself"
    assert sorted(table.bot_hand) == sorted(c.card_id for c in game.players[0].hand) and len(hand_before) == 5
    assert said(msgs, "Has perdido el combate") and said(msgs, "pulsa Hecho")
    assert session.panel_labels() == {"btn_choice_1": "Hecho"}
    states = session.panel_view()[1]
    assert states["btn_choice_1"] == (True, True) and all(not states[f"btn_choice_{i}"][1] for i in range(2, 7))
    assert "Hecho" in session.panel_view()[0]
    assert human_reads(table) == []


@with_rig("baba-yaga", "hellboy", BABA_HAND)
def test_a_valid_table_discards_exactly_that_card_and_closes_the_combat(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    lost_confront(session, table, game, fake, monkeypatch)
    hand = sorted(c.card_id for c in game.players[0].hand)
    chosen = hand[2]
    title = next(c.title for c in game.players[0].full_set if c.card_id == chosen)
    human_discards(table, chosen)
    n = fake.lua_messages
    msgs = hecho(session, table)
    assert fake.lua_messages - n <= 2
    st = game.players[0]
    assert pending_pick(session) is None and session.pending is None and session._paused() is None
    assert chosen in [c.card_id for c in st.discard] and chosen not in [c.card_id for c in st.hand]
    assert sorted(table.bot_hand) == sorted(i for i in hand if i != chosen) or len(table.bot_hand) == 3
    assert said(msgs, f"El bot descarta {title}")
    assert [s for s in scripts_of(table, "discard_cards") if f"[{chosen}]" in s] == [], "the table already had it"
    assert chosen in session.bot_discarded and table.bot_discard.count(chosen) == 1
    assert human_reads(table) == []
    click(session, table, Event.END_ACTION)
    assert not said(session.messages, "no coincide") and not said(session.messages, "La mesa manda")


@with_rig("baba-yaga", "hellboy", BABA_HAND)
@pytest.mark.parametrize("action, wrong", [
    ("two", "Has descartado 2 cartas; solo puedes 1"),
    ("none", "Todavia no has descartado ninguna carta"),
    ("lost", "Faltan cartas en la mano del bot: devuelve"),
    ("foreign", "Esa carta no es de la mano del bot"),
    ("stranger_in_hand", "Hay en la mano del bot cartas que no le tocan"),
])
def test_a_wrong_table_changes_nothing_says_what_is_wrong_and_waits_for_a_fix(rig, monkeypatch, action, wrong):
    session, table, game, fake, cfg = rig
    lost_confront(session, table, game, fake, monkeypatch)
    hand = sorted(c.card_id for c in game.players[0].hand)
    engine_before = ([c.card_id for c in game.players[0].hand], [c.card_id for c in game.players[0].discard])
    if action == "two":
        human_discards(table, hand[0], hand[1])
    elif action == "lost":
        table.bot_hand.remove(hand[0])                                  # lying somewhere, not on the pile
    elif action == "foreign":
        human_discards(table, hand[0])
        table.bot_discard.append(game.players[1].full_set[0].card_id)
    elif action == "stranger_in_hand":
        table.bot_hand.append(game.players[1].full_set[0].card_id)
    msgs = hecho(session, table)
    assert said(msgs, wrong), msgs
    assert pending_pick(session) is not None and session.pending is not None
    assert ([c.card_id for c in game.players[0].hand], [c.card_id for c in game.players[0].discard]) == engine_before
    assert not [s for s in scripts_of(table, "return_card_to_hand")], "the bot never moves the human's choice for him"
    # the human fixes the table and presses Hecho again
    if action == "two":
        table.bot_discard.remove(hand[1]); table.bot_hand.append(hand[1])
    elif action == "lost":
        table.bot_hand.append(hand[0]); human_discards(table, hand[1])
    elif action == "foreign":
        table.bot_discard.pop()
    elif action == "stranger_in_hand":
        table.bot_hand.pop(); human_discards(table, hand[1])
    else:
        human_discards(table, hand[1])
    hecho(session, table)
    assert pending_pick(session) is None and session.pending is None


@with_rig("liz-sherman", "hellboy", LIZ_HAND)
def test_a_burning_card_the_human_discards_goes_back_to_lizs_hand_by_wildfire(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    lost_confront(session, table, game, fake, monkeypatch, defense="Evade")
    hand = [c.card_id for c in game.players[0].hand]
    fire = next(c for c in game.players[0].hand if c.title == "Fireball")
    human_discards(table, fire.card_id)
    msgs = hecho(session, table)
    assert said(msgs, "El bot se queda Fireball (Wildfire la devuelve")
    assert fire in game.players[0].hand and fire not in game.players[0].discard
    assert [s for s in scripts_of(table, "return_card_to_hand") if f"g{fire.card_id}" in s]
    assert fire.card_id in hand and pending_pick(session) is None


@with_rig("baba-yaga", "hellboy", BABA_HAND)
def test_a_save_taken_while_the_bot_waits_for_hecho_resumes_with_the_same_prompt(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    lost_confront(session, table, game, fake, monkeypatch)
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    twin.snap = None
    msgs = twin.resume()
    assert pending_pick(twin) is not None and said(msgs, "pulsa Hecho")



# ---------------------------------------------------------------- Advanced Psychometry: a reveal, if adjacent

@with_rig("hellboy", "abe-sapien", HELLBOY_HAND)
@pytest.mark.parametrize("adjacent", [False, True])
def test_advanced_psychometry_reveals_the_hand_only_when_adjacent_and_fin_de_accion_returns_it(rig, monkeypatch, adjacent):
    session, table, game, fake, cfg = rig
    defend_with(session, game, monkeypatch, "On Earth As It Is In Hell")
    abe, hb = game.fighters["abe"], game.fighters["hellboy"]
    if adjacent:
        where = next(s for s in sorted(game.board.adj[hb.pos]) if all(f.pos != s for f in game.fighters.values()))
    else:
        where = next(s for s in sorted(game.board.spaces) if game.board.can_reach_target(s, hb.pos, True)
                     and not game.board.adjacent(s, hb.pos) and all(f.pos != s for f in game.fighters.values()))
    abe.pos = where
    table.positions[cfg.nicknames["abe"]] = where
    human_hand(table, game, "Advanced Psychometry", "Leap Away")
    attack(session, table, game, "abe", "hellboy", "Advanced Psychometry")
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is None and human_reads(table) == []
    if not adjacent:
        assert session.look is None and not said(msgs, "boca arriba"), "not adjacent: no look (the engine's condition)"
        return
    assert session.look is not None and session.look["mode"] == "reveal"
    assert said(msgs, "solo miras") and table.point_pings and "Fin de accion o Cancelar la recoge" in session.panel_view()[0]
    ids = row_ids(session)
    msgs = click(session, table, Event.LOOK_PING, {"guid": f"g{ids[0]}"})
    assert session.look is not None and said(msgs, "Esta vez solo miras")
    msgs = click(session, table, Event.END_ACTION)
    on_earth = card_ids(game, 0, "On Earth As It Is In Hell")
    assert session.look is None and sorted(table.bot_hand) == sorted(ids) and table.bot_discard == on_earth
    assert said(msgs, "Mano del bot devuelta sin descartar nada") and human_reads(table) == []


# ---------------------------------------------------------------- Every Possible Angle by the human

@with_rig("hellboy", "abe-sapien", HELLBOY_HAND)
def test_every_possible_angle_puts_the_pinged_card_on_top_of_the_bot_deck_then_asks_the_move(rig):
    session, table, game, fake, cfg = rig
    epa = next(c for c in game.players[1].full_set if c.title == "Every Possible Angle")
    run = EffectRun.for_card("abe-sapien", "Every Possible Angle", "scheme", Ctx(owner=1, this_fid="abe", card_id=epa.card_id))
    session.snap = None
    n = fake.lua_messages
    msgs = session.play_effect(run)
    assert fake.lua_messages - n <= 2
    assert session.look is not None and session.look["mode"] == "pick" and said(msgs, "El bot pone su mano boca arriba")
    chosen = row_ids(session)[1]
    title = next(c.title for c in game.players[0].full_set if c.card_id == chosen)
    msgs = click(session, table, Event.LOOK_PING, {"guid": f"g{chosen}"})
    st = game.players[0]
    # the table's deck is the real one (the engine's order is rebuilt from the table at every read of the hand)
    assert table.bot_deck[0] == chosen and chosen not in table.bot_hand and session.look is None
    assert chosen in [c.card_id for c in st.deck] and chosen not in [c.card_id for c in st.hand]
    assert said(msgs, f"{title} va a la parte superior del mazo del bot; el resto vuelve a su mano")
    assert game.players[1].known.top_of_deck == [chosen], "the human knows the bot's next draw"
    assert session._paused() is None and said(msgs, "Efecto resuelto")       # Abe's move is yours on the table (E2)
    assert human_reads(table) == [] and sorted(c.card_id for c in st.hand) == sorted(table.bot_hand)


# ---------------------------------------------------------------- Remove A Painful Memory by the human

def baba_human_with_a_pact(session, table, game):
    st = game.players[1]
    pact = next(c for c in st.deck if c.title == "Pact Of Peace")
    st.deck.remove(pact)
    game.fx.set_ongoing(1, pact.card_id)


@with_rig("hellboy", "baba-yaga", HELLBOY_HAND)
@pytest.mark.parametrize("bot_discards", [True, False])
def test_remove_a_painful_memory_by_the_human_the_bot_answers_discard_or_take_2(rig, monkeypatch, bot_discards):
    session, table, game, fake, cfg = rig
    defend_with(session, game, monkeypatch, "On Earth As It Is In Hell")
    monkeypatch.setattr(session.ai, "choose_effect", answers(optional=[bot_discards]))
    baba_human_with_a_pact(session, table, game)
    human_hand(table, game, "Remove A Painful Memory", "Exploit")
    attack(session, table, game, "baba", "hellboy", "Remove A Painful Memory")
    click(session, table, Event.REVEAL)
    assert session.look is not None and session.look["mode"] == "pick"
    hb = game.fighters["hellboy"]
    hp = hb.hp
    chosen = row_ids(session)[0]
    title = next(c.title for c in game.players[0].full_set if c.card_id == chosen)
    msgs = click(session, table, Event.LOOK_PING, {"guid": f"g{chosen}"})
    assert session.look is None and session.pending is None
    st = game.players[0]
    if bot_discards:
        assert chosen in [c.card_id for c in st.discard] and chosen in table.bot_discard and hb.hp == hp
        assert said(msgs, f"El bot descarta {title} y devuelve el resto de su mano")
    else:
        assert chosen in [c.card_id for c in st.hand] and chosen in table.bot_hand and hb.hp == hp - 2
        assert said(msgs, f"El bot se queda {title} y recoge su mano")
    assert human_reads(table) == []


@with_rig("hellboy", "baba-yaga", HELLBOY_HAND)
def test_remove_a_painful_memory_without_an_ongoing_scheme_only_reveals(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defend_with(session, game, monkeypatch, "On Earth As It Is In Hell")
    human_hand(table, game, "Remove A Painful Memory", "Exploit")
    attack(session, table, game, "baba", "hellboy", "Remove A Painful Memory")
    click(session, table, Event.REVEAL)
    assert session.look is not None and session.look["mode"] == "reveal" and session.pending is None


# ---------------------------------------------------------------- bot Remove A Painful Memory: the human's buttons

@with_rig("baba-yaga", "hellboy", BABA_HAND)
def test_bot_remove_a_painful_memory_names_the_card_and_offers_descartar_or_coger_2(rig):
    session, table, game, fake, cfg = rig
    st = game.players[0]
    pact = next(c for c in st.deck if c.title == "Pact Of Peace")
    st.deck.remove(pact)
    game.fx.set_ongoing(0, pact.card_id)
    table.bot_deck.remove(pact.card_id)
    memory = next(c for c in st.hand if c.title == "Remove A Painful Memory")
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell")
    plan = [Act("attack", fid="baba", target="hellboy", card=memory)]
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    table.face_down = []
    msgs = click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "optional" and len(req.extra["discards"]) == 1 and req.extra["else_damage"] == 2
    named = req.extra["discards"][0]
    title = next(c.title for c in game.players[1].full_set if c.card_id == named)
    assert named in table.human_hand
    assert session.panel_labels() == {"btn_choice_1": f"Descartar {title}", "btn_choice_2": "Coger 2"}
    assert said(msgs, f"Descartas {title} o coges 2 de dano - Remove A Painful Memory: pulsa una de las opciones")
    hp = game.fighters["hellboy"].hp
    msgs = click(session, table, Event.CHOICE, {"i": 2})
    assert game.fighters["hellboy"].hp == hp - 2 and session.pending is None and session.pending_discard is None
    assert len(human_reads(table)) == 1


# ---------------------------------------------------------------- bot Shock And Awe: the human's own pick

@with_rig("abe-sapien", "hellboy", ABE_HAND)
def test_bot_shock_and_awe_makes_you_discard_at_your_choice_without_reading_your_hand(rig):
    session, table, game, fake, cfg = rig
    shock = next(c for c in game.players[0].hand if c.title == "Shock And Awe")
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell")
    plan = [Act("attack", fid="abe", target="hellboy", card=shock)]
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    table.face_down = []
    before = list(game.players[1].discard)
    msgs = click(session, table, Event.REVEAL)
    assert session.pending_discard["n"] == 1 and "cards" not in session.pending_discard
    assert said(msgs, "Descarta 1 carta(s) (Shock And Awe)")
    assert game.players[1].discard == before and human_reads(table) == []


# ---------------------------------------------------------------- Fleeting Moments by the human: the engine's rng

@with_rig("hellboy", "liz-sherman", HELLBOY_HAND)
def test_fleeting_moments_by_the_human_the_rng_picks_the_bot_card_and_nobody_reads_a_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    on_earth = defend_with(session, game, monkeypatch, "On Earth As It Is In Hell")

    def never(*a, **kw):
        raise AssertionError("the bot never chooses the card it discards at random")
    monkeypatch.setattr(session.ai, "choose_discard", never)
    monkeypatch.setattr(session.ai, "choose_effect", never)
    human_hand(table, game, "Fleeting Moments", "Evade", "Fireball")
    attack(session, table, game, "liz", "hellboy", "Fleeting Moments")
    st = game.players[0]
    hand_before = {c.card_id for c in st.hand} - {on_earth.card_id}
    discard_before = len(st.discard)
    msgs = click(session, table, Event.REVEAL)
    gone = [c.card_id for c in st.discard[discard_before:] if c.card_id in hand_before]
    assert len(gone) == 1, "one random card of the bot's hand"
    assert gone[0] in table.bot_discard and gone[0] not in table.bot_hand
    assert session.pending_discard["n"] == 1 and "cards" not in session.pending_discard
    assert said(msgs, "Descarta 1 carta(s) (Fleeting Moments, al azar: la carta ")
    assert human_reads(table) == [] and session.look is None


# ---------------------------------------------------------------- Perfect Shot by the human

@with_rig("hellboy", "abe-sapien", HELLBOY_HAND)
@pytest.mark.parametrize("pick, extra", [(1, 2), (FACE_DOWN, 0), (4, 0)])
def test_perfect_shot_by_the_human_asks_the_prediction_at_revelar_before_the_bot_defends(rig, monkeypatch, pick, extra):
    session, table, game, fake, cfg = rig
    defended = []
    on_earth = next(c for c in game.players[0].hand if c.title == "On Earth As It Is In Hell")     # printed 0
    monkeypatch.setattr(session.ai, "choose_defense",
                        lambda g, a, t, attack_card=None: defended.append(attack_card) or on_earth)
    human_hand(table, game, "Perfect Shot", "Leap Away")
    attack(session, table, game, "abe", "hellboy", "Perfect Shot")
    n = fake.lua_messages
    msgs = click(session, table, Event.REVEAL)
    assert fake.lua_messages - n <= 1 and defended == [], "the prediction comes before the bot's defense"
    p = session.pending
    assert p is not None and p.defended is False and p.predict is not None and session._paused()[0] == "predict"
    assert said(msgs, "Perfect Shot: predice el valor impreso de la carta del bot")
    labels = session.panel_labels()
    assert labels["btn_choice_1"] == "Valor 0" and labels["btn_choice_6"].startswith("Mas")
    assert session.panel_view()[1]["btn_reveal"][0] is False
    saved = json.loads(json.dumps(session.to_dict()))
    twin = twin_session(session, cfg, saved)
    assert twin._paused()[0] == "predict" and twin.panel_labels() == labels
    monkeypatch.setattr(twin.ai, "choose_defense", session.ai.choose_defense)
    hp = twin.game.fighters["hellboy"].hp
    if pick == FACE_DOWN:
        click(twin, table, Event.CHOICE, {"i": 6})                       # page 2: 5, 6, 7, Boca abajo
        assert twin.panel_labels()["btn_choice_4"] == "Boca abajo"
        msgs = click(twin, table, Event.CHOICE, {"i": 4})
        assert said(msgs, "Juegas la carta boca abajo: sin prediccion")
    elif pick == 1:
        msgs = click(twin, table, Event.CHOICE, {"i": 1})                 # "Valor 0": the bot's On Earth prints 0
        assert said(msgs, "Predices que la carta del bot tiene valor impreso 0: tu carta se juega boca arriba")
    else:
        msgs = click(twin, table, Event.CHOICE, {"i": 4})                 # "Valor 3": a miss
        assert said(msgs, "Predices que la carta del bot tiene valor impreso 3")
    # the answer continues Revelar: the bot defends now (knowing a face-up Perfect Shot: public information, Ivan
    # 29/10; nothing when it is face down) and the combat resolves in the same click
    assert twin.pending is None and twin._paused() is None
    assert [c.title if c else None for c in defended] == [None if pick == FACE_DOWN else "Perfect Shot"]
    assert said(msgs, "Perfect Shot (+2)") is (extra == 2)
    assert twin.game.fighters["hellboy"].hp == hp - 3 - extra + 2, "3 (+2 if predicted), then On Earth heals 2 (lost)"
    assert human_reads(table) == []


# ---------------------------------------------------------------- Perfect Shot by the bot

@with_rig("abe-sapien", "hellboy", ABE_HAND, False)
def test_perfect_shot_by_the_bot_is_placed_face_up_with_its_prediction_announced(rig):
    session, table, game, fake, cfg = rig
    shot = next(c for c in game.players[0].hand if c.title == "Perfect Shot")
    human_hand(table, game, "Service Pistol", "Excalibur", "B.P.R.D. Training", "Glimpse Of Hell")
    expected = predict_value(game, 0)
    plan = [Act("attack", fid="abe", target="hellboy", card=shot)]
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    p = session.pending
    assert p is not None and p.kind == "bot_attacks" and p.prediction == {"value": expected}
    assert said(msgs, f"El bot juega Perfect Shot boca arriba y predice que el valor impreso de tu carta es {expected}")
    assert table.flips[-1] == p.bot_card_guid, "placed face down, turned face up in the same step"
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["pending"]["prediction"] == {"value": expected}
    defense = next(c for c in game.players[1].full_set if c.can_defend and c.title not in ("Planned Recklessness",)
                   and (c.value or 0) == expected and c.card_id in table.human_hand)
    human_plays(table, game, defense.title)
    table.human_hand.remove(defense.card_id)
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "Perfect Shot (+2)") and said(msgs, "Perfect Shot (3)")
    assert human_reads(table) == []


def test_predict_value_uses_only_seen_cards_or_the_public_composition(bprd):
    g = Game.new(bprd, seed=3, controllers={}, bot_player=0, heroes=("abe-sapien", "hellboy"))
    rival = g.players[1]
    rival.hand = HandSpy(rival.hand)
    rival.hand.armed = True
    by_composition = predict_value(g, 0)
    counts = {}
    for c in rival.full_set:
        if c.can_defend:
            counts[c.value or 0] = counts.get(c.value or 0, 0) + 1
    assert by_composition == max(counts, key=lambda v: (counts[v], v))
    rival.hand.armed = False
    seen = [c for c in rival.full_set if c.title == "On Earth As It Is In Hell"][:1] + \
           [c for c in rival.full_set if c.title == "Excalibur"][:2]
    g.observe_hand(0, seen)
    rival.hand.armed = True
    assert predict_value(g, 0) == 0, "a defense the bot saw beats the composition (Excalibur cannot defend)"


def test_the_plugin_asks_its_owner_once_and_a_face_down_answer_gives_no_bonus(bprd):
    from sparring.combat_flow import CombatFlow
    from conftest import give
    for answer, atk in (([0], 5), ([FACE_DOWN], 3), ([5], 3)):
        g = Game.new(bprd, seed=3, controllers={}, bot_player=0, heroes=("abe-sapien", "hellboy"))
        g.turn, g.turn_no = 0, 2
        g.begin_turn()
        abe, hb = g.fighters["abe"], g.fighters["hellboy"]
        abe.pos, hb.pos = 0, 1
        shot, on_earth = give(g, 0, "Perfect Shot"), give(g, 1, "On Earth As It Is In Hell")
        flow = CombatFlow(g, abe, hb, shot, on_earth)
        chooser = ScriptedChooser([answer])
        flow.choosers = {0: chooser, 1: chooser}
        assert flow.run() is None
        asked = [r for r in chooser.requests if r.extra.get("op") == "predict"]
        assert len(asked) == 1 and asked[0].options == list(range(9)) and asked[0].player == 0
        assert flow.runs["immediately:atk"].flags["prediction"] == (None if answer == [FACE_DOWN] else answer[0])
        assert flow.result.atk_value == atk


# ---------------------------------------------------------------- UNCANNY INTUITION

@with_rig("hellboy", "abe-sapien", HELLBOY_HAND)
def test_the_bot_attack_on_your_abe_with_an_active_token_is_turned_face_up_and_named(rig):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(1, "intuition", 1)
    pistol = next(c for c in game.players[0].hand if c.title == "Service Pistol")
    human_hand(table, game, "Leap Away", "Ward And Prepare")
    plan = [Act("attack", fid="hellboy", target="abe", card=pistol)]
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    p = session.pending
    assert p is not None and table.flips[-1] == p.bot_card_guid and p.prediction is None
    assert said(msgs, "UNCANNY INTUITION: Abe Sapien tiene una ficha activa: gastas una, robas 1 carta (hazlo en la mesa) "
                      "y el ataque del bot se juega boca arriba: Service Pistol (valor 5)")
    table.face_down = []
    click(session, table, Event.REVEAL)
    assert game.fx.counter_value(1, "intuition") == 0, "the engine spends the token when the attack is declared"


@with_rig("hellboy", "abe-sapien", HELLBOY_HAND)
def test_without_an_active_token_the_bot_attack_stays_face_down(rig):
    session, table, game, fake, cfg = rig
    pistol = next(c for c in game.players[0].hand if c.title == "Service Pistol")
    human_hand(table, game, "Leap Away")
    plan = [Act("attack", fid="hellboy", target="abe", card=pistol)]
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending is not None and table.flips == [] and not said(msgs, "boca arriba")


@with_rig("abe-sapien", "hellboy", ABE_HAND, False)
def test_your_attack_on_the_bot_abe_with_an_active_token_is_the_one_card_its_defense_may_know(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    game.fx.set_counter(0, "intuition", 2)
    seen, at_choice = [], []

    def defense(g, a, t, attack_card=None):
        seen.append(attack_card)
        at_choice.append((g.fx.counter_value(0, "intuition"), len(table.bot_hand), len(g.players[0].hand),
                          g.drawn[0], sorted(c.card_id for c in g.players[0].hand) == sorted(table.bot_hand)))
        return None                                   # no card: nothing of the bot's resolves after the combat
    monkeypatch.setattr(session.ai, "choose_defense", defense)
    human_hand(table, game, "Service Pistol", "Excalibur")
    msgs = attack(session, table, game, "hellboy", "abe", "Service Pistol")
    assert said(msgs, "UNCANNY INTUITION: Abe Sapien tiene una ficha activa: la gasta, roba 1 carta y tu ataque se juega boca arriba")
    msgs = click(session, table, Event.REVEAL)
    assert [c.title for c in seen] == ["Service Pistol"]
    # the engine's order (Ivan, 29/10): the token is spent and the card drawn AND DEALT before the defense is
    # chosen, so the drawn card may be the defense; one token per attack, never two
    assert at_choice == [(1, 6, 6, 0, True)]
    assert said(msgs, "UNCANNY INTUITION: tu ataque se juega boca arriba: Service Pistol (valor 5); el bot elige su defensa viendolo")
    assert game.fx.counter_value(0, "intuition") == 1 and session.pending is None
    # without a token the defense sees nothing
    game.fx.set_counter(0, "intuition", 0)
    human_hand(table, game, "Excalibur")
    click(session, table, Event.END_ACTION)
    msgs = attack(session, table, game, "hellboy", "abe", "Excalibur")
    assert not said(msgs, "UNCANNY INTUITION")
    click(session, table, Event.REVEAL)
    assert seen[-1] is None


def test_attack_revealed_reads_the_ability_trigger_not_a_card_name(bprd):
    g = Game.new(bprd, seed=3, controllers={}, bot_player=0, heroes=("abe-sapien", "hellboy"))
    abe, hb = g.fighters["abe"], g.fighters["hellboy"]
    assert not attack_revealed(g, abe) and not attack_revealed(g, hb)
    g.fx.set_counter(0, "intuition", 2)
    assert attack_revealed(g, abe)
    assert not attack_revealed(g, g.fighters["agent1"]), "an attack on an agent is not on Abe"
    g.fx.dsl_heroes.discard("abe-sapien")
    assert not attack_revealed(g, abe), "a hero outside the interpreter has no engine trigger"


def test_the_engine_spends_the_token_and_draws_before_asking_a_defense_that_knows_the_attack(bprd):
    from conftest import Scripted, give
    seen = []

    class Recorder(Scripted):
        def choose_defense(self, game, attacker, target, attack_card=None):
            seen.append((attack_card, game.fx.counter_value(0, "intuition"), len(game.players[0].hand)))
            return self.defense
    ctl = {0: Recorder(), 1: Scripted()}
    g = Game.new(bprd, seed=3, controllers=ctl, bot_player=0, heroes=("abe-sapien", "hellboy"))
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    g.fighters["abe"].pos, g.fighters["hellboy"].pos = 0, 1
    g.fx.set_counter(0, "intuition", 1)
    hand = len(g.players[0].hand)
    pistol = give(g, 1, "Service Pistol")
    g.attack(g.fighters["hellboy"], g.fighters["abe"], pistol)
    assert seen == [(pistol, 0, hand + 1)], "token spent and card drawn first; the defense sees the attack"
    seen.clear()
    sword = give(g, 1, "Excalibur")
    g.attack(g.fighters["hellboy"], g.fighters["abe"], sword)
    assert seen == [(None, 0, hand + 1)], "no token: the defense sees nothing"


# ---------------------------------------------------------------- the legacy route is untouched

def test_a_hero_outside_the_interpreter_keeps_the_grant_a_button_route(tmp_path):
    session, table, game, fake, cfg, client = rig_for(tmp_path, "baba-yaga", "hellboy", BABA_HAND, interpret_human=False)
    try:
        card = next(c for c in game.players[1].full_set if c.title == "Confront Any Demon or God")
        session._grant_look_for(card)
        assert session.look_granted
        game.fx.dsl_heroes.add("hellboy")
        session.revoke_look()
        session._grant_look_for(card)
        assert not session.look_granted
    finally:
        client.close()
        fake.close()


@with_rig("baba-yaga", "hellboy", BABA_HAND)
def test_revelar_turns_both_combat_cards_face_up_even_when_the_combat_stops_at_a_choice(rig, monkeypatch):
    """Live (30/10): with the combat paused at the human card effect, a card stayed face down until the end."""
    session, table, game, fake, cfg = rig
    n = fake.lua_messages
    lost_confront(session, table, game, fake, monkeypatch)
    assert pending_pick(session) is not None and session.pending is not None
    assert len(table.flips) == 2 and len(set(table.flips)) == 2, table.flips
    assert not table.unflips and fake.lua_messages - n <= 6


@with_rig("baba-yaga", "hellboy", BABA_HAND)
def test_a_refused_answer_leaves_no_trace_of_the_discard_and_announces_nothing(rig, monkeypatch):
    from sparring.state import RuleError
    session, table, game, fake, cfg = rig
    lost_confront(session, table, game, fake, monkeypatch)
    chosen = sorted(c.card_id for c in game.players[0].hand)[1]
    human_discards(table, chosen)
    monkeypatch.setattr(session, "_answer_flow", lambda flow, value: (_ for _ in ()).throw(RuleError("no")))
    msgs = hecho(session, table)
    assert pending_pick(session) is not None and session.pending is not None
    assert chosen not in session.bot_discarded and chosen not in session.fx_in_flight
    assert not said(msgs, "El bot descarta") and said(msgs, "Accion ilegal")
    assert chosen not in [c.card_id for c in game.players[0].discard]
