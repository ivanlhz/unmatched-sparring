"""Real scenario: Medusa (2 HP, no Harpies, 1 card in the deck, hand of 7) against Hellboy (14 HP, ANUNG UN RAMA) on
space 30. The bot did "maneuver, maneuver" without moving, drew past the limit and discarded good cards."""
import pytest

from sparring import sim
from sparring.ai_medusa import MedusaAI, Model, keep_value
from sparring.state import ANUNG, EXHAUST_DAMAGE, HAND_LIMIT
from conftest import give, place

HAND = ["Second Shot", "Clutching Claws", "Clutching Claws", "The Hounds of Mighty Zeus", "The Hounds of Mighty Zeus",
        "Gaze of Stone", "Dash"]


@pytest.fixture
def ai(game):
    a = MedusaAI(0)
    game.controllers[0] = a
    return a


def endgame(game, deck_left=1, medusa_pos=0, hellboy_pos=30, hand=HAND, lobster=False):
    """Exact state of the live game (the rival's hand is 5 unknown cards)."""
    seen = {}
    for t in hand:
        seen[t] = seen.get(t, -1) + 1
        give(game, 0, t, seen[t])
    p = game.players[0]
    rest = [c for c in p.full_set if c not in p.hand]
    p.deck[:] = rest[:deck_left]
    p.discard[:] = rest[deck_left:]
    medusa = game.fighters["medusa"]
    medusa.hp = 2
    place(game, medusa=medusa_pos, hellboy=hellboy_pos)
    for fid in ("harpy1", "harpy2", "harpy3") + (() if lobster else ("lobster",)):
        f = game.fighters[fid]
        f.alive, f.pos, f.hp = False, None, 0
    if lobster:
        place(game, lobster=27)
    game.fighters["hellboy"].hp = 14
    h = game.players[1]
    h.discard[:] = [c for c in h.full_set if c.destiny][:6]
    while len(h.hand) < 5:
        h.hand.append(next(c for c in h.deck if c not in h.hand and c not in h.discard))
    assert game.form(1) == ANUNG
    return game


def play_turn(game, ai):
    """A whole bot turn without the ability (there is nobody in her zone at the start) nor end of turn."""
    ai.take_turn(game)


def test_live_state_no_pointless_double_maneuver(game, ai):
    endgame(game)
    first = ai.plan(game)
    assert first.kind != "maneuver" or first.moves["medusa"] != 0, "the maneuver does not move"
    play_turn(game, ai)
    medusa = game.fighters["medusa"]
    assert medusa.alive
    assert game.winner is None
    assert len(game.players[0].deck) == 0 or game.players[0].deck, "it cannot have drawn more than the deck"


def test_live_state_moves_into_hellboys_zone_and_attacks(game, ai):
    endgame(game)
    start = len(game.players[0].hand)
    play_turn(game, ai)
    hb = game.fighters["hellboy"]
    medusa = game.fighters["medusa"]
    assert game.board.share_zone(medusa.pos, hb.pos), "Medusa had to enter Hellboy's zone"
    assert hb.hp < 14, "it had to attack Hellboy with the best card"
    assert medusa.hp == 2, "the deck cannot be exhausted"
    assert len(game.players[0].deck) == 0 and game.drawn[0] <= 1


def test_live_state_plan_is_maneuver_then_attack(game, ai):
    endgame(game)
    a1 = ai.plan(game)
    assert a1.kind == "maneuver"
    assert a1.boost is not None, "to reach the beige zone (5 spaces) it needs a boost"
    assert game.board.share_zone(a1.moves["medusa"], 30)
    g1 = ai.apply_expected(game, a1)
    a2 = ai.candidates(g1, Model(g1, 0))[0]
    assert a2.kind == "attack" and a2.target == "hellboy"


def test_never_picks_exhaustion_suicide_when_alternative_exists(game, ai):
    endgame(game, deck_left=0, medusa_pos=29, hellboy_pos=30)  # already in his zone: she can attack
    act = ai.plan(game)
    assert act.kind != "maneuver"
    g = ai.apply_expected(game, ai.maneuver_acts(game, Model(game, 0))[0])
    assert g.winner == 1 and not g.fighters["medusa"].alive


def test_snipe_and_regroup_not_played_to_death(game, ai):
    endgame(game, deck_left=0, medusa_pos=29, hellboy_pos=30, hand=["Snipe", "Regroup", "Dash", "Gaze of Stone"])
    for _ in range(2):
        act = ai.plan(game)
        assert not (act.kind == "attack" and act.card.title in ("Snipe", "Regroup"))
        ai.execute(game, act)
        game.log.clear()
        if game.winner is not None:
            break
    assert game.winner is None


def test_apply_expected_models_exhaustion(game, ai):
    endgame(game, deck_left=1, medusa_pos=29, hellboy_pos=30)
    man = ai.maneuver_acts(game, Model(game, 0))[0]
    g1 = ai.apply_expected(game, man)
    assert g1.winner is None and len(g1.players[0].deck) == 0 and g1.phantom_draws == 1
    g2 = ai.apply_expected(g1, man)
    assert g2.winner == 1 and g2.fighters["medusa"].hp == 2 - EXHAUST_DAMAGE


def test_maneuver_at_hand_limit_pays_for_the_discarded_card(game, ai):
    endgame(game, deck_left=10, medusa_pos=29, hellboy_pos=30)
    model = Model(game, 0)
    man = next(a for a in ai.candidates(game, model) if a.kind == "maneuver" and a.boost is None
               and a.moves["medusa"] == 29)
    assert len(game.players[0].hand) == HAND_LIMIT
    g = ai.apply_expected(game, man)
    hand = game.players[0].hand
    assert ai.terminal_value(g) <= -min(keep_value(c, hand) for c in hand) + 1e-9


def test_desperation_rises_when_losing_only(game, ai):
    endgame(game)
    assert ai.desperation(game) > 0.7
    fresh = sim.Game.new(game.board, 1, {0: ai, 1: ai.__class__(1)})
    assert ai.desperation(fresh) < 0.1


def test_aggression_beats_kiting_when_time_is_against_us(game, ai):
    endgame(game, deck_left=1, medusa_pos=29, hellboy_pos=30)
    play_turn(game, ai)   # attacks from where he cannot reach her (maneuver + shot) or shoots now: never flees without attacking
    assert game.fighters["medusa"].alive and game.winner is None
    assert game.fighters["hellboy"].hp < 14


def test_live_state_with_lobster_alive_still_survives_and_attacks(game, ai):
    endgame(game, lobster=True)
    play_turn(game, ai)
    assert game.fighters["medusa"].alive and game.winner is None
