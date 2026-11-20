"""The search's defense against a face-down attack when its tree cannot tell the options apart (sparring/search/defense.py).

The position is the live one of 20/11 (game ...cdf9, turn 6): the bot's Hellboy, 18 hit points and six cards, attacked twice in a row by
a Clone of Sun Wukong. The tree rated no defense 0.579, Glimpse Of Hell 0.564 and B.P.R.D. Training 0.551 with 158 iterations, and took
neither attack; both were Ruyi Jingo Bang, either could have been Ox Form's 7. Ivan: "they could have been the Ox and the bot would have
eaten all the damage". The combat ledger fights every card the Clone may have played, weighed by its copies still unseen."""
from __future__ import annotations

import json

import pytest

from sparring import decision_log, persist
from sparring.ai_medusa import MedusaAI
from sparring.search import defense
from sparring.search.adapter import RESOLUTION, EngineState, hero_weights
from sparring.search.controller import make_bot_ai
from sparring.search.ismcts import SearchReport
from sparring.state import Game

LIVE_ITERATIONS = 158       # what the 3 s of the live game gave
HELLBOY_HAND = [19700, 19705, 19718, 19704, 19714, 19727]      # Excalibur, Service Pistol, B.P.R.D. Training, Right Hand Of Doom, Glimpse Of Hell, ...Crown Of Flame
HELLBOY_PILE = [19728, 19702, 19720, 19703]                    # Pancakes!, Right Hand Of Doom, Planned Recklessness, Right Hand Of Doom
SLY, TAUNT, OX, RUYI = 17613, 17607, 17601, (17602, 17603, 17604)
# the human's real hands the same public position may hide; the first one is the live game's (Phoenix Form, Infinite Strikes, Ox Form, Ruyi x2)
HIDDEN_HANDS = {"live hand, Ruyi played": [17629, 17609, 17601, 17602, 17603],
                "two Ox Forms": [17600, 17601, 17618, 17619, 17620],
                "no attack above 3": [17608, 17609, 17611, 17615, 17621]}
NONE, GLIMPSE, TRAINING = ("defend", None), ("defend", "Glimpse Of Hell"), ("defend", "B.P.R.D. Training")


def searcher(seed=0, iterations=LIVE_ITERATIONS):
    return make_bot_ai({"ai": "ismcts", "ai_iterations": iterations, "ai_seed": seed, "ai_eval": dict(RESOLUTION)}, 0)


def clone_attacks(bprd, ai, human_hand=HIDDEN_HANDS["live hand, Ruyi played"], human_pile=(SLY, TAUNT), hellboy_hand=HELLBOY_HAND, actions=2):
    """The table when the Clone's card lies face down: Sun Wukong (the human, player 1) has `human_pile` in the discard pile and
    `human_hand` in hand, the played card still among it, as in the live engine."""
    g = Game.new(bprd, 3, {0: ai, 1: MedusaAI(1)}, bot_player=0, heroes=("hellboy", "sun-wukong"))
    state = persist.game_to_dict(g)
    state.update(turn=1, turn_no=6, actions_left=actions, winner=None)
    for fid, (hp, pos) in {"hellboy": (18, 5), "lobster": (6, 3), "wukong": (12, 17), "clone1": (1, 15), "clone2": (1, 14), "clone3": (1, 19)}.items():
        state["fighters"][fid].update(hp=hp, pos=pos, alive=True)
    for p, hand, pile in ((0, hellboy_hand, HELLBOY_PILE), (1, human_hand, human_pile)):
        out = set(hand) | set(pile)
        state["players"][p].update(hand=list(hand), discard=list(pile), deck=sorted(c.card_id for c in g.players[p].full_set if c.card_id not in out))
    persist.apply_game(g, state)
    return g, g.fighters["clone2"], g.fighters["hellboy"]


def root_of(g, ai):
    return EngineState(g, observer=0, knowledge=ai.knowledge(g), pending=("clone2", "hellboy", None), weights=hero_weights(ai.weights, "hellboy", ai.explicit))


def title(card):
    return None if card is None else card.title


# ---------------------------------------------------------------- what the ledger measures

def test_the_ledger_weighs_every_card_the_clone_may_have_played_by_its_unseen_copies(bprd):
    ai = searcher()
    g, clone, hellboy = clone_attacks(bprd, ai)
    chance = {c.title: w for c, w in defense.beliefs(root_of(g, ai))}
    # 19 attack cards unseen: one Taunting Laughter and one Sly Monkey are in the discard pile
    assert chance == pytest.approx({"Ox Form": 2 / 19, "Ruyi Jingo Bang": 3 / 19, "Taunting Laughter": 2 / 19, "Infinite Strikes": 3 / 19,
                                    "Sly Monkey": 3 / 19, "72 Transformations": 3 / 19, "Wily Fighting": 3 / 19})


def test_not_defending_costs_hellboy_almost_three_times_what_a_defense_does(bprd):
    ai = searcher()
    g, clone, hellboy = clone_attacks(bprd, ai)
    loss = defense.ledger(root_of(g, ai), seed=0)
    # no card: Ox 7, Taunting 3, Wily 3 + 1, the four 2s (Infinite Strikes alone beside Hellboy), Ruyi 0
    assert loss[NONE] == pytest.approx((2 * 7 + 2 * 3 + 3 * 4 + 9 * 2) / 19)
    assert loss[TRAINING] < 1.0 and loss[GLIMPSE] < 1.1, "Ruyi's TRICKED YOU (4, met by the other defense) and Ox Form's remainder included"
    assert loss[NONE] - max(loss[TRAINING], loss[GLIMPSE]) > defense.CLEAR_HP


def ruyi_likely(bprd, but=(SLY,)):
    """The table where Ruyi Jingo Bang is the likely card: every other attack card of Sun Wukong except those of `but` is in the discard
    pile, and Hellboy's only defense is Glimpse Of Hell (2)."""
    full_set = Game.new(bprd, 3, {0: MedusaAI(0), 1: MedusaAI(1)}, bot_player=0, heroes=("hellboy", "sun-wukong")).players[1].full_set
    return {"human_hand": [17629, 17621, *RUYI], "hellboy_hand": [19700, 19705, 19704, 19714, 19727],
            "human_pile": [c.card_id for c in full_set if c.can_attack and c.card_id not in RUYI and c.card_id not in but]}


def test_the_ledger_prices_the_second_part_only_for_the_card_that_has_it(bprd):
    """Ivan D8 kept: with Ruyi Jingo Bang the likely card and one weak defense, playing it is what costs."""
    ai = searcher()
    g, clone, hellboy = clone_attacks(bprd, ai, **ruyi_likely(bprd))
    loss = defense.ledger(root_of(g, ai), seed=0)
    assert loss[NONE] == pytest.approx(2 / 4), "three Ruyi (0) and one Sly Monkey (2)"
    assert loss[GLIMPSE] >= 3 * loss[NONE], "TRICKED YOU's 4 three times in four, met by whatever Glimpse Of Hell drew"
    for seed in range(4):
        ai = searcher(seed)
        g.controllers[0] = ai
        assert ai.choose_defense(g, clone, hellboy) is None, seed


# ---------------------------------------------------------------- the live decision

@pytest.mark.parametrize("seed", [0, 1, 2, 4])
def test_hellboy_defends_the_clone_attack_that_may_be_ox_form(bprd, seed, tmp_path):
    """The four seeds are ones whose tree picks no defense at the live iteration count (seed 0 is the live game's own, with its values)."""
    ai = searcher(seed)
    ai.journal = decision_log.DecisionJournal(tmp_path / "decisions.jsonl")
    g, clone, hellboy = clone_attacks(bprd, ai)
    card = ai.choose_defense(g, clone, hellboy)
    report = ai.last_report
    assert report.ledger["tree"] is None, "the tree alone still takes the blow: the test would prove nothing otherwise"
    assert title(card) in ("Glimpse Of Hell", "B.P.R.D. Training") and report.move == ("defend", card.title)
    line = next(json.loads(x) for x in (tmp_path / "decisions.jsonl").read_text(encoding="utf-8").splitlines() if json.loads(x).get("kind") == "defense")
    assert line["chosen"]["card"] == card.title and line["chosen"]["combat_ledger"]["settled"] == card.title
    assert [a["move"][1] for a in line["alternatives"] if a.get("chosen")] == [card.title]


def test_the_live_seed_reproduces_the_values_of_the_game(bprd):
    ai = searcher(0)
    g, clone, hellboy = clone_attacks(bprd, ai)
    ai.choose_defense(g, clone, hellboy)
    assert {m[1]: round(v, 3) for m, v in ai.last_report.values.items()} == {None: 0.579, "Glimpse Of Hell": 0.564, "B.P.R.D. Training": 0.551}


def test_hellboy_defends_the_second_attack_in_a_row_too(bprd):
    ai = searcher(0)
    g, clone, hellboy = clone_attacks(bprd, ai, human_hand=[17629, 17609, 17601, 17603], human_pile=(SLY, TAUNT, RUYI[0]), actions=1)
    assert ai.choose_defense(g, clone, hellboy) is not None


def test_the_heuristic_defends_it_as_well(bprd):
    ai = MedusaAI(0)
    g, clone, hellboy = clone_attacks(bprd, ai)
    assert title(ai.choose_defense(g, clone, hellboy)) == "B.P.R.D. Training"


# ---------------------------------------------------------------- no cheating

class Opaque:
    card_id = 999999
    destiny = False

    def __getattr__(self, name):
        raise AssertionError(f"the defense read the rival's real hand ({name})")


def test_the_defense_is_the_same_whatever_card_the_human_put_face_down(bprd):
    seen = {}
    for name, hand in HIDDEN_HANDS.items():
        ai = searcher(0)
        g, clone, hellboy = clone_attacks(bprd, ai, human_hand=hand)
        seen[name] = title(ai.choose_defense(g, clone, hellboy)), ai.last_report.ledger, ai.last_report.values
    ai = searcher(0)
    g, clone, hellboy = clone_attacks(bprd, ai)
    g.players[1].hand[:] = [Opaque() for _ in range(5)]        # five cards nobody may look at
    seen["opaque"] = title(ai.choose_defense(g, clone, hellboy)), ai.last_report.ledger, ai.last_report.values
    assert ai.fallbacks == 0, "a search that fell back to the heuristic proves nothing"
    first = seen["live hand, Ruyi played"]
    assert first[0] is not None and all(other == first for other in seen.values()), seen


def test_the_ledger_alone_never_reads_the_rival_hand(bprd):
    ai = searcher()
    g, clone, hellboy = clone_attacks(bprd, ai)
    expected = defense.ledger(root_of(g, ai), seed=0)
    g.players[1].hand[:] = [Opaque() for _ in range(5)]
    assert defense.ledger(root_of(g, ai), seed=0) == expected


def test_a_card_seen_in_the_rival_hand_counts_whole(bprd):
    """A legitimate look (Confront Any Demon or God) showed Ox Form: it is in the hand for sure, the unseen cards only with the chance of the four other places."""
    ai = searcher()
    g, clone, hellboy = clone_attacks(bprd, ai)
    ox = next(c for c in g.players[1].full_set if c.card_id == OX)
    g.players[0].known.add(ox, g.turn_no)
    chance = {c.title: w for c, w in defense.beliefs(root_of(g, ai))}
    unseen = 4 / 27         # four hidden places among the 27 cards neither seen nor in a public pile
    assert chance["Ox Form"] == pytest.approx((1 + unseen) / (1 + 18 * unseen)) and chance["Ruyi Jingo Bang"] == pytest.approx(3 * unseen / (1 + 18 * unseen))


# ---------------------------------------------------------------- the tree keeps what it is sure of

def settled(bprd, values, errors, tree=NONE, **table):
    ai = searcher()
    g, clone, hellboy = clone_attacks(bprd, ai, **table)
    report = SearchReport(tree, 100, 0.0, dict.fromkeys(values, 50), dict(values), errors=dict.fromkeys(values, errors))
    return defense.settle(root_of(g, ai), report, tree, seed=0), report


def test_a_tree_that_cannot_tell_them_apart_gives_way_to_the_cheapest_combat(bprd):
    move, report = settled(bprd, {NONE: 0.579, GLIMPSE: 0.564, TRAINING: 0.575}, errors=0.008)
    assert move == TRAINING and report.move == TRAINING and report.ledger["tree"] is None


def test_an_undecided_tree_that_defended_a_sure_ruyi_is_turned_back(bprd):
    """Ivan D8, the other way round: the ledger also takes a defense card back when playing it is what brings TRICKED YOU."""
    move, report = settled(bprd, {NONE: 0.72, GLIMPSE: 0.725}, errors=0.008, tree=GLIMPSE, **ruyi_likely(bprd, but=()))
    assert report.ledger["loss"]["None"] == 0 and report.ledger["loss"]["Glimpse Of Hell"] >= 1.5
    assert move == NONE


def test_a_tree_sure_of_its_move_keeps_it(bprd):
    move, report = settled(bprd, {NONE: 0.62, GLIMPSE: 0.56, TRAINING: 0.55}, errors=0.008)
    assert move == NONE and report.move == NONE, "0.06 above both, more than 1.65 standard errors of the difference (0.019)"
    assert report.ledger["settled"] is None


def test_only_the_options_the_tree_does_not_rate_clearly_below_are_open(bprd):
    move, _ = settled(bprd, {NONE: 0.579, GLIMPSE: 0.570, TRAINING: 0.50}, errors=0.008)
    assert move == GLIMPSE, "B.P.R.D. Training is the cheapest combat, but the tree is sure it is worse"


def test_a_saving_under_a_hit_point_does_not_move_the_tree(bprd):
    move, report = settled(bprd, {NONE: 0.57, GLIMPSE: 0.58, TRAINING: 0.575}, errors=0.008, tree=GLIMPSE)
    assert report.ledger["loss"]["Glimpse Of Hell"] - report.ledger["loss"]["B.P.R.D. Training"] < defense.CLEAR_HP
    assert move == GLIMPSE


def test_the_last_card_of_the_hand_is_never_spent_by_the_ledger(bprd):
    """Ivan, 16/11: not the last card on a defense unless the search itself wants it."""
    move, report = settled(bprd, {NONE: 0.579, TRAINING: 0.575}, errors=0.008, hellboy_hand=[19718])
    assert report.ledger["loss"]["None"] - report.ledger["loss"]["B.P.R.D. Training"] > defense.CLEAR_HP
    assert move == NONE


def test_an_attack_played_face_up_is_left_to_the_tree(bprd):
    ai = searcher()
    g, clone, hellboy = clone_attacks(bprd, ai)
    ox = next(c for c in g.players[1].full_set if c.card_id == OX)
    root = EngineState(g, observer=0, knowledge=ai.knowledge(g), pending=("clone2", "hellboy", ox), weights=hero_weights(ai.weights, "hellboy", ai.explicit))
    report = SearchReport(NONE, 100, 0.0, {NONE: 50}, {NONE: 0.5})
    assert defense.settle(root, report, NONE, seed=0) == NONE and report.ledger is None
