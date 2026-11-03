"""Houdini's Sleight Of Hand (IMMEDIATELY: return this card to your hand and play a different one), engine and bot side: the card swapped
inside the running combat (`CombatFlow.replace_attack_card(back_to_hand=True)`), what stays and what changes, and the bot's decision
against the rival's card that is already face up. The table (FakeTTS) side is in tests/test_houdini_sleight_table.py."""
from __future__ import annotations

from conftest import give
from sparring.ai_medusa import MedusaAI
from sparring.combat_flow import CombatFlow, Phase
from sparring.state import Game
from test_effects_combat import Asking, pair

SLEIGHT = "Sleight of Hand"


class Swapper(Asking):
    """The bot's answers by hand: the card it plays instead of Sleight Of Hand (None keeps it)."""

    def __init__(self):
        super().__init__()
        self.instead = None
        self.boosts: list = []

    def choose_effect(self, game, req):
        self.requests.append(req)
        if req.extra.get("purpose") == "swap_attack":
            return [] if self.instead is None else [self.instead.card_id]
        return None

    def choose_combat_boost(self, game, ctx):
        return self.boosts.pop(0) if self.boosts else None


def mk(bprd, foe="hellboy", seed=3, ai=False):
    """Houdini = player 0, `foe` = player 1; player 0's turn, empty hands, fighters out of the way."""
    ctl = {0: MedusaAI(0) if ai else Swapper(), 1: Asking()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=("houdini", foe), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def duel(g, att="houdini", tgt="hellboy"):
    pair(g, att, tgt)
    return g.fighters[att], g.fighters[tgt]


def defense(g, title):
    """A defense of the rival's, in its hand."""
    return give(g, 1, title)


# ---------------------------------------------------------------- the swap in the engine

def test_the_card_goes_back_to_the_hand_and_the_new_one_is_played_with_its_value(bprd):
    g = mk(bprd)
    a, t = duel(g)
    sleight, instead = give(g, 0, SLEIGHT), give(g, 0, "An Illusion of My Own Design")
    g.controllers[0].instead = instead
    res = g.attack(a, t, sleight, None)
    assert res.atk_card is instead and res.atk_value == 4 and res.damage == 4
    assert sleight in g.players[0].hand and sleight not in g.players[0].discard      # back in the hand, not discarded
    assert instead in g.players[0].discard and instead not in g.players[0].hand
    assert res.atk_parts[0] == "An Illusion of My Own Design (4)"
    assert any(line.startswith(f"{SLEIGHT}: ") and "An Illusion of My Own Design" in line for line in res.applied), res.applied
    assert g.players[1].known.seen == [sleight.card_id]                               # the rival saw it, so it knows it is in that hand


def test_declining_keeps_sleight_of_hand_as_a_plain_value_1_attack(bprd):
    g = mk(bprd)
    a, t = duel(g)
    sleight = give(g, 0, SLEIGHT)
    give(g, 0, "Flourish")
    res = g.attack(a, t, sleight, None)
    assert res.atk_card is sleight and res.atk_value == 1 and sleight in g.players[0].discard
    assert [r.options for r in g.controllers[0].requests] and not g.players[1].known.seen


def test_the_new_cards_own_immediately_runs_now(bprd):
    g = mk(bprd)
    a, t = duel(g)
    sleight, misdirection = give(g, 0, SLEIGHT), give(g, 0, "Misdirection")
    g.controllers[0].instead = misdirection
    res = g.attack(a, t, sleight, defense(g, "B.P.R.D. Training"))
    assert res.atk_card is misdirection and "def" in res.cancelled and "atk" not in res.cancelled      # "cancel all effects on the opponent's card"


def test_the_bonuses_already_applied_stay_with_the_new_card(bprd):
    g = mk(bprd)
    a, t = duel(g)
    sleight, instead = give(g, 0, SLEIGHT), give(g, 0, "For My Next Trick")
    g.controllers[0].instead = instead
    flow = g.begin_attack(a, t, sleight, None, values=(2, 0))                 # +2 from an effect before the cards were revealed
    flow.drive(lambda choice: None)
    assert flow.result.atk_value == 2 + 2 and flow.result.damage == 4


def test_a_defense_is_played_against_the_new_value(bprd):
    g = mk(bprd)
    a, t = duel(g)
    sleight, instead = give(g, 0, SLEIGHT), give(g, 0, "Flourish")
    g.controllers[0].instead = instead
    res = g.attack(a, t, sleight, defense(g, "B.P.R.D. Training"))
    assert (res.atk_value, res.def_value, res.damage) == (3, 3, 0)


def test_only_attack_or_versatile_cards_the_fighter_may_play_are_offered_and_never_another_sleight(bprd):
    g = mk(bprd)
    a, t = duel(g)
    sleight, second = give(g, 0, SLEIGHT), give(g, 0, SLEIGHT, 1)
    defense_card, scheme, bess_only = give(g, 0, "Grand Escape"), give(g, 0, "A Magician Never Reveals His Secrets"), give(g, 0, "And the Beautiful Bess!")
    good = give(g, 0, "Vanishing Act")
    g.attack(a, t, sleight, None)
    options = g.controllers[0].requests[-1].options
    assert good.card_id in options
    assert not {second.card_id, defense_card.card_id, scheme.card_id, bess_only.card_id} & set(options)


def test_a_sidekick_is_not_offered_the_heros_cards(bprd):
    g = mk(bprd)
    a, t = duel(g, "bess", "hellboy")
    sleight, hero_only, any_card = give(g, 0, SLEIGHT), give(g, 0, "The Big Reveal"), give(g, 0, "Flourish")
    g.attack(a, t, sleight, None)
    options = g.controllers[0].requests[-1].options
    assert any_card.card_id in options and hero_only.card_id not in options


def test_nothing_is_asked_when_there_is_no_other_card(bprd):
    g = mk(bprd)
    a, t = duel(g)
    sleight = give(g, 0, SLEIGHT)
    g.attack(a, t, sleight, None)
    assert g.controllers[0].requests == []


def test_a_cancelled_sleight_of_hand_cannot_be_swapped(bprd):
    g = mk(bprd, foe="medusa")
    a, t = duel(g, "houdini", "medusa")
    sleight, instead = give(g, 0, SLEIGHT), give(g, 0, "Flourish")
    g.controllers[0].instead = instead
    res = g.attack(a, t, sleight, give(g, 1, "Feint"))
    assert res.atk_card is sleight and "atk" in res.cancelled and sleight in g.players[0].discard
    assert g.controllers[0].requests == []


def test_the_new_card_may_be_boosted_with_the_returned_sleight(bprd):
    g = mk(bprd)
    a, t = duel(g)
    sleight, flourish = give(g, 0, SLEIGHT), give(g, 0, "Flourish")
    g.controllers[0].instead = flourish
    g.controllers[0].boosts = [sleight]                                       # back in the hand: a 3 boost that also draws
    before = len(g.players[0].hand)
    res = g.attack(a, t, sleight, None)
    assert res.atk_card is flourish and res.atk_value == 3 + 3 and sleight in g.players[0].discard
    assert len(g.players[0].hand) == before - 2 + 1


def test_the_flow_survives_a_save_taken_right_after_the_swap(bprd):
    g = mk(bprd)
    a, t = duel(g)
    sleight, instead = give(g, 0, SLEIGHT), give(g, 0, "An Illusion of My Own Design")
    g.controllers[0].instead = instead
    flow = g.begin_attack(a, t, sleight, None)
    while flow.phase is not Phase.DURING:
        assert flow.step() is None
    again = CombatFlow.from_dict(g, flow.to_dict())
    assert again.atk_card is instead and again.again is False and again.ctx.atk_value == 4
    again.drive(lambda choice: None)
    assert again.result.atk_value == 4 and again.result.damage == 4 and instead in g.players[0].discard


# ---------------------------------------------------------------- the bot's decision

def play(bprd, hand, block=None, foe="hellboy"):
    """The combat with the real AI: Sleight Of Hand attacks, `hand` is the rest of the bot's hand, `block` the rival's defense."""
    g = mk(bprd, foe=foe, ai=True)
    a, t = duel(g, "houdini", foe)
    sleight = give(g, 0, SLEIGHT)
    for title in hand:
        give(g, 0, title)
    return g, g.attack(a, t, sleight, None if block is None else defense(g, block)), sleight


def test_the_bot_swaps_when_the_other_card_is_clearly_better(bprd):
    g, res, sleight = play(bprd, ["The Big Reveal", "Flourish"], "B.P.R.D. Training")
    assert res.atk_card.title != SLEIGHT and res.damage >= 1
    assert sleight in g.players[0].hand or sleight in g.players[0].discard         # kept in the hand, or then spent as the boost


def test_the_swap_into_the_big_reveal_depends_on_the_revealed_defense_and_the_damage(bprd):
    """Bait: the swap is not automatic. With a boost card for the Big Reveal the blow is heavy against the revealed 3 and it swaps;
    without it the Big Reveal would not beat the defense and Sleight Of Hand stays a plain attack."""
    g, res, _ = play(bprd, ["The Big Reveal", "Grand Escape"], "B.P.R.D. Training")
    assert res.atk_card.title == "The Big Reveal" and res.damage >= 4
    g, res, sleight = play(bprd, ["The Big Reveal"], "B.P.R.D. Training")
    assert res.atk_card is sleight and res.damage == 0


def test_the_bot_swaps_against_an_open_rival(bprd):
    g, res, sleight = play(bprd, ["Flourish"])
    assert res.atk_card.title == "Flourish" and res.damage > 1


def test_the_bot_keeps_sleight_when_the_other_card_changes_nothing_against_the_defense(bprd):
    g, res, sleight = play(bprd, ["Vanishing Act"], "B.P.R.D. Training")            # 1 + 0 against 3, or 2 + a boost of 3 less than the 1 it needs
    assert res.atk_card is sleight and res.damage == 0 and sleight in g.players[0].discard


def test_the_bot_swaps_for_the_effect_of_the_card_even_when_the_blow_does_not_change(bprd):
    g, res, sleight = play(bprd, ["For My Next Trick"], "B.P.R.D. Training")        # it draws a card and gives an action after the combat
    assert res.atk_card.title == "For My Next Trick" and res.damage == 0


def test_the_bot_keeps_sleight_when_a_stronger_card_would_only_equal_the_defense(bprd):
    g, res, sleight = play(bprd, ["Smoke and Mirrors"], "B.P.R.D. Training")
    assert res.atk_card is sleight and "Smoke and Mirrors" not in " ".join(res.applied)


def test_the_decision_uses_the_rivals_face_up_card_and_not_its_hand(bprd):
    # the rival holds attacks and a defense in hand: only the card on the table counts, and the request carries only totals
    g = mk(bprd, ai=True)
    a, t = duel(g)
    sleight = give(g, 0, SLEIGHT)
    give(g, 0, "Flourish")
    for title in ("Excalibur", "Service Pistol", "Right Hand Of Doom"):
        give(g, 1, title)
    spy = []
    real = g.controllers[0].choose_effect
    g.controllers[0].choose_effect = lambda game, req: (spy.append(req), real(game, req))[1]
    g.attack(a, t, sleight, defense(g, "B.P.R.D. Training"))
    req = next(r for r in spy if r.extra.get("purpose") == "swap_attack")
    assert req.extra["sleight"]["def_value"] == 3 and set(req.extra["sleight"]) == {"fighter", "target", "old", "atk_value", "def_value"}
