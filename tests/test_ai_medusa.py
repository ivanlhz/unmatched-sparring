import pytest

from sparring import sim
from sparring.ai_medusa import MedusaAI, Model
from sparring.state import ANUNG, DETECTIVE
from conftest import give, place


@pytest.fixture
def ai(game):
    a = MedusaAI(0)
    game.controllers[0] = a
    return a


def set_destiny(game, n):
    game.players[1].discard = [c for c in game.players[1].full_set if c.destiny][:n]


def fill_hand(game, player, n):
    """Rival hand with n cards from the deck (the hand size matters for the model)."""
    deck = game.players[player].deck
    while len(game.players[player].hand) < n:
        game.players[player].hand.append(deck.pop(0))


def test_ability_prefers_killing_lobster_at_one_hp(game, ai):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    game.fighters["lobster"].hp = 1
    assert game.board.share_zone(4, 2) and game.board.share_zone(4, 3)
    assert ai.pick_ability_target(game).fid == "lobster"
    game.fighters["lobster"].hp = 6
    assert ai.pick_ability_target(game).fid == "hellboy"
    game.fighters["lobster"].hp = 3
    assert ai.pick_ability_target(game).fid == "lobster"


def test_ability_not_used_without_target(game, ai):
    place(game, medusa=0, hellboy=27, lobster=28, harpy1=1, harpy2=2, harpy3=3)
    assert not game.board.share_zone(0, 27) and not game.board.share_zone(0, 28)
    assert ai.pick_ability_target(game) is None


def test_take_turn_uses_ability_first(game, ai):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    game.fighters["lobster"].hp = 1
    ai.take_turn(game)
    assert not game.fighters["lobster"].alive


def strike_steps(board, hb_pos, target_pos):
    """Steps Hellboy (melee) needs to end adjacent to the target."""
    return min(board.distance(hb_pos, s) for s in board.adj[target_pos])


def test_kiting_retreats_out_of_hellboy_reach(game, ai):
    b = game.board
    # scenario: Medusa is within Hellboy's reach without a boost and can leave it with a maneuver
    m, h = next((m, h) for h in b.spaces for m in b.spaces
                if 0 < strike_steps(b, h, m) <= 2 and max(strike_steps(b, h, d) for d in b.reachable(m, 3, set(), set())) >= 3)
    place(game, medusa=m, hellboy=h, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    game.players[0].deck[:] = [c for c in game.players[0].full_set if c.title == "Hiss and Slither"]
    fill_hand(game, 1, 5)  # empty hand and a deck without attacks: she can only reposition, with no defense to protect her
    game.actions_left = 1
    ai.take_turn(game)
    assert strike_steps(b, h, game.fighters["medusa"].pos) > 2


def test_position_is_riskier_in_anung(game, ai):
    place(game, medusa=5, hellboy=9, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 5)
    set_destiny(game, 5)
    assert game.form(1) == DETECTIVE
    calm = ai.position_value(game, Model(game, 0))
    set_destiny(game, 6)
    assert game.form(1) == ANUNG
    assert ai.position_value(game, Model(game, 0)) < calm


def test_prefers_attack_when_target_is_exposed(game, ai):
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    give(game, 0, "Gaze of Stone")
    act = ai.plan(game)  # the rival has no cards in hand: it cannot defend
    assert act.kind == "attack" and act.card.title == "Gaze of Stone"


def test_defense_picks_hiss_when_no_transformation_risk(game, ai):
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    hiss = give(game, 0, "Hiss and Slither")
    give(game, 0, "Snipe")
    fill_hand(game, 1, 5)
    assert ai.choose_defense(game, game.fighters["hellboy"], game.fighters["medusa"]) is hiss


def test_defense_avoids_hiss_when_hellboy_is_close_to_transforming(game, ai):
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    give(game, 0, "Hiss and Slither")
    give(game, 0, "Snipe")
    fill_hand(game, 1, 5)
    set_destiny(game, 5)  # one destiny short
    choice = ai.choose_defense(game, game.fighters["hellboy"], game.fighters["medusa"])
    assert choice is None or choice.title != "Hiss and Slither"


def test_defense_uses_card_against_strong_anung_attack(game, ai):
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    give(game, 0, "Snipe")
    give(game, 0, "Feint")
    fill_hand(game, 1, 6)
    set_destiny(game, 6)
    choice = ai.choose_defense(game, game.fighters["hellboy"], game.fighters["medusa"])
    assert choice is not None


def test_clutching_claws_penalized_near_transformation_unless_decisive(game, ai):
    place(game, medusa=20, hellboy=1, harpy1=0, lobster=27, harpy2=21, harpy3=22)
    claws = give(game, 0, "Clutching Claws")
    snipe = give(game, 0, "Snipe")
    fill_hand(game, 1, 5)
    harpy, hb = game.fighters["harpy1"], game.fighters["hellboy"]
    model = Model(game, 0)
    far = ai.eval_attack(game, model, harpy, hb, claws) - ai.eval_attack(game, model, harpy, hb, snipe)
    set_destiny(game, 5)
    model = Model(game, 0)
    near = ai.eval_attack(game, model, harpy, hb, claws) - ai.eval_attack(game, model, harpy, hb, snipe)
    assert far > 0 > near
    # decisive: kills Lobster (1 life) and then no penalty applies
    lob = game.fighters["lobster"]
    place(game, lobster=2)
    lob.hp = 1
    game.players[1].hand.clear()  # no possible defense, death is certain
    model = Model(game, 0)
    decisive = ai.eval_attack(game, model, harpy, lob, claws) - ai.eval_attack(game, model, harpy, lob, snipe)
    assert decisive > 0


def test_deterministic_with_fixed_seed():
    a = sim.play(7)
    b = sim.play(7)
    assert a == b


def test_cli_hundred_games_no_exceptions(capsys):
    assert sim.main(["--games", "100", "--seed", "1000"]) == 0
    out = capsys.readouterr().out
    assert "games=100 errors=0" in out


def test_ai_never_acts_illegally_on_both_maps():
    for key in ("bprd-hq", "azuchi-castle"):
        for seed in range(5):
            sim.play(seed, key)
