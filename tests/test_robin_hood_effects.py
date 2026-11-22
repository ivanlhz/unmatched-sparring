"""Robin Hood on the interpreter, bot side (player 0 plays Robin Hood, the controllers answer): the ability, every card of the deck with
the numbers printed on it (sheet 176, read from the images on 2026-11-22) and the Ambush plugin. The human side (panel, FakeTTS) is in
tests/test_robin_hood_human.py and the full games in tests/test_robin_hood_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.state import Game, RuleError
from test_bigfoot_effects import Answers
from test_effects_combat import hand_filler, pair, put_adjacent

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3
OUTLAWS = ["outlaw1", "outlaw2", "outlaw3", "outlaw4"]


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Robin Hood = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("robin-hood", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def fight(g, title, foe_card=None, att="robin", foe="hellboy"):
    attacker, rival = pair(g, att, foe)
    attack = give(g, 0, title)
    defense = give(g, 1, foe_card) if foe_card else None
    return g.attack(attacker, rival, attack, defense), attacker, rival


def spaces_requests(g):
    return [r for r in g.controllers[0].requests if r.kind == "space"]


def first_free(g, near, within=2):
    """An empty space of the board at most `within` steps from `near`, the farthest first."""
    taken = {f.pos for f in g.fighters.values() if f.alive}
    return sorted((s for s in g.board.spaces if s not in taken and 0 < g.board.distance(near, s) <= within),
                  key=lambda s: (-g.board.distance(near, s), s))


# ---------------------------------------------------------------- the figures and the sheet

def test_robin_hood_is_interpreted_and_has_the_printed_figures(bprd):
    g = mk(bprd)
    assert "robin-hood" in g.fx.dsl_heroes
    assert [f.fid for f in g.own(0)] == ["robin", *OUTLAWS]
    robin, outlaws = g.fighters["robin"], [g.fighters[o] for o in OUTLAWS]
    assert (robin.hp, robin.move, robin.ranged, robin.name) == (13, 2, True, "Robin Hood")
    assert all((o.hp, o.move, o.ranged, o.name) == (1, 2, False, "Outlaw") for o in outlaws)
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629


def test_the_sheet_follows_the_images(bprd):
    deck = {c.card_id: c for c in mk(bprd).players[0].full_set}
    by_idx = lambda i: deck[17600 + i]
    assert [by_idx(i).title for i in (0, 3, 5, 7, 9, 13, 16, 19, 22, 25, 27)] == [
        "A Hunter's Eye", "Piercing Shot", "Disarming Shot", "Ambush", "Highway Robbery", "Regroup", "Feint", "Snark", "Wily Fighting",
        "Defenders of Sherwood", "Steal From the Rich"]
    assert [(by_idx(i).type, by_idx(i).value, by_idx(i).boost) for i in (0, 3, 5, 7, 9, 13, 16, 19, 22, 25)] == [
        ("attack", 5, 4), ("attack", 2, 3), ("attack", 4, 3), ("attack", 2, 3), ("attack", 2, 2), ("versatile", 1, 2),
        ("versatile", 2, 2), ("versatile", 3, 1), ("versatile", 3, 1), ("defense", 3, 2)]
    assert (by_idx(27).type, by_idx(27).value, by_idx(27).boost) == ("scheme", None, 3)
    assert {by_idx(i).fighter for i in (9, 10, 11, 12)} == {"Outlaw"}
    assert {by_idx(i).fighter for i in (7, 8, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26)} == {"any"}
    assert {by_idx(i).fighter for i in (0, 1, 2, 3, 4, 5, 6, 27, 28, 29)} == {"Robin Hood"}


def test_only_an_outlaw_plays_highway_robbery_and_only_robin_the_shots(bprd):
    g = mk(bprd)
    robin, rival = pair(g, "robin", "hellboy")
    robbery = give(g, 0, "Highway Robbery")
    with pytest.raises(RuleError):
        g.attack(robin, rival, robbery, None)
    g2 = mk(bprd)
    outlaw, rival2 = pair(g2, "outlaw1", "hellboy")
    with pytest.raises(RuleError):
        g2.attack(outlaw, rival2, give(g2, 0, "A Hunter's Eye"), None)
    res = g2.attack(outlaw, rival2, give(g2, 0, "Highway Robbery"), None)
    assert res.atk_value == 2


# ---------------------------------------------------------------- the ability: move after the attack

def test_the_owner_who_says_yes_moves_the_attacker_up_to_two_spaces_after_the_attack(bprd):
    g = mk(bprd)
    robin, rival = pair(g, "robin", "hellboy")
    away = first_free(g, robin.pos)[0]
    g.controllers[0].queue = [[away]]
    g.attack(robin, rival, give(g, 0, "A Hunter's Eye"), give(g, 1, TRAINING))
    assert robin.pos == away and g.board.distance(robin.pos, rival.pos) >= 1
    (ask,) = spaces_requests(g)
    assert ask.extra["steps"] == 2 and ask.extra["up_to"] and ask.extra["fighter"] == "robin" and not ask.extra["through"]
    assert away in ask.options


def test_the_owner_who_answers_with_no_space_does_not_move(bprd):
    g = mk(bprd)
    robin, rival = pair(g, "robin", "hellboy")
    spot = robin.pos
    g.controllers[0].queue = [[]]
    g.attack(robin, rival, give(g, 0, "A Hunter's Eye"), give(g, 1, TRAINING))
    (ask,) = spaces_requests(g)
    assert robin.pos == spot and ask.min == 0                    # "up to": no space is a legal answer


def test_the_move_is_ordinary_movement_never_to_an_occupied_space_and_never_more_than_two_away(bprd):
    g = mk(bprd)
    robin, rival = pair(g, "robin", "hellboy")
    start = robin.pos
    g.controllers[0].queue = [None]
    g.attack(robin, rival, give(g, 0, "A Hunter's Eye"), None)
    (ask,) = spaces_requests(g)
    occupied = {f.pos for f in g.fighters.values() if f.alive and f is not robin}
    assert ask.options and not set(ask.options) & occupied
    assert all(g.board.distance(start, s) <= 2 for s in ask.options)
    assert not ask.extra["through"]


def test_an_outlaw_that_attacks_is_the_fighter_that_moves(bprd):
    g = mk(bprd)
    outlaw, rival = pair(g, "outlaw1", "hellboy")
    robin = g.fighters["robin"]
    robin_spot = robin.pos
    away = first_free(g, outlaw.pos)[0]
    g.controllers[0].queue = [[away]]
    g.attack(outlaw, rival, give(g, 0, "Highway Robbery"), give(g, 1, TRAINING))
    assert outlaw.pos == away and robin.pos == robin_spot
    assert spaces_requests(g)[0].extra["fighter"] == "outlaw1"


def test_the_move_comes_after_every_after_combat_effect_of_both_cards(bprd):
    """Snark draws only if the attacker is still next to the defender: the draw is settled before the attacker steps away."""
    g = mk(bprd)
    robin, rival = pair(g, "robin", "hellboy")
    start, seen = robin.pos, []
    g.controllers[0].queue = [lambda req: seen.append(len(g.players[0].hand)) or [first_free(g, robin.pos)[0]]]
    g.attack(robin, rival, give(g, 0, "Snark"), give(g, 1, TRAINING))
    assert seen == [1]                                   # the Snark card is gone, the card it drew is in the hand
    assert robin.pos != start


def test_the_move_follows_the_defenders_after_effects_too(bprd):
    """Medusa's Regroup as the defense draws its card in the defender's AFTER: the draw is in the hand when Robin is asked where to go."""
    g = mk(bprd, foe="medusa")
    robin, rival = pair(g, "robin", "medusa")
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(len(g.players[1].hand)) or [first_free(g, robin.pos)[0]]]
    g.attack(robin, rival, give(g, 0, "A Hunter's Eye"), give(g, 1, "Regroup"))
    assert seen == [1]


def test_a_defeated_attacker_does_not_move(bprd):
    g = mk(bprd, foe="baba-yaga")
    outlaw, rival = pair(g, "outlaw1", "baba")
    g.controllers[0].queue = [[]]
    g.attack(outlaw, rival, give(g, 0, "Highway Robbery"), give(g, 1, "Hasten Towards Death"))
    # Highway Robbery cancels Hasten Towards Death: the Outlaw lives. Same fight with the effect left alone:
    assert outlaw.alive and spaces_requests(g)
    g2 = mk(bprd, foe="baba-yaga")
    outlaw2, rival2 = pair(g2, "outlaw1", "baba")
    g2.controllers[0].queue = [[]]
    g2.attack(outlaw2, rival2, give(g2, 0, "Snark"), give(g2, 1, "Hasten Towards Death"))
    assert not outlaw2.alive and not spaces_requests(g2) and not g2.controllers[0].requests


def test_a_defeated_defender_does_not_stop_the_attacker_moving(bprd):
    g = mk(bprd, foe="yennenga")
    robin, archer = pair(g, "robin", "archer1")
    away = first_free(g, robin.pos)[0]
    g.controllers[0].queue = [[away]]
    g.attack(robin, archer, give(g, 0, "A Hunter's Eye"), None)
    assert not archer.alive and robin.pos == away


def test_the_ability_does_not_fire_when_robin_defends(bprd):
    g = mk(bprd, turn=1)
    robin, rival = pair(g, "robin", "hellboy")
    g.controllers[0].queue = [[]]
    g.attack(rival, robin, give(g, 1, "Service Pistol"), give(g, 0, "Defenders of Sherwood"))
    assert not spaces_requests(g) and g.controllers[0].queue == [[]]


# ---------------------------------------------------------------- the attacks

def test_a_hunters_eye_is_a_plain_five(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[]]
    res, robin, rival = fight(g, "A Hunter's Eye", TRAINING)
    assert (res.atk_value, res.def_value, res.damage) == (5, 3, 2) and rival.hp == rival.max_hp - 2


def test_piercing_shot_draws_two_after_the_combat(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[]]
    deck = len(g.players[0].deck)
    fight(g, "Piercing Shot", TRAINING)
    assert len(g.players[0].hand) == 2 and len(g.players[0].deck) == deck - 3


def test_disarming_shot_draws_as_many_cards_as_the_combat_damage(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[]]
    res, _, rival = fight(g, "Disarming Shot", TRAINING)
    assert res.damage == 1 and len(g.players[0].hand) == 1
    g2 = mk(bprd)
    g2.controllers[0].queue = [[]]
    res2, _, rival2 = fight(g2, "Disarming Shot")
    assert res2.damage == 4 and len(g2.players[0].hand) == 4 and rival2.hp == rival2.max_hp - 4


def test_disarming_shot_counts_the_overkill(bprd):
    g = mk(bprd, foe="yennenga")
    robin, archer = pair(g, "robin", "archer1")
    g.controllers[0].queue = [[]]
    g.attack(robin, archer, give(g, 0, "Disarming Shot"), None)
    assert not archer.alive and archer.hp <= 0 and len(g.players[0].hand) == 4          # 4 dealt to a fighter with 2 health


def test_disarming_shot_draws_what_the_damage_reduction_left(bprd):
    g = mk(bprd, foe="luke-cage")
    g.controllers[0].queue = [[]]
    res, _, rival = fight(g, "Disarming Shot", foe="luke")
    assert res.damage == 2 and len(g.players[0].hand) == 2


def test_disarming_shot_draws_nothing_when_no_damage_lands(bprd):
    g = mk(bprd, foe="medusa")
    g.controllers[0].queue = [[]]
    res, *_ = fight(g, "Disarming Shot", "Hiss and Slither", foe="medusa")           # a 4 against a 4
    assert res.damage == 0 and not g.players[0].hand


def test_disarming_shot_cancelled_by_a_feint_draws_nothing(bprd):
    g = mk(bprd, foe="medusa")
    g.controllers[0].queue = [[]]
    res, *_ = fight(g, "Disarming Shot", "Feint", foe="medusa")
    assert res.damage == 2 and not g.players[0].hand


def test_ambush_discards_a_random_card_of_the_hand_and_adds_its_boost(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[]]
    robin, rival = pair(g, "robin", "hellboy")
    victim = give(g, 1, "Excalibur")
    res = g.attack(robin, rival, give(g, 0, "Ambush"), None)
    assert victim in g.players[1].discard and not g.players[1].hand
    assert res.atk_value == 2 + victim.boost and res.damage == 2 + victim.boost


def test_ambush_against_an_empty_hand_is_a_plain_two(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[]]
    res, *_ = fight(g, "Ambush")
    assert res.atk_value == 2


def test_ambush_takes_one_card_of_the_hand_only_never_from_the_deck(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[]]
    robin, rival = pair(g, "robin", "hellboy")
    cards = [give(g, 1, t) for t in ("Excalibur", "Service Pistol", TRAINING)]
    deck, discard = len(g.players[1].deck), len(g.players[1].discard)
    res = g.attack(robin, rival, give(g, 0, "Ambush"), None)
    gone = [c for c in cards if c in g.players[1].discard]
    assert len(gone) == 1 and res.atk_value == 2 + gone[0].boost
    assert len(g.players[1].deck) == deck and len(g.players[1].discard) == discard + 1


def test_a_cancelled_ambush_discards_nothing(bprd):
    g = mk(bprd, foe="medusa")
    g.controllers[0].queue = [[]]
    robin, rival = pair(g, "robin", "medusa")
    kept = give(g, 1, "Snipe")
    res = g.attack(robin, rival, give(g, 0, "Ambush"), give(g, 1, "Feint"))
    assert res.atk_value == 2 and kept in g.players[1].hand


def test_highway_robbery_cancels_the_effects_and_ignores_the_defense_value(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[]]
    res, outlaw, rival = fight(g, "Highway Robbery", TRAINING, att="outlaw1")
    assert (res.atk_value, res.def_value, res.damage) == (2, 0, 2) and rival.hp == rival.max_hp - 2


def test_highway_robbery_against_no_defense_is_a_plain_two(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[]]
    res, *_ = fight(g, "Highway Robbery", att="outlaw1")
    assert (res.atk_value, res.def_value) == (2, 0)


def test_highway_robbery_cancels_the_defenders_after_effects(bprd):
    g = mk(bprd, foe="baba-yaga")
    outlaw, rival = pair(g, "outlaw1", "baba")
    g.controllers[0].queue = [[]]
    g.attack(outlaw, rival, give(g, 0, "Highway Robbery"), give(g, 1, "Hasten Towards Death"))
    assert outlaw.alive and rival.hp == rival.max_hp - 2          # Hasten Towards Death (4) is ignored and its damage to the attacker is cancelled


# ---------------------------------------------------------------- the versatile cards

def test_regroup_draws_one_and_two_if_the_combat_was_won(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[]]
    fight(g, "Regroup")                                          # 1 against nothing: the attacker's damage lands, it wins
    assert len(g.players[0].hand) == 2
    g2 = mk(bprd)
    g2.controllers[0].queue = [[]]
    fight(g2, "Regroup", TRAINING)                               # 1 against 3: no damage, the defender wins
    assert len(g2.players[0].hand) == 1


def test_regroup_as_a_defense_that_does_not_hold_draws_one(bprd):
    g = mk(bprd, turn=1)
    robin, rival = pair(g, "robin", "hellboy")
    g.attack(rival, robin, give(g, 1, "Horseshoes And Hand Grenades"), give(g, 0, "Regroup"))
    assert robin.hp == 13 - 1 - 1 and len(g.players[0].hand) == 1      # 1 combat damage and the 1 of Horseshoes And Hand Grenades


def test_feint_cancels_the_effects_of_the_opponents_card(bprd):
    g = mk(bprd, foe="medusa")
    g.controllers[0].queue = [[]]
    robin, rival = pair(g, "robin", "medusa")
    g.attack(robin, rival, give(g, 0, "Piercing Shot"), give(g, 1, "Feint"))
    assert not g.players[0].hand                                 # the Piercing Shot draw was cancelled


def test_snark_draws_one_only_if_the_fighter_is_adjacent_to_the_opposing_fighter(bprd):
    g = mk(bprd)
    g.controllers[0].queue = [[]]
    fight(g, "Snark", TRAINING)
    assert len(g.players[0].hand) == 1
    g2 = mk(bprd)
    g2.controllers[0].queue = [[]]
    robin, rival = pair(g2, "robin", "hellboy")
    zone = next(s for s in sorted(g2.board.spaces) if s != robin.pos and s not in g2.board.adj[robin.pos]
                and g2.board.share_zone(robin.pos, s) and all(f.pos != s for f in g2.fighters.values() if f.alive))
    rival.pos = zone
    g2.attack(robin, rival, give(g2, 0, "Snark"), give(g2, 1, TRAINING))
    assert not g2.players[0].hand


def test_wily_fighting_hurts_every_enemy_next_to_the_fighter(bprd):
    g = mk(bprd, foe="yennenga")
    g.controllers[0].queue = [[]]
    robin, yen = pair(g, "robin", "yennenga")
    near = put_adjacent(g, "archer1", "robin")
    far = g.fighters["archer2"]
    g.attack(robin, yen, give(g, 0, "Wily Fighting"), give(g, 1, "Shield Formation"))
    assert g.fighters["archer1"].hp == 1 and far.hp == 2 and yen.hp == yen.max_hp - 1


def test_wily_fighting_played_by_an_outlaw_counts_the_enemies_next_to_the_outlaw_not_next_to_robin(bprd):
    g = mk(bprd, foe="yennenga")
    g.controllers[0].queue = [[]]
    outlaw, yen = pair(g, "outlaw1", "yennenga")
    put_adjacent(g, "archer1", "outlaw1")
    far = [s for s in sorted(g.board.spaces, reverse=True) if not g.board.share_zone(outlaw.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive)]
    g.fighters["robin"].pos = far[0]
    g.fighters["archer2"].pos = far[1]
    put_adjacent(g, "archer2", "robin")
    g.attack(outlaw, yen, give(g, 0, "Wily Fighting"), give(g, 1, "Shield Formation"))
    assert g.fighters["archer1"].hp == 1 and g.fighters["archer2"].hp == 2


def test_wily_fighting_spares_the_fighters_of_its_own_side(bprd):
    g = mk(bprd, foe="yennenga")
    g.controllers[0].queue = [[]]
    robin, yen = pair(g, "robin", "yennenga")
    put_adjacent(g, "outlaw1", "robin")
    g.attack(robin, yen, give(g, 0, "Wily Fighting"), give(g, 1, "Shield Formation"))
    assert g.fighters["outlaw1"].hp == 1


# ---------------------------------------------------------------- Defenders of Sherwood

def defenders_game(bprd, defeated=("outlaw1",)):
    g = mk(bprd, turn=1)
    robin, rival = pair(g, "robin", "hellboy")
    for fid in defeated:
        g.damage(g.fighters[fid], 1, "effect")
        assert not g.fighters[fid].alive
    return g, robin, rival


def test_defenders_of_sherwood_draws_and_returns_a_defeated_outlaw_to_robins_zone(bprd):
    g, robin, rival = defenders_game(bprd)
    zone_spaces = [s for s in g.board.spaces if g.board.share_zone(robin.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive)]
    assert zone_spaces
    g.controllers[0].queue = [lambda req: [max(req.options)]]
    g.attack(rival, robin, give(g, 1, "Service Pistol"), give(g, 0, "Defenders of Sherwood"))
    outlaw = g.fighters["outlaw1"]
    assert outlaw.alive and outlaw.hp == 1 and g.board.share_zone(outlaw.pos, robin.pos) and outlaw.pos in zone_spaces
    assert len(g.players[0].hand) == 1


def test_defenders_of_sherwood_only_offers_empty_spaces_of_robins_zone(bprd):
    g, robin, rival = defenders_game(bprd)
    seen = []
    g.controllers[0].queue = [lambda req: seen.append(req) or [max(req.options)]]
    g.attack(rival, robin, give(g, 1, "Service Pistol"), give(g, 0, "Defenders of Sherwood"))
    (req,) = seen
    taken = {f.pos for f in g.fighters.values() if f.alive and f is not g.fighters["outlaw1"]}
    assert req.options and all(g.board.share_zone(s, robin.pos) and s not in taken for s in req.options)


def test_defenders_of_sherwood_with_no_defeated_outlaw_only_draws(bprd):
    g, robin, rival = defenders_game(bprd, defeated=())
    g.attack(rival, robin, give(g, 1, "Service Pistol"), give(g, 0, "Defenders of Sherwood"))
    assert len(g.players[0].hand) == 1 and not g.controllers[0].requests


def test_defenders_of_sherwood_returns_one_outlaw_even_if_several_fell(bprd):
    g, robin, rival = defenders_game(bprd, defeated=("outlaw1", "outlaw3"))
    g.controllers[0].queue = [lambda req: [max(req.options)]]
    g.attack(rival, robin, give(g, 1, "Service Pistol"), give(g, 0, "Defenders of Sherwood"))
    assert sum(g.fighters[o].alive for o in OUTLAWS) == 3


def test_defenders_of_sherwood_brings_back_an_outlaw_defeated_in_an_earlier_turn(bprd):
    g, robin, rival = defenders_game(bprd, defeated=("outlaw2",))
    g.fighters["outlaw2"].died_at = 1
    g.controllers[0].queue = [lambda req: [max(req.options)]]
    g.attack(rival, robin, give(g, 1, "Service Pistol"), give(g, 0, "Defenders of Sherwood"))
    assert g.fighters["outlaw2"].alive


def test_defenders_of_sherwood_with_no_free_space_in_the_zone_only_draws(bprd):
    g, robin, rival = defenders_game(bprd)
    free = [s for s in g.board.spaces if g.board.share_zone(robin.pos, s) and all(f.pos != s for f in g.fighters.values() if f.alive)]
    blockers = [f for f in g.fighters.values() if f.alive and f.fid not in ("robin", "hellboy")]
    far = [s for s in g.board.spaces if s not in free and not g.board.share_zone(robin.pos, s)]
    for f, s in zip(blockers, free):
        f.pos = s
    rest = [s for s in free if s not in {f.pos for f in g.fighters.values() if f.alive}]
    if rest:
        pytest.skip("the zone has more spaces than there are fighters to fill them")
    g.attack(rival, robin, give(g, 1, "Service Pistol"), give(g, 0, "Defenders of Sherwood"))
    assert not g.fighters["outlaw1"].alive and len(g.players[0].hand) == 1


# ---------------------------------------------------------------- Steal From the Rich

def test_steal_from_the_rich_draws_one_and_a_second_if_the_rival_keeps_their_hand(bprd):
    g = mk(bprd)
    hand_filler(g, 1, 3)
    g.controllers[1].queue = [[False]]
    robin = g.fighters["robin"]
    g.play_scheme(0, robin, give(g, 0, "Steal From the Rich"))
    assert len(g.players[0].hand) == 2 and len(g.players[1].hand) == 3


def test_steal_from_the_rich_the_rival_who_discards_a_card_leaves_robin_one_draw(bprd):
    g = mk(bprd)
    pool = hand_filler(g, 1, 3)
    g.controllers[1].queue = [[True], [pool[0].card_id]]
    g.play_scheme(0, g.fighters["robin"], give(g, 0, "Steal From the Rich"))
    assert len(g.players[0].hand) == 1 and len(g.players[1].hand) == 2 and pool[0] in g.players[1].discard


def test_steal_from_the_rich_against_an_empty_hand_gives_the_second_card_without_asking(bprd):
    g = mk(bprd)
    g.play_scheme(0, g.fighters["robin"], give(g, 0, "Steal From the Rich"))
    assert len(g.players[0].hand) == 2 and not g.controllers[1].requests


def test_steal_from_the_rich_asks_the_rival_not_robin(bprd):
    g = mk(bprd)
    hand_filler(g, 1, 2)
    g.controllers[1].queue = [[False]]
    g.play_scheme(0, g.fighters["robin"], give(g, 0, "Steal From the Rich"))
    assert [r.kind for r in g.controllers[1].requests] == ["optional"] and not g.controllers[0].requests


def test_an_outlaw_that_falls_defending_with_defenders_of_sherwood_may_be_the_one_that_comes_back(bprd):
    g = mk(bprd, turn=1)
    outlaw, rival = pair(g, "outlaw1", "hellboy")
    g.controllers[0].queue = [lambda req: [max(req.options)]]
    g.attack(rival, outlaw, give(g, 1, "Service Pistol"), give(g, 0, "Defenders of Sherwood"))
    assert outlaw.alive and outlaw.hp == 1 and g.board.share_zone(outlaw.pos, g.fighters["robin"].pos)
