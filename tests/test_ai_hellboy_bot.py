"""Hellboy (+ Lobster Johnson) as the bot against Baba Yaga: the live game of 31/10 ended with the bot maneuvering at
1 HP with an empty deck (exhaustion), and it barely attacked (16 maneuvers, 4 attacks, none by Lobster)."""
import pytest

from conftest import Scripted, give
from sparring.ai_medusa import MedusaAI, Model
from sparring.search.controller import IsmctsMedusa
from sparring.search.ismcts import SearchConfig
from sparring.state import ANUNG, Game

BABA = 20
NEXT_TO_BABA = 17        # adjacent to Baba
FAR_FROM_BABA = 5        # three spaces away
LOBSTER = 4              # shares a zone with Baba


def hellboy_vs_baba(bprd, hand, hellboy=NEXT_TO_BABA, lobster=LOBSTER, anung=True, deck_left=None):
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Scripted()}, bot_player=0, heroes=("hellboy", "baba-yaga"))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    seen = {}
    for title in hand:
        seen[title] = seen.get(title, -1) + 1
        give(g, 0, title, seen[title])
    g.fighters["hellboy"].pos, g.fighters["lobster"].pos, g.fighters["baba"].pos = hellboy, lobster, BABA
    koschei = g.fighters["koschei"]
    koschei.alive, koschei.pos, koschei.hp = False, None, 0
    me = g.players[0]
    if anung:
        destiny = [c for c in me.full_set if c.destiny and c not in me.hand][:6]
        me.deck[:] = [c for c in me.deck if c not in destiny]
        me.discard[:] = destiny
        assert g.form(0) == ANUNG
    if deck_left is not None:
        rest = [c for c in me.full_set if c not in me.hand and c not in me.discard]
        me.deck[:] = rest[:deck_left]
        me.discard.extend(rest[deck_left:])
    rival = g.players[1]
    while len(rival.hand) < 5:
        rival.hand.append(rival.deck.pop(0))
    return g


def exhausted_and_low(g):
    g.players[0].deck.clear()
    g.fighters["hellboy"].hp = 1
    g.fighters["lobster"].hp = 4


BOTS = [lambda: MedusaAI(0), lambda: IsmctsMedusa(0, SearchConfig(iterations=300, seed=5))]
BOT_IDS = ["heuristic", "ismcts"]


@pytest.mark.parametrize("make", BOTS, ids=BOT_IDS)
def test_never_draws_into_exhaustion_that_kills_the_hero_when_an_attack_exists(bprd, make):
    g = hellboy_vs_baba(bprd, ["Service Pistol", "B.P.R.D. Training"])
    exhausted_and_low(g)
    act = make().plan(g)
    assert act.kind == "attack", "a maneuver draws from the empty deck: 2 damage to each fighter, Hellboy dies"


@pytest.mark.parametrize("make", BOTS, ids=BOT_IDS)
def test_never_draws_into_exhaustion_when_only_a_sidekick_can_attack(bprd, make):
    g = hellboy_vs_baba(bprd, ["Service Pistol"], hellboy=FAR_FROM_BABA)
    exhausted_and_low(g)
    act = make().plan(g)
    assert act.kind == "attack" and act.fid == "lobster"


def test_the_heuristic_scores_the_exhausting_maneuver_as_a_loss(bprd):
    g = hellboy_vs_baba(bprd, ["Service Pistol"])
    exhausted_and_low(g)
    ai = MedusaAI(0)
    ranked = ai.candidates(g, Model(g, 0))
    man = next(a for a in ranked if a.kind == "maneuver")
    assert man.total < -100 and ranked[0].kind == "attack"


def test_with_nothing_in_hand_and_an_empty_deck_the_maneuver_is_forced(bprd):
    """The live position: no card to attack or scheme with. The only legal action is the maneuver, so the exhaustion
    cannot be avoided; every candidate is a maneuver."""
    g = hellboy_vs_baba(bprd, [])
    exhausted_and_low(g)
    ranked = MedusaAI(0).candidates(g, Model(g, 0))
    assert ranked and {a.kind for a in ranked} == {"maneuver"}


def test_anung_plus_two_counts_in_the_value_of_the_bots_own_attack(bprd):
    ai = MedusaAI(0)
    anung = hellboy_vs_baba(bprd, ["Service Pistol"], anung=True)
    detective = hellboy_vs_baba(bprd, ["Service Pistol"], anung=False)
    values = {}
    for name, g in (("anung", anung), ("detective", detective)):
        hb, baba = g.fighters["hellboy"], g.fighters["baba"]
        values[name] = ai.attack_eval(g, Model(g, 0), hb, baba, g.players[0].hand[0])[1]
    assert values["anung"] > values["detective"]


@pytest.mark.parametrize("hand", [["Service Pistol", "Excalibur", "Planned Recklessness"]])
def test_hellboy_in_anung_in_reach_attacks_instead_of_maneuvering(bprd, hand):
    g = hellboy_vs_baba(bprd, hand)
    act = MedusaAI(0).plan(g)
    assert act.kind == "attack" and act.fid == "hellboy"


def test_lobster_shoots_when_hellboy_cannot_reach_and_a_decent_card_is_in_hand(bprd):
    """Hellboy needs the whole turn to close in; Lobster (ranged) is in Baba's zone with a 5: shoot, do not
    shuffle without moving anyone."""
    g = hellboy_vs_baba(bprd, ["Service Pistol", "B.P.R.D. Training"], hellboy=FAR_FROM_BABA)
    ai = MedusaAI(0)
    ranked = ai.candidates(g, Model(g, 0))
    shot = next(a for a in ranked if a.kind == "attack" and a.fid == "lobster")
    assert shot.value > 0
    idle = [a for a in ranked if a.kind == "maneuver" and a.boost is None
            and all(g.fighters[f].pos == d for f, d in a.moves.items())]
    assert all(shot.total > a.total for a in idle)


def test_an_idle_maneuver_loses_to_a_modest_attack_that_the_old_draw_bonus_beat(bprd):
    g = hellboy_vs_baba(bprd, ["Horseshoes And Hand Grenades", "On Earth As It Is In Hell"], lobster=8)
    g.fighters["hellboy"].pos = 21
    ai = MedusaAI(0)
    ranked = ai.candidates(g, Model(g, 0))
    idle = [a for a in ranked if a.kind == "maneuver" and a.boost is None
            and all(g.fighters[f].pos == d for f, d in a.moves.items())]
    assert all(a.value < 0.4 for a in idle), "a draw that moves nobody is worth less than a plain draw"


# ---- the deck is worth what the strategy says: a draw is cheap in a race the bot wins before the deck runs out,
# ---- and pays for the exhaustion to come when the game will outlast the deck
def idle_draw_total(bprd, deck_left, baba_hp=None, hand=("B.P.R.D. Training",)):
    g = hellboy_vs_baba(bprd, list(hand), deck_left=deck_left)
    g.actions_left = 1
    if baba_hp is not None:
        g.fighters["baba"].hp = baba_hp
    ranked = MedusaAI(0).candidates(g, Model(g, 0))
    return max(a.total for a in ranked if a.kind == "maneuver" and a.boost is None
               and all(g.fighters[f].pos == d for f, d in a.moves.items())), ranked


def test_a_low_deck_in_a_long_race_makes_the_idle_draw_pay_for_the_exhaustion_to_come(bprd):
    full, _ = idle_draw_total(bprd, deck_left=14)
    low, ranked = idle_draw_total(bprd, deck_left=3)
    assert low < full - 5, "the game outlasts three cards: every draw brings exhaustion damage closer"
    attack = max(a.total for a in ranked if a.kind == "attack")
    assert attack > low + 3, "so even a weak attack beats the draw that moves nobody"


def test_a_race_won_before_the_deck_runs_out_still_draws_freely(bprd):
    full, _ = idle_draw_total(bprd, deck_left=14, baba_hp=3)
    low, _ = idle_draw_total(bprd, deck_left=3, baba_hp=3)
    assert low > full - 1, "Baba dies in a turn or two: three cards are enough, drawing costs next to nothing"


def test_the_race_estimate_separates_winning_from_losing(bprd):
    ai = MedusaAI(0)
    even = hellboy_vs_baba(bprd, ["Service Pistol"])
    t_kill, t_die = ai.race(even, Model(even, 0))
    assert t_kill < 12 and t_die > 0
    weak = hellboy_vs_baba(bprd, ["Service Pistol"])
    weak.fighters["hellboy"].hp = 4
    assert ai.race(weak, Model(weak, 0))[1] < t_die, "fewer hit points: the rival kills the bot sooner"
    assert ai.deck_cost(weak, Model(weak, 0)) >= ai.deck_cost(even, Model(even, 0)), "losing the race: exhaustion costs more"
