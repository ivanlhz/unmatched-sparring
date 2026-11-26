"""Sherlock Holmes' schemes and AFTER COMBAT cards on the engine, bot side: Confirm Suspicion (a value named, the rival discards a card of it or shows their
hand), Master of Disguise, Administer Aid, Eliminate the Impossible, Counterpunch, Fixed Point in a Changing Age, Education Never Ends, The Game is Afoot and
Study Methods. The ability, Elementary and Deduce Strategy are in tests/test_sherlock_effects.py."""
from __future__ import annotations

from sparring.effects.choose import ControllerChooser
from sparring.effects.modifiers import add_status
from sparring.effects.run import Ctx, EffectRun
from test_effects_combat import pair, put_adjacent
from test_sherlock_effects import asked, hand_of, mk, run_scheme


def confirm(g, named, hand_titles):
    """Holmes plays Confirm Suspicion naming `named` against a rival hand of `hand_titles`."""
    g.players[1].hand.clear()
    for title in hand_titles:
        hand_of(g, 1, title)
    g.controllers[0].queue = [[named]]
    run_scheme(g, g.fighters["holmes"], "Confirm Suspicion")


def known(g):
    return {c.title for c in g.players[0].known.cards(g.players[1])}


# ---------------------------------------------------------------- Confirm Suspicion

def test_confirm_suspicion_the_rival_discards_a_card_of_the_named_value_and_their_hero_takes_its_boost(bprd):
    g = mk(bprd)
    confirm(g, 3, ["Snipe", "Hiss and Slither"])                 # Snipe: 3 (BOOST 1); Hiss and Slither: 4
    assert [c.title for c in g.players[1].hand] == ["Hiss and Slither"]
    assert [c.title for c in g.players[1].discard] == ["Snipe"]
    assert g.fighters["medusa"].hp == 16 - 1


def test_confirm_suspicion_a_versatile_card_matches_by_its_value_and_the_rival_chooses_among_several(bprd):
    g = mk(bprd)
    confirm(g, 3, ["Snipe", "Dash"])                             # two versatile 3s
    assert len(g.players[1].hand) == 1 and len(g.players[1].discard) == 1
    req = next(r for r in g.controllers[1].requests if r.kind == "cards")
    assert req.player == 1 and len(req.options) == 2


def test_confirm_suspicion_the_damage_is_the_boost_of_the_discarded_card(bprd):
    g = mk(bprd)
    confirm(g, 4, ["Hiss and Slither"])                          # defense 4, BOOST 3
    assert g.fighters["medusa"].hp == 16 - 3


def test_confirm_suspicion_a_scheme_never_matches(bprd):
    g = mk(bprd)
    assert next(c for c in g.players[1].full_set if c.title == "Winged Frenzy").value is None
    confirm(g, 0, ["Winged Frenzy"])                             # a scheme has no value: naming 0 does not match it, so the hand is shown
    assert [c.title for c in g.players[1].hand] == ["Winged Frenzy"] and g.fighters["medusa"].hp == 16
    assert known(g) == {"Winged Frenzy"}


def test_confirm_suspicion_with_no_matching_card_the_rival_reveals_their_hand(bprd):
    g = mk(bprd)
    confirm(g, 5, ["Snipe", "Hiss and Slither"])
    assert len(g.players[1].hand) == 2 and g.fighters["medusa"].hp == 16
    assert known(g) == {"Snipe", "Hiss and Slither"}             # Holmes' player now knows the hand (known-hand)


def test_confirm_suspicion_with_an_empty_hand_the_look_shows_nothing(bprd):
    g = mk(bprd)
    confirm(g, 3, [])
    assert g.players[1].hand == [] and g.fighters["medusa"].hp == 16 and known(g) == set()


def test_confirm_suspicion_any_number_can_be_named(bprd):
    g = mk(bprd)
    run = EffectRun([{"op": "plugin", "id": "holmes:confirm_suspicion", "args": {"as": "confirmed"}}], Ctx(owner=0, this_fid="holmes"))
    g.controllers[0].queue = [[7]]
    run.run(g, ControllerChooser())
    assert list(asked(g, 0, "amount")[0].options) == list(range(8))


def test_confirm_suspicion_a_rule_against_forced_discards_leaves_the_rival_alone(bprd):
    g = mk(bprd)
    add_status(g.fx, "immune_to_enemy_forced_discards", owner=1, until={"event": "end_of_turn"}, player=1)
    confirm(g, 3, ["Snipe"])
    assert [c.title for c in g.players[1].hand] == ["Snipe"] and g.fighters["medusa"].hp == 16 and known(g) == set()


# ---------------------------------------------------------------- Master of Disguise

def test_master_of_disguise_swaps_the_heroes_at_any_distance_and_deals_one_damage(bprd):
    g = mk(bprd)
    h, foe = g.fighters["holmes"], g.fighters["medusa"]
    foe.pos = max(g.board.spaces, key=lambda s: g.board.distance(h.pos, s))
    before = (h.pos, foe.pos)
    run_scheme(g, h, "Master of Disguise")
    assert (h.pos, foe.pos) == (before[1], before[0]) and foe.hp == 16 - 1


def test_master_of_disguise_when_the_swap_cannot_happen_there_is_no_damage(bprd):
    g = mk(bprd)
    h, foe = g.fighters["holmes"], g.fighters["medusa"]
    add_status(g.fx, "cannot_leave_space", owner=1, until={"event": "end_of_turn"}, fid="medusa")
    before = (h.pos, foe.pos)
    run_scheme(g, h, "Master of Disguise")
    assert (h.pos, foe.pos) == before and foe.hp == 16


# ---------------------------------------------------------------- the other schemes

def test_administer_aid_places_watson_next_to_holmes_heals_him_and_draws(bprd):
    g = mk(bprd)
    h, w = g.fighters["holmes"], g.fighters["watson"]
    h.hp = 10
    w.pos = max(g.board.spaces, key=lambda s: g.board.distance(h.pos, s))
    deck = len(g.players[0].deck)
    run_scheme(g, w, "Administer Aid")                           # the card leaves the deck to be played, then one card is drawn
    assert w.pos in g.board.adj[h.pos] and h.hp == 11 and len(g.players[0].hand) == 1 and len(g.players[0].deck) == deck - 2


def test_eliminate_the_impossible_looks_at_the_hand_and_the_owner_picks_the_discard(bprd):
    g = mk(bprd)
    hand_of(g, 1, "Snipe")
    hand_of(g, 1, "Hiss and Slither")
    run_scheme(g, g.fighters["holmes"], "Eliminate the Impossible")
    assert len(g.players[1].hand) == 1 and len(g.players[1].discard) == 1
    assert known(g) <= {"Snipe", "Hiss and Slither"} and len(known(g)) == 1      # one card left, and it is the one seen


# ---------------------------------------------------------------- the AFTER COMBAT cards

def test_counterpunch_deals_two_while_holmes_is_adjacent_and_nothing_at_range(bprd):
    g = mk(bprd)
    h, foe = pair(g, "holmes", "medusa")
    g.attack(h, foe, hand_of(g, 0, "Counterpunch"), hand_of(g, 1, "Hiss and Slither"))      # 3 against 4: no combat damage
    assert foe.hp == 16 - 2


def test_counterpunch_defending_at_range_does_nothing(bprd):
    g = mk(bprd, turn=1)
    foe, h = pair(g, "medusa", "holmes")
    foe.pos = next(s for s in sorted(g.board.spaces) if s != h.pos and s not in g.board.adj[h.pos] and g.board.share_zone(h.pos, s))     # Medusa shoots from a zone mate that is not adjacent
    g.attack(foe, h, hand_of(g, 1, "Snipe"), hand_of(g, 0, "Counterpunch"))
    assert foe.hp == 16


def test_fixed_point_heals_holmes_and_watson_when_they_are_adjacent(bprd):
    g = mk(bprd)
    w, foe = pair(g, "watson", "medusa")
    h = g.fighters["holmes"]
    put_adjacent(g, "holmes", "watson")
    h.hp, w.hp = 10, 5
    g.attack(w, foe, hand_of(g, 0, "Fixed Point in a Changing Age"), hand_of(g, 1, "Hiss and Slither"))
    assert (h.hp, w.hp) == (11, 6)


def test_fixed_point_does_nothing_when_watson_is_not_adjacent(bprd):
    g = mk(bprd)
    w, foe = pair(g, "watson", "medusa")
    h = g.fighters["holmes"]
    h.pos = max(g.board.spaces, key=lambda s: g.board.distance(w.pos, s))
    h.hp, w.hp = 10, 5
    g.attack(w, foe, hand_of(g, 0, "Fixed Point in a Changing Age"), hand_of(g, 1, "Hiss and Slither"))
    assert (h.hp, w.hp) == (10, 5)


def test_education_never_ends_the_winner_gives_a_card_and_the_loser_draws_two(bprd):
    g = mk(bprd)
    h, foe = pair(g, "holmes", "medusa")
    g.attack(h, foe, hand_of(g, 0, "Education Never Ends"), None)                  # 3 unopposed: Holmes wins, the rival draws
    assert len(g.players[1].hand) == 1 and len(g.players[0].hand) == 0
    g2 = mk(bprd)
    h2, foe2 = pair(g2, "holmes", "medusa")
    g2.attack(h2, foe2, hand_of(g2, 0, "Education Never Ends"), hand_of(g2, 1, "Hiss and Slither"))     # 3 against 4: lost, Holmes draws two
    assert len(g2.players[0].hand) == 2 and len(g2.players[1].hand) == 0


def test_the_game_is_afoot_moves_holmes_up_to_three_spaces(bprd):
    g = mk(bprd)
    h, foe = pair(g, "holmes", "medusa")
    start = h.pos
    g.attack(h, foe, hand_of(g, 0, "The Game is Afoot"), None)
    moves = asked(g, 0, "space")
    assert moves and moves[0].extra["op"] == "move" and moves[0].extra["steps"] == 3 and moves[0].min == 0
    assert g.board.distance(start, h.pos) <= 3


def test_study_methods_looks_at_the_hand_only_when_holmes_won(bprd):
    g = mk(bprd)
    h, foe = pair(g, "holmes", "medusa")
    hand_of(g, 1, "Snipe")
    g.attack(h, foe, hand_of(g, 0, "Study Methods"), None)
    assert known(g) == {"Snipe"}
    g2 = mk(bprd)
    h2, foe2 = pair(g2, "holmes", "medusa")
    hand_of(g2, 1, "Snipe")
    g2.attack(h2, foe2, hand_of(g2, 0, "Study Methods"), hand_of(g2, 1, "Hiss and Slither"))
    assert known(g2) == set()
