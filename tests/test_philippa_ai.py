"""The AI's side of Philippa (sparring/ai_philippa.py and the `EffectAI` answers to her plugin requests): Regicide is a 6 against a hero, the
lightning is worth the foes in her zone only without a Maneuver, the bot discards for Blinding dust only when the blow beats the card's
keep value, makes the rival play its weakest card for Do my bidding, discards the two best of the cards the rival reveals and reveals the
four it would miss least, picks the zone with the most foes, and does not draw at the end of the turn with a deck too short for it."""
from __future__ import annotations

from conftest import give
from sparring import ai_philippa
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import MedusaAI
from sparring.effects.choose import ChoiceRequest
from test_effects_combat import hand_filler, pair
from test_philippa_effects import mk


def req(kind, player, options, lo, hi, **extra):
    return ChoiceRequest(kind, player, list(options), lo, hi, None, "k", "", extra, 0)


def test_regicide_is_worth_six_against_a_hero_and_four_against_a_sidekick(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    regicide = give(g, 0, "Regicide")
    ai = MedusaAI(0)
    assert ai.card_value(g, ph, foe, regicide) == 6.0
    assert ai.card_value(g, ph, g.fighters["lobster"], regicide) == 4.0


def test_the_lightning_is_worth_the_foes_in_her_zone_and_nothing_after_a_maneuver(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    bolt = give(g, 0, "Lightning bolt")
    assert ai_philippa.after_value(g, 0, bolt, 0.5, 2.0, 1.0) == 2.0 * len(ai_philippa.foes_in_zone(g, 0)) > 0
    g.fx.maneuvers = 1
    assert ai_philippa.after_value(g, 0, bolt, 0.5, 2.0, 1.0) == 0.0


def test_spellbreaker_as_an_attack_costs_the_actions_it_throws_away(bprd):
    g = mk(bprd)
    assert ai_philippa.ends_turn(give(g, 0, "Spellbreaker")) and not ai_philippa.ends_turn(give(g, 0, "Cunning"))


def test_blinding_dust_discards_the_card_whose_boost_beats_its_keep_value_or_none(bprd):
    g = mk(bprd, turn=1)
    ph, foe = pair(g, "philippa", "hellboy")
    junk, best = give(g, 0, "Spymaster's ruse"), give(g, 0, "Owlform")           # BOOST 2 and 3
    ai = EffectAI(0)
    options = [c.card_id for c in g.players[0].hand]
    answer = ai._dust_card(g, req("cards", 0, options, 0, 1, zone="hand", purpose="dust", of=0, foe=foe.fid, foe_hp=foe.hp))
    assert answer in ([], [junk.card_id], [best.card_id])
    foe.hp = 2                                                                  # any boost kills: a discard always pays
    answer = ai._dust_card(g, req("cards", 0, options, 0, 1, zone="hand", purpose="dust", of=0, foe=foe.fid, foe_hp=foe.hp))
    assert len(answer) == 1


def test_do_my_bidding_makes_the_rival_play_its_weakest_card(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    ph, leo = pair(g, "philippa", "leonardo")
    cards = sorted((c for c in g.players[1].deck if c.can_attack and c.usable_by(leo.name) and c.value), key=lambda c: c.value)
    weak, strong = cards[0], cards[-1]
    ai = EffectAI(0)
    assert ai._bidding_card(g, req("cards", 0, [strong.card_id, weak.card_id], 1, 1, zone="hand", purpose="bidding", of=1)) == [weak.card_id]


def test_the_ruse_discards_the_two_best_revealed_cards_and_the_bot_reveals_its_four_worst(bprd):
    g = mk(bprd, foe="leonardo", turn=1)
    hand = hand_filler(g, 1, 6)
    ai = EffectAI(0)
    shown = [c.card_id for c in hand[:4]]
    by_id = {c.card_id: c for c in hand}
    picked = ai._ruse_discards(g, req("cards", 0, shown, 2, 2, zone="hand", purpose="ruse", of=1))
    from sparring.search.adapter import card_worth
    assert sorted(card_worth(by_id[i]) for i in picked) == sorted(sorted((card_worth(by_id[i]) for i in shown), reverse=True)[:2])
    me = EffectAI(1)
    revealed = me._ruse_reveal(g, req("cards", 1, [c.card_id for c in hand], 4, 4, zone="hand", purpose="ruse_reveal", of=1))
    assert len(revealed) == 4


def test_chain_lightning_picks_the_zone_with_more_foes(bprd):
    g = mk(bprd)
    ph, foe = pair(g, "philippa", "hellboy")
    ai = EffectAI(0)
    assert ai._zone(g, req("effect", 0, [0, 1], 1, 1, tag="zone", labels=["a", "b"], hits=[[], ["hellboy", "lobster"]])) == 1
    assert ai._zone(g, req("effect", 0, [0, 1], 1, 1, tag="zone", labels=["a", "b"], hits=[["hellboy"], []])) == 0


def test_the_bot_does_not_draw_up_to_four_with_a_deck_too_short_for_it(bprd):
    g = mk(bprd)
    del g.players[0].deck[2:]
    hand_filler(g, 0, 0)
    request = req("optional", 0, [True, False], 1, 1, draws=4, draws_at="end_of_turn")
    assert EffectAI._free_draw(g, request) is False
    g2 = mk(bprd)
    assert EffectAI._free_draw(g2, req("optional", 0, [True, False], 1, 1, draws=4, draws_at="end_of_turn")) is True


def test_with_the_search_ai_a_whole_game_as_philippa_has_no_fallback_and_ends():
    from sparring import sim
    ai = sim.make_bot("ismcts", iterations=6, seed=2)
    out = sim.play(2, bot_hero="philippa", human_hero="hellboy", medusa=ai, max_turns=30, rival="chaser")
    assert out.turns >= 1 and ai.fallbacks == 0
