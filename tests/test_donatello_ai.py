"""The bot's judgement with Donatello's cards: inventions are kept and played early, removals take the cheapest cards,
and the search bot plays him on both sides without falling back."""
import pytest

from sparring import sim
from sparring.ai_medusa import MedusaAI, keep_value
from test_donatello_effects import adjacent, attack, g, give, make, to_discard  # noqa: F401


def test_the_bot_never_gives_up_an_invention_before_a_plain_card(g):
    hand = [give(g, t) for t in ("Electro grenade", "Self defense grid", "Smoke bomb", "Quick strike", "Turtle power!")]
    worst = sorted(hand, key=lambda c: (keep_value(c, hand), c.card_id))[:2]
    assert not any("invention" in c.tags for c in worst)
    chosen = MedusaAI(0).choose_discard(g, 0, 2, "hand limit")
    assert sorted(c.card_id for c in chosen) == sorted(c.card_id for c in worst)


def test_the_bot_removes_its_cheapest_cards_up_to_the_limit(g):
    g.controllers[0] = MedusaAI(0)
    eg = give(g, "Electro grenade")
    cheap = [to_discard(g, "Quick strike", nth=i) for i in range(3)]
    strong = [to_discard(g, "Turtle power!", nth=i) for i in range(2)]
    res = attack(g, eg)
    assert set(cheap) <= set(g.players[0].removed) and len([c for c in strong if c in g.players[0].discard]) == 1
    assert res.atk_value == 2 + len(g.players[0].removed)



@pytest.mark.parametrize("other", ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"])
def test_the_search_bot_plays_donatello_both_ways_without_falling_back(other):
    for bot, human in (("donatello", other), (other, "donatello")):
        ai = sim.make_bot("ismcts", iterations=6, seed=1)
        out = sim.play(1, bot_hero=bot, human_hero=human, medusa=ai, max_turns=30)
        assert out.turns >= 1 and ai.fallbacks == 0


# ---------------------------------------------------------------- the bot's square for Party wagon! (damage to a rival it passed)

def wagon_game(bprd):
    from test_donatello_effects import make
    g = make(bprd, human="baba-yaga")
    g.controllers[0] = MedusaAI(0)
    return g


def wagon_request(g, card):
    from sparring.effects.choose import ChoiceRequest
    don = g.hero(0)
    return ChoiceRequest("space", 0, sorted(g.legal_moves(don, 5, True)), 0, 1, card.card_id, "k", "move to",
                         {"fighter": "donatello", "op": "move", "steps": 5, "through": True, "up_to": True}, 0)


def test_the_bot_moves_through_a_one_hp_sidekick_with_party_wagon_and_kills_it(bprd):
    from sparring.ai_effects import EffectAI
    from sparring.effects.ops_core import _passed_through
    g = wagon_game(bprd)
    don = g.hero(0)
    sidekick = next(f for f in g.own(1) if not f.hero)
    a = sorted(g.board.spaces)[0]
    b = min(g.board.adj[a])
    don.pos, sidekick.pos, sidekick.hp = a, b, 1
    for f in g.fighters.values():
        if f.alive and f.fid not in ("donatello", sidekick.fid, "metalhead"):
            f.pos = max(g.board.spaces, key=lambda s: g.board.distance(a, s))
    g.fighters["metalhead"].alive, g.fighters["metalhead"].pos = False, None       # Donatello is the only mover to choose
    pw = give(g, "Party wagon!")
    dest = EffectAI(0).choose_effect(g, wagon_request(g, pw))
    assert dest and sidekick.fid in _passed_through(g, don, a, dest[0], 5, True)
    g.play_scheme(0, don, pw)
    assert not sidekick.alive


def test_party_wagon_damages_one_chosen_rival_so_the_bot_values_the_best_single_blow(bprd):
    from sparring.ai_effects import EffectAI
    from test_donatello_effects import give as give_wagon
    g = wagon_game(bprd)
    pw = give_wagon(g, "Party wagon!")
    assert EffectAI._pass_damage(g, wagon_request(g, pw)) == (2.0, False)
