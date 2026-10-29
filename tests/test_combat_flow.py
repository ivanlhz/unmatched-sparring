"""Combat flow as a serializable state machine (sparring/combat_flow.py). See docs/combat-flow.md."""
import json

import pytest

from conftest import give, place
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from sparring.combat_flow import RULES, CombatFlow, PendingChoice, Phase

NO_DECK = lambda card_id: False  # noqa: E731


# ---------- types ----------
def test_pending_choice_roundtrip():
    choice = PendingChoice("boost", player=1, card_id=19709, deck=True,
                           extra={"guid": "abc123", "baseline": [3, 4], "hand": 5, "stuck": True})
    raw = json.loads(json.dumps(choice.to_dict()))
    assert raw == {"kind": "boost", "player": 1, "card": 19709, "deck": True,
                   "guid": "abc123", "baseline": [3, 4], "hand": 5, "stuck": True}
    assert PendingChoice.from_dict(raw, default_player=1, deck_of=NO_DECK) == choice


def test_pending_choice_translates_legacy_boost_wait():
    old = {"card": 19709, "guid": None, "baseline": [7], "hand": None, "stuck": False}   # old save: no kind/player/deck
    choice = PendingChoice.from_dict(old, default_player=1, deck_of=lambda card_id: card_id == 19709)
    assert (choice.kind, choice.player, choice.card_id, choice.deck) == ("boost", 1, 19709, True)
    assert choice.extra == {"guid": None, "baseline": [7], "hand": None, "stuck": False}
    flat = choice.to_dict()
    assert flat["card"] == 19709 and flat["baseline"] == [7] and flat["stuck"] is False and flat["deck"] is True


@pytest.mark.parametrize("raw", [
    {"card": "x"},
    {"card": True},
    {"baseline": []},
    {"kind": "teleport", "player": 1, "card": 1, "deck": False},
    {"kind": "boost", "player": "1", "card": 1, "deck": False},
    [],
    None,
])
def test_pending_choice_rejects_invalid(raw):
    with pytest.raises(KeyError):
        PendingChoice.from_dict(raw, default_player=1, deck_of=NO_DECK)


def test_phase_order():
    assert [p.value for p in Phase] == ["declared", "cards_set", "revealed", "immediately", "during", "damage",
                                        "after", "done"]
    assert Phase("during") is Phase.DURING


# ---------- engine ----------
def adjacent(game):
    place(game, medusa=0, hellboy=1, harpy1=20, harpy2=21, harpy3=22, lobster=27)
    return game.fighters["medusa"], game.fighters["hellboy"]


def test_rule_order_matches_legacy_chains():
    by_phase = {phase: [r.name for r in RULES if r.phase is phase] for phase in Phase}
    # C5: Medusa's own rules (feint, second_shot, medusa_after) are gone, her cards go through the dsl_* rules
    assert by_phase[Phase.IMMEDIATELY] == ["planned_recklessness", "dsl_immediately"]
    assert by_phase[Phase.DURING] == ["on_earth_value", "boost_this_attack", "dsl_during"]
    # D1: the bot's box hero is interpreted; `bot_card_outside_the_interpreter` only guards a save that switched it off
    assert by_phase[Phase.AFTER] == ["bot_card_outside_the_interpreter", "human_card_after", "dsl_after"]
    assert [r.name for r in RULES if r.when_cancelled] == ["on_earth_value"]


def test_defender_resolves_first(game):
    med, hb = adjacent(game)
    feint, planned = give(game, 0, "Feint"), give(game, 1, "Planned Recklessness")
    flow = CombatFlow(game, med, hb, feint, planned)
    assert flow.run() is None
    assert [s.name for s in flow.sides] == ["def", "atk"]
    assert flow.result.cancelled == {"atk"}                 # Planned (defender) cancels Feint before it resolves
    assert flow.done and flow.phase is Phase.DONE


def test_after_gate_evaluated_once(game):
    med, hb = adjacent(game)
    snipe, glimpse = give(game, 0, "Snipe"), give(game, 1, "Glimpse Of Hell")
    flow = CombatFlow(game, med, hb, snipe, glimpse)
    while flow.phase is not Phase.DAMAGE:
        assert flow.step() is None
    assert flow.after_open is None                           # not evaluated before entering AFTER
    flow.step()
    assert flow.phase is Phase.AFTER and flow.after_open is True
    game.winner = 0                                          # a death mid-AFTER does not close the window
    assert flow.run() is None
    assert flow.result.human_effects and len(game.players[0].hand) == 1       # Glimpse pending for the human, Snipe drew


def test_cancelled_side_skips_except_when_cancelled(game):
    med, hb = adjacent(game)
    game.players[1].discard = [c for c in game.players[1].full_set if c.destiny][:4]
    oe, gaze = give(game, 1, "On Earth As It Is In Hell"), give(game, 0, "Gaze of Stone")
    free = CombatFlow(game, med, hb, gaze, oe)
    free.run()
    assert free.result.def_value == 4 and free.result.cancelled == set()

    oe2, feint = give(game, 1, "On Earth As It Is In Hell", 1), give(game, 0, "Feint")
    cancelled = CombatFlow(game, med, hb, feint, oe2)
    cancelled.run()
    assert cancelled.result.cancelled == {"def"} and cancelled.result.def_value == 0
    assert cancelled.result.def_parts[0].endswith("cancelada")
    # a cancelled On Earth heals nobody in AFTER; the only line is the bot's Feint narration (D3: Medusa narrated too)
    assert cancelled.result.applied == ["Feint: cancela los efectos de On Earth As It Is In Hell"]


# ---------- await / resume ----------
def second_shot_rig(game):
    """Medusa's Second Shot against On Earth with 4 destiny cards; Gaze of Stone is the boost card in hand."""
    med, hb = adjacent(game)
    game.players[1].discard = [c for c in game.players[1].full_set if c.destiny][:4]
    return med, hb, give(game, 0, "Second Shot"), give(game, 1, "On Earth As It Is In Hell"), give(game, 0, "Gaze of Stone")


def test_second_shot_awaits_in_during_after_defender_value(game):
    med, hb, shot, on_earth, gaze = second_shot_rig(game)
    flow = CombatFlow(game, med, hb, shot, on_earth)
    wait = flow.run()
    assert flow.phase is Phase.DURING and flow.pending == wait.choice
    assert (wait.choice.kind, wait.choice.player, wait.choice.card_id, wait.choice.deck) == ("boost", 0, shot.card_id, False)
    assert flow.ctx.def_value == 4                           # On Earth, resolved first, is already applied
    assert gaze in game.players[0].hand and flow.result.boost_card is None      # nothing mutated while waiting


def test_resume_with_boost_adds_it(game):
    med, hb, shot, on_earth, gaze = second_shot_rig(game)
    flow = CombatFlow(game, med, hb, shot, on_earth)
    flow.run()
    flow.resume(gaze)
    assert flow.pending is None and flow.run() is None
    assert flow.result.boost_card is gaze and flow.result.atk_value == shot.value + gaze.boost
    assert gaze in game.players[0].discard and gaze not in game.players[0].hand


def test_resume_with_none_is_no_boost(game):
    med, hb, shot, on_earth, gaze = second_shot_rig(game)
    flow = CombatFlow(game, med, hb, shot, on_earth)
    flow.run()
    flow.resume(None)
    assert flow.run() is None
    assert flow.result.boost_card is None and flow.result.atk_value == shot.value and gaze in game.players[0].hand


def _waiting_session(brig):
    from test_review9 import _boost_rig
    session, table, game, fake, second, _ = _boost_rig(brig)
    click(session, table, Event.REVEAL)
    return session, table, game, second


def test_old_save_boost_wait_loads_as_pending_choice(brig):
    session, table, game, second = _waiting_session(brig)
    saved = json.loads(json.dumps(session.to_dict()))
    old = {k: v for k, v in saved["pending"]["boost_wait"].items() if k not in ("kind", "player", "deck", "stuck")}
    saved["pending"]["boost_wait"] = old
    session.pending = None
    session.load_dict(saved)
    wait = session.pending.wait
    assert isinstance(wait, PendingChoice) and (wait.kind, wait.player, wait.card_id) == ("boost", session.human, second.card_id)
    assert wait.extra["stuck"] is False and wait.deck is False
    assert session.pending.boost_wait["card"] == second.card_id


def test_boost_wait_save_keeps_flat_keys(brig):
    session, table, game, second = _waiting_session(brig)
    flat = json.loads(json.dumps(session.to_dict()))["pending"]["boost_wait"]
    assert {"card", "guid", "baseline", "hand", "stuck", "deck"} <= set(flat) and flat["kind"] == "boost"
    assert flat["card"] == second.card_id and session.pending.boost_wait == flat
    session.pending.wait = None
    assert json.loads(json.dumps(session.to_dict()))["pending"]["boost_wait"] is None


def test_stuck_flag_persists_via_wait(brig):
    session, table, game, second = _waiting_session(brig)
    session.pending.wait.extra["stuck"] = True
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["pending"]["boost_wait"]["stuck"] is True
    session.pending = None
    session.load_dict(saved)
    assert session.pending.wait.extra["stuck"] is True and session.pending.boost_wait["stuck"] is True
    assert session.panel_view()[1]["btn_cancel"] == (True, True)


def fresh_rig():
    from conftest import Scripted
    from sparring.board import Board
    from sparring.state import Game
    g = Game.new(Board.load("bprd-hq"), seed=3, controllers={0: Scripted(), 1: Scripted()})
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def test_flow_roundtrip_mid_during():
    from sparring import persist
    from test_combat_flow_diff import result_record
    straight, paused = fresh_rig(), fresh_rig()
    outcomes = []
    for g in (straight, paused):
        med, hb, shot, on_earth, gaze = second_shot_rig(g)
        flow = CombatFlow(g, med, hb, shot, on_earth)
        wait = flow.run()
        outcomes.append((flow, wait, gaze))
    flow, wait, gaze = outcomes[0]
    flow.resume(gaze)
    flow.run()

    flow, wait, gaze = outcomes[1]
    saved_flow = json.loads(json.dumps(flow.to_dict()))
    saved_game = json.loads(json.dumps(persist.game_to_dict(paused)))
    reloaded = fresh_rig()
    persist.apply_game(reloaded, saved_game)
    restored = CombatFlow.from_dict(reloaded, saved_flow)
    assert restored.phase is Phase.DURING and restored.pending == wait.choice
    restored.resume(restored.card_by_id(gaze.card_id, wait.choice.player))
    assert restored.run() is None

    assert result_record(restored.result) == result_record(outcomes[0][0].result)
    assert persist.game_to_dict(reloaded) == persist.game_to_dict(straight)
