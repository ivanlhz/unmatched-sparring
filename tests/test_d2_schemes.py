"""D2: the bot plays the schemes and abilities of any interpreted hero, in the heuristic AI and in ISMCTS.

Schemes of a box hero are decided INSIDE the card by a chooser (no presets): the heuristic simulates them with
EffectAI deciding and values what they swing; the search enumerates one move per scheme title and chooser variant
(greedy / safe) and executes the one it chose with that same chooser. The ONGOING slot is valued, so replacing one
is a trade. Start-of-turn abilities reach the bot through `events.dispatch` at `begin_turn`, in the simulator and
inside the search's `_advance`. The search only ever shows a chooser the determinized rival hand."""
from __future__ import annotations

import random
import time

import pytest

from conftest import Scripted, give, place
from sparring import sim
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import ACTION_VALUE, CARD_VALUE, DEATH, MedusaAI, Model
from sparring.effects import ongoing
from sparring.effects.choose import SCHEME_VARIANTS, ChoiceRequest, SyntheticChooser
from sparring.search.adapter import SCHEME_MOVES_KEEP, EngineState, scheme_variants
from sparring.search.controller import IsmctsMedusa, make_bot_ai
from sparring.search.ismcts import SearchConfig
from sparring.state import ANUNG, Game
from test_d1_bot_cards import far_from, fight, mk, zone_mate
from test_effects_combat import pair
from test_effects_info import HandSpy


def bot_game(bprd, bot, human, seed=3):
    """Bot = player 0 with `bot` under MedusaAI, human = player 1 scripted; bot's turn, empty hands."""
    g = mk(bprd, bot, human, seed)
    g.controllers = {0: MedusaAI(0), 1: Scripted()}
    return g


def fill(g, player, n):
    st = g.players[player]
    while len(st.hand) < n:
        st.hand.append(st.deck.pop(0))


# ---------------------------------------------------------------- the ONGOING slot is worth something

def test_ongoing_worth_per_card(bprd):
    g = bot_game(bprd, "liz-sherman", "baba-yaga")
    assert ongoing.worth(g, 0) == 0.0
    g.play_scheme(0, g.hero(0), give(g, 0, "Fight Or Flight"))
    assert ongoing.worth(g, 0) == ongoing.VALUE_POINT_HP
    g.add_combat_bonus(1, 2, "legacy")
    assert ongoing.worth(g, 1) == 2 * ongoing.VALUE_POINT_HP
    a = bot_game(bprd, "abe-sapien", "baba-yaga")
    a.play_scheme(0, a.hero(0), give(a, 0, "Counterhex Shield"))
    assert ongoing.worth(a, 0) == 3 * ongoing.IMMUNITY_HP
    b = bot_game(bprd, "baba-yaga", "abe-sapien")
    b.play_scheme(0, b.hero(0), give(b, 0, "Pact Of Mortality"))
    assert ongoing.worth(b, 0) == ongoing.EFFECT_BONUS_HP
    b.play_scheme(0, b.hero(0), give(b, 0, "Pact Of Time"))
    assert ongoing.worth(b, 0) == 0.0, "a rule that binds both players is not an advantage by itself"


def test_evaluation_counts_the_ongoing_on_both_sides(bprd):
    g = bot_game(bprd, "liz-sherman", "baba-yaga")
    ai = EffectAI(0)
    before = ai.evaluate(g, 0)
    g.fx.set_ongoing(0, give(g, 0, "Fight Or Flight").card_id)
    g.players[0].hand.clear()
    assert ai.evaluate(g, 0) > before
    st = EngineState(g, observer=0)
    with_it = st._side_value(0)
    st.game.fx.take_ongoing(0)
    assert with_it > st._side_value(0)


# ---------------------------------------------------------------- heuristic: generic scheme acts

def test_the_heuristic_values_a_scheme_by_simulating_it(bprd):
    g = bot_game(bprd, "hellboy", "liz-sherman")
    crown = give(g, 0, "And Upon His Brow Is Set A Crown Of Flame")
    give(g, 0, "Service Pistol")
    ai = g.controllers[0]
    acts = ai.scheme_acts(g, Model(g, 0))
    assert [a.kind for a in acts] == ["scheme"] and acts[0].card is crown and acts[0].sim is not None
    act = acts[0]
    # discards Service Pistol (its keep_value), draws 2 unknown cards, gains 2 actions, costs the card itself
    pistol = g.players[0].hand[1]
    from sparring.ai_medusa import keep_value
    expected = 2 * CARD_VALUE - keep_value(pistol, g.players[0].hand) + 2 * ACTION_VALUE - CARD_VALUE
    assert act.value == pytest.approx(expected)
    assert len(g.players[0].hand) == 2, "valuing does not touch the real game"
    after = ai.apply_expected(g, act)
    assert after.actions_left == 2 + 2 - 1 and len(after.players[0].hand) == 2
    ai.execute(g, act)
    assert g.actions_left == 3 and len(g.players[0].hand) == 2 and crown in g.players[0].discard


def test_the_heuristic_plays_a_scheme_that_wins_the_game(bprd):
    """A scheme that kills the rival hero is the winning move, not a loss (`outcome` reads who won)."""
    g = bot_game(bprd, "baba-yaga", "liz-sherman")
    zone_mate(g, "liz", "baba")
    g.fighters["liz"].hp = 1
    peace = give(g, 0, "Pact Of Peace")
    give(g, 0, "Iron Teeth")
    g.actions_left = 1
    ai = g.controllers[0]
    act = ai.plan(g)
    assert act.kind == "scheme" and act.card is peace and act.total > DEATH / 2
    ai.execute(g, act)
    assert g.winner == 0


def test_one_act_per_scheme_title_and_the_same_chooser_decides_in_the_real_play(bprd):
    g = bot_game(bprd, "liz-sherman", "baba-yaga")
    give(g, 0, "Fight Or Flight", 0)
    give(g, 0, "Fight Or Flight", 1)
    ai = g.controllers[0]
    acts = [a for a in ai.candidates(g, Model(g, 0)) if a.kind == "scheme"]
    assert len(acts) == 1
    act = acts[0]
    expected = act.sim.fighters["liz"].pos
    ai.execute(g, act)
    assert g.fighters["liz"].pos == expected, "the plan and the play decide alike"
    assert g.fx.ongoing_card_id(0) == act.card.card_id and len(g.players[0].hand) == 2


# ---------------------------------------------------------------- replacement of the ONGOING

def test_a_new_ongoing_replaces_the_old_and_the_value_is_the_trade(bprd):
    g = bot_game(bprd, "baba-yaga", "abe-sapien")
    peace = give(g, 0, "Pact Of Peace")
    g.play_scheme(0, g.hero(0), peace)
    mortality = give(g, 0, "Pact Of Mortality")
    ai = g.controllers[0]
    act = ai.scheme_act(g, mortality)
    assert act.sim.fx.ongoing_card_id(0) == mortality.card_id and peace in act.sim.players[0].discard
    # Peace is worth 0 and Mortality +1 effect damage: the trade is the gain of the new card, minus the card played
    assert act.value == pytest.approx(EffectAI.material_delta(g, act.sim, 0) - CARD_VALUE)
    assert EffectAI.material_delta(g, act.sim, 0) == pytest.approx(1.2 * ongoing.EFFECT_BONUS_HP)
    ai.execute(g, act)
    assert g.fx.ongoing_card_id(0) == mortality.card_id and g.players[0].discard.count(peace) == 1


def test_replacing_a_better_ongoing_costs_in_the_value(bprd):
    g = bot_game(bprd, "liz-sherman", "baba-yaga")
    g.play_scheme(0, g.hero(0), give(g, 0, "Fight Or Flight", 0))
    fof = give(g, 0, "Fight Or Flight", 1)
    act = g.controllers[0].scheme_act(g, fof)
    assert EffectAI.material_delta(g, act.sim, 0) == pytest.approx(0.0), "same card in, same card out"
    g.fx.take_ongoing(0)
    better = g.controllers[0].scheme_act(g, fof)
    assert better.value > act.value, "playing it over nothing is worth more than replacing a twin"


# ---------------------------------------------------------------- the search

def test_scheme_moves_are_one_per_title_and_variant_only_when_the_card_asks(bprd):
    g = bot_game(bprd, "baba-yaga", "abe-sapien")
    for t in ("Pact Of Freedom", "Pact Of Peace", "Pact Of Time"):
        give(g, 0, t)
    st = EngineState(g, observer=0)
    schemes = [m for m in st.legal_moves() if m[0] == "scheme"]
    assert schemes == [("scheme", "Pact Of Freedom", None, "greedy"), ("scheme", "Pact Of Freedom", None, "safe"),
                       ("scheme", "Pact Of Peace", None, None),
                       ("scheme", "Pact Of Time", None, "greedy"), ("scheme", "Pact Of Time", None, "safe")]
    assert scheme_variants("abe-sapien", "Counterhex Shield") == (None,)
    assert scheme_variants("hellboy", "Pancakes!") == SCHEME_VARIANTS == ("greedy", "safe")


def test_scheme_moves_are_capped_and_the_safe_lines_go_first(bprd):
    g = bot_game(bprd, "baba-yaga", "abe-sapien")
    for t in ("Pact Of Freedom", "Pact Of Mortality", "Pact Of Secrecy", "Pact Of Time", "Pact Of Peace"):
        give(g, 0, t)
    st = EngineState(g, observer=0)
    schemes = [m for m in st.legal_moves() if m[0] == "scheme"]
    assert len(schemes) == SCHEME_MOVES_KEEP
    assert {m[1] for m in schemes if m[3] != "safe"} == {"Pact Of Freedom", "Pact Of Mortality", "Pact Of Secrecy",
                                                          "Pact Of Time", "Pact Of Peace"}


def test_the_search_applies_a_scheme_with_the_variant_chooser_and_the_lines_differ(bprd):
    g = bot_game(bprd, "baba-yaga", "abe-sapien")
    give(g, 0, "Pact Of Freedom")
    fill(g, 1, 3)
    outcomes = {}
    for v in SCHEME_VARIANTS:
        st = EngineState(g, observer=0)
        st.determinize(0, random.Random(0))
        st.apply(("scheme", "Pact Of Freedom", None, v))
        sg = st.game
        assert sg.fx.ongoing_card_id(0) is not None and sg.actions_left == 1 and len(sg.players[0].hand) == 2
        outcomes[v] = (sg.fighters["baba"].pos, sg.fighters["abe"].pos)
    assert outcomes["greedy"] != outcomes["safe"]
    assert g.fx.ongoing_card_id(0) is None, "the root game is untouched"


def test_the_bot_executes_the_scheme_the_search_chose_with_its_chooser(bprd):
    g = bot_game(bprd, "baba-yaga", "abe-sapien")
    give(g, 0, "Pact Of Freedom")
    ai = IsmctsMedusa(0, SearchConfig(iterations=10, seed=1))
    act = ai.to_act(g, [("scheme", "Pact Of Freedom", None, "safe")])
    assert act.kind == "scheme" and act.variant == "safe" and act.card.title == "Pact Of Freedom"
    st = EngineState(g, observer=0)
    st.determinize(0, random.Random(0))
    st.apply(("scheme", "Pact Of Freedom", None, "safe"))
    ai.execute(g, act)
    assert g.fx.ongoing_card_id(0) == act.card.card_id
    assert (g.fighters["baba"].pos, g.fighters["abe"].pos) == (st.game.fighters["baba"].pos, st.game.fighters["abe"].pos)


def test_every_box_hero_plays_schemes_in_simulated_games(monkeypatch):
    """Heuristic and ISMCTS bots of the four heroes play at least one scheme over a few games, with no fallback."""
    played = {}
    real = Game.play_scheme

    def spy(self, player, fighter, card, *a, **k):
        if player == 0:
            played[self.players[0].hero.slug] = played.get(self.players[0].hero.slug, 0) + 1
        return real(self, player, fighter, card, *a, **k)
    monkeypatch.setattr(Game, "play_scheme", spy)
    for bot in ("hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "medusa"):
        for seed in range(3):
            sim.play(seed, bot_hero=bot, human_hero="hellboy" if bot != "hellboy" else "medusa", max_turns=40)
            ai = sim.make_bot("ismcts", iterations=8, seed=seed)
            sim.play(seed, bot_hero=bot, human_hero="hellboy" if bot != "hellboy" else "medusa", medusa=ai, max_turns=24)
            assert ai.fallbacks == 0
        assert played.get(bot, 0) >= 1, bot


def test_a_box_hero_decides_within_the_default_time_budget(bprd):
    g = bot_game(bprd, "baba-yaga", "abe-sapien")
    for t in ("Pact Of Freedom", "Pact Of Secrecy", "Pact Of Peace", "Iron Teeth", "Out Of Time"):
        give(g, 0, t)
    zone_mate(g, "abe", "baba")
    fill(g, 1, 5)
    ai = make_bot_ai({"ai": "ismcts"})
    t0 = time.perf_counter()
    ai.plan(g)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0 and ai.fallbacks == 0, f"{elapsed:.2f}s"
    assert ai.last_report.iterations > 300, ai.last_report.iterations


# ---------------------------------------------------------------- start-of-turn abilities inside the search

def pass_turn(st):
    """Two bot maneuvers end its turn; `_advance` then begins the rival's."""
    for _ in range(2):
        st.apply(("maneuver", None))
        if st.phase == "maneuver_place":
            st.apply(("place", st.game.hero(st.game.turn).pos, "stay"))


def test_hellboy_bot_in_occult_detective_draws_two_on_the_rival_start_inside_the_search(bprd):
    g = bot_game(bprd, "hellboy", "liz-sherman")
    g.turn = 1
    place(g, hellboy=g.start_spaces[1], liz=far_from(g, "hellboy"))
    fill(g, 1, 2)
    st = EngineState(g, observer=0)
    st.determinize(0, random.Random(0))
    pass_turn(st)
    assert st.game.turn == 0 and st.phase == "action" and len(st.game.players[0].hand) == 2


def test_hellboy_bot_in_anung_discards_and_moves_without_a_search_decision(bprd):
    g = bot_game(bprd, "hellboy", "liz-sherman")
    g.players[0].discard += [c for c in g.players[0].deck if c.destiny][:6]
    for c in g.players[0].discard:
        g.players[0].deck.remove(c)
    assert g.form(0) == ANUNG
    g.turn = 1
    place(g, liz=far_from(g, "hellboy"))
    fill(g, 0, 3)
    fill(g, 1, 2)
    st = EngineState(g, observer=0)
    st.determinize(0, random.Random(0))
    pass_turn(st)
    assert st.game.turn == 0 and st.phase == "action"
    assert len(st.game.players[0].hand) == 2 and all(m[0] != "anung" for m in st.legal_moves())


def test_liz_bot_wildfire_discards_the_bottom_card_at_her_start_in_the_search_and_the_simulator(bprd):
    g = bot_game(bprd, "liz-sherman", "hellboy")
    assert len(g.players[0].discard) == 1, "mk began Liz's turn: Wildfire already burnt one bottom card"
    g.turn = 1
    fill(g, 1, 2)
    n_deck, n_out = len(g.players[0].deck), len(g.players[0].discard) + len(g.players[0].hand)
    st = EngineState(g, observer=0)
    st.determinize(0, random.Random(0))
    pass_turn(st)
    sg = st.game
    assert sg.turn == 0 and st.phase == "action" and len(sg.players[0].deck) == n_deck - 1
    assert len(sg.players[0].discard) + len(sg.players[0].hand) == n_out + 1      # discarded, or back in hand (burning)
    trace = []
    sim.play(2, bot_hero="liz-sherman", human_hero="hellboy", max_turns=4, trace=trace)
    liz_turns = [line for line in trace if line.startswith("T") and " P0: " in line]
    assert liz_turns, trace


def test_abe_bot_gains_an_intuition_token_from_combat_damage_inside_the_search(bprd):
    g = bot_game(bprd, "abe-sapien", "hellboy")
    pair(g, "abe", "hellboy")
    give(g, 0, "Advanced Psychometry")
    fill(g, 1, 2)
    st = EngineState(g, observer=0)
    st.determinize(0, random.Random(0))
    st.apply(("attack", "abe", "hellboy"))
    st.apply(("defend", None))
    assert st.game.fx.counter_value(0, "intuition") == 1
    assert g.fx.counter_value(0, "intuition") == 0, "the root game is untouched"


def test_a_pact_of_peace_of_the_bot_hurts_the_attacker_at_the_end_of_the_turn_inside_the_search(bprd):
    g = bot_game(bprd, "baba-yaga", "hellboy")
    g.play_scheme(0, g.hero(0), give(g, 0, "Pact Of Peace"))
    pair(g, "baba", "hellboy")
    give(g, 0, "Iron Teeth")
    fill(g, 1, 2)
    st = EngineState(g, observer=0)
    st.determinize(0, random.Random(0))
    st.apply(("attack", "baba", "hellboy"))
    st.apply(("defend", None))
    hp = st.game.fighters["baba"].hp
    st.apply(("maneuver", None))
    if st.phase == "maneuver_place":
        st.apply(("place", st.game.hero(0).pos, "stay"))
    assert st.game.turn == 1 and st.game.fighters["baba"].hp == hp - 1


# ---------------------------------------------------------------- no cheating

def test_the_search_chooser_only_sees_the_determinized_rival_hand(bprd):
    """Every Possible Angle inside the search: the look and the pick read the sampled hand; the real one is
    never read (HandSpy), and the card put on top is one the sample held."""
    g = bot_game(bprd, "abe-sapien", "hellboy")
    give(g, 0, "Every Possible Angle")
    fill(g, 1, 3)
    real = list(g.players[1].hand)
    spy = HandSpy(real)
    g.players[1].hand = spy
    st = EngineState(g, observer=0)
    spy.armed = True
    try:
        st.determinize(0, random.Random(5))
        sampled = list(st.game.players[1].hand)
        assert sampled != real
        st.apply(("scheme", "Every Possible Angle", None, "greedy"))
        top = st.game.players[1].deck[0]
        assert top in sampled and top not in st.game.players[1].hand
        assert st.game.players[0].known.top_of_deck == [top.card_id]
    finally:
        spy.armed = False
    assert g.players[0].known.is_empty(), "the root game learned nothing"


def test_a_search_scheme_never_moves_the_live_rng(bprd):
    g = bot_game(bprd, "baba-yaga", "hellboy")
    give(g, 0, "Pact Of Secrecy")
    fill(g, 1, 3)
    state = g.rng.getstate()
    st = EngineState(g, observer=0)
    st.determinize(0, random.Random(0))
    st.apply(("scheme", "Pact Of Secrecy", None, "greedy"))       # shuffles both decks through the run's rng
    assert g.rng.getstate() == state


def test_synthetic_policies_are_deterministic_and_opposite(bprd):
    g = bot_game(bprd, "baba-yaga", "hellboy")
    req = ChoiceRequest("optional", 0, [True, False], 1, 1, extra={"cost_cards": 1})
    assert SyntheticChooser(policy="greedy").choose(g, req) == [True]
    assert SyntheticChooser(policy="safe").choose(g, req) == [False]
    req = ChoiceRequest("effect", 0, [0, 1, 2], 1, 1)
    assert SyntheticChooser(policy="greedy").choose(g, req) == [0] and SyntheticChooser(policy="safe").choose(g, req) == [2]
    req = ChoiceRequest("amount", 0, list(range(4)), 1, 1)
    g.players[0].deck = g.players[0].deck[:2]
    assert SyntheticChooser(policy="greedy").choose(g, req) == [2], "never draws into exhaustion"
    with pytest.raises(ValueError):
        SyntheticChooser(policy="bold")


# ---------------------------------------------------------------- Liz: a burning card at the bottom (Wildfire)

def test_liz_bot_pyrotechnics_leaves_a_burning_card_at_the_very_bottom(bprd):
    g = bot_game(bprd, "liz-sherman", "hellboy")
    zone_mate(g, "hellboy", "liz", adjacent=True)
    burning = next(c for c in g.players[0].deck if "burning" in c.tags and c.value and c.can_attack)
    g.players[0].deck.remove(burning)
    g.players[0].hand.append(burning)
    plain = give(g, 0, "Evade")
    res = fight(g, "liz", "hellboy", "Pyrotechnics")
    deck = g.players[0].deck
    assert burning not in g.players[0].hand and deck[-1] is burning, res.applied
    assert plain in g.players[0].hand or deck[-2] is plain
    g.end_turn()
    g.begin_turn()
    g.end_turn()
    g.begin_turn()
    assert burning in g.players[0].hand, "Wildfire brought it back"


def test_liz_bot_orders_the_bottom_so_the_burning_card_is_last(bprd):
    g = bot_game(bprd, "liz-sherman", "hellboy")
    ai = EffectAI(0, g.controllers[0])
    burning = next(c for c in g.players[0].deck if "burning" in c.tags)
    plain = next(c for c in g.players[0].deck if "burning" not in c.tags)
    req = ChoiceRequest("order", 0, [burning.card_id, plain.card_id], 2, 2, extra={"zone": "deck", "purpose": "order", "position": "bottom"})
    assert ai.decide(g, req, nested=True) == [plain.card_id, burning.card_id]
    req = ChoiceRequest("order", 0, [burning.card_id, plain.card_id], 2, 2, extra={"zone": "deck", "purpose": "order", "position": "top"})
    assert ai.decide(g, req, nested=True)[0] == max((burning, plain), key=lambda c: (c.value or 0) + 0.5 * c.boost).card_id
