"""Daredevil's cards and special ability on the interpreter, bot side (player 0 plays Daredevil, controllers answer).

The human side (panel, FakeTTS) is in tests/test_daredevil_human.py. Every card has a test here; the numbers are the ones printed
on the real cards (data/heroes/daredevil.json)."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.ai_effects import EffectAI
from sparring.effects.choose import ChoiceRequest
from sparring.state import Game
from test_effects_combat import Asking, hp, pair, put_adjacent

DEVIL = "Devil of Hell's Kitchen"


def mk(bprd, foe="hellboy", seed=3):
    """Daredevil = player 0 (the bot), `foe` = player 1; player 0's turn, empty hands."""
    ctl = {0: Asking(), 1: Asking()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("daredevil", foe), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def on_top(g, player, *titles):
    """The cards titled so go to the top of the deck, in that order."""
    deck = g.players[player].deck
    cards = []
    for title in titles:
        cards.append(next(c for c in deck if c.title == title and c not in cards))
    for c in cards:
        deck.remove(c)
    deck[:0] = cards
    return cards


def script(g, count=0, order=0, other=None):
    """The owner's answers (recorded in `requests`): `count` blind boosts, option `order` of an order choice (0: the ability
    first) and, for any other request, whatever `other(req)` says (None: the generic answer)."""
    ctl = g.controllers[0]

    def choose(game, req):
        ctl.requests.append(req)
        if req.extra.get("blind_count"):
            return [count]
        if req.extra.get("during_order"):
            return [order]
        return other(req) if other else None
    ctl.choose_effect = choose


def asked(g):
    return [r for r in g.controllers[0].requests]


def to_discard(g, player, *titles):
    out = []
    for title in titles:
        c = next(c for c in g.players[player].deck if c.title == title and c not in out)
        g.players[player].deck.remove(c)
        g.players[player].discard.append(c)
        out.append(c)
    return out


# ---------------------------------------------------------------- the deck and the switch

def test_daredevil_is_interpreted_alone_with_22_cards_and_17_hit_points(bprd):
    g = mk(bprd)
    assert "daredevil" in g.fx.dsl_heroes
    assert [f.fid for f in g.own(0)] == ["daredevil"] and g.fighters["daredevil"].hp == 17 and not g.fighters["daredevil"].ranged
    assert len(g.players[0].full_set) == 22


# ---------------------------------------------------------------- the special ability: BLIND BOOST with 2 or fewer cards in hand

def test_the_ability_asks_for_a_blind_boost_only_with_two_or_fewer_cards_in_hand(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    for n, expected in ((2, True), (3, False)):
        g.players[0].deck.extend(g.players[0].hand)
        g.players[0].hand.clear()
        g.actions_left = 2
        for c in list(g.players[0].discard):
            g.players[0].discard.remove(c)
            g.players[0].deck.append(c)
        spare = [c for c in g.players[0].deck if c.title == "Breather"][:n]
        for c in spare:
            g.players[0].deck.remove(c)
            g.players[0].hand.append(c)
        g.controllers[0].requests.clear()
        script(g, 0)
        attack = give(g, 0, "Grappling Hook")                 # the played card leaves the hand: n + 0 cards stay in it
        g.attack(d, liz, attack, None)
        counts = [r for r in asked(g) if r.extra.get("blind_count")]
        assert bool(counts) is expected, (n, counts)
        if expected:
            assert counts[0].options == [0, 1] and counts[0].extra["ability"] is True and counts[0].extra["times"] == 1


def test_the_ability_discards_the_declared_top_card_and_adds_its_boost_to_an_attack(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    (top,) = on_top(g, 0, DEVIL)
    script(g, 1)
    hook = give(g, 0, "Grappling Hook")
    deck = len(g.players[0].deck)
    res = g.attack(d, liz, hook, None)
    assert res.atk_value == 3 + top.boost == 6 and top in g.players[0].discard and len(g.players[0].deck) == deck - 1


def test_the_ability_boosts_a_defense_too(bprd):
    g = mk(bprd, "liz-sherman")
    liz, d = pair(g, "liz", "daredevil")
    (top,) = on_top(g, 0, DEVIL)
    script(g, 1)
    g.turn = 1
    attacker_card = next(c for c in g.players[1].deck if c.can_attack and c.usable_by("Liz Sherman"))
    g.players[1].deck.remove(attacker_card)
    g.players[1].hand.append(attacker_card)
    res = g.attack(liz, d, attacker_card, give(g, 0, "Son Of A Boxer"))
    assert res.def_value == 3 + top.boost and top in g.players[0].discard


def test_declaring_zero_blind_boosts_moves_nothing(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    script(g, 0)
    hook = give(g, 0, "Grappling Hook")
    deck = len(g.players[0].deck)
    res = g.attack(d, liz, hook, None)
    assert res.atk_value == 3 and len(g.players[0].deck) == deck


def test_an_empty_deck_asks_for_no_blind_boost(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    g.players[0].deck.clear()
    script(g, 1)
    res = g.attack(d, liz, give(g, 0, "Grappling Hook"), None)
    assert res.atk_value == 3 and not [r for r in asked(g) if r.extra.get("blind_count")]


def test_the_ability_survives_a_feint_it_is_on_the_hero_not_on_the_card(bprd):
    """Feint cancels the effects of Man Without Fear (its own BLIND BOOST) but not Daredevil's ability."""
    g = mk(bprd, "doctor-strange")
    d, strange = pair(g, "daredevil", "strange")
    (top,) = on_top(g, 0, DEVIL)
    script(g, 1)
    res = g.attack(d, strange, give(g, 0, "Man Without Fear"), give(g, 1, "Feint"))
    counts = [r for r in asked(g) if r.extra.get("blind_count")]
    assert len(counts) == 1 and counts[0].extra["ability"] is True       # only the ability asked
    assert res.atk_value == 2 + top.boost and top in g.players[0].discard


def test_man_without_fear_adds_its_own_blind_boost_to_the_one_of_the_ability(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    a, b = on_top(g, 0, "Breather", "Breather")
    script(g, 1)
    res = g.attack(d, liz, give(g, 0, "Man Without Fear"), None)
    counts = [r for r in asked(g) if r.extra.get("blind_count")]
    assert len(counts) == 2 and [r.extra.get("ability", False) for r in counts] == [True, False]
    assert res.atk_value == 2 + a.boost + b.boost == 6 and {a, b} <= set(g.players[0].discard)


def test_the_owner_chooses_the_order_when_the_card_has_its_own_during_effect(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    on_top(g, 0, "Breather", "Breather")
    script(g, 1, order=1)
    g.attack(d, liz, give(g, 0, "Man Without Fear"), None)
    orders = [r for r in asked(g) if r.extra.get("during_order")]
    assert len(orders) == 1 and orders[0].kind == "effect" and len(orders[0].options) == 2
    counts = [r for r in asked(g) if r.extra.get("blind_count")]
    assert [r.extra.get("ability", False) for r in counts] == [False, True]            # the card first, then the ability


def test_a_card_without_during_effects_and_a_hand_over_two_asks_no_order(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    script(g, 0)
    g.attack(d, liz, give(g, 0, "Grappling Hook"), None)
    assert not [r for r in asked(g) if r.extra.get("during_order")]


# ---------------------------------------------------------------- Devil of Hell's Kitchen

def test_the_devil_is_worth_8_with_no_cards_in_the_deck(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    g.players[0].deck.clear()
    res = g.attack(d, liz, give(g, 0, DEVIL), None)
    assert res.atk_value == 8


def test_the_devil_is_worth_4_with_cards_left_in_the_deck(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    script(g, 0)
    res = g.attack(d, liz, give(g, 0, DEVIL), None)
    assert res.atk_value == 4


def test_a_blind_boost_that_empties_the_deck_first_makes_the_devil_worth_8(bprd):
    """The ability first (it takes the last card of the deck), then the Devil's DURING sees the empty deck."""
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    (last,) = on_top(g, 0, "Breather")
    g.players[0].deck[:] = [last]
    script(g, 1, order=0)
    res = g.attack(d, liz, give(g, 0, DEVIL), None)
    assert res.atk_value == 8 + last.boost == 10 and last in g.players[0].deck      # the AFTER shuffled it back


def test_the_card_first_order_misses_the_empty_deck(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    (last,) = on_top(g, 0, "Breather")
    g.players[0].deck[:] = [last]
    script(g, 1, order=1)
    res = g.attack(d, liz, give(g, 0, DEVIL), None)
    assert res.atk_value == 4 + last.boost


def test_the_devil_shuffles_itself_and_the_last_four_cards_that_reached_the_discard_pile_into_the_deck(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    script(g, 0)
    old = to_discard(g, 0, "Feint", "Breather", "Grappling Hook", "Take A Knee", "Son Of A Boxer")      # arrival order: Feint first ... Boxer last
    devil = give(g, 0, DEVIL)
    deck = len(g.players[0].deck)
    g.attack(d, liz, devil, None)
    back = {devil, *old[1:]}                                                        # itself + the last 4 (Ivan, 2026-11-07)
    assert set(g.players[0].discard) == {old[0]} and back <= set(g.players[0].deck)
    assert len(g.players[0].deck) == deck + 5


def test_the_devil_returns_fewer_cards_when_the_discard_pile_is_short(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    script(g, 0)
    (old,) = to_discard(g, 0, "Feint")
    devil = give(g, 0, DEVIL)
    g.attack(d, liz, devil, None)
    assert not g.players[0].discard and {devil, old} <= set(g.players[0].deck)


def test_boosts_and_blind_boosted_cards_of_this_combat_count_as_the_last_cards_played(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    (milled,) = on_top(g, 0, "Breather")
    older = to_discard(g, 0, "Feint", "Grappling Hook")
    script(g, 1)
    devil = give(g, 0, DEVIL)
    g.attack(d, liz, devil, None)
    assert {devil, milled, *older} <= set(g.players[0].deck)        # itself, the milled card and the 2 most recent others
    assert not g.players[0].discard


def test_a_cancelled_devil_does_not_shuffle_anything(bprd):
    g = mk(bprd, "doctor-strange")
    d, strange = pair(g, "daredevil", "strange")
    script(g, 0)
    (old,) = to_discard(g, 0, "Breather")
    devil = give(g, 0, DEVIL)
    g.attack(d, strange, devil, give(g, 1, "Feint"))
    assert old in g.players[0].discard and devil in g.players[0].discard


# ---------------------------------------------------------------- the other cards

def test_take_a_knee_discards_the_top_card_and_heals_its_boost(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    script(g, 0)
    (top,) = on_top(g, 0, DEVIL)                       # boost 3
    d.hp = 10
    g.attack(d, liz, give(g, 0, "Take A Knee"), None)
    assert top in g.players[0].discard and d.hp == 13


def test_take_a_knee_heals_at_most_to_the_maximum_and_nothing_with_an_empty_deck(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    script(g, 0)
    on_top(g, 0, DEVIL)
    d.hp = 16
    g.attack(d, liz, give(g, 0, "Take A Knee"), None)
    assert d.hp == 17
    g.players[0].deck.clear()
    d.hp = 10
    g.actions_left = 2
    g.attack(d, liz, give(g, 0, "Take A Knee", 1), None)
    assert d.hp == 10


def test_take_a_knee_also_works_as_a_defense(bprd):
    g = mk(bprd, "liz-sherman")
    liz, d = pair(g, "liz", "daredevil")
    script(g, 0)
    (top,) = on_top(g, 0, DEVIL)
    d.hp = 10
    g.turn = 1
    attacker_card = next(c for c in g.players[1].deck if c.can_attack and c.usable_by("Liz Sherman"))
    g.players[1].deck.remove(attacker_card)
    g.players[1].hand.append(attacker_card)
    res = g.attack(liz, d, attacker_card, give(g, 0, "Take A Knee"))
    assert top in g.players[0].discard and d.hp == 10 - res.damage + top.boost


def test_son_of_a_boxer_hits_a_fighter_next_to_daredevil_only_when_he_lost(bprd):
    g = mk(bprd, "liz-sherman")
    liz, d = pair(g, "liz", "daredevil")
    script(g, 0)
    g.turn = 1
    strong = max((c for c in g.players[1].deck if c.can_attack and c.usable_by("Liz Sherman")), key=lambda c: c.value or 0)
    g.players[1].deck.remove(strong)
    g.players[1].hand.append(strong)
    before = liz.hp
    res = g.attack(liz, d, strong, give(g, 0, "Son Of A Boxer"), values=(0, 0))
    lost = res.attacker_won
    assert (liz.hp == before - 2) is lost
    g.actions_left = 2
    weak = next(c for c in g.players[1].deck if c.can_attack and c.usable_by("Liz Sherman") and c is not strong)
    g.players[1].deck.remove(weak)
    g.players[1].hand.append(weak)
    before = liz.hp
    res = g.attack(liz, d, weak, give(g, 0, "Son Of A Boxer", 1), values=(0, 9))      # a wall: the attack cannot win
    assert not res.attacker_won and liz.hp == before - 0


def test_grappling_hook_moves_daredevil_up_to_two_spaces(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    script(g, 0)
    start = d.pos
    far = next(s for s in g.board.spaces if g.board.distance(start, s) == 2 and s != liz.pos
               and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].moves = {"daredevil": far}
    g.attack(d, liz, give(g, 0, "Grappling Hook"), None)
    assert d.pos == far


def line_of_three(board):
    """Spaces a - b - c in a row: a and c two steps apart with b between them."""
    for a in sorted(board.spaces):
        for b in sorted(board.adj[a]):
            for c in sorted(board.adj[b]):
                if board.distance(a, c) == 2:
                    return a, b, c


def test_through_adversity_moves_through_a_fighter_and_deals_it_one_damage(bprd):
    g = mk(bprd, "hellboy")
    d, hell = g.fighters["daredevil"], g.hero(1)
    a, b, c = line_of_three(g.board)
    d.pos, hell.pos = a, b
    for f in g.fighters.values():
        if f not in (d, hell) and f.alive:
            f.pos = max(g.board.spaces)
    g.controllers[0].moves = {"daredevil": c}
    before = hell.hp
    g.play_scheme(0, d, give(g, 0, "Through Adversity"))
    assert d.pos == c and hell.hp == before - 1


def test_through_adversity_damages_each_fighter_he_moves_through(bprd):
    g = mk(bprd, "baba-yaga")                                    # Baba Yaga has harpies: several fighters on the way
    d = g.fighters["daredevil"]
    path = None
    for a in sorted(g.board.spaces):
        for b in sorted(g.board.adj[a]):
            for c in sorted(g.board.adj[b] - {a}):
                for e in sorted(g.board.adj[c] - {a, b}):
                    if len({a, b, c, e}) == 4 and g.board.distance(a, e) == 3:
                        path = (a, b, c, e)
                        break
                if path: break
            if path: break
        if path: break
    a, b, c, e = path
    foes = [f for f in g.own(1)]
    d.pos = a
    foes[0].pos, foes[1].pos = b, c
    for f in foes[2:]:
        f.pos = max(s for s in g.board.spaces if s not in path)
    g.controllers[0].moves = {"daredevil": e}
    before = [f.hp for f in foes]
    g.play_scheme(0, d, give(g, 0, "Through Adversity"))
    after = [f.hp for f in foes]
    assert d.pos == e and after[0] == before[0] - 1 and after[1] == before[1] - 1 and after[2:] == before[2:]


def test_through_adversity_hits_nobody_when_the_path_met_no_fighter(bprd):
    g = mk(bprd, "hellboy")
    d, hell = g.fighters["daredevil"], g.hero(1)
    a, b, c = line_of_three(g.board)
    far = max(g.board.spaces, key=lambda s: g.board.distance(a, s))
    d.pos, hell.pos = a, far
    g.controllers[0].moves = {"daredevil": c}
    before = hell.hp
    g.play_scheme(0, d, give(g, 0, "Through Adversity"))
    assert d.pos == c and hell.hp == before


def test_breather_returns_an_attack_defense_or_versatile_card_from_the_discard_pile_but_never_a_scheme(bprd):
    g = mk(bprd, "liz-sherman")
    schemes = to_discard(g, 0, "Through Adversity")
    other, feint = to_discard(g, 0, "Son Of A Boxer", "Feint")
    script(g, other=lambda req: [other.card_id] if req.kind == "cards" else None)
    g.play_scheme(0, g.fighters["daredevil"], give(g, 0, "Breather"))
    req = next(r for r in asked(g) if r.kind == "cards")
    assert sorted(req.options) == sorted([other.card_id, feint.card_id]) and schemes[0].card_id not in req.options
    assert other in g.players[0].hand and schemes[0] in g.players[0].discard


# ---------------------------------------------------------------- the bot decides BLIND BOOST

def request(g, **extra):
    d = g.fighters["daredevil"]
    base = dict(blind_count=True, times=1, attacking=True, margin=0, value=3, limit=None, target="liz", ability=True)
    return ChoiceRequest("amount", 0, [0, 1], 1, 1, None, "k", "", {**base, **extra}, 0)


def test_the_bot_blind_boosts_when_the_extra_value_decides_the_blow(bprd):
    g = mk(bprd, "liz-sherman")
    pair(g, "daredevil", "liz")
    ai = EffectAI(0)
    assert ai._blind_boost(g, request(g, margin=-1, value=3)) == 1       # one short of winning
    assert ai._blind_boost(g, request(g, margin=-1, value=3, limit=3)) == 0          # a card that ignores a total over 3 would lose it


def test_the_bot_counts_the_empty_deck_bonus_of_the_devil_when_declaring(bprd):
    g = mk(bprd, "liz-sherman")
    d, liz = pair(g, "daredevil", "liz")
    (last,) = on_top(g, 0, "Breather")
    g.players[0].deck[:] = [last]
    devil = give(g, 0, DEVIL)
    ai = EffectAI(0)
    req = request(g, margin=-3, value=4)
    req.card_id = devil.card_id
    assert ai._blind_boost(g, req) == 1
    assert ai.decide(g, ChoiceRequest("effect", 0, [0, 1], 1, 1, devil.card_id, "k", "", {"during_order": True, "labels": ["a", "b"]}, 0), False) == [0]


# ---------------------------------------------------------------- the engine pieces Daredevil added

def test_the_validator_accepts_pick_last_on_the_discard_pile_only():
    from tools.validate_effects import load_schema, validate
    doc = {"schema": 1, "hero": "daredevil", "ability": {"text": "x", "triggers": [], "passives": []}, "plugins": [],
           "cards": [{"title": "Breather", "copies": 1, "text": "x", "effects": {
               "immediately": [], "during": [], "after": [], "boost": [],
               "scheme": [{"op": "put_in_hand", "cards": {"zone": "hand", "player": "owner", "pick": "last"}}]}}]}
    errors = validate(doc, load_schema(), None)
    assert any("pick 'last'" in e for e in errors), errors
    doc["cards"][0]["effects"]["scheme"][0]["cards"]["zone"] = "discard"
    assert not [e for e in validate(doc, load_schema(), None) if "pick 'last'" in e]


def test_a_single_forced_option_is_still_asked_when_the_run_asks_for_a_confirmation(bprd):
    from sparring.effects.choose import PanelChooser, Suspend
    from sparring.effects.run import Ctx, EffectRun
    g = mk(bprd)
    run = EffectRun([{"op": "end_turn"}], Ctx(owner=0))
    run._choosers, run._game, run._op_key = {0: PanelChooser(), 1: PanelChooser()}, g, "x"
    assert run.ask(g, "amount", 0, [1], 1, 1, "go") == [1]                          # forced: taken without asking
    with pytest.raises(Suspend) as paused:
        run.ask(g, "amount", 0, [1], 1, 1, "go", confirm=True)
    assert paused.value.request.extra == {"confirm": True}


def test_deck_sheet_finds_a_deck_of_22_cards_with_its_character_card():
    from tools.import_save import deck_sheet
    ids = {"DeckIDs": [338, *range(17600, 17622)]}
    assert deck_sheet(ids, 22) == ((17600, 17621), 338) and deck_sheet(ids) is None
