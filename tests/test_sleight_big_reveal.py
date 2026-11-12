"""F-SLEIGHT-BIG-REVEAL (live report 12/11): the human swapped Sleight Of Hand for The Big Reveal and the combat resolved at once,
with no chance to BOOST the new card ("Your card: The Big Reveal: no effect"). "Resolve all effects on that card as normal": after the
swap the card's own free BOOST is offered exactly as when it is played from the start (the cards in the discard pile, Continue or
No boost), and The Big Reveal's AFTER then returns one of the cards it was boosted with."""
from __future__ import annotations

import json

from sparring.session import Session
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import said
from test_e2_human_cards import press
from test_houdini_human import combat_line, spend
from test_houdini_sleight_table import SLEIGHT, done, hid, rig, sleight_attack, swap_on_table, with_rig  # noqa: F401

REVEAL = "The Big Reveal"


def swap_to(session, table, game, cfg, monkeypatch, title):
    sleight_attack(session, table, game, cfg, monkeypatch)
    click(session, table, Event.CHOICE, {"i": 1})
    swap_on_table(table, game, SLEIGHT, title)
    return done(session, table)


@with_rig("hellboy", "houdini")
def test_the_big_reveal_played_instead_waits_for_its_two_boosts_before_the_combat_resolves(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hp = game.fighters["hellboy"].hp
    msgs = swap_to(session, table, game, cfg, monkeypatch, REVEAL)
    assert said(msgs, "Sleight of Hand: vuelve a tu mano y juegas The Big Reveal en su lugar")
    assert said(msgs, "The Big Reveal revelado: puedes potenciarlo hasta 2 veces"), msgs
    assert not said(msgs, "Combate:") and game.fighters["hellboy"].hp == hp
    assert session.pending is not None and session.pending.wait is not None and session.pending.wait.card_id == hid(game, REVEAL)
    states = session.panel_view()[1]
    assert states["btn_boost"] == (True, True) and states["btn_noboost"] == (True, True)


@with_rig("hellboy", "houdini")
def test_boosted_twice_after_the_swap_it_adds_both_values_and_returns_one_of_the_boost_cards(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hp = game.fighters["hellboy"].hp
    swap_to(session, table, game, cfg, monkeypatch, REVEAL)
    spent = spend(table, game, "Flourish", SLEIGHT)              # the returned Sleight Of Hand is in the hand again: a boost of 3
    msgs = click(session, table, Event.BOOST)
    assert "total 7" in combat_line(msgs), combat_line(msgs)     # 2 + Flourish 2 + Sleight Of Hand 3
    assert game.fighters["hellboy"].hp == hp - 7
    assert not said(msgs, "The Big Reveal: sin efecto")
    req = session.effect_run.awaiting                            # AFTER COMBAT: return one card you boosted with
    assert req.kind == "cards" and sorted(req.options) == sorted(spent)
    press(session, table, spent[1])
    assert spent[1] in [c.card_id for c in game.players[1].hand] and session.pending is None
    assert spent[0] in [c.card_id for c in game.players[1].discard]


@with_rig("hellboy", "houdini")
def test_a_single_boost_after_the_swap_is_enough(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    swap_to(session, table, game, cfg, monkeypatch, REVEAL)
    spent = spend(table, game, "Flourish")
    msgs = click(session, table, Event.BOOST)
    assert "total 4" in combat_line(msgs), combat_line(msgs)
    assert not said(msgs, "The Big Reveal: sin efecto"), msgs
    assert spent[0] in [c.card_id for c in game.players[1].hand] and session.pending is None      # the only boost card comes back


@with_rig("hellboy", "houdini")
def test_no_boost_after_the_swap_resolves_the_combat_with_the_card_alone(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hp = game.fighters["hellboy"].hp
    swap_to(session, table, game, cfg, monkeypatch, REVEAL)
    msgs = click(session, table, Event.NO_BOOST)
    assert "Houdini ataca con The Big Reveal (2)" in combat_line(msgs) and "total 2" in combat_line(msgs)
    assert game.fighters["hellboy"].hp == hp - 2 and session.pending is None


@with_rig("hellboy", "houdini")
def test_a_third_boost_card_after_the_swap_is_refused_and_the_combat_keeps_waiting(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hp = game.fighters["hellboy"].hp
    swap_to(session, table, game, cfg, monkeypatch, REVEAL)
    spend(table, game, "Flourish", SLEIGHT, "Vanishing Act")
    msgs = click(session, table, Event.BOOST)
    assert said(msgs, "esta carta admite como mucho 2 boosts") and session.pending.wait is not None
    assert game.fighters["hellboy"].hp == hp


@with_rig("hellboy", "houdini")
def test_continue_without_a_card_in_the_discard_pile_only_warns(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    swap_to(session, table, game, cfg, monkeypatch, REVEAL)
    msgs = click(session, table, Event.BOOST)
    assert said(msgs, "No veo ninguna carta nueva en tu descarte") and session.pending.wait is not None


@with_rig("hellboy", "houdini")
def test_a_card_with_one_free_boost_played_instead_is_offered_that_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hp = game.fighters["hellboy"].hp
    msgs = swap_to(session, table, game, cfg, monkeypatch, "Flourish")
    assert said(msgs, "Flourish revelado: si quieres potenciar") and not said(msgs, "Combate:")
    spend(table, game, SLEIGHT)
    msgs = click(session, table, Event.BOOST)
    assert "total 6" in combat_line(msgs), combat_line(msgs)     # 3 + Sleight Of Hand 3
    assert game.fighters["hellboy"].hp == hp - 6


@with_rig("hellboy", "houdini")
def test_a_card_without_a_boost_played_instead_still_resolves_at_once(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    msgs = swap_to(session, table, game, cfg, monkeypatch, "Vanishing Act")
    assert said(msgs, "Combate:") and (session.pending is None or session.pending.wait is None)


@with_rig("hellboy", "houdini")
def test_reveal_pressed_while_the_boost_waits_repeats_what_to_do(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    swap_to(session, table, game, cfg, monkeypatch, REVEAL)
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "Las cartas ya estan reveladas: pon tu carta de boost en el descarte")


@with_rig("hellboy", "houdini")
def test_a_save_at_the_boost_pause_resumes_waiting_for_the_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    hp = game.fighters["hellboy"].hp
    swap_to(session, table, game, cfg, monkeypatch, REVEAL)
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["pending"]["flow"] is not None and saved["pending"]["boost_wait"] is not None
    resumed = Session(game, session.client, session.ai, session.cfg)
    table.session = resumed
    resumed.load_dict(saved)
    assert resumed.pending.wait is not None and resumed.pending.flow.atk_card.title == REVEAL
    spent = spend(table, game, "Flourish", SLEIGHT)
    msgs = click(resumed, table, Event.BOOST)
    assert "total 7" in combat_line(msgs) and game.fighters["hellboy"].hp == hp - 7
    assert sorted(resumed.effect_run.awaiting.options) == sorted(spent)


# ---------------------------------------------------------------- parity: any card played instead resolves as if played from the start

import pytest

from test_d3_table_effects import build, human_attack, human_hand
from test_e2_human_cards import bot_defends_with, bot_defends_with_nothing, put_adjacent
from test_houdini_sleight_table import SleightTable

PARITY_HAND = (SLEIGHT, "Flourish", "Flourish", "Vanishing Act", "For My Next Trick", "Misdirection", "Smoke and Mirrors",
               "An Illusion of My Own Design", REVEAL)
TRAINING = "B.P.R.D. Training"


@pytest.fixture
def tables(tmp_path):
    """Two identical tables (same seed, same hands): one plays the card face down from the start, the other through Sleight Of Hand."""
    opened = []

    def open_one(name):
        (tmp_path / name).mkdir()
        session, table, game, fake, cfg, client = build(tmp_path / name, "hellboy", "houdini", (TRAINING,), table_cls=SleightTable)
        table.human_spot = tuple(cfg.session_config().human_card_spot)
        table.bot_spot_z = cfg.session_config().bot_card_spot[2]
        table.human_deck = []
        opened.append((client, fake))
        return session, table, game, cfg
    yield open_one
    for client, fake in opened:
        client.close()
        fake.close()


def resolve(session, table, game, boosts, trace):
    """Answers whatever the combat asks until it is over: a boost wait takes `boosts` (none: No boost), every panel question its
    first button. `trace` records each prompt, in order."""
    for _ in range(12):
        p = session.pending
        if p is not None and p.wait is not None:
            trace.append(("boost", p.wait.card_id, session.panel_view()[1]["btn_boost"]))
            if boosts:
                spend(table, game, *boosts)
            msgs = click(session, table, Event.BOOST if boosts else Event.NO_BOOST)
        elif session.effect_run is not None:
            req = session.effect_run.awaiting
            trace.append((session.effect_run.label, req.kind, req.extra.get("purpose"), sorted(map(str, req.options)), req.min, req.max))
            msgs = click(session, table, Event.CHOICE, {"i": 1})
        else:
            return
        trace.extend(m for m in msgs if m.startswith(("Combate:", "Tu carta:", "Aplicado:")) and SLEIGHT + ": vuelve" not in m)
    raise AssertionError(f"the combat never ended: {trace}")


def outcome(session, table, game, trace):
    st = game.players[1]
    return {"trace": trace, "hp": {f.fid: f.hp for f in game.fighters.values()}, "pos": {f.fid: f.pos for f in game.fighters.values()},
            "discard": sorted(c.card_id for c in st.discard), "hand": len(st.hand), "table_hand": table.human_count,
            "table_discard": sorted(table.human_discard), "bot_discard": sorted(c.card_id for c in game.players[0].discard),
            "actions": game.actions_left, "pending": session.pending is None, "dealt": sum(table.human_deals)}


def play(tables, monkeypatch, title, *, via_sleight, boosts=(), defense=None):
    session, table, game, cfg = tables("swap" if via_sleight else "plain")
    if defense is None:
        bot_defends_with_nothing(session, monkeypatch)
    else:
        bot_defends_with(session, game, defense, monkeypatch)
    put_adjacent(game, table, cfg, "houdini", "hellboy")
    human_hand(table, game, *PARITY_HAND)
    trace = []
    if via_sleight:
        human_attack(session, table, game, "houdini", "hellboy", SLEIGHT)
        click(session, table, Event.REVEAL)
        click(session, table, Event.CHOICE, {"i": 1})
        swap_on_table(table, game, SLEIGHT, title)
        msgs = done(session, table)
    else:
        human_attack(session, table, game, "houdini", "hellboy", title)
        msgs = click(session, table, Event.REVEAL)
    trace.extend(m for m in msgs if m.startswith(("Combate:", "Tu carta:", "Aplicado:")) and SLEIGHT + ": vuelve" not in m)
    resolve(session, table, game, boosts, trace)
    return outcome(session, table, game, trace)


@pytest.mark.parametrize("title, boosts, defense", [
    (REVEAL, ("Flourish", "Flourish"), None),               # DURING: boost twice; AFTER: return one of the boost cards (a question)
    (REVEAL, (), None),
    (REVEAL, ("Flourish",), TRAINING),
    ("Flourish", ("Misdirection",), None),                  # DURING: one boost, whose BOOSTED WITH asks who takes 2 damage
    ("Misdirection", (), TRAINING),                         # IMMEDIATELY: cancel the effects of the rival's card
    ("Smoke and Mirrors", (), None),                        # IMMEDIATELY: a question (swap Houdini and Bess)
    ("An Illusion of My Own Design", ("Flourish",), TRAINING),   # IMMEDIATELY: the rival may boost; DURING: boost
    ("For My Next Trick", (), None),                        # AFTER: move, draw, gain an action
    ("Vanishing Act", (), TRAINING),                        # AFTER: a move the human makes by hand
])
def test_a_card_played_instead_of_sleight_resolves_exactly_as_when_played_from_the_start(tables, monkeypatch, title, boosts, defense):
    plain = play(tables, monkeypatch, title, via_sleight=False, boosts=boosts, defense=defense)
    swapped = play(tables, monkeypatch, title, via_sleight=True, boosts=boosts, defense=defense)
    assert plain["trace"], plain
    assert swapped == plain
