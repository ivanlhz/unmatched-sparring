"""Adaptador del motor actual (Medusa vs Hellboy) al Protocol de busqueda. Lo central: la determinizacion no lee la
mano real del rival."""
import random

import pytest

from sparring.search.adapter import EngineState, Knowledge
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


# ---------- determinizacion ----------

def test_determinize_samples_rival_hand_from_public_info_only(game):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 5)
    set_destiny(game, 3)
    real_hand = list(game.players[1].hand)
    st = EngineState(game, observer=0)
    st.determinize(0, random.Random(1))
    opp = st.game.players[1]
    assert len(opp.hand) == 5
    assert not (set(opp.hand) & set(opp.discard)), "lo descartado no puede estar en la mano"
    assert len(set(opp.hand)) == 5 and len(set(opp.deck) & set(opp.hand)) == 0
    assert sorted(c.card_id for c in opp.hand + opp.deck + opp.discard) == sorted(c.card_id for c in opp.full_set)
    assert real_hand != opp.hand or True   # puede coincidir por azar; lo que importa es el test de abajo
    assert game.players[1].hand == real_hand, "el juego original no se toca"


def test_determinize_is_blind_to_the_rival_real_hand(game):
    """Dos partidas identicas salvo la mano oculta del rival: la misma semilla produce la misma muestra."""
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 5)
    other = game.clone()
    p = other.players[1]
    p.hand, p.deck = p.deck[:5], p.hand + p.deck[5:]      # otra mano, mismo conteo, mismo descarte
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
    assert len(orders) > 1, "el orden del mazo propio tambien es informacion oculta"


def test_known_card_already_out_is_not_forced_into_the_hand(game):
    """Si la carta vista ya esta en el descarte, el motor la ha descontado; el adaptador tampoco la mete."""
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 3)
    exc = next(c for c in game.players[1].full_set if c.title == "Excalibur")
    game.players[1].discard.append(exc)
    st = EngineState(game, observer=0, knowledge=Knowledge({1: (exc,)}))
    st.determinize(0, random.Random(0))
    assert exc not in st.game.players[1].hand


def test_pending_attack_card_is_sampled_among_legal_attacks(game):
    """El bot defiende: la carta boca abajo del humano es oculta y se muestrea entre los ataques legales del atacante."""
    place(game, medusa=4, hellboy=3, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 5)
    medusa_hand(game, "Hiss and Slither", "Feint")
    game.turn = 1
    game.actions_left = 1
    hb, medusa = game.fighters["hellboy"], game.fighters["medusa"]
    st = EngineState(game, observer=0, pending=(hb.fid, medusa.fid, None))
    assert st.player_to_move() == 0
    assert st.pending_card() is None, "en la raiz la carta del humano es oculta"
    for seed in range(10):
        sample = st.clone()                 # como la busqueda: cada iteracion determiniza un clon de la raiz
        sample.determinize(0, random.Random(seed))
        card = sample.pending_card()
        assert card.can_attack and card.usable_by("Hellboy") and card in sample.game.players[1].hand
        assert len(sample.game.players[1].hand) == 5
    moves = st.legal_moves()
    assert ("defend", None) in moves and ("defend", "Hiss and Slither") in moves and ("defend", "Feint") in moves


# ---------- jugadas ----------

def test_action_phase_moves_cover_attacks_schemes_and_maneuvers(game):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Second Shot", "Gaze of Stone", "A Momentary Glance", "Regroup")
    st = EngineState(game, observer=0)
    moves = st.legal_moves()
    kinds = {m[0] for m in moves}
    assert kinds == {"attack", "scheme", "maneuver"}
    attacks = [m for m in moves if m[0] == "attack"]
    assert ("attack", "medusa", "hellboy", "Second Shot") in attacks
    assert sum(1 for m in attacks if m[3] == "Second Shot" and m[2] == "hellboy") == 1, "las copias no se repiten"
    assert ("scheme", "A Momentary Glance", "hellboy", None) in moves
    boosts = {m[1] for m in moves if m[0] == "maneuver"}
    assert None in boosts and len(boosts) >= 2


def test_apply_attack_then_defend_resolves_combat(game):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot")
    fill_hand(game, 1, 2)
    st = EngineState(game, observer=0)
    st.determinize(0, random.Random(0))
    st.apply(("attack", "medusa", "hellboy", "Second Shot"))
    assert st.player_to_move() == 1 and all(m[0] == "defend" for m in st.legal_moves())
    assert st.observe(("attack", "medusa", "hellboy", "Second Shot"), 1) == ("attack", "medusa", "hellboy", None)
    assert st.observe(("attack", "medusa", "hellboy", "Second Shot"), 0) == ("attack", "medusa", "hellboy", "Second Shot")
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
    st.apply(("maneuver", None, (("medusa", 4), ("harpy1", 20), ("harpy2", 21), ("harpy3", 22))))
    assert st.game.actions_left == 1
    st.apply(("maneuver", None, (("medusa", 4), ("harpy1", 20), ("harpy2", 21), ("harpy3", 22))))
    assert st.player_to_move() == 1 and st.game.actions_left == 2 and st.game.turn == 1


def test_anung_start_is_a_decision_of_hellboy(game):
    place(game, medusa=4, hellboy=27, lobster=28, harpy1=20, harpy2=21, harpy3=22)
    set_destiny(game, 6)
    fill_hand(game, 1, 3)
    game.turn = 1
    st = EngineState(game, observer=1, phase="start")
    assert st.game.form(1) == ANUNG
    moves = st.legal_moves()
    assert moves and all(m[0] == "anung" for m in moves)
    st.apply(moves[0])
    assert len(st.game.players[1].hand) == 2 and st.game.actions_left == 2


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
        assert m in st.legal_moves(), m
        st.apply(m)
