"""Ivan's rulings of 28/10: only a card with a boost value can boost, and there is one active ONGOING per player."""
import json

import pytest

from conftest import give, place
from sparring import persist
from sparring.ai_medusa import MedusaAI
from sparring.cards import can_be_boost
from sparring.combat import FIGHT_OR_FLIGHT
from sparring.search.adapter import SearchController
from sparring.state import RuleError
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_fight_or_flight import play_plan
from test_review10 import flame_rig, rig
from test_session import card

HB, MED = 1, 0


_changed = []


@pytest.fixture(autouse=True)
def _restore_boosts():
    yield
    for c, boost in _changed:
        object.__setattr__(c, "boost", boost)
    _changed.clear()


def zero_boost(game, player, title="Service Pistol"):
    """No test-box deck has boost-0 cards (Liz's burning ones): strip the boost from one."""
    c = card(game, player, title)
    _changed.append((c, c.boost))
    object.__setattr__(c, "boost", 0)
    if c not in game.players[player].hand:
        game.players[player].hand.append(c)
    return c


def test_helper_distinguishes_zero_and_positive_boost(game):
    assert not can_be_boost(zero_boost(game, HB))
    assert can_be_boost(give(game, HB, "Glimpse Of Hell"))


def test_engine_rejects_a_zero_boost_in_combat_and_maneuver(game, ctl):
    place(game, medusa=0, hellboy=1, harpy1=20, harpy2=21, harpy3=22, lobster=27)
    med, hb = game.fighters["medusa"], game.fighters["hellboy"]
    zero = zero_boost(game, MED, "Gaze of Stone")
    ctl[MED].boost = zero
    with pytest.raises(RuleError):
        game.attack(med, hb, give(game, MED, "Second Shot"), None)
    assert zero in game.players[MED].hand
    ctl[MED].boost = None
    game.turn = MED
    with pytest.raises(RuleError):
        game.maneuver(MED, {}, zero)


def test_ai_controllers_never_choose_a_zero_boost(game):
    place(game, medusa=0, hellboy=1, harpy1=20, harpy2=21, harpy3=22, lobster=27)
    game.players[MED].hand[:] = [zero_boost(game, MED, "Gaze of Stone")]

    class Ctx:
        target, atk_value, def_value = game.fighters["hellboy"], 5, 5
    for ctrl in (MedusaAI(MED), SearchController(MED, None)):
        assert ctrl.choose_combat_boost(game, Ctx) is None


def test_human_zero_boost_does_not_count_and_waits_like_no_boost_was_placed(brig):  # noqa: F811
    session, table, game, fake, second = rig(brig)
    table.human_count = 4
    click(session, table, Event.REVEAL)
    zero = zero_boost(game, HB)
    table.human_discard = [zero.card_id]
    table.human_count = 3
    hp = game.fighters["medusa"].hp
    msgs = click(session, table, Event.BOOST)
    assert session.pending is not None and session.pending.boost_wait is not None
    assert not session.pending.boost_wait.get("stuck")
    assert any(f"{zero.title} no tiene valor de impulso: no cuenta" in m for m in msgs), msgs
    assert game.fighters["medusa"].hp == hp and zero not in game.players[HB].discard


def test_flame_lash_bottom_card_with_zero_boost_still_resolves(brig):  # noqa: F811
    session, table, game, flame = flame_rig(brig)
    table.human_count = 4
    click(session, table, Event.REVEAL)
    zero = zero_boost(game, HB)
    table.human_discard = [zero.card_id]
    msgs = click(session, table, Event.BOOST)
    assert session.pending is None, msgs
    assert not any("no tiene valor de impulso" in m for m in msgs)


# ---------- one ONGOING per player ----------
def test_second_ongoing_replaces_the_first_and_reports_it(game):
    assert game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT) is None
    assert game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT) == FIGHT_OR_FLIGHT
    assert game.combat_bonus_parts(HB) == [(1, FIGHT_OR_FLIGHT)] and game.combat_bonus_total(HB) == 1
    assert game.combat_bonus_total(MED) == 0, "the rival's ONGOING is untouched"


def test_replacing_ongoing_is_per_player_and_clone_is_independent(game):
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    game.add_combat_bonus(MED, 1, FIGHT_OR_FLIGHT)
    c = game.clone()
    c.add_combat_bonus(HB, 3, "Otro")
    assert c.combat_bonus_parts(HB) == [(3, "Otro")] and c.combat_bonus_total(MED) == 1
    assert game.combat_bonus_parts(HB) == [(1, FIGHT_OR_FLIGHT)]


def test_old_save_with_several_bonuses_keeps_the_last(game):
    data = json.loads(json.dumps(persist.game_to_dict(game)))
    data["combat_bonus"] = [[], [[1, FIGHT_OR_FLIGHT], [2, "Otro"]]]
    persist.apply_game(game, data)
    assert game.combat_bonus_parts(HB) == [(2, "Otro")]


def test_session_announces_the_replacement(brig):  # noqa: F811
    session, table, game, fake = brig
    play_plan(session, table, game)
    game.actions_left = 3                         # keep the turn from ending between the two schemes
    plan2 = card(game, HB, "Pancakes!")
    object.__setattr__(plan2, "title", FIGHT_OR_FLIGHT)
    object.__setattr__(plan2, "text", "ONGOING: Add +1 to the value of your combat cards.")
    click(session, table, Event.SCHEME)
    table.human_discard = [plan2.card_id]
    msgs = click(session, table, Event.END_ACTION)
    assert game.combat_bonus_total(HB) == 1
    assert any("Fight Or Flight reemplaza a Fight Or Flight" in m for m in msgs), msgs
