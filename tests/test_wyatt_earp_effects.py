"""Wyatt Earp on the engine, bot side (player 0 plays him, the controllers answer): SHOWDOWN and its bound, the free action that can only
attack (`Game.free_attacks`), the two schemes that grant it, and every card with the numbers printed on it. The human side (panel,
FakeTTS) is in tests/test_wyatt_earp_human.py and the full games in tests/test_wyatt_earp_matrix.py."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.combat_flow import CombatFlow
from sparring.persist import apply_game, game_to_dict
from sparring.state import Game, RuleError
from test_bigfoot_effects import Answers, empty_spaces
from test_effects_combat import pair, put_adjacent

DRAW, ATTACK, MOVE = 0, 1, 2          # the printed order of the SHOWDOWN options
LABELS = ["Draw 1 card", "Gain 1 free action to attack", "Move your fighter up to 1 space"]


def mk(bprd, foe="hellboy", seed=3, turn=0):
    """Wyatt Earp = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("wyatt-earp", foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def picks(*options):
    """Answers for the requests that ask one of a fixed list of options, in order (an option index or a fighter / space id)."""
    return [lambda req, k=k: [k] for k in options]


def prefer(*order):
    """An answer that takes the first of `order` the request offers (SHOWDOWN: the best effect still open)."""
    return lambda req: [next(k for k in order if k in req.options)]


def showdowns(g):
    return [r for r in g.controllers[0].requests if r.extra.get("tag") == "showdown"]


def win(g, title="You Just Gonna Stand There And Bleed?", attacker="wyatt", target="hellboy"):
    """Wyatt (or Doc) attacks `target` with `title` and the rival plays nothing."""
    a, d = g.fighters[attacker], g.fighters[target]
    return g.attack(a, d, give(g, 0, title), None)


def half_shell(g, player=1):
    """Leonardo's HEROES IN A HALF SHELL (defense 5, no text): a wall that beats every attack of Wyatt's deck but Stand There."""
    c = next(c for c in g.players[player].deck if c.title == "Heroes in a half shell")
    g.players[player].deck.remove(c)
    g.players[player].hand.append(c)
    return c


def arena(g, attacker="wyatt", target="hellboy", hp=99):
    a, d = pair(g, attacker, target)
    d.hp = d.max_hp = hp
    return a, d


# ---------------------------------------------------------------- the hero

def test_wyatt_is_a_ranged_hero_with_doc_holliday_and_a_deck_of_thirty(bprd):
    g = mk(bprd)
    wyatt, doc = g.fighters["wyatt"], g.fighters["doc"]
    assert (wyatt.hp, wyatt.move, wyatt.ranged, wyatt.name, wyatt.hero) == (15, 2, True, "Wyatt Earp", True)
    assert (doc.hp, doc.move, doc.ranged, doc.name, doc.hero) == (8, 2, True, "Doc Holliday", False)
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 18700 and deck[-1].card_id == 18729
    assert "wyatt-earp" in g.fx.dsl_heroes


def test_the_deck_has_the_printed_values_copies_and_restrictions(bprd):
    g = mk(bprd)
    seen = {}
    for c in g.players[0].full_set:
        seen.setdefault(c.title, [c, 0])[1] += 1
    printed = {  # title: (copies, restriction, type, value, boost)
        "You Just Gonna Stand There And Bleed?": (3, "Wyatt Earp", "attack", 5, 1),
        "I Have Two Guns, One For Each Of You": (3, "Doc Holliday", "attack", 4, 1),
        "Second Shot": (2, "any", "attack", 2, 1), "Fan The Hammer": (2, "Wyatt Earp", "attack", 1, 3),
        "You're A Daisy If You Do": (2, "Doc Holliday", "versatile", 4, 3), "A Marshal And An Outlaw": (3, "Wyatt Earp", "versatile", 3, 2),
        "I'm Your Huckleberry": (3, "any", "versatile", 3, 2), "Gunfight At The O.K. Corral": (2, "Wyatt Earp", "versatile", 2, 3),
        "Better Swear Me In": (3, "any", "versatile", 2, 2), "Bring 'Em To Justice": (3, "Wyatt Earp", "defense", 0, 2),
        "In Vino Veritas": (2, "Doc Holliday", "scheme", None, 3), "You Die First": (2, "Wyatt Earp", "scheme", None, 3)}
    assert {t: (n, c.fighter, c.type, c.value, c.boost) for t, (c, n) in seen.items()} == printed


# ---------------------------------------------------------------- SHOWDOWN

def test_winning_an_attack_offers_the_three_effects_and_draw_draws(bprd):
    g = mk(bprd)
    arena(g)
    g.controllers[0].queue = picks(DRAW)
    win(g)
    (req,) = showdowns(g)
    assert req.options == [0, 1, 2] and req.extra["labels"] == LABELS
    assert len(g.players[0].hand) == 1                         # the card played left, the card drawn arrived


def test_the_free_action_is_an_extra_action_that_only_an_attack_can_spend(bprd):
    g = mk(bprd)
    arena(g)
    g.controllers[0].queue = picks(ATTACK)
    win(g)
    assert (g.actions_left, g.paid_actions, g.free_attacks) == (2, 1, [None])
    g.players[0].hand.append(g.players[0].deck.pop(0))
    g.use_action()                                             # the paid one
    assert (g.actions_left, g.paid_actions) == (1, 0)
    with pytest.raises(RuleError, match="gratis"):
        g.maneuver(0, {"wyatt": g.fighters["wyatt"].pos})
    with pytest.raises(RuleError, match="gratis"):
        g.use_action()
    assert g.actions_left == 1                                 # nothing was spent by the refusals


def test_an_attack_spends_the_free_action_before_the_ordinary_ones(bprd):
    g = mk(bprd)
    arena(g)
    g.controllers[0].queue = picks(ATTACK)
    win(g)
    win(g)
    assert (g.actions_left, g.paid_actions, g.free_attacks) == (1, 1, [])


def test_the_move_effect_moves_the_fighter_that_attacked_up_to_one_space(bprd):
    g = mk(bprd)
    wyatt, _ = arena(g)
    spot = empty_spaces(g, wyatt.pos, 1)[0]
    g.controllers[0].queue = picks(MOVE)
    g.controllers[0].moves = {"wyatt": spot}
    win(g)
    assert wyatt.pos == spot


def test_doc_holliday_wins_a_combat_and_it_is_doc_who_moves(bprd):
    g = mk(bprd)
    doc, _ = arena(g, "doc")
    spot = empty_spaces(g, doc.pos, 1)[0]
    g.controllers[0].queue = picks(MOVE)
    g.controllers[0].moves = {"doc": spot, "wyatt": g.fighters["wyatt"].pos}
    win(g, "I Have Two Guns, One For Each Of You", "doc")
    assert doc.pos == spot and len(showdowns(g)) == 1


def test_a_lost_combat_and_a_defense_won_offer_nothing(bprd):
    g = mk(bprd, "leonardo")
    _, leo = arena(g, target="leonardo")
    g.attack(g.fighters["wyatt"], leo, give(g, 0, "Second Shot"), half_shell(g))           # 2 against a wall: lost
    assert showdowns(g) == [] and g.free_attacks == []
    g2 = mk(bprd)
    pair(g2, "wyatt", "hellboy")
    atk = give(g2, 1, "Service Pistol")
    g2.turn = 1
    g2.begin_turn()
    g2.attack(g2.fighters["hellboy"], g2.fighters["wyatt"], atk, give(g2, 0, "Bring 'Em To Justice"))     # Wyatt defends
    assert showdowns(g2) == [] and g2.free_attacks == []


def test_the_same_effect_is_not_offered_twice_in_a_turn(bprd):
    g = mk(bprd)
    arena(g)
    g.controllers[0].queue = picks(ATTACK, DRAW)
    win(g)
    win(g)
    first, second = showdowns(g)
    assert first.options == [0, 1, 2] and second.options == [DRAW, MOVE]


def test_after_the_three_effects_there_is_no_fourth(bprd):
    g = mk(bprd)
    wyatt, _ = arena(g)
    g.controllers[0].queue = picks(DRAW, ATTACK, MOVE)
    g.controllers[0].moves = {"wyatt": wyatt.pos}
    g.grant_free_attack()
    g.grant_free_attack()                                      # 4 attacks, and the free action of the 2nd Showdown is the 5th
    for _ in range(4):
        win(g)
    assert len(showdowns(g)) == 2 and g.actions_left == 1       # the 3rd offers one effect only (answered by itself), the 4th none
    assert [g.fx.counter_value(0, n, 0) for n in ("showdown_draw", "showdown_attack", "showdown_move")] == [1, 1, 1]


def test_the_effects_are_open_again_on_the_next_turn(bprd):
    g = mk(bprd)
    arena(g)
    g.controllers[0].queue = picks(DRAW)
    win(g)
    assert g.fx.counter_value(0, "showdown_draw", 0) == 1
    g.end_turn()
    g.begin_turn()
    g.end_turn()
    g.begin_turn()
    assert g.turn == 0 and [g.fx.counter_value(0, n, 0) for n in ("showdown_draw", "showdown_attack", "showdown_move")] == [0, 0, 0]


def test_the_chain_of_free_attacks_is_bounded_by_the_three_effects(bprd):
    """A bot that always takes the free action: Showdown cannot feed itself, the turn ends after 2 + 1 attacks."""
    g = mk(bprd)
    arena(g)
    g.controllers[0].queue = [prefer(ATTACK, DRAW, MOVE)] * 10
    attacks = 0
    while g.actions_left > 0 and attacks < 20:
        win(g)
        attacks += 1
    assert attacks == 3 and g.actions_left == 0 and len(showdowns(g)) == 2


def test_schemes_that_grant_free_attacks_are_bounded_by_the_cards(bprd):
    g = mk(bprd)
    arena(g)
    g.controllers[0].queue = [prefer(ATTACK, DRAW, MOVE)] * 20
    for _ in range(2):
        give(g, 0, "In Vino Veritas")
    attacks = schemes = 0
    while g.actions_left > 0 and attacks + schemes < 30:
        vino = next((c for c in g.players[0].hand if c.title == "In Vino Veritas"), None)
        if vino is not None and g.paid_actions > 0:
            g.play_scheme(0, g.fighters["doc"], vino)
            schemes += 1
        else:
            win(g)
            attacks += 1
    assert schemes == 2 and g.actions_left == 0 and attacks <= 4 and attacks + schemes < 30


def test_a_free_action_cannot_be_gained_when_the_rival_forbids_it(bprd):
    g = mk(bprd)
    g.fx.statuses.append({"name": "cannot_gain_actions", "owner": 1, "player": 0, "until": {"event": "end_of_turn"}, "amount": 0, "label": ""})
    assert g.grant_free_attack() is False and (g.free_attacks, g.actions_left) == ([], 2)
    arena(g)
    g.controllers[0].queue = picks(ATTACK)
    win(g)                                                     # SHOWDOWN's free action is refused too
    assert (g.free_attacks, g.actions_left) == ([], 1)


def test_free_attacks_survive_a_save_and_a_clone(bprd):
    g = mk(bprd)
    g.grant_free_attack("hellboy")
    g.grant_free_attack()
    assert g.clone().free_attacks == ["hellboy", None]
    h = mk(bprd)
    apply_game(h, game_to_dict(g))
    assert h.free_attacks == ["hellboy", None] and h.actions_left == 4
    g.begin_turn()
    assert g.free_attacks == [] and g.actions_left == 2


def test_a_free_attack_bound_to_a_fighter_attacks_only_that_fighter(bprd):
    g = mk(bprd)
    wyatt, hellboy = arena(g)
    lobster = g.fighters["lobster"]
    put_adjacent(g, "lobster", "wyatt")
    g.use_action()
    g.use_action()
    g.actions_left = 0
    g.grant_free_attack("lobster")
    card = give(g, 0, "You Just Gonna Stand There And Bleed?")
    with pytest.raises(RuleError):
        g.attack(wyatt, hellboy, card, None)
    assert g.actions_left == 1 and card in g.players[0].hand
    g.attack(wyatt, lobster, card, None)
    assert g.actions_left == 0 and g.free_attacks == []


def test_the_bot_loses_the_free_attacks_it_cannot_use(bprd):
    g = mk(bprd)
    arena(g)
    g.grant_free_attack()
    g.prune_free_attacks(0)                                    # an empty hand: nothing to attack with
    assert (g.actions_left, g.free_attacks) == (2, [])
    give(g, 0, "You Just Gonna Stand There And Bleed?")
    g.grant_free_attack()
    g.prune_free_attacks(0)
    assert (g.actions_left, g.free_attacks) == (3, [None])


# ---------------------------------------------------------------- the cards

def test_you_just_gonna_stand_there_is_a_plain_five(bprd):
    g = mk(bprd)
    _, hellboy = arena(g)
    g.controllers[0].queue = picks(DRAW)
    res = win(g)
    assert res.atk_value == 5 and hellboy.hp == 99 - 5


def test_second_shot_asks_for_a_boost(bprd):
    g = mk(bprd)
    wyatt, hellboy = arena(g)
    shot = give(g, 0, "Second Shot")
    boost = give(g, 0, "Fan The Hammer")                       # BOOST 3
    flow = CombatFlow(g, wyatt, hellboy, shot, None)
    wait = flow.run()
    assert wait.choice.kind == "boost" and wait.choice.card_id == shot.card_id
    flow.resume(boost)
    while (wait := flow.run()) is not None:
        flow.resume(None) if wait.choice.kind != "effect" else flow.resume([DRAW])
    assert flow.result.atk_value == 2 + 3


def test_fan_the_hammer_returns_to_the_hand_when_the_fighter_it_hit_is_defeated(bprd):
    g = mk(bprd)
    wyatt, lobster = pair(g, "wyatt", "lobster")
    lobster.hp = 1
    g.controllers[0].queue = picks(DRAW)
    fan = give(g, 0, "Fan The Hammer")
    g.attack(wyatt, lobster, fan, None)
    assert not lobster.alive and fan in g.players[0].hand and fan not in g.players[0].discard


def test_fan_the_hammer_goes_to_the_discard_pile_when_the_fighter_survives(bprd):
    g = mk(bprd)
    wyatt, lobster = pair(g, "wyatt", "lobster")
    g.controllers[0].queue = picks(DRAW)
    fan = give(g, 0, "Fan The Hammer")
    g.attack(wyatt, lobster, fan, None)
    assert lobster.alive and fan in g.players[0].discard


def test_youre_a_daisy_draws_two_whatever_the_result(bprd):
    g = mk(bprd, "leonardo")
    doc, leo = arena(g, "doc", "leonardo")
    daisy = give(g, 0, "You're A Daisy If You Do")
    g.attack(doc, leo, daisy, half_shell(g))                   # lost against the wall (Daisy is 4)
    assert len(g.players[0].hand) == 2 and showdowns(g) == []


def test_a_marshal_and_an_outlaw_attacking_makes_the_rival_discard_one(bprd):
    g = mk(bprd)
    _, hellboy = arena(g)
    for _ in range(3):
        g.players[1].hand.append(g.players[1].deck.pop(0))
    g.controllers[0].queue = picks(DRAW)
    win(g, "A Marshal And An Outlaw")
    assert len(g.players[1].hand) == 2 and len(g.players[0].hand) == 1


def test_a_marshal_and_an_outlaw_defending_draws_one(bprd):
    g = mk(bprd)
    pair(g, "wyatt", "hellboy")
    atk = give(g, 1, "Service Pistol")
    g.turn = 1
    g.begin_turn()
    g.attack(g.fighters["hellboy"], g.fighters["wyatt"], atk, give(g, 0, "A Marshal And An Outlaw"))
    assert len(g.players[0].hand) == 1 and len(g.players[1].hand) == 0


def test_huckleberry_hits_an_opposing_fighter_in_the_zone_when_it_wins(bprd):
    g = mk(bprd)
    wyatt, hellboy = arena(g)
    lobster = g.fighters["lobster"]
    put_adjacent(g, "lobster", "wyatt")
    g.controllers[0].queue = picks(DRAW, "lobster")
    win(g, "I'm Your Huckleberry")
    assert lobster.hp == lobster.max_hp - 1 and hellboy.hp == 99 - 3


def test_huckleberry_does_nothing_when_the_combat_is_lost(bprd):
    g = mk(bprd, "leonardo")
    wyatt, leo = arena(g, target="leonardo")
    splinter = g.fighters["splinter"]
    put_adjacent(g, "splinter", "wyatt")
    g.attack(wyatt, leo, give(g, 0, "I'm Your Huckleberry"), half_shell(g))
    assert splinter.hp == splinter.max_hp and leo.hp == 99


def test_i_have_two_guns_hits_a_different_fighter_for_the_printed_value_of_the_rivals_card(bprd):
    g = mk(bprd, "leonardo")
    doc, leo = arena(g, "doc", "leonardo")
    splinter = g.fighters["splinter"]
    splinter.hp = splinter.max_hp = 99
    put_adjacent(g, "splinter", "doc")
    g.attack(doc, leo, give(g, 0, "I Have Two Guns, One For Each Of You"), half_shell(g))
    assert splinter.hp == 99 - 5 and leo.hp == 99                # 5 = the printed value of the half shell; Leonardo took no damage


def test_i_have_two_guns_needs_a_rival_card_and_a_different_fighter(bprd):
    g = mk(bprd)
    doc, hellboy = arena(g, "doc")
    lobster = g.fighters["lobster"]
    put_adjacent(g, "lobster", "doc")
    g.controllers[0].queue = picks(DRAW)
    win(g, "I Have Two Guns, One For Each Of You", "doc")        # the rival played nothing
    assert lobster.hp == lobster.max_hp
    g2 = mk(bprd, "leonardo")
    doc2, leo2 = arena(g2, "doc", "leonardo")
    far = sorted((s for s in g2.board.spaces if not g2.board.share_zone(doc2.pos, s) and s != leo2.pos), reverse=True)
    g2.fighters["splinter"].pos = far[0]                         # out of Doc's zone: the only one left is the fighter of the combat
    g2.attack(doc2, leo2, give(g2, 0, "I Have Two Guns, One For Each Of You"), half_shell(g2))
    assert leo2.hp == 99 and g2.fighters["splinter"].hp == g2.fighters["splinter"].max_hp


def test_gunfight_deals_four_hits_chosen_by_turns(bprd):
    g = mk(bprd)
    arena(g)
    g.controllers[0].queue = picks(DRAW)
    g.controllers[0].queue += picks("hellboy", "hellboy")
    g.controllers[1].queue = picks("doc", "wyatt")
    win(g, "Gunfight At The O.K. Corral")
    hp = {fid: f.hp for fid, f in g.fighters.items()}
    assert (hp["doc"], hp["wyatt"], hp["hellboy"]) == (8 - 1, 15 - 1, 99 - 2 - 2)


def test_better_swear_me_in_cancels_the_rivals_effects(bprd):
    g = mk(bprd)
    wyatt, hellboy = pair(g, "wyatt", "hellboy")
    atk = give(g, 1, "Right Hand Of Doom")
    g.turn = 1
    g.begin_turn()
    g.controllers[0].queue = picks(False)
    g.attack(hellboy, wyatt, atk, give(g, 0, "Better Swear Me In"))
    assert atk.text and wyatt.hp == 15 - max(0, atk.value - 2)


def test_better_swear_me_in_reveals_the_top_card_and_may_bury_it(bprd):
    g = mk(bprd)
    arena(g)
    top = g.players[1].deck[0]
    g.controllers[0].queue = picks(DRAW, True)
    win(g, "Better Swear Me In")
    swear = [r for r in g.controllers[0].requests if r.kind == "optional"]
    assert len(swear) == 1 and swear[0].extra["bury_rival"] == top.card_id and swear[0].extra["of"] == 1
    assert g.players[1].deck[-1] is top and g.players[1].deck[0] is not top


def test_better_swear_me_in_leaves_the_card_on_top_when_declined(bprd):
    g = mk(bprd)
    arena(g)
    top = g.players[1].deck[0]
    g.controllers[0].queue = picks(DRAW, False)
    win(g, "Better Swear Me In")
    assert g.players[1].deck[0] is top
    assert g.players[0].known.top(g.players[1]) == [top]


def test_bring_em_to_justice_adds_twice_the_boost_of_the_top_card(bprd):
    g = mk(bprd)
    pair(g, "wyatt", "hellboy")
    atk = give(g, 1, "Service Pistol")
    g.turn = 1
    g.begin_turn()
    top = g.players[1].deck[0]
    g.players[0].deck.remove(next(c for c in g.players[0].deck if c.title == "Bring 'Em To Justice"))
    res = g.attack(g.fighters["hellboy"], g.fighters["wyatt"], atk, give(g, 0, "Bring 'Em To Justice"))
    assert res.def_value == 0 + 2 * top.boost


def test_in_vino_veritas_draws_until_four_cards_and_gives_a_free_attack(bprd):
    g = mk(bprd)
    arena(g)
    vino = give(g, 0, "In Vino Veritas")
    g.play_scheme(0, g.fighters["doc"], vino)
    assert len(g.players[0].hand) == 4 and g.free_attacks == [None] and (g.actions_left, g.paid_actions) == (2, 1)


def test_in_vino_veritas_with_a_full_hand_only_gives_the_action(bprd):
    g = mk(bprd)
    arena(g)
    for _ in range(5):
        g.players[0].hand.append(g.players[0].deck.pop(0))
    vino = give(g, 0, "In Vino Veritas")
    g.play_scheme(0, g.fighters["doc"], vino)
    assert len(g.players[0].hand) == 5 and g.free_attacks == [None]


def test_in_vino_veritas_stops_when_the_deck_runs_out(bprd):
    g = mk(bprd)
    arena(g)
    del g.players[0].deck[:-2]
    vino = give(g, 0, "In Vino Veritas")
    g.play_scheme(0, g.fighters["doc"], vino)
    assert len(g.players[0].hand) == 2 and g.players[0].deck == []


def test_you_die_first_moves_a_rival_up_to_one_space_and_the_free_attack_is_for_that_fighter(bprd):
    g = mk(bprd)
    wyatt, hellboy = arena(g)
    lobster = g.fighters["lobster"]
    spot = empty_spaces(g, lobster.pos, 1)[0]
    g.controllers[0].queue = picks("lobster", spot)
    die = give(g, 0, "You Die First")
    g.play_scheme(0, wyatt, die)
    assert lobster.pos == spot and g.free_attacks == ["lobster"]
    g.use_action()                                             # the paid one is gone: only the free attack at the lobster is left
    card = give(g, 0, "You Just Gonna Stand There And Bleed?")
    put_adjacent(g, "lobster", "wyatt")
    with pytest.raises(RuleError):
        g.attack(wyatt, hellboy, card, None)
    g.attack(wyatt, lobster, card, None)
    assert g.actions_left == 0


def test_you_die_first_is_wyatts_and_in_vino_veritas_is_docs(bprd):
    g = mk(bprd)
    die, vino = give(g, 0, "You Die First"), give(g, 0, "In Vino Veritas")
    assert die.usable_by("Wyatt Earp") and not die.usable_by("Doc Holliday")
    assert vino.usable_by("Doc Holliday") and not vino.usable_by("Wyatt Earp")
    with pytest.raises(RuleError):
        g.play_scheme(0, g.fighters["doc"], die)
