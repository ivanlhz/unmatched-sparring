"""Donatello's cards, INVENTIVE and the inventions on the engine (bot side: the controllers decide)."""
import pytest

from conftest import Scripted, card
from sparring import persist
from sparring.ai_medusa import MedusaAI
from sparring.combat import resolve_combat
from sparring.effects import ongoing
from sparring.effects.choose import ScriptedChooser
from sparring.state import Game


def make(bprd, human="hellboy", seed=3):
    g = Game.new(bprd, seed=seed, controllers={0: Scripted(), 1: Scripted()}, bot_player=0, heroes=("donatello", human))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def adjacent(g, a="donatello", b="hellboy"):
    s = sorted(g.board.spaces)[0]
    g.fighters[a].pos, g.fighters[b].pos = s, min(g.board.adj[s])
    g.fighters["metalhead"].pos = max(g.board.spaces)


def give(g, title, player=0, nth=0):
    c = card(g, player, title, nth)
    for zone in (g.players[player].deck, g.players[player].discard):
        if c in zone:
            zone.remove(c)
    g.players[player].hand.append(c)
    return c


def to_discard(g, title, player=0, nth=0):
    c = card(g, player, title, nth)
    for zone in (g.players[player].deck, g.players[player].hand):
        if c in zone:
            zone.remove(c)
    g.players[player].discard.append(c)
    return c


def rival_attack(g, nth=0):
    """A plain attack of the human (Hellboy) put in their hand: the strongest attack cards, no effect asked."""
    plain = [c for c in g.players[1].full_set if c.type == "attack" and (c.value or 0) >= 3 and "ANUNG" not in c.text]
    c = plain[nth]
    g.players[1].hand.append(c)
    return c


@pytest.fixture
def g(bprd):
    g = make(bprd)
    adjacent(g)
    return g


def attack(g, atk, dfn=None):
    return resolve_combat(g, g.hero(0), g.hero(1), atk, dfn)


def test_quick_strike_draws_one_after_combat(g):
    q = give(g, "Quick strike")
    before = len(g.players[0].deck)
    attack(g, q)
    assert len(g.players[0].hand) == 1 and len(g.players[0].deck) == before - 1


def test_bo_staff_hits_an_adjacent_rival_and_draws_when_defending(g):
    g.turn = 1
    bo = give(g, "Bo staff")
    atk = rival_attack(g)
    hp = g.hero(1).hp
    resolve_combat(g, g.hero(1), g.hero(0), atk, bo)
    assert g.hero(1).hp == hp - 1 and len(g.players[0].hand) == 1


def test_thinking_ahead_puts_a_discard_card_at_the_bottom_only_when_it_won(g):
    t = give(g, "Thinking ahead")
    old = to_discard(g, "Quick strike")
    attack(g, t)                              # no defense: it wins
    assert g.players[0].deck[-1] is old and old not in g.players[0].discard
    g2 = make(g.board)
    adjacent(g2)
    t2, old2 = give(g2, "Thinking ahead"), to_discard(g2, "Quick strike")
    big = max((c for c in g2.players[1].full_set if c.can_defend), key=lambda c: c.value)
    g2.players[1].hand.append(big)
    attack(g2, t2, big)                       # lost
    assert old2 in g2.players[0].discard


def test_short_circuit_cancels_only_the_after_combat_of_the_opposing_card(g):
    sc = give(g, "Short circuit")
    after = next(c for c in g.players[1].full_set if c.can_defend and "AFTER COMBAT" in c.text and "Draw" in c.text)
    g.players[1].hand.append(after)
    hand0 = len(g.players[1].hand)
    attack(g, sc, after)
    assert len(g.players[1].hand) == hand0 - 1          # played; its draw was cancelled


def test_short_circuit_keeps_the_other_moments(g):
    sc = give(g, "Short circuit")
    during = next(c for c in g.players[1].full_set if c.can_defend and "DURING COMBAT" in c.text)
    g.players[1].hand.append(during)
    res = attack(g, sc, during)
    assert "def" not in res.cancelled                     # not a full cancel


def test_untested_enhancements_adds_the_boost_of_the_bottom_card(g):
    u = give(g, "Untested enhancements")
    bottom = g.players[0].deck[-1]
    res = attack(g, u)
    assert bottom in g.players[0].discard and res.atk_value == 3 + bottom.boost


def test_turtle_power_may_boost_from_the_hand(g):
    tp = give(g, "Turtle power!")
    spare = give(g, "Quick strike")
    flow_res = resolve_combat(g, g.hero(0), g.hero(1), tp, None, boost=spare)
    assert flow_res.atk_value >= 3


def test_heroes_in_a_half_shell_is_a_plain_5(g):
    g.turn = 1
    hh = give(g, "Heroes in a half shell")
    atk = rival_attack(g)
    res = resolve_combat(g, g.hero(1), g.hero(0), atk, hh)
    assert res.def_value == 5


def test_shift_focus_moves_another_fighter_in_the_zone(g):
    sf = give(g, "Shift focus")
    taken = {f.pos for f in g.fighters.values()}
    step = next(s for s in sorted(g.board.adj[g.hero(1).pos]) if s not in taken)
    g.controllers[0].moves = {"hellboy": step}
    attack(g, sf)
    assert g.hero(1).pos == step


def test_donatello_does_machines_returns_an_attack_and_draws(g):
    m = give(g, "Donatello does machines")
    old = to_discard(g, "Thinking ahead")
    scheme = to_discard(g, "Smoke bomb")
    g.play_scheme(0, g.hero(0), m)
    assert old in g.players[0].hand and scheme not in g.players[0].hand
    assert len(g.players[0].hand) == 2


def line_of_three(board):
    """Spaces a - b - c in a row: a and c two steps apart with b between them."""
    for a in sorted(board.spaces):
        for b in sorted(board.adj[a]):
            for c in sorted(board.adj[b]):
                if board.distance(a, c) == 2:
                    return a, b, c


def test_party_wagon_moves_and_hits_a_fighter_it_passed_through(g):
    pw = give(g, "Party wagon!")
    don, hell = g.hero(0), g.hero(1)
    a, b, c = line_of_three(g.board)
    don.pos, hell.pos = a, b
    g.fighters["metalhead"].pos = max(g.board.spaces)
    g.controllers[0].moves = {"donatello": c}
    hp = hell.hp
    g.play_scheme(0, don, pw)
    assert don.pos == c and hell.hp == hp - 2


def test_party_wagon_hits_nobody_when_the_mover_passed_through_no_one(g):
    pw = give(g, "Party wagon!")
    don, hell = g.hero(0), g.hero(1)
    a, b, c = line_of_three(g.board)
    far = max(g.board.spaces, key=lambda s: g.board.distance(a, s))
    don.pos, hell.pos = a, far
    g.fighters["metalhead"].pos = c
    g.controllers[0].moves = {"donatello": b}
    hp = hell.hp
    g.play_scheme(0, don, pw)
    assert hell.hp == hp


def test_the_future_of_ninjutsu_draws_gains_an_action_and_buries_a_weak_top_card(g):
    f = give(g, "The future of Ninjutsu")
    weak = min(g.players[0].deck, key=lambda c: (c.value or 0) + c.boost)
    g.players[0].deck.remove(weak)
    g.players[0].deck.insert(0, weak)
    left, deck = g.actions_left, len(g.players[0].deck)
    g.controllers[0] = MedusaAI(0)
    g.play_scheme(0, g.fighters["metalhead"], f)
    assert g.actions_left == left                      # spent one, gained one
    assert len(g.players[0].hand) == 1 and g.players[0].deck[-1] is weak and len(g.players[0].deck) == deck - 1


def test_the_future_of_ninjutsu_keeps_a_strong_top_card_and_draws_it(g):
    f = give(g, "The future of Ninjutsu")
    strong = give(g, "Electro grenade")
    g.players[0].hand.remove(strong)
    g.players[0].deck.insert(0, strong)
    g.controllers[0] = MedusaAI(0)
    g.play_scheme(0, g.fighters["metalhead"], f)
    assert g.players[0].hand == [strong]


# ---------------------------------------------------------------- inventions

def test_electro_grenade_removes_attack_cards_adds_value_and_is_tucked(g):
    eg = give(g, "Electro grenade")
    olds = [to_discard(g, "Thinking ahead", nth=i) for i in range(3)]
    res = attack(g, eg)
    assert res.atk_value == 2 + 3
    assert all(c in g.players[0].removed for c in olds) and not any(c in g.players[0].discard for c in olds)
    assert eg in g.players[0].tucked and eg not in g.players[0].discard


def test_a_tucked_electro_grenade_adds_one_to_every_attack_but_not_to_defenses(g):
    eg = give(g, "Electro grenade")
    attack(g, eg)
    q = give(g, "Quick strike")
    assert g.attack_bonus_parts(g.hero(0)) == [(1, "Electro grenade")]
    assert g.defense_bonus_parts(0) == []
    res = attack(g, q)
    assert res.atk_value == 4


def test_self_defense_grid_heals_what_it_removes_and_adds_one_to_defenses(g):
    g.turn = 1
    sdg = give(g, "Self defense grid")
    olds = [to_discard(g, "Heroes in a half shell"), to_discard(g, "Bo staff")]
    g.hero(0).hp = 5
    atk = rival_attack(g)
    resolve_combat(g, g.hero(1), g.hero(0), atk, sdg)
    assert g.hero(0).hp >= 5 + 2 - atk.value and sdg in g.players[0].tucked
    assert g.defense_bonus_parts(0) == [(1, "Self defense grid")]
    hh = give(g, "Heroes in a half shell", nth=1)
    atk2 = rival_attack(g, 1)
    res = resolve_combat(g, g.hero(1), g.hero(0), atk2, hh)
    assert res.def_value == 6


def test_smoke_bomb_removes_schemes_gains_actions_and_later_schemes_give_one_back(g):
    sb = give(g, "Smoke bomb")
    to_discard(g, "Party wagon!", nth=0)
    to_discard(g, "Party wagon!", nth=1)
    left = g.actions_left
    g.play_scheme(0, g.hero(0), sb)
    assert sb in g.players[0].tucked and len(g.players[0].removed) == 2
    assert g.actions_left == left - 1 + 2
    q = give(g, "Donatello does machines")
    left = g.actions_left
    g.play_scheme(0, g.hero(0), q)
    assert g.actions_left == left - 1 + 1


def test_removed_and_tucked_cards_are_public_and_leave_the_rivals_unseen_pool(g):
    eg = give(g, "Electro grenade")
    old = to_discard(g, "Thinking ahead")
    attack(g, eg)
    gone = g.players[0].gone
    assert eg in gone and old in gone
    known, pool, _ = g.hidden_hand(1)
    assert eg not in pool and old not in pool


def test_tucked_and_removed_cards_survive_a_save_and_load(g, bprd):
    eg = give(g, "Electro grenade")
    old = to_discard(g, "Thinking ahead")
    attack(g, eg)
    saved = persist.game_to_dict(g)
    g2 = make(bprd)
    persist.apply_game(g2, saved)
    assert [c.card_id for c in g2.players[0].tucked] == [eg.card_id]
    assert [c.card_id for c in g2.players[0].removed] == [old.card_id]
    assert g2.attack_bonus_parts(g2.hero(0)) == [(1, "Electro grenade")]
    assert g2.clone().players[0].tucked == g2.players[0].tucked


# ---------------------------------------------------------------- INVENTIVE

def test_inventive_draws_one_extra_card_and_puts_one_at_the_bottom(g):
    g.players[0].hand.extend(g.players[0].deck[:3])
    del g.players[0].deck[:3]
    hand, deck = len(g.players[0].hand), len(g.players[0].deck)
    g.maneuver(0, {})
    assert len(g.players[0].hand) == hand + 1 and len(g.players[0].deck) == deck - 1
    bottom = g.players[0].deck[-1]
    assert bottom in g.players[0].full_set and bottom not in g.players[0].hand


def test_inventive_is_not_offered_with_an_empty_deck(g):
    g.players[0].deck.clear()
    hp = g.hero(0).hp
    g.maneuver(0, {})
    assert len(g.players[0].hand) == 0 and g.hero(0).hp == hp - 2        # only the plain draw's exhaustion


def test_inventive_keeps_the_inventions_and_buries_the_weakest_card(g):
    for title in ("Electro grenade", "Self defense grid", "Smoke bomb"):
        give(g, title)
    give(g, "Heroes in a half shell")
    g.maneuver(0, {})
    assert {c.title for c in g.players[0].hand} >= {"Electro grenade", "Self defense grid", "Smoke bomb"}
