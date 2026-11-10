"""The defense values the effects of the committed attack card (forced discards, damage) through the rival's possible cards,
and a cancel-effects defense (Feint, read from the data) gets credit only for what it prevents."""
from __future__ import annotations

import pytest

from conftest import give
from sparring.ai_hazards import attack_harm
from sparring.ai_medusa import MedusaAI, Model
from sparring.state import Game
from test_effects_combat import hand_filler


def scenario(bprd, hero="bigfoot", rival_hand=3):
    """The bot (`hero`, player 0) has Feint and one plain defense; a Harpy of Medusa (player 1) attacks its hero."""
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=(hero, "medusa"), bot_player=0)
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    feint = give(g, 0, "Feint")
    weak = give(g, 0, "Skirmish")
    harpy = next(f for f in g.foes(0) if not f.hero)
    me = g.hero(0)
    harpy.pos = next(s for s in g.board.adj[me.pos] if all(f.pos != s for f in g.fighters.values() if f.alive))
    hand_filler(g, 1, rival_hand)
    return g, feint, weak, harpy, me


def restrict_attacks_to(g, titles):
    """The rival's remaining attack cards are only the copies of `titles` (the others are public in its discard pile)."""
    st = g.players[1]
    for c in list(st.full_set):
        if c.can_attack and c.title not in titles and c not in st.discard:
            st.discard.append(c)
            for zone in (st.deck, st.hand):
                if c in zone:
                    zone.remove(c)


def equal_defenses(g, feint, weak):
    """`weak` defends exactly like Feint (same value and boost) and sits first in the hand: only the effects can tell them apart."""
    object.__setattr__(weak, "value", feint.value)
    object.__setattr__(weak, "boost", feint.boost)
    hand = g.players[0].hand
    hand.sort(key=lambda c: c is feint)


def test_feint_is_chosen_against_a_harpy_that_can_force_a_discard(bprd):
    g, feint, weak, harpy, me = scenario(bprd)
    equal_defenses(g, feint, weak)
    restrict_attacks_to(g, ("Clutching Claws",))
    assert MedusaAI(0).choose_defense(g, harpy, me) is feint


def test_feint_is_not_preferred_for_its_effect_when_no_harmful_card_is_left(bprd):
    g, feint, weak, harpy, me = scenario(bprd)
    equal_defenses(g, feint, weak)
    restrict_attacks_to(g, ("Winged Frenzy", "A Momentary Glance"))
    assert MedusaAI(0).choose_defense(g, harpy, me) is not feint


def test_feint_effect_value_scales_with_the_harmful_cards_left(bprd):
    g, feint, weak, harpy, me = scenario(bprd)
    ai = MedusaAI(0)
    model = Model(g, 0)
    harm_now = model.committed_harm_by_value(harpy, me)
    assert any(h[0] > 0 for h in harm_now.values())
    # every card of the rival that forces a discard or deals damage is already in its discard pile: nothing left for Feint to cancel
    st = g.players[1]
    for c in list(st.full_set):
        if c.title in ("Clutching Claws", "Hiss and Slither") and c not in st.discard:
            st.discard.append(c)
            for zone in (st.deck, st.hand):
                if c in zone:
                    zone.remove(c)
    dist = Model(g, 0).committed_attack_dist(harpy, me)
    ai._attack_harm = Model(g, 0).committed_harm_by_value(harpy, me)
    assert all(h[0] == 0 for h in ai._attack_harm.values())
    gain_empty = ai.attack_effect_harm(g, dist, me, None) - ai.attack_effect_harm(g, dist, me, feint)
    ai._attack_harm = harm_now
    dist_now = model.committed_attack_dist(harpy, me)
    gain_now = ai.attack_effect_harm(g, dist_now, me, None) - ai.attack_effect_harm(g, dist_now, me, feint)
    assert gain_empty == pytest.approx(0.0)
    assert gain_now > 0.03


def test_a_defense_that_does_not_cancel_gets_no_credit_for_the_effects(bprd):
    g, feint, weak, harpy, me = scenario(bprd)
    ai = MedusaAI(0)
    model = Model(g, 0)
    ai._attack_harm = model.committed_harm_by_value(harpy, me)
    dist = model.committed_attack_dist(harpy, me)
    assert ai.attack_effect_harm(g, dist, me, weak) > 0
    assert ai.attack_effect_harm(g, dist, me, feint) == 0


def effect_slugs():
    from sparring.effects.model import EFFECTS_DIR
    return sorted(p.stem for p in EFFECTS_DIR.glob("*.json") if p.stem != "schema")


@pytest.mark.parametrize("slug", effect_slugs())
def test_attack_harm_reads_every_deck_without_error(bprd, slug):
    from sparring.ai_hazards import attack_harm
    try:
        g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=(slug, "hellboy" if slug == "medusa" else "medusa"), bot_player=0)
    except Exception:
        pytest.skip(f"{slug} cannot be set up on this board")
    for card in g.players[0].full_set:
        discards, damage, direct = attack_harm(card)
        assert 0 <= discards <= 4 and 0 <= damage <= 10 and 0 <= direct <= 5, card.title


def test_attack_harm_known_values(bprd):
    from sparring.ai_hazards import attack_harm
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=("medusa", "hellboy"), bot_player=0)
    claws = next(c for c in g.players[0].full_set if c.title == "Clutching Claws")
    assert attack_harm(claws) == (1.0, 0.0, 0.0)
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=("abe-sapien", "medusa"), bot_player=0)
    device = next(c for c in g.players[0].full_set if c.title == "Concussion Device")
    assert attack_harm(device)[1] == 2.0


def test_baba_yagas_memory_reference_is_priced_without_error(bprd):
    """Remove A Painful Memory discards "$memory" (a card an earlier op chose), not a filter: it cannot be resolved statically, so
    it counts as a half discard, and the rival's choice between that and the 2 damage takes the cheaper branch."""
    from sparring.ai_hazards import attack_harm
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=("baba-yaga", "medusa"), bot_player=0)
    memory = next(c for c in g.players[0].full_set if c.title == "Remove A Painful Memory")
    assert attack_harm(memory) == (0.25, 0.0, 0.0)           # an `if` halves the half discard; the 2 damage is the dearer branch


# ---------- whose effects run: the Mists replace the card, the Cloak only zeroes its value ----------
def strange_scenario(bprd):
    """Doctor Strange (the bot) is attacked by a Harpy next to him with a face-up card; he holds the Mists, the Cloak and a
    spare card (so a forced discard still finds a card after the defense is paid)."""
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=("doctor-strange", "medusa"), bot_player=0)
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    mists, cloak = give(g, 0, "The Mists of Munnopor"), give(g, 0, "Cloak of Levitation")
    give(g, 0, "Feint")
    harpy = next(f for f in g.foes(0) if not f.hero)
    me = g.hero(0)
    harpy.pos = next(s for s in g.board.adj[me.pos] if all(f.pos != s for f in g.fighters.values() if f.alive))
    hand_filler(g, 1, 3)
    return g, mists, cloak, harpy, me


def defense_value(g, ai, harpy, me, attack_card, defense):
    """eval_defense of `defense` against the face-up `attack_card`, set up as choose_defense does."""
    from sparring.ai_hazards import attack_harm
    model = Model(g, 0)
    dist = [(1.0, attack_card.value + g.attack_bonus(harpy, me))]
    ai._attacker, ai._defender = harpy, me
    ai._attack_harm = {dist[0][1]: attack_harm(attack_card)}
    try:
        return ai.eval_defense(g, model, dist, me, defense)
    finally:
        ai._attacker = ai._defender = None
        ai._attack_harm = {}


def rival_card(g, title):
    return next(c for c in g.players[1].full_set if c.title == title)


def test_the_mists_pay_for_the_effects_of_the_revealed_card_not_of_the_committed_one(bprd, monkeypatch):
    """The committed card is discarded without effects and the replacement's run (doctor-strange.json, the Mists' note)."""
    from sparring.ai_medusa import CARD_VALUE
    g, mists, cloak, harpy, me = strange_scenario(bprd)
    ai = MedusaAI(0)
    claws, snipe = rival_card(g, "Clutching Claws"), rival_card(g, "Snipe")
    # a harmful card committed, only harmless ones left to reveal: nothing of the Claws' discard is charged
    restrict_attacks_to(g, ("Snipe",))
    harmful_committed = defense_value(g, ai, harpy, me, claws, mists)
    assert harmful_committed == pytest.approx(defense_value(g, ai, harpy, me, snipe, mists))
    # a harmless card committed, only Claws left to reveal: the forced discard of the revealed card is charged
    g, mists, cloak, harpy, me = strange_scenario(bprd)
    restrict_attacks_to(g, ("Clutching Claws",))
    snipe = rival_card(g, "Snipe")
    charged = defense_value(g, ai, harpy, me, snipe, mists)
    monkeypatch.setattr(ai, "mists_harm", lambda *a: {})
    assert charged == pytest.approx(defense_value(g, ai, harpy, me, snipe, mists) - CARD_VALUE)


def test_the_cloak_zeroes_the_value_but_the_committed_cards_effects_still_run(bprd):
    from sparring.ai_medusa import CARD_VALUE
    g, mists, cloak, harpy, me = strange_scenario(bprd)
    ai = MedusaAI(0)
    claws, snipe = rival_card(g, "Clutching Claws"), rival_card(g, "Snipe")
    assert claws.value == snipe.value               # same blow: only the effects differ
    assert g.board.adjacent(harpy.pos, me.pos)
    against_claws, against_snipe = (defense_value(g, ai, harpy, me, card, cloak) for card in (claws, snipe))
    assert against_claws == pytest.approx(against_snipe - CARD_VALUE)


def test_a_forced_discard_takes_no_more_than_the_hand_left_after_paying_for_the_defense(bprd):
    from sparring.ai_medusa import CARD_VALUE
    g, feint, weak, harpy, me = scenario(bprd)                # two cards in hand: Feint and a plain defense
    ai = MedusaAI(0)
    ai._attack_harm = {3: (3.0, 0.0, 0.0)}                    # an attack that forces three discards
    dist = [(1.0, 3)]
    assert ai.attack_effect_harm(g, dist, me, None) == pytest.approx(2 * CARD_VALUE)     # only two cards to lose
    assert ai.attack_effect_harm(g, dist, me, weak) == pytest.approx(1 * CARD_VALUE)     # one went to pay for the defense
    g.players[0].hand.remove(feint)
    assert ai.attack_effect_harm(g, dist, me, weak) == pytest.approx(0.0)                # the defense was the last card


# ---------- attack_harm: choices, damage to "any" side, statuses on a fighter ----------
def deck_card(bprd, hero, title):
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=(hero, "hellboy" if hero == "medusa" else "medusa"), bot_player=0)
    return next(c for c in g.players[0].full_set if c.title == title)


def test_the_branch_prices_are_the_heuristics_own(bprd):
    from sparring import ai_hazards, ai_medusa
    assert (ai_hazards.DISCARD_COST, ai_hazards.DAMAGE_COST) == (ai_medusa.CARD_VALUE, ai_medusa.W_MEDUSA_HP)


def test_a_choice_of_the_defender_takes_its_cheapest_option(bprd):
    """Merigold's Hailstorm: discard 2 (0.8), 3 damage to the hero (3.6) or mill 4 (a plugin: UNREAD_OPTION_HARM). Legalese:
    won, the defender picks both draw (free); lost, the attacker picks (the average option: half a discard); each under an `if`."""
    from sparring.ai_hazards import UNREAD_OPTION_HARM, attack_harm
    assert attack_harm(deck_card(bprd, "triss-yennefer", "Merigold's Hailstorm")) == (0.0, 0.0, UNREAD_OPTION_HARM)
    assert attack_harm(deck_card(bprd, "she-hulk", "Legalese")) == (0.25, 0.0, 0.0)


def test_the_defenders_branch_is_compared_by_what_each_harm_costs_not_by_raw_units():
    """Three discards (3 x 0.4) are cheaper than two points of damage (2 x 1.2), though 3 > 2."""
    from sparring.ai_hazards import ops_harm
    discard = {"op": "discard", "cards": {"zone": "hand", "player": "opponent", "amount": 3}}
    damage = {"op": "damage", "target": "opposing", "amount": 2}
    assert ops_harm([[{"op": "optional", "chooser": "opponent", "ops": [discard], "else": [damage]}]]) == (3.0, 0.0, 0.0)
    options = [{"ops": [damage]}, {"ops": [discard]}]
    assert ops_harm([[{"op": "choose_effect", "chooser": "opponent", "amount": 1, "options": options}]]) == (3.0, 0.0, 0.0)


@pytest.mark.parametrize("hero, title, damage", [
    ("baba-yaga", "Iron Teeth", 0.5),          # 1 to an adjacent fighter of any side
    ("bigfoot", "Savagery", 0.25),             # 1 to each fighter next to Bigfoot, if he won
    ("bullseye", "Ricochet", 0.25),            # 1 to a fighter in the defender's zone, if it survived
])
def test_damage_to_a_fighter_of_any_side_counts_half(bprd, hero, title, damage):
    from sparring.ai_hazards import attack_harm
    assert attack_harm(deck_card(bprd, hero, title)) == (0.0, damage, 0.0)


def test_a_status_on_the_opposing_fighter_is_harm(bprd):
    from sparring.ai_hazards import STATUS_HARM, attack_harm
    assert attack_harm(deck_card(bprd, "liz-sherman", "Burning Barrier")) == (0.0, 1.0, STATUS_HARM)
    assert attack_harm(deck_card(bprd, "she-hulk", "Nerve Cluster Strike")) == (0.0, 0.0, STATUS_HARM / 2)


# ---------- what a cancel cannot cancel, and no flat bonus for the title ----------
def ciri_attacks(bprd, source):
    """The bot Bigfoot holds Feint and a plain defense just like it; Ciri, with `source` Source cards in her discard pile, attacks
    him. At SOURCE 7 the effects of her cards cannot be canceled (UNCONTAINABLE POWER)."""
    from test_ciri_effects import set_source
    g = Game.new(bprd, 3, controllers={0: MedusaAI(0), 1: MedusaAI(1)}, heroes=("bigfoot", "ciri"), bot_player=0)
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    feint, weak = give(g, 0, "Feint"), give(g, 0, "Skirmish")
    equal_defenses(g, feint, weak)
    me, ciri = g.hero(0), g.hero(1)
    ciri.pos = next(s for s in g.board.adj[me.pos] if all(f.pos != s for f in g.fighters.values() if f.alive))
    set_source(g, source, player=1)
    hand_filler(g, 1, 3)
    return g, feint, weak, ciri, me


def harm_left(g, ciri, me, card):
    ai, model = MedusaAI(0), Model(g, 0)
    ai._attack_harm = model.committed_harm_by_value(ciri, me)
    ai._attack_harm_fixed = model.committed_harm_by_value(ciri, me, uncancelable=True)
    return ai.attack_effect_harm(g, model.committed_attack_dist(ciri, me), me, card)


def test_feint_gets_no_credit_against_cards_that_cannot_be_canceled(bprd):
    g, feint, weak, ciri, me = ciri_attacks(bprd, source=6)
    assert harm_left(g, ciri, me, weak) > 0.03 and harm_left(g, ciri, me, feint) == 0
    assert MedusaAI(0).choose_defense(g, ciri, me) is feint
    g, feint, weak, ciri, me = ciri_attacks(bprd, source=7)
    assert harm_left(g, ciri, me, feint) == pytest.approx(harm_left(g, ciri, me, weak)) and harm_left(g, ciri, me, feint) > 0.03
    assert MedusaAI(0).choose_defense(g, ciri, me) is weak


def test_a_known_attack_card_that_cannot_be_canceled_leaves_feint_without_credit(bprd):
    """The attack card is face up (Perfect Shot, UNCANNY INTUITION): its own effects are the ones priced."""
    g, feint, weak, ciri, me = ciri_attacks(bprd, source=7)
    harmful = max((c for c in g.players[1].full_set if c.can_attack and c.usable_by(ciri.name)), key=lambda c: sum(attack_harm(c)))
    assert sum(attack_harm(harmful)) > 0
    assert MedusaAI(0).choose_defense(g, ciri, me, attack_card=harmful) is weak
    g, feint, weak, ciri, me = ciri_attacks(bprd, source=0)
    harmful = next(c for c in g.players[1].full_set if c.title == harmful.title)
    assert MedusaAI(0).choose_defense(g, ciri, me, attack_card=harmful) is feint


def test_feint_is_worth_exactly_a_plain_defense_when_the_attack_has_no_effect_to_cancel(bprd):
    """No flat bonus for the title: with nothing harmful left in the rival's cards, Feint and a defense of the same value and
    boost are valued the same."""
    g, feint, weak, harpy, me = scenario(bprd)
    equal_defenses(g, feint, weak)
    restrict_attacks_to(g, ("Winged Frenzy", "A Momentary Glance"))
    ai, model = MedusaAI(0), Model(g, 0)
    dist = model.committed_attack_dist(harpy, me)
    ai._attack_harm = model.committed_harm_by_value(harpy, me)
    ai._attack_harm_fixed = model.committed_harm_by_value(harpy, me, uncancelable=True)
    assert ai.eval_defense(g, model, dist, me, feint) == pytest.approx(ai.eval_defense(g, model, dist, me, weak))
