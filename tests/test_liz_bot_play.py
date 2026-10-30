"""Bot-Liz must close in and attack instead of manoeuvring in place (reported live 30/10: two turns of manoeuvres at her
start space 3 with Hellboy at 13 and the Lobster at 12, then a hand over the limit). Position and hand come from that
save; no TTS and no sockets."""
import pytest

from sparring.ai_medusa import MedusaAI, Model
from sparring.board import Board
from sparring.hellboy_script import ScriptedHellboy
from sparring.state import Game

BOT, HUMAN = 0, 1
# Liz's hand in the saved session (CardIDs of sheet 199): Incinerate, Burning Barrier, Fleeting Moments, Fireball,
# Pyrotechnics, Flame Lash, Fight Or Flight
SAVED_HAND = [19900, 19909, 19906, 19901, 19913, 19904, 19927]


def reported_position() -> tuple[Game, MedusaAI]:
    ai = MedusaAI(BOT)
    game = Game.new(Board.load("bprd-hq"), 1, {BOT: ai, HUMAN: ScriptedHellboy(HUMAN, 0)}, bot_player=BOT,
                    heroes=("liz-sherman", "hellboy"))
    me, rival = game.players[BOT], game.players[HUMAN]
    by_id = {c.card_id: c for c in me.full_set}
    hand = [by_id[i] for i in SAVED_HAND]
    me.hand[:] = hand
    me.deck[:] = [c for c in me.full_set if c not in hand]
    rival.discard.clear()
    for fid, pos in (("liz", 3), ("hellboy", 13), ("lobster", 12)):
        game.fighters[fid].pos = pos
    game.turn, game.actions_left = BOT, 2
    return game, ai


def test_liz_walks_into_reach_and_attacks_in_the_same_turn():
    game, ai = reported_position()
    liz = game.hero(BOT)
    assert not any(game.can_attack(liz, e) for e in game.foes(BOT))
    attacks = []
    real_attack = game.attack
    game.attack = lambda *a, **k: (attacks.append(a), real_attack(*a, **k))[1]
    ai.take_turn(game)
    assert liz.pos != 3
    assert any(game.board.can_reach_target(liz.pos, e.pos, liz.ranged) for e in game.foes(BOT))
    assert len(attacks) == 1, "the second action should be an attack, not another draw"


def test_liz_far_from_every_rival_still_closes_the_distance():
    game, ai = reported_position()
    game.fighters["hellboy"].pos, game.fighters["lobster"].pos = 30, 19
    liz = game.hero(BOT)
    before = min(game.board.distance(3, e.pos) for e in game.foes(BOT))
    ai.take_turn(game)
    after = min(game.board.distance(liz.pos, e.pos) for e in game.foes(BOT))
    assert after < before or liz.pos != 3


def test_medusa_keeps_her_own_rules():
    """The approach rules are for the other heroes: Medusa's first act on a fresh game does not change."""
    game = Game.new(Board.load("bprd-hq"), 7, {BOT: MedusaAI(BOT), HUMAN: ScriptedHellboy(HUMAN, 7)}, bot_player=BOT)
    ai = game.controllers[BOT]
    assert ai.approach_acts(game, ai.candidates(game, Model(game, BOT))) == []


@pytest.mark.parametrize("bot_hero, rival_hero", [("hellboy", "baba-yaga"), ("abe-sapien", "baba-yaga"),
                                                  ("baba-yaga", "abe-sapien"), ("liz-sherman", "hellboy")])
def test_every_non_medusa_hero_with_an_attack_walks_into_reach_of_a_far_rival(bot_hero, rival_hero):
    """The approach rules apply to every bot hero but Medusa: with the rival hero four spaces away and the rest of the
    pieces out of the way, the bot ends its turn having attacked, or in reach of a rival."""
    ai = MedusaAI(BOT)
    game = Game.new(Board.load("bprd-hq"), 5, {BOT: ai, HUMAN: ScriptedHellboy(HUMAN, 0)}, bot_player=BOT,
                    heroes=(bot_hero, rival_hero))
    spaces = sorted(game.board.spaces, reverse=True)
    others = [f for f in game.fighters.values() if not f.hero]
    for f, space in zip(others, spaces):
        f.pos = space
    game.hero(BOT).pos, game.hero(HUMAN).pos = 3, 13
    hero = game.hero(BOT)
    assert any(c.can_attack and c.usable_by(hero.name) for c in game.players[BOT].hand)
    attacks = []
    real_attack = game.attack
    game.attack = lambda *a, **k: (attacks.append(a), real_attack(*a, **k))[1]
    game.turn, game.actions_left = BOT, 2
    ai.take_turn(game)
    assert hero.pos != 3
    assert attacks or any(game.board.can_reach_target(hero.pos, e.pos, hero.ranged) for e in game.foes(BOT))
