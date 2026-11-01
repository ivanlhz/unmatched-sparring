"""Raphael as the bot (heuristic and ISMCTS) and as the rival of the five other heroes, headless to game over."""
import pytest

from sparring import sim

OTHERS = ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"]
PAIRS = [("raphael", o) for o in OTHERS] + [(o, "raphael") for o in OTHERS]
IDS = [f"{b}-vs-{h}" for b, h in PAIRS]


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_heuristic_games_finish(bot, human):
    for seed in range(5):
        assert sim.play(seed, bot_hero=bot, human_hero=human).turns >= 1


@pytest.mark.parametrize("bot,human", PAIRS, ids=IDS)
def test_ismcts_games_finish_without_falling_back(bot, human):
    for seed in range(3):
        ai = sim.make_bot("ismcts", iterations=6, seed=seed)
        out = sim.play(seed, bot_hero=bot, human_hero=human, medusa=ai, max_turns=30)
        assert out.turns >= 1 and ai.fallbacks == 0


def test_raphael_bot_uses_its_scheme_and_attacks_with_casey():
    """Over a few games the heuristic bot plays its scheme and attacks with Casey (ranged), not only with Raphael."""
    from sparring.ai_medusa import MedusaAI
    from sparring.board import Board
    from sparring.hellboy_script import ScriptedHellboy
    from sparring.state import Game
    seen = {"scheme": 0, "casey": 0}
    for seed in range(8):
        ai = MedusaAI(0)
        game = Game.new(Board.load("bprd-hq"), seed, {0: ai, 1: ScriptedHellboy(1, seed)}, bot_player=0,
                        heroes=("raphael", "hellboy"))
        real_scheme, real_attack = game.play_scheme, game.attack

        def scheme(*a, _real=real_scheme, **k):
            seen["scheme"] += 1
            return _real(*a, **k)

        def attack(att, tgt, card, *a, _real=real_attack, **k):
            seen["casey"] += att.fid == "casey"
            return _real(att, tgt, card, *a, **k)
        game.play_scheme, game.attack = scheme, attack
        for _ in range(40):
            if game.winner is not None:
                break
            game.begin_turn()
            if game.turn == 0:
                ai.take_turn(game)
            game.end_turn()
    assert seen["scheme"] > 0 and seen["casey"] > 0
