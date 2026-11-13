"""The human's attack-only actions (Wyatt Earp's `Game.free_attacks`; John Henry's, Washington's and Rosie's `fx.attack_credit`) and End action.

The human's hand in the engine is a virtual one (the real cards are on the table), so it never decides whether such an action is usable:
with only attack-only actions left, End action says so, and pressed again with nothing done in between it gives them up. While a
paid action is left, End action keeps them."""
from __future__ import annotations

import pytest

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import build, said
from test_e2_human_cards import put_adjacent
from test_jill_trent_human import JillTable

MECHANISMS = {"wyatt-earp": "free_attacks", "john-henry": "attack_credit", "george-washington": "attack_credit", "rosie-the-riveter": "attack_credit"}


def rig(tmp_path, human, real_attack: bool):
    """A game where the human's REAL hand (on the table) and the engine's VIRTUAL one disagree about holding an attack."""
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", human, ("B.P.R.D. Training",), table_cls=JillTable)
    hero = game.hero(1)
    put_adjacent(game, table, cfg, hero.fid, "hellboy")
    st = game.players[1]
    pool = st.hand + st.deck
    att = [c for c in pool if c.can_attack and c.fighter in ("any", hero.name)][:2]
    non = [c for c in pool if not c.can_attack][:2]
    real, virtual = (att, non) if real_attack else (non, att)
    table.human_hand, table.human_count = [c.card_id for c in real], len(real)
    st.hand[:] = virtual
    st.deck[:] = [c for c in pool if c not in virtual]
    game.turn = 1
    return session, table, game, fake, client


def grant(game, human, actions, paid):
    """`actions` left, of which all but `paid` are attack-only."""
    game.actions_left = actions
    if MECHANISMS[human] == "free_attacks":
        game.free_attacks = [None] * (actions - paid)
    else:
        game.fx.attack_credit = actions - paid


def free_left(game, human):
    return len(game.free_attacks) if MECHANISMS[human] == "free_attacks" else game.fx.attack_credit


@pytest.mark.parametrize("real_attack", [True, False], ids=["real-hand-attacks", "real-hand-does-not"])
@pytest.mark.parametrize("human", MECHANISMS)
def test_only_attack_only_actions_left_end_action_asks_and_then_gives_them_up_whatever_the_hand(tmp_path, human, real_attack):
    session, table, game, fake, client = rig(tmp_path, human, real_attack)
    try:
        grant(game, human, 1, paid=0)
        msgs = click(session, table, Event.END_ACTION)
        assert game.turn == 1 and game.actions_left == 1 and free_left(game, human) == 1, msgs
        assert said(msgs, "solo para atacar") and said(msgs, "otra vez"), msgs
        msgs = click(session, table, Event.END_ACTION)
        assert game.turn == 0 and said(msgs, "Renuncias"), msgs
    finally:
        client.close()
        fake.close()


@pytest.mark.parametrize("real_attack", [True, False], ids=["real-hand-attacks", "real-hand-does-not"])
@pytest.mark.parametrize("human", MECHANISMS)
def test_a_paid_action_left_end_action_keeps_the_free_attack_and_reports_it(tmp_path, human, real_attack):
    session, table, game, fake, client = rig(tmp_path, human, real_attack)
    try:
        grant(game, human, 2, paid=1)
        for _ in range(3):
            msgs = click(session, table, Event.END_ACTION)
            assert game.turn == 1 and game.actions_left == 2 and free_left(game, human) == 1, msgs
        assert said(msgs, "gratis y solo para atacar"), msgs
    finally:
        client.close()
        fake.close()


def test_a_maneuver_between_two_end_actions_does_not_give_up_the_free_attack(tmp_path):
    """The first End action after an action that spent one reports; only a repeat with nothing done in between gives up."""
    session, table, game, fake, client = rig(tmp_path, "wyatt-earp", True)
    try:
        grant(game, "wyatt-earp", 2, paid=1)
        click(session, table, Event.MANEUVER)
        msgs = click(session, table, Event.END_ACTION)
        assert game.turn == 1 and game.actions_left == 1 and game.free_attacks == [None] and said(msgs, "otra vez"), msgs
    finally:
        client.close()
        fake.close()
