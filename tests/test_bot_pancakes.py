"""The bot plays Pancakes! (live 31/10: heal only, the search's `greedy` line took the first two options of the card,
heal and a return it did not even announce). Two different effects must resolve, the ones that do something."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.ai_medusa import MedusaAI
from sparring.effects.choose import SCHEME_VARIANTS, SyntheticChooser
from sparring.state import Game


def bot_game(bprd, hp=12, discard=("Right Hand Of Doom", "Glimpse Of Hell", "B.P.R.D. Training")):
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=("hellboy", "liz-sherman"), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    me = g.players[0]
    for p in g.players:
        p.hand.clear()
    for title in discard:
        card = next(c for c in me.deck if c.title == title)
        me.deck.remove(card)
        me.discard.append(card)
    g.fighters["hellboy"].hp = hp
    return g


def play(g, variant):
    choosers = None
    if variant is not None:
        choosers = {0: SyntheticChooser(policy=variant), 1: SyntheticChooser(policy=variant)}
    card = give(g, 0, "Pancakes!")
    sizes = len(g.players[0].deck), len(g.players[0].discard)
    g.play_scheme(0, g.hero(0), card, choosers=choosers)
    return sizes



@pytest.mark.parametrize("variant", [None, *SCHEME_VARIANTS])
def test_hurt_hellboy_heals_and_draws(bprd, variant):
    g = bot_game(bprd)
    me = g.players[0]
    discard0 = play(g, variant)[1]
    assert g.fighters["hellboy"].hp == 14
    assert len(me.hand) == 2 and g.drawn[0] == 2
    assert len(me.discard) == discard0 + 1          # only the Pancakes! card itself arrived


@pytest.mark.parametrize("variant", [None, *SCHEME_VARIANTS])
def test_healthy_hellboy_draws_and_returns_at_least_one_card(bprd, variant):
    g = bot_game(bprd, hp=18)
    me = g.players[0]
    deck0, discard0 = play(g, variant)
    assert g.fighters["hellboy"].hp == 18 and len(me.hand) == 2
    moved = (discard0 + 1) - len(me.discard)
    assert moved >= 1 and len(me.deck) == deck0 - 2 + moved
    assert all(c.title != "Pancakes!" for c in me.deck[-moved:])


@pytest.mark.parametrize("variant", [None, *SCHEME_VARIANTS])
def test_nothing_to_return_means_heal_and_draw(bprd, variant):
    g = bot_game(bprd, discard=())
    play(g, variant)
    assert g.fighters["hellboy"].hp == 14 and len(g.players[0].hand) == 2


@pytest.mark.parametrize("variant", [None, *SCHEME_VARIANTS])
def test_empty_deck_means_heal_and_return(bprd, variant):
    g = bot_game(bprd)
    me = g.players[0]
    me.discard.extend(me.deck)
    me.deck.clear()
    play(g, variant)
    assert g.fighters["hellboy"].hp == 14 and g.drawn[0] == 0
    assert len(me.deck) == 2 and all(c.title != "Pancakes!" for c in me.deck)


# ---------------------------------------------------------------- the session: chat and table

from sparring.ai_medusa import Act                                                       # noqa: E402
from test_action_announce_hold import announced_at, tag_of                                 # noqa: E402
from test_d3_table_effects import bot_turn, human_hand, to_bot_discard                    # noqa: E402,F401
from test_e2_human_cards import rig, with_rig                                             # noqa: E402,F401

HAND = ("Pancakes!", "Service Pistol", "Excalibur", "B.P.R.D. Training")


def pancakes_turn(session, table, game, **back):
    to_bot_discard(session, table, game, "Right Hand Of Doom", "Glimpse Of Hell")
    game.fighters["hellboy"].hp = back.get("hp", 12)
    human_hand(table, game, "Evade", "Fireball")
    pancakes = next(c for c in game.players[0].hand if c.title == "Pancakes!")
    return bot_turn(session, table, [Act("scheme", fid="hellboy", card=pancakes, variant="greedy")])


@with_rig("hellboy", "liz-sherman", *HAND, action_announce_hold=2.0)
def test_the_bot_says_both_effects_and_moves_the_drawn_cards_in_the_table(rig):
    session, table, game, fake, cfg = rig
    mark = len(table.scripts)
    msgs = pancakes_turn(session, table, game)
    line = next(m for m in msgs if m.startswith("El bot juega Pancakes!"))
    assert "Hellboy recupera 2 (12 -> 14) y roba 2" in line
    assert "PV:" not in line, "the heal is said once"
    announced_at(table.scripts[mark:], "El bot juega Pancakes!")
    assert len(game.players[0].hand) >= 2 and game.fighters["hellboy"].hp >= 14


@with_rig("hellboy", "liz-sherman", *HAND, action_announce_hold=2.0)
def test_the_bot_says_the_cards_it_puts_at_the_bottom_of_its_deck(rig):
    """verify_live: `card_to_deck_bottom` for the bot's discard has never been seen on the real table."""
    session, table, game, fake, cfg = rig
    msgs = pancakes_turn(session, table, game, hp=18)
    line = next(m for m in msgs if m.startswith("El bot juega Pancakes!"))
    assert "roba 2 y pone 2 cartas del descarte al fondo de su mazo" in line
    assert any("Right Hand Of Doom y Glimpse Of Hell de su descarte en el fondo de su mazo" in m for m in msgs)
    assert [kind for kind, _ in table.deck_moves].count("bottom") >= 1
    assert not any(i in table.bot_discard for _, ids in table.deck_moves for i in ids)
