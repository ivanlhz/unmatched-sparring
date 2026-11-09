"""Yennefer & Triss on the engine, bot side (player 0 plays the hero, the controllers answer), for BOTH variants: `yennefer-triss`
(Yennefer is the hero, Triss the 6 HP sidekick) and `triss-yennefer` (the other way round). The deck is the same; the ability is the
hero's own (SORCERESS OF VENGERBERG for Yennefer, MERIGOLD THE FEARLESS for Triss) and the card bands (Incinerate is Yennefer's,
Merigold's Hailstorm is Triss's) follow who is the hero. Every card is tested with the numbers printed on it. The human side (panel,
FakeTTS) is in tests/test_yennefer_triss_human.py and the full games in tests/test_yennefer_triss_matrix.py."""
from __future__ import annotations

import json

import pytest

from conftest import give
from sparring.combat_flow import CombatFlow
from sparring.effects.model import load_effects
from sparring.heroes import load_hero
from sparring.state import Game
from test_bigfoot_effects import Answers, pick
from test_effects_combat import pair, put_adjacent

VARIANTS = {"yennefer-triss": ("yennefer", "triss"), "triss-yennefer": ("triss", "yennefer")}


def mk(bprd, hero="yennefer-triss", foe="hellboy", seed=3, turn=0):
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=(hero, foe), bot_player=0)
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def defend(g, title="B.P.R.D. Training", player=1):
    return give(g, player, title)


def filler(g, player, n, avoid=()):
    """n cards more in the hand of `player` that are not named in `avoid`."""
    pool = [c for c in g.players[player].deck if c.title not in avoid][:n]
    for c in pool:
        g.players[player].deck.remove(c)
        g.players[player].hand.append(c)
    return pool


# ---------------------------------------------------------------- the hero and its sidekick

@pytest.mark.parametrize("slug,hero,side", [(s, *f) for s, f in VARIANTS.items()])
def test_one_heroine_is_the_hero_with_14_life_and_the_other_a_6_life_sidekick(bprd, slug, hero, side):
    g = mk(bprd, slug)
    h, s = g.fighters[hero], g.fighters[side]
    assert (h.hero, h.hp, h.move, h.ranged, h.name) == (True, 14, 2, True, hero.capitalize())
    assert (s.hero, s.hp, s.move, s.ranged, s.name) == (False, 6, 2, True, side.capitalize())
    assert [f.fid for f in g.own(0)] == [hero, side] and g.hero(0) is h
    deck = g.players[0].full_set
    assert len(deck) == 30 and deck[0].card_id == 17600 and deck[-1].card_id == 17629
    assert slug in g.fx.dsl_heroes


def test_the_two_variants_are_the_same_deck_with_different_abilities():
    y, t = load_hero("yennefer-triss"), load_hero("triss-yennefer")
    assert [(c["title"], c["fighter"], c["value"], c["boost"], c["text"]) for c in y.cards] == \
           [(c["title"], c["fighter"], c["value"], c["boost"], c["text"]) for c in t.cards]
    assert "SORCERESS OF VENGERBERG" in y.ability and "MERIGOLD THE FEARLESS" in t.ability
    fy, ft = load_effects("yennefer-triss"), load_effects("triss-yennefer")
    same = lambda fx, prefix: json.dumps({k: v.moments for k, v in fx.cards.items()}, sort_keys=True).replace(prefix, "@")      # the plugin ids carry the hero's fid
    assert same(fy, "yennefer:") == same(ft, "triss:")
    assert fy.passives and not fy.triggers and ft.triggers and not ft.passives


@pytest.mark.parametrize("slug,hero,side", [(s, *f) for s, f in VARIANTS.items()])
def test_the_card_bands_follow_who_is_the_hero(bprd, slug, hero, side):
    g = mk(bprd, slug)
    inc, hail, echo = give(g, 0, "Incinerate"), give(g, 0, "Merigold's Hailstorm"), give(g, 0, "Echoing blast")
    assert inc.usable_by("Yennefer") and not inc.usable_by("Triss")
    assert hail.usable_by("Triss") and not hail.usable_by("Yennefer")
    assert echo.usable_by("Yennefer") and echo.usable_by("Triss")
    assert (inc.value, inc.boost, hail.value, hail.boost) == (7, 2, 4, 3)


# ---------------------------------------------------------------- SORCERESS OF VENGERBERG (Yennefer is the hero)

def test_yennefer_attacking_may_boost_whatever_the_card(bprd):
    g = mk(bprd)
    yen, foe = pair(g, "yennefer", "hellboy")
    card = give(g, 0, "Echoing blast")                              # a card with no BOOST text of its own
    flow = CombatFlow(g, yen, foe, card, None)
    wait = flow.run()
    assert wait.choice.kind == "boost" and wait.choice.player == 0 and wait.choice.card_id == card.card_id
    boost = give(g, 0, "Telepathy")                                 # BOOST 1
    flow.resume(boost)
    assert flow.run() is None
    assert flow.result.atk_value == card.value + boost.boost and boost in g.players[0].discard


def test_declining_the_boost_adds_nothing(bprd):
    g = mk(bprd)
    yen, foe = pair(g, "yennefer", "hellboy")
    flow = CombatFlow(g, yen, foe, give(g, 0, "Echoing blast"), None)
    assert flow.run().choice.kind == "boost"
    flow.resume(None)
    assert flow.run() is None and flow.result.atk_value == 3


def test_a_defending_yennefer_and_an_attacking_triss_sidekick_do_not_boost(bprd):
    g = mk(bprd, turn=1)
    yen, foe = pair(g, "yennefer", "hellboy")
    atk = give(g, 1, "Excalibur") if any(c.title == "Excalibur" for c in g.players[1].deck) else give(g, 1, g.players[1].deck[0].title)
    flow = CombatFlow(g, foe, yen, next(c for c in g.players[1].hand if c.can_attack), give(g, 0, "Magical barrier"))
    assert flow.run() is None                                       # Yennefer defends: no boost question
    g2 = mk(bprd)
    triss, foe2 = pair(g2, "triss", "hellboy")
    flow2 = CombatFlow(g2, triss, foe2, give(g2, 0, "Echoing blast"), None)
    assert flow2.run() is None                                      # the sidekick has no ability


def test_the_boost_cannot_be_canceled(bprd):
    g = mk(bprd, foe="medusa")
    yen, foe = pair(g, "yennefer", "medusa")
    feint = give(g, 1, "Feint")
    card = give(g, 0, "Echoing blast")
    flow = CombatFlow(g, yen, foe, card, feint)
    wait = flow.run()
    assert "atk" in flow.ctx.cancelled and wait is not None and wait.choice.kind == "boost"
    boost = give(g, 0, "Telepathy")
    flow.resume(boost)
    assert flow.run() is None and flow.result.atk_value >= boost.boost


def test_triss_as_the_hero_has_no_boost_ability(bprd):
    g = mk(bprd, "triss-yennefer")
    triss, foe = pair(g, "triss", "hellboy")
    flow = CombatFlow(g, triss, foe, give(g, 0, "Echoing blast"), None)
    assert flow.run() is None
    g.fighters["yennefer"].pos = next(s for s in sorted(g.board.adj[triss.pos]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    yen = g.fighters["yennefer"]                                    # Yennefer as the SIDEKICK: nobody has the ability
    g2 = mk(bprd, "triss-yennefer")
    yen2, foe2 = pair(g2, "yennefer", "hellboy")
    assert CombatFlow(g2, yen2, foe2, give(g2, 0, "Echoing blast"), None).run() is None


# ---------------------------------------------------------------- MERIGOLD THE FEARLESS (Triss is the hero)

@pytest.mark.parametrize("scheme", ["Advisor to the king", "Lodge of sorceresses"])
def test_after_triss_plays_a_scheme_a_fighter_next_to_her_takes_two(bprd, scheme):
    g = mk(bprd, "triss-yennefer")
    triss, foe = pair(g, "triss", "hellboy")
    hp = foe.hp
    g.play_scheme(0, triss, give(g, 0, scheme))
    assert foe.hp == hp - 2


def test_with_nobody_next_to_her_nothing_happens(bprd):
    g = mk(bprd, "triss-yennefer")
    triss, foe = pair(g, "triss", "hellboy")
    foe.pos = next(s for s in sorted(g.board.spaces, reverse=True) if s not in g.board.adj[triss.pos] and s != triss.pos
                   and all(f.pos != s for f in g.fighters.values() if f.alive))
    hp = foe.hp
    g.play_scheme(0, triss, give(g, 0, "Advisor to the king"))
    assert foe.hp == hp


def test_she_chooses_among_the_fighters_next_to_her(bprd):
    g = mk(bprd, "triss-yennefer")
    triss, foe = pair(g, "triss", "hellboy")
    put_adjacent(g, "lobster", "triss")
    g.controllers[0].queue = [["lobster"]]
    lobster = g.fighters["lobster"]
    hp, lhp = foe.hp, lobster.hp
    g.play_scheme(0, triss, give(g, 0, "Advisor to the king"))
    assert foe.hp == hp and lobster.hp == lhp - 2


def test_the_bots_choice_hits_the_rival_not_her_own_sidekick(bprd):
    from sparring.ai_medusa import MedusaAI
    g = mk(bprd, "triss-yennefer")
    g.controllers[0] = MedusaAI(0)
    triss, foe = pair(g, "triss", "hellboy")
    put_adjacent(g, "yennefer", "triss")
    hp, mine = foe.hp, g.fighters["yennefer"].hp
    g.play_scheme(0, triss, give(g, 0, "Advisor to the king"))
    assert foe.hp == hp - 2 and g.fighters["yennefer"].hp == min(6, mine + 1)           # the ONGOING's heal reached her, the damage did not


def test_with_only_her_own_sidekick_next_to_her_the_damage_is_not_optional(bprd):
    g = mk(bprd, "triss-yennefer")
    triss, foe = pair(g, "triss", "hellboy")
    foe.pos = max(s for s in g.board.spaces if s not in g.board.adj[triss.pos] and s != triss.pos
                  and all(f.pos != s for f in g.fighters.values() if f.alive))
    put_adjacent(g, "yennefer", "triss")
    g.play_scheme(0, triss, give(g, 0, "Lodge of sorceresses"))
    assert g.fighters["yennefer"].hp == 4                                         # "a fighter adjacent to Triss": no exception for her own


def test_yennefer_as_the_hero_has_no_merigold(bprd):
    g = mk(bprd)
    yen, foe = pair(g, "yennefer", "hellboy")
    hp = foe.hp
    g.play_scheme(0, yen, give(g, 0, "Advisor to the king"))
    assert foe.hp == hp


# ---------------------------------------------------------------- the cards

def test_incinerate_the_opponent_may_discard_two_cards_to_ignore_its_value(bprd):
    g = mk(bprd)
    yen, foe = pair(g, "yennefer", "hellboy")
    filler(g, 1, 2)
    g.controllers[1].queue = [[True]]
    res = g.attack(yen, foe, give(g, 0, "Incinerate"), None)
    assert res.atk_value == 0 and foe.hp == foe.max_hp and len(g.players[1].hand) == 0


def test_incinerate_declined_hits_for_seven(bprd):
    g = mk(bprd)
    yen, foe = pair(g, "yennefer", "hellboy")
    filler(g, 1, 2)
    g.controllers[1].queue = [[False]]
    res = g.attack(yen, foe, give(g, 0, "Incinerate"), None)
    assert res.atk_value == 7 and foe.hp == foe.max_hp - 7 and len(g.players[1].hand) == 2


def test_incinerate_with_fewer_than_two_cards_cannot_be_paid_and_cannot_be_canceled(bprd):
    g = mk(bprd, foe="medusa")
    yen, foe = pair(g, "yennefer", "medusa")
    filler(g, 1, 1, avoid=("Feint",))
    res = g.attack(yen, foe, give(g, 0, "Incinerate"), give(g, 1, "Feint"))
    assert res.atk_value == 7                                        # Feint cancels everything else, not this card's effect


def test_echoing_blast_returns_to_the_hand_only_when_won(bprd):
    g = mk(bprd, foe="leonardo")
    yen, leo = pair(g, "yennefer", "leonardo")
    blast = give(g, 0, "Echoing blast")
    res = g.attack(yen, leo, blast, None)
    assert res.attacker_won and blast in g.players[0].hand and blast not in g.players[0].discard
    g.actions_left = 2
    lost = give(g, 0, "Echoing blast", 1)
    res = g.attack(yen, leo, lost, give(g, 1, max((c.title for c in g.players[1].deck if c.can_defend and (c.value or 0) >= 4), key=len)))
    assert not res.attacker_won and lost in g.players[0].discard


def test_portal_to_anywhere_places_any_fighter_of_the_combat_and_gains_an_action(bprd):
    g = mk(bprd, foe="leonardo")
    yen, leo = pair(g, "yennefer", "leonardo")
    far = max(s for s in g.board.spaces if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [["leonardo"], [far]]
    g.attack(yen, leo, give(g, 0, "Portal to anywhere"), None)
    assert leo.pos == far and g.actions_left == 2                    # 2 - 1 for the attack + 1 gained


def test_portal_may_place_her_own_fighter_too(bprd):
    g = mk(bprd, foe="leonardo")
    yen, leo = pair(g, "yennefer", "leonardo")
    far = max(s for s in g.board.spaces if all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [["yennefer"], [far]]
    g.attack(yen, leo, give(g, 0, "Portal to anywhere"), None)
    assert yen.pos == far


@pytest.mark.parametrize("option,check", [(0, "discard"), (1, "damage"), (2, "mill")])
def test_merigolds_hailstorm_the_opponent_chooses_one(bprd, option, check):
    g = mk(bprd, "triss-yennefer", foe="leonardo")
    triss, leo = pair(g, "triss", "leonardo")
    filler(g, 1, 3)
    g.controllers[1].queue = [[option]]
    deck, hp = len(g.players[1].deck), leo.hp
    g.attack(triss, leo, give(g, 0, "Merigold's Hailstorm"), None)
    combat = 4                                                       # no defense: the 4 of the card
    if check == "discard":
        assert len(g.players[1].hand) == 1 and leo.hp == hp - combat
    elif check == "damage":
        assert leo.hp == hp - combat - 3 and len(g.players[1].hand) == 3
    else:
        assert len(g.players[1].deck) == deck - 4 and len(g.players[1].discard) == 4 and leo.hp == hp - combat


def test_hailstorm_mill_takes_what_is_left_of_a_short_deck(bprd):
    g = mk(bprd, "triss-yennefer", foe="leonardo")
    triss, leo = pair(g, "triss", "leonardo")
    del g.players[1].deck[2:]
    g.controllers[1].queue = [[2]]
    g.attack(triss, leo, give(g, 0, "Merigold's Hailstorm"), None)
    assert g.players[1].deck == [] and len(g.players[1].discard) == 2


def test_telepathy_the_opponent_discards_one_card_or_loses_their_effects(bprd):
    g = mk(bprd, foe="leonardo")
    yen, leo = pair(g, "yennefer", "leonardo")
    defense = defend(g, next(c.title for c in g.players[1].deck if c.can_defend and c.type == "defense"))
    filler(g, 1, 1, avoid=(defense.title,))
    g.controllers[1].queue = [[False]]
    flow = g.begin_attack(yen, leo, give(g, 0, "Telepathy"), defense)
    flow.run()
    assert flow.is_cancelled("def")
    g2 = mk(bprd, foe="leonardo")
    yen2, leo2 = pair(g2, "yennefer", "leonardo")
    defense2 = defend(g2, defense.title)
    filler(g2, 1, 1, avoid=(defense.title,))
    g2.controllers[1].queue = [[True]]
    flow2 = g2.begin_attack(yen2, leo2, give(g2, 0, "Telepathy"), defense2)
    flow2.run()
    assert not flow2.is_cancelled("def") and len(g2.players[1].hand) == 0


def test_telepathy_with_an_empty_hand_cancels(bprd):
    g = mk(bprd, foe="leonardo")
    yen, leo = pair(g, "yennefer", "leonardo")
    defense = defend(g, next(c.title for c in g.players[1].deck if c.can_defend and c.type == "defense"))
    flow = g.begin_attack(yen, leo, give(g, 0, "Telepathy"), defense)
    flow.run()
    assert flow.is_cancelled("def")


def test_quick_and_ready_places_the_fighter_in_their_zone_and_draws(bprd):
    g = mk(bprd, foe="leonardo")
    yen, leo = pair(g, "yennefer", "leonardo")
    spot = next(s for s in sorted(g.board.spaces) if g.board.share_zone(leo.pos, s) and s not in (yen.pos, leo.pos)
                and s not in g.board.adj[leo.pos] and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.controllers[0].queue = [[spot]]
    g.attack(yen, leo, give(g, 0, "Quick and ready"), None)
    assert yen.pos == spot and len(g.players[0].hand) == 1


def test_ball_lightning_won_only_the_opponent_discards_and_lost_both(bprd):
    g = mk(bprd, foe="leonardo")
    yen, leo = pair(g, "yennefer", "leonardo")
    filler(g, 1, 2)
    filler(g, 0, 2)
    g.attack(yen, leo, give(g, 0, "Ball lightning"), None)
    assert len(g.players[1].hand) == 1 and len(g.players[0].hand) == 2
    g2 = mk(bprd, foe="leonardo")
    yen2, leo2 = pair(g2, "yennefer", "leonardo")
    filler(g2, 1, 2, avoid=())
    filler(g2, 0, 2)
    wall = defend(g2, max((c.title for c in g2.players[1].deck if c.can_defend), key=lambda t: next(c.value or 0 for c in g2.players[1].deck if c.title == t)))
    res = g2.attack(yen2, leo2, give(g2, 0, "Ball lightning"), wall)
    assert not res.attacker_won and len(g2.players[0].hand) == 1 and len(g2.players[1].hand) == 1      # 2 - 1 each (the wall left the rival's hand too)
    assert len(g2.players[0].discard) == 2


def test_paralyzing_fetters_locks_the_attackers_value_at_its_printed_value(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    yen, leo = pair(g, "yennefer", "leonardo")
    flow = g.begin_attack(leo, yen, give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and (c.value or 0) >= 3)),
                          give(g, 0, "Paralyzing fetters"), values=(3, 0))
    flow.run()
    assert "atk" in flow.value_locked and flow.ctx.atk_value == flow.atk_card.value


def test_magical_barrier_heals_the_defender_one_before_the_blow(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    yen, leo = pair(g, "yennefer", "leonardo")
    yen.hp = 10
    attack = give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack and c.value == 5)) \
        if any(c.can_attack and c.value == 5 for c in g.players[1].deck) else give(g, 1, next(c.title for c in g.players[1].deck if c.can_attack))
    res = g.attack(leo, yen, attack, give(g, 0, "Magical barrier"))
    assert yen.hp == 10 + 1 - max(0, attack.value - 4)


def test_advisor_to_the_king_heals_every_fighter_draws_one_and_adds_one_to_boosts(bprd):
    g = mk(bprd)
    yen, foe = pair(g, "yennefer", "hellboy")
    yen.hp, g.fighters["triss"].hp = 10, 3
    advisor = give(g, 0, "Advisor to the king")
    g.play_scheme(0, yen, advisor)
    assert (yen.hp, g.fighters["triss"].hp) == (11, 4) and len(g.players[0].hand) == 1
    assert g.fx.ongoing_card_id(0) == advisor.card_id and g.fx.boost_bonus(0) == 1 and g.fx.boost_bonus(1) == 0
    card = give(g, 0, "Echoing blast")
    flow = CombatFlow(g, yen, foe, card, None)
    assert flow.run().choice.kind == "boost"
    boost = give(g, 0, "Telepathy")
    flow.resume(boost)
    assert flow.run() is None and flow.result.atk_value == 3 + 1 + 1       # the printed boost 1, plus the ONGOING's 1


def test_advisor_leaves_play_at_the_end_of_the_turn_unless_you_attacked(bprd):
    g = mk(bprd)
    yen, foe = pair(g, "yennefer", "hellboy")
    advisor = give(g, 0, "Advisor to the king")
    g.play_scheme(0, yen, advisor)
    g.end_turn()
    assert g.fx.ongoing_card_id(0) is None and advisor in g.players[0].discard
    g2 = mk(bprd)
    yen2, foe2 = pair(g2, "yennefer", "hellboy")
    advisor2 = give(g2, 0, "Advisor to the king")
    g2.play_scheme(0, yen2, advisor2)
    g2.attack(yen2, foe2, give(g2, 0, "Echoing blast"), None, boost=None)
    g2.end_turn()
    assert g2.fx.ongoing_card_id(0) == advisor2.card_id


def test_the_rivals_end_of_turn_does_not_discard_it(bprd):
    g = mk(bprd)
    yen, foe = pair(g, "yennefer", "hellboy")
    advisor = give(g, 0, "Advisor to the king")
    g.play_scheme(0, yen, advisor)
    g.fx.emit("end_of_turn", 1)
    assert g.fx.ongoing_card_id(0) == advisor.card_id


def test_advisor_boost_bonus_also_counts_in_a_maneuver(bprd):
    g = mk(bprd)
    yen, foe = pair(g, "yennefer", "hellboy")
    g.play_scheme(0, yen, give(g, 0, "Advisor to the king"))
    boost = give(g, 0, "Telepathy")
    far = next(s for s in sorted(g.board.spaces) if g.board.distance(yen.pos, s) == 4 and all(f.pos != s for f in g.fighters.values() if f.alive))
    g.maneuver(0, {"yennefer": far}, boost)
    assert yen.pos == far                                           # move 2 + boost 1 + the ONGOING's 1 = 4 spaces: 3 would not reach


# ---------------------------------------------------------------- Lodge of sorceresses

def with_boost(g, player, boost):
    """A card of `player`'s deck whose BOOST value is `boost`, moved to their hand."""
    card = next(c for c in g.players[player].deck if c.boost == boost)
    g.players[player].deck.remove(card)
    g.players[player].hand.append(card)
    return card


def lodge(bprd, mine, theirs, hero="yennefer-triss", foe="leonardo"):
    """`mine` / `theirs`: the BOOST value of the card each player holds (and will reveal)."""
    g = mk(bprd, hero, foe=foe)
    cards0 = [with_boost(g, 0, n) for n in mine]
    cards1 = [with_boost(g, 1, n) for n in theirs]
    g.controllers[0].queue = [[cards0[0].card_id]] if cards0 else []
    g.controllers[1].queue = [[cards1[0].card_id]] if cards1 else []
    return g, g.hero(0), cards0, cards1


def test_lodge_both_draw_their_cards_boost_and_the_one_who_drew_more_takes_that_damage(bprd):
    g, yen, (a,), (b,) = lodge(bprd, [2], [1])
    g.play_scheme(0, yen, give(g, 0, "Lodge of sorceresses"))
    assert len(g.players[0].hand) == 1 + 2 and len(g.players[1].hand) == 1 + 1
    assert yen.hp == 14 - 2 and g.hero(1).hp == g.hero(1).max_hp
    assert a in g.players[0].hand and b in g.players[1].hand               # revealed, not discarded


def test_lodge_a_tie_hurts_both_heroes(bprd):
    g, yen, (a,), (b,) = lodge(bprd, [2], [2])
    g.play_scheme(0, yen, give(g, 0, "Lodge of sorceresses"))
    assert yen.hp == 12 and g.hero(1).hp == g.hero(1).max_hp - 2


def test_lodge_the_rival_who_drew_more_is_the_one_hurt(bprd):
    g, yen, (a,), (b,) = lodge(bprd, [1], [3])
    g.play_scheme(0, yen, give(g, 0, "Lodge of sorceresses"))
    assert yen.hp == 14 and g.hero(1).hp == g.hero(1).max_hp - 3 and len(g.players[1].hand) == 1 + 3


def test_lodge_with_an_empty_hand_draws_nothing_and_nobody_is_hurt(bprd):
    g = mk(bprd)
    yen = g.hero(0)
    g.play_scheme(0, yen, give(g, 0, "Lodge of sorceresses"))
    assert yen.hp == 14 and g.hero(1).hp == g.hero(1).max_hp and len(g.players[0].hand) == 0


def test_lodge_hurts_the_hero_not_the_sidekick(bprd):
    g, yen, (a,), (b,) = lodge(bprd, [2], [1], hero="triss-yennefer")
    pair(g, "triss", "leonardo")
    g.play_scheme(0, g.hero(0), give(g, 0, "Lodge of sorceresses"))
    assert g.fighters["triss"].hp == 12 and g.fighters["yennefer"].hp == 6


def test_the_bot_reveals_the_card_it_can_afford(bprd):
    from sparring.ai_effects import EffectAI
    g = mk(bprd)
    cards = [give(g, 0, t) for t in ("Incinerate", "Telepathy", "Quick and ready")]
    req = type("Req", (), {"player": 0, "options": [c.card_id for c in cards]})()
    assert EffectAI()._lodge_card(g, req) == [cards[0].card_id]               # 14 HP: the BOOST 2 card draws the most
    g.hero(0).hp = 3
    assert EffectAI()._lodge_card(g, req) == [cards[1].card_id]               # hurt: the smallest BOOST (1) takes the least


# ---------------------------------------------------------------- the scripted rival of the simulator

def test_the_scripted_rival_never_plays_an_adjacent_only_card_against_a_target_that_is_not_adjacent(bprd):
    """Found by the simulator (Yennefer vs a scripted Tomoe Gozen): Witness My Last Battle, her adjacent-only attack, was chosen
    against a target two spaces away and the game died with a RuleError."""
    from sparring.hellboy_script import ScriptedHellboy
    g = Game.new(bprd, 3, controllers={0: Answers(), 1: Answers()}, heroes=("yennefer-triss", "tomoe-gozen"), bot_player=0)
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    tomoe, yen = g.fighters["tomoe"], g.fighters["yennefer"]
    a = min(g.board.spaces)
    tomoe.pos = a
    yen.pos = next(s for s in sorted(g.board.spaces) if g.board.share_zone(a, s) and s != a and s not in g.board.adj[a])
    far = sorted((s for s in g.board.spaces if not g.board.share_zone(a, s)), reverse=True)
    for f, s in zip([f for f in g.fighters.values() if f.fid not in ("tomoe", "yennefer")], far):
        f.pos = s
    witness = give(g, 1, "Witness My Last Battle")
    assert g.can_attack(tomoe, yen) and not g.attack_card_reaches(tomoe, yen, witness)
    script = ScriptedHellboy(1, 0)
    assert script.try_attack(g) is False and witness in g.players[1].hand          # nothing else to play: no attack, no crash
    yen.pos = next(s for s in sorted(g.board.adj[a]) if all(f.pos != s for f in g.fighters.values() if f.alive))
    assert script.try_attack(g) is True and witness not in g.players[1].hand
