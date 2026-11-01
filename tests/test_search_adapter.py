"""Adapter of the current engine (Medusa vs Hellboy) to the search Protocol. The key point: determinization does not read the
rival's real hand."""
import random

import pytest

from sparring.search.adapter import PLACEMENT_KEEP, PLACEMENT_STRIKE_KEEP, SIDEKICK_POLICIES, EngineState, Knowledge
from sparring.state import ANUNG
from conftest import give, place


def set_destiny(game, n):
    game.players[1].discard = [c for c in game.players[1].full_set if c.destiny][:n]


def fill_hand(game, player, n):
    deck = game.players[player].deck
    while len(game.players[player].hand) < n:
        game.players[player].hand.append(deck.pop(0))


def medusa_hand(game, *titles):
    seen = {}
    for t in titles:
        seen[t] = seen.get(t, -1) + 1
        give(game, 0, t, seen[t])


# ---------- determinization ----------

def test_determinize_samples_rival_hand_from_public_info_only(game):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 5)
    set_destiny(game, 3)
    real_hand = list(game.players[1].hand)
    st = EngineState(game, observer=0)
    st.determinize(0, random.Random(1))
    opp = st.game.players[1]
    assert len(opp.hand) == 5
    assert not (set(opp.hand) & set(opp.discard)), "what was discarded cannot be in the hand"
    assert len(set(opp.hand)) == 5 and len(set(opp.deck) & set(opp.hand)) == 0
    assert sorted(c.card_id for c in opp.hand + opp.deck + opp.discard) == sorted(c.card_id for c in opp.full_set)
    assert real_hand != opp.hand or True   # may coincide by chance; what matters is the test below
    assert game.players[1].hand == real_hand, "the original game is not touched"


def test_determinize_is_blind_to_the_rival_real_hand(game):
    """Two identical games except for the rival's hidden hand: the same seed produces the same sample."""
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 5)
    other = game.clone()
    p = other.players[1]
    p.hand, p.deck = p.deck[:5], p.hand + p.deck[5:]      # another hand, same count, same discard
    assert game.players[1].hand != other.players[1].hand
    a, b = EngineState(game, observer=0), EngineState(other, observer=0)
    a.determinize(0, random.Random(9))
    b.determinize(0, random.Random(9))
    assert [c.card_id for c in a.game.players[1].hand] == [c.card_id for c in b.game.players[1].hand]
    assert [c.card_id for c in a.game.players[1].deck] == [c.card_id for c in b.game.players[1].deck]
    assert [c.card_id for c in a.game.players[0].deck] == [c.card_id for c in b.game.players[0].deck]


def test_determinize_keeps_known_cards_in_hand_and_shuffles_own_deck(game):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 4)
    known = [c for c in game.players[1].full_set if c.title == "Excalibur"]
    st = EngineState(game, observer=0, knowledge=Knowledge({1: tuple(known)}))
    own_before = [c.card_id for c in game.players[0].deck]
    orders = set()
    for seed in range(5):
        st.determinize(0, random.Random(seed))
        assert known[0] in st.game.players[1].hand and len(st.game.players[1].hand) == 4
        own = [c.card_id for c in st.game.players[0].deck]
        assert sorted(own) == sorted(own_before)
        orders.add(tuple(own))
    assert len(orders) > 1, "the order of the own deck is also hidden information"


def test_known_card_already_out_is_not_forced_into_the_hand(game):
    """If the seen card is already in the discard, the engine has discounted it; the adapter does not put it in either."""
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 3)
    exc = next(c for c in game.players[1].full_set if c.title == "Excalibur")
    game.players[1].discard.append(exc)
    st = EngineState(game, observer=0, knowledge=Knowledge({1: (exc,)}))
    st.determinize(0, random.Random(0))
    assert exc not in st.game.players[1].hand


def test_pending_attack_card_is_sampled_among_legal_attacks(game):
    """The bot defends: the human's face-down card is hidden and is sampled among the attacker's legal attacks."""
    place(game, medusa=4, hellboy=3, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 5)
    medusa_hand(game, "Hiss and Slither", "Feint")
    game.turn = 1
    game.actions_left = 1
    hb, medusa = game.fighters["hellboy"], game.fighters["medusa"]
    st = EngineState(game, observer=0, pending=(hb.fid, medusa.fid, None))
    assert st.player_to_move() == 0
    assert st.pending_card() is None, "at the root the human's card is hidden"
    for seed in range(10):
        sample = st.clone()                 # like the search: each iteration determinizes a clone of the root
        sample.determinize(0, random.Random(seed))
        card = sample.pending_card()
        assert card.can_attack and card.usable_by("Hellboy") and card in sample.game.players[1].hand
        assert len(sample.game.players[1].hand) == 5
    moves = st.legal_moves()
    assert ("defend", None) in moves and ("defend", "Hiss and Slither") in moves and ("defend", "Feint") in moves


def test_pending_attack_without_legal_attack_in_public_pool_falls_back(game):
    """Out-of-sync discard: every attack Hellboy can use is already in his discard. It does not blow up and the defense
    is decided against any card of the pool."""
    place(game, medusa=4, hellboy=3, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    st1 = game.players[1]
    st1.discard = [c for c in st1.full_set if c.can_attack and c.usable_by("Hellboy")]
    st1.deck = [c for c in st1.full_set if c not in st1.discard]
    st1.hand = st1.deck[:3]
    st1.deck = st1.deck[3:]
    medusa_hand(game, "Hiss and Slither")
    game.turn, game.actions_left = 1, 1
    st = EngineState(game, observer=0, pending=("hellboy", "medusa", None))
    for seed in range(5):
        sample = st.clone()
        sample.determinize(0, random.Random(seed))
        card = sample.pending_card()
        assert card is not None and card in sample.game.players[1].hand and card not in st1.discard
        sample.apply(("defend", "Hiss and Slither"))
        assert sample.pending is None
    from sparring.search.controller import IsmctsMedusa
    from sparring.search.ismcts import SearchConfig
    IsmctsMedusa(0, SearchConfig(iterations=50, seed=0)).choose_defense(game, game.fighters["hellboy"],
                                                                      game.fighters["medusa"])


def test_own_hand_and_deck_order_do_not_change_the_sample(game):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Dash", "Regroup")
    fill_hand(game, 1, 4)
    other = game.clone()
    random.Random(1).shuffle(other.players[0].deck)
    random.Random(2).shuffle(other.players[0].hand)
    a, b = EngineState(game, observer=0), EngineState(other, observer=0)
    a.determinize(0, random.Random(5))
    b.determinize(0, random.Random(5))
    assert [c.card_id for c in a.game.players[0].deck] == [c.card_id for c in b.game.players[0].deck]
    assert [c.card_id for c in a.game.players[0].hand] == [c.card_id for c in b.game.players[0].hand]
    assert a.legal_moves() == b.legal_moves()
    assert game.players[0].deck != other.players[0].deck, "the originals are not touched"


# ---------- moves ----------

def test_action_phase_moves_cover_attacks_schemes_and_maneuvers(game):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Second Shot", "Gaze of Stone", "A Momentary Glance", "Regroup")
    st = EngineState(game, observer=0)
    moves = st.legal_moves()
    kinds = {m[0] for m in moves}
    assert kinds == {"attack", "scheme", "maneuver"}
    assert ("attack", "medusa", "hellboy") in moves and ("attack", "medusa", "lobster") in moves
    assert ("scheme", "A Momentary Glance", "hellboy", None) in moves
    boosts = {m[1] for m in moves if m[0] == "maneuver"}
    assert None in boosts and len(boosts) >= 2
    assert len(moves) < 20, "the root is narrow: the action is decomposed into sub-moves"
    st.apply(("attack", "medusa", "hellboy"))
    cards = st.legal_moves()
    assert st.decision_pending() and st.player_to_move() == 0
    assert cards == [("attack_card", "medusa", "Second Shot"), ("attack_card", "medusa", "Gaze of Stone"),
                     ("attack_card", "medusa", "Regroup")], "unique titles, copies are not repeated"


def test_maneuver_is_two_chained_decisions(game):
    place(game, medusa=4, hellboy=27, lobster=28, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Regroup", "Dash")
    st = EngineState(game, observer=0)
    st.apply(("maneuver", "Regroup"))
    placements = st.legal_moves()
    assert st.decision_pending() and all(m[0] == "place" for m in placements) and ("place", 4, "stay") in placements
    options = st._hero_options(st.game.fighters["medusa"])
    assert len(options) > len(game.board.reachable(4, 3, set(), set())), "with boost 2 it reaches farther"
    # only the best placements enter the tree (pruning by static evaluation), all reachable
    assert {m[1] for m in placements} <= options and {m[2] for m in placements} <= set(SIDEKICK_POLICIES)
    assert len(placements) <= PLACEMENT_KEEP + PLACEMENT_STRIKE_KEEP + 1
    st.apply(("place", 4, "advance"))
    assert not st.decision_pending() and st.game.actions_left == 1
    assert st.game.fighters["medusa"].pos == 4
    assert "Regroup" in [c.title for c in st.game.players[0].discard]
    assert any(st.game.fighters[h].pos != p for h, p in (("harpy1", 20), ("harpy2", 21), ("harpy3", 22)))


def test_single_option_subphases_resolve_themselves(game):
    """A single attack title and no living sidekicks: the card and the sidekicks open no decisions."""
    place(game, medusa=4, hellboy=2, lobster=3)
    for fid in ("harpy1", "harpy2", "harpy3"):
        game.fighters[fid].alive, game.fighters[fid].pos = False, None
    medusa_hand(game, "Second Shot", "Second Shot")
    fill_hand(game, 1, 5)
    st = EngineState(game, observer=0)
    st.apply(("attack", "medusa", "hellboy"))
    assert st.pending is not None and st.pending[2].title == "Second Shot" and st.player_to_move() == 1
    st2 = EngineState(game, observer=0)
    st2.apply(("maneuver", None))
    assert st2.phase == "maneuver_place"
    assert all(m[2] == "stay" for m in st2.legal_moves()), "without living sidekicks, the only policy is to stay"
    st2.apply(("place", 4, "stay"))
    assert not st2.decision_pending() and st2.game.actions_left == 1


def test_apply_attack_then_defend_resolves_combat(game):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Dash")
    fill_hand(game, 1, 2)
    st = EngineState(game, observer=0)
    st.determinize(0, random.Random(0))
    st.apply(("attack", "medusa", "hellboy"))
    st.apply(("attack_card", "medusa", "Second Shot"))
    assert st.player_to_move() == 1 and all(m[0] == "defend" for m in st.legal_moves())
    assert st.observe(("attack_card", "medusa", "Second Shot"), 1) == ("attack_card", "medusa", None)
    assert st.observe(("attack_card", "medusa", "Second Shot"), 0) == ("attack_card", "medusa", "Second Shot")
    st.apply(("defend", None))
    assert st.observe(("defend", None), 1) == ("defend", None) == st.observe(("defend", None), 0)
    assert st.game.fighters["hellboy"].hp == 18 - 3
    assert st.game.actions_left == 1 and st.player_to_move() == 0


def test_turn_ends_and_rival_start_of_turn_is_automatic(game):
    place(game, medusa=4, hellboy=27, lobster=28, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Regroup")
    fill_hand(game, 1, 3)
    st = EngineState(game, observer=0)
    st.determinize(0, random.Random(0))
    for _ in range(2):
        st.apply(("maneuver", None))
        st.apply(("place", 4, "stay"))
    assert st.player_to_move() == 1 and st.game.actions_left == 2 and st.game.turn == 1


def test_anung_start_is_a_decision_of_hellboy(game):
    game.fx.dsl_heroes.discard("hellboy")        # interpreted (E2), the dispatcher does it at begin_turn: no anung moves
    place(game, medusa=4, hellboy=27, lobster=28, harpy1=20, harpy2=21, harpy3=22)
    set_destiny(game, 6)
    fill_hand(game, 1, 3)
    game.turn = 1
    st = EngineState(game, observer=1, phase="start")
    assert st.game.form(1) == ANUNG
    moves = st.legal_moves()
    assert moves and all(m[0] == "anung" for m in moves)
    hand = st.game.players[1].hand
    st.apply(max(moves, key=lambda m: next(c.boost for c in hand if c.title == m[1])))   # with boost 1 there is no destination
    dests = st.legal_moves()
    assert all(m[0] == "anung_to" for m in dests) and ("anung_to", None) in dests
    st.apply(("anung_to", None))
    assert len(st.game.players[1].hand) == 2 and st.game.actions_left == 2 and st.game.fighters["hellboy"].pos == 27


def test_evaluate_is_symmetric_and_terminal(game):
    place(game, medusa=4, hellboy=27, lobster=28, harpy1=20, harpy2=21, harpy3=22)
    st = EngineState(game, observer=0)
    assert abs(st.evaluate(0) + st.evaluate(1) - 1.0) < 1e-9
    game.fighters["hellboy"].hp = 1
    assert EngineState(game, observer=0).evaluate(0) > st.evaluate(0)
    game.damage(game.fighters["hellboy"], 5)
    t = EngineState(game, observer=0)
    assert t.is_terminal() and t.winner() == 0 and t.evaluate(0) == 1.0 and t.evaluate(1) == 0.0


def test_rollout_move_is_legal(game):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Dash", "Winged Frenzy")
    fill_hand(game, 1, 4)
    st = EngineState(game, observer=0)
    st.determinize(0, random.Random(2))
    rng = random.Random(0)
    for _ in range(30):
        if st.is_terminal():
            break
        m = st.rollout_move(rng)
        if m[0] == "place":         # the rollout moves the hero over its whole reach, without the tree's pruning
            assert m[1] in st._hero_options(st.game.hero(st.game.turn)) and m[2] in SIDEKICK_POLICIES, m
        else:
            assert m in st.legal_moves(), m
        st.apply(m)
