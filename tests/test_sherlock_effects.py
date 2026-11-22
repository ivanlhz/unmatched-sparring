"""Sherlock Holmes on the engine, bot side (player 0 plays him, the controllers answer): the ability (HOLMES and DR. WATSON cards cannot be canceled,
ANY cards can, "ignore the value" is not a cancel), Elementary (the prediction, also against an uncancelable card), Deduce Strategy, Confirm Suspicion
(a value named, the rival discards a card of it or shows their hand), Master of Disguise, Administer Aid and the AFTER COMBAT cards. The human side (panel,
FakeTTS) is in tests/test_sherlock_human.py, the full games in tests/test_sherlock_matrix.py.

The rival is Medusa: her Feint (IMMEDIATELY cancel) is the card that must not touch Holmes' cards, Snipe (3, draw 1) is an attack with an effect and
Second Shot (3) one without. Liz Sherman's Incinerate is the uncancelable attack Elementary must still stop."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.effects.choose import ControllerChooser
from sparring.effects.modifiers import is_uncancelable
from sparring.effects.run import Ctx, EffectRun
from sparring.state import Game
from test_bigfoot_effects import Answers
from test_effects_combat import pair, put_adjacent

HERO = "sherlock-holmes"
FOE = "medusa"


def mk(bprd, foe=FOE, seed=3, turn=0):
    """Holmes = player 0 (the bot), `foe` = player 1; the turn is `turn`'s, empty hands."""
    ctl = {0: Answers(), 1: Answers()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=(HERO, foe), bot_player=0)
    g.fx.dsl_heroes |= {HERO}
    g.turn, g.turn_no = turn, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    for c in ctl.values():
        c.requests.clear()
    return g


def hand_of(g, player, title, nth=0):
    return give(g, player, title, nth)


def asked(g, player, kind):
    return [r for r in g.controllers[player].requests if r.kind == kind]


def run_scheme(g, fighter, title):
    card = hand_of(g, 0, title)
    g.play_scheme(0, fighter, card)
    return card


# ---------------------------------------------------------------- the hero and the deck

def test_holmes_is_a_melee_hero_with_a_ranged_doctor_watson(bprd):
    g = mk(bprd)
    h, w = g.fighters["holmes"], g.fighters["watson"]
    assert (h.hp, h.move, h.ranged, h.name) == (16, 2, False, "Sherlock Holmes")
    assert (w.hp, w.move, w.ranged, w.name, w.alive) == (8, 2, True, "Dr. Watson", True)
    assert HERO in g.fx.dsl_heroes and g.winner is None


def test_the_deck_has_the_printed_bands_and_numbers(bprd):
    g = mk(bprd)
    seen = {}
    for c in g.players[0].full_set:
        s = seen.setdefault(c.title, (c.type, c.value, c.boost, c.fighter, 0))
        seen[c.title] = s[:4] + (s[4] + 1,)
    assert len(g.players[0].full_set) == 30
    H, W = "Sherlock Holmes", "Dr. Watson"
    assert seen == {
        "The Game is Afoot": ("attack", 5, 2, H, 2), "Service Revolver": ("attack", 5, 3, W, 2),
        "Deduce Strategy": ("versatile", 3, 1, H, 3), "Counterpunch": ("versatile", 3, 1, H, 3),
        "Study Methods": ("versatile", 3, 2, "any", 2), "Education Never Ends": ("versatile", 3, 1, "any", 2),
        "Feint": ("versatile", 2, 1, "any", 3), "Fixed Point in a Changing Age": ("versatile", 3, 1, W, 2),
        "Elementary": ("defense", 3, 3, H, 2), "Master of Disguise": ("scheme", None, 2, H, 2),
        "Confirm Suspicion": ("scheme", None, 1, H, 3), "Eliminate the Impossible": ("scheme", None, 2, H, 2),
        "Administer Aid": ("scheme", None, 2, W, 2)}


def test_watson_cannot_play_a_holmes_card_and_holmes_not_a_watson_card(bprd):
    g = mk(bprd)
    revolver = next(c for c in g.players[0].full_set if c.title == "Service Revolver")
    afoot = next(c for c in g.players[0].full_set if c.title == "The Game is Afoot")
    feint = next(c for c in g.players[0].full_set if c.title == "Feint")
    assert revolver.usable_by("Dr. Watson") and not revolver.usable_by("Sherlock Holmes")
    assert afoot.usable_by("Sherlock Holmes") and not afoot.usable_by("Dr. Watson")
    assert feint.usable_by("Dr. Watson") and feint.usable_by("Sherlock Holmes")


# ---------------------------------------------------------------- the ability: HOLMES and WATSON cards cannot be canceled

HOLMES_WATSON = ["Counterpunch", "Elementary", "Deduce Strategy", "The Game is Afoot", "Service Revolver",
                 "Fixed Point in a Changing Age", "Eliminate the Impossible", "Confirm Suspicion", "Master of Disguise", "Administer Aid"]


@pytest.mark.parametrize("title", HOLMES_WATSON)
def test_every_holmes_and_watson_card_is_uncancelable_and_no_any_card_is(bprd, title):
    g = mk(bprd)
    card = next(c for c in g.players[0].full_set if c.title == title)
    assert is_uncancelable(card)
    assert not any(is_uncancelable(c) for c in g.players[0].full_set if c.fighter == "any")


def test_an_opponents_feint_does_not_cancel_counterpunch(bprd):
    g = mk(bprd)
    h, foe = pair(g, "holmes", "medusa")
    g.attack(h, foe, hand_of(g, 0, "Counterpunch"), hand_of(g, 1, "Feint"))
    assert foe.hp == foe.max_hp - 3                         # attack 3 against defense 2 is 1, plus the 2 of the AFTER effect (adjacent)


def test_an_opponents_feint_does_cancel_an_any_card(bprd):
    g = mk(bprd, turn=0)
    h, foe = pair(g, "holmes", "medusa")
    hand_of(g, 0, "Feint")
    g.attack(h, foe, hand_of(g, 0, "Education Never Ends"), hand_of(g, 1, "Feint"))
    assert len(g.players[1].hand) == 0 and len(g.players[0].hand) == 1      # its AFTER effect was canceled: nobody drew


def test_holmes_feint_cancels_the_rivals_card(bprd):
    g = mk(bprd, turn=1)
    foe, h = pair(g, "medusa", "holmes")
    g.attack(foe, h, hand_of(g, 1, "Snipe"), hand_of(g, 0, "Feint"))
    assert len(g.players[1].hand) == 0                       # Snipe's "draw 1 card" was canceled


def test_an_effect_that_ignores_the_value_is_not_a_cancel_of_the_effects(bprd):
    """Pandora's Celestial Raiments ignore the value of Holmes' Counterpunch (no combat damage) but its AFTER effect still resolves: ignoring a value cancels nothing."""
    g = mk(bprd, foe="pandora")
    h, foe = pair(g, "holmes", "pandora")
    hp = foe.hp
    flow = g.begin_attack(h, foe, hand_of(g, 0, "Counterpunch"), hand_of(g, 1, "Celestial Raiments"))
    flow.drive(lambda choice: None)
    assert flow.result.damage == 0 and foe.hp == hp - 2 and "atk" not in flow.ctx.cancelled


# ---------------------------------------------------------------- Elementary

def test_elementary_a_right_guess_cancels_the_effects_and_ignores_the_value(bprd):
    g = mk(bprd, turn=1)
    foe, h = pair(g, "medusa", "holmes")
    g.controllers[0].queue = [[3]]
    g.attack(foe, h, hand_of(g, 1, "Snipe"), hand_of(g, 0, "Elementary"))
    assert h.hp == 16 and len(g.players[1].hand) == 0       # no damage (value ignored) and Snipe's draw canceled


def test_elementary_a_wrong_guess_does_nothing(bprd):
    g = mk(bprd, turn=1)
    foe, h = pair(g, "medusa", "holmes")
    g.controllers[0].queue = [[4]]
    g.attack(foe, h, hand_of(g, 1, "Snipe"), hand_of(g, 0, "Elementary"))
    assert h.hp == 16 and len(g.players[1].hand) == 1        # 3 against 3 is a tie: no damage, and Snipe's draw happens


def test_elementary_a_wrong_guess_against_a_bigger_attack_takes_the_damage(bprd):
    g = mk(bprd, foe="hellboy", turn=1)
    foe, h = pair(g, "hellboy", "holmes")
    g.controllers[0].queue = [[5]]
    g.attack(foe, h, hand_of(g, 1, "Excalibur"), hand_of(g, 0, "Elementary"))
    assert h.hp == 16 - 3                                    # Excalibur 6 against Elementary 3


def test_elementary_a_right_guess_stops_an_attack_that_would_have_hurt(bprd):
    g = mk(bprd, foe="hellboy", turn=1)
    foe, h = pair(g, "hellboy", "holmes")
    g.controllers[0].queue = [[6]]
    g.attack(foe, h, hand_of(g, 1, "Excalibur"), hand_of(g, 0, "Elementary"))
    assert h.hp == 16


def test_elementary_predicts_the_printed_value_of_a_versatile_card(bprd):
    g = mk(bprd, turn=1)
    foe, h = pair(g, "medusa", "holmes")
    g.controllers[0].queue = [[1]]
    g.attack(foe, h, hand_of(g, 1, "Regroup"), hand_of(g, 0, "Elementary"))      # Regroup is a versatile 1
    assert len(g.players[1].hand) == 0                       # its draw was canceled: the guess was right


def test_elementary_cancels_an_uncancelable_card_too(bprd):
    g = mk(bprd, foe="liz-sherman", turn=1)
    foe, h = pair(g, "liz", "holmes")
    incinerate = next(c for c in g.players[1].full_set if c.title == "Incinerate")
    assert is_uncancelable(incinerate)
    g.players[1].deck.remove(incinerate)
    g.players[1].hand.append(incinerate)
    hand_of(g, 0, "Feint")
    hand_of(g, 0, "Counterpunch")                            # two cards in hand: the offer "discard 2 to ignore this card's value" is possible
    g.controllers[0].queue = [[incinerate.value]]
    g.attack(foe, h, incinerate, hand_of(g, 0, "Elementary"))
    assert h.hp == 16 and asked(g, 0, "optional") == []      # Incinerate's DURING effect (the offer made to Holmes) never ran: its effects were canceled


def test_elementary_cancels_the_free_boost_of_the_card_with_its_effects(bprd):
    """"Cancel all effects" takes Second Shot's "you may BOOST this attack" away too: the attacker is not offered the BOOST that would have beaten Elementary's 3
    (its value is ignored, 0, and a 4 from Gaze of Stone would have made 4)."""
    g = mk(bprd, turn=1)
    foe, h = pair(g, "medusa", "holmes")
    g.controllers[0].queue = [[3]]
    boost = hand_of(g, 1, "Gaze of Stone")
    offered = []
    flow = g.begin_attack(foe, h, hand_of(g, 1, "Second Shot"), hand_of(g, 0, "Elementary"))
    flow.drive(lambda choice: offered.append(choice) or (boost if choice.kind == "boost" else None))
    assert offered == [] and flow.result.damage == 0 and h.hp == 16


# ---------------------------------------------------------------- Deduce Strategy

def deduce(g, foe_card_title, take):
    """Holmes attacks with Deduce Strategy (3) against `foe_card_title` and answers `take` to the free change; returns (flow, Holmes, Medusa)."""
    h, foe = pair(g, "holmes", "medusa")
    g.controllers[0].queue = [[take]]
    flow = g.begin_attack(h, foe, hand_of(g, 0, "Deduce Strategy"), hand_of(g, 1, foe_card_title))
    flow.drive(lambda choice: None)
    return flow, h, foe


def test_deduce_strategy_changes_the_printed_value_of_the_rivals_card_to_its_boost(bprd):
    g = mk(bprd)
    flow, h, foe = deduce(g, "Snipe", True)                    # Snipe: printed 3, BOOST 1 -> the defense is 1, Holmes' 3 does 2
    assert flow.result.damage == 2 and foe.hp == foe.max_hp - 2


def test_deduce_strategy_is_optional_and_declining_leaves_the_printed_value(bprd):
    g = mk(bprd)
    flow, h, foe = deduce(g, "Snipe", False)                   # 3 against 3: a tie, the defender keeps it
    assert flow.result.damage == 0 and foe.hp == foe.max_hp
    assert [r.kind for r in g.controllers[0].requests] == ["optional"]


def test_deduce_strategy_defending_changes_the_attackers_value_first_as_the_defender(bprd):
    g = mk(bprd, turn=1)
    foe, h = pair(g, "medusa", "holmes")
    g.controllers[0].queue = [[True]]
    flow = g.begin_attack(foe, h, hand_of(g, 1, "Dash"), hand_of(g, 0, "Deduce Strategy"))     # Dash: 3 with BOOST 1
    flow.drive(lambda choice: None)
    assert flow.result.damage == 0 and h.hp == 16             # the attack became 1 against Holmes' 3


def test_deduce_strategy_with_no_card_against_it_asks_nothing(bprd):
    g = mk(bprd)
    h, foe = pair(g, "holmes", "medusa")
    flow = g.begin_attack(h, foe, hand_of(g, 0, "Deduce Strategy"), None)
    flow.drive(lambda choice: None)
    assert g.controllers[0].requests == [] and flow.result.damage == 3
