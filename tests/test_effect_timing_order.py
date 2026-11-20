"""The order card effects resolve in (Ivan, 20/11/2026): every effect has a timing, IMMEDIATELY (1st), DURING COMBAT (2nd),
AFTER COMBAT (3rd). Effects resolve in timing order; with the same timing the defender's goes first, so the defender's goes
first when its timing is earlier than or equal to the attacker's, else the attacker's. A free BOOST a card allows DURING COMBAT
(Second Shot, Out Of Time) and the BOOSTED WITH effects of that boost belong to DURING: they are settled, a human's boost read
from the table included, before any AFTER of either side and before the combat damage is decided.

Three nets: the 3 x 3 matrix of timings (with an IMMEDIATELY cancel on top) on a recorded interpreter, real cards on the
engine, and real cards through the session with a human at the table, both ways."""
from __future__ import annotations

import pytest

from sparring import combat_flow
from sparring.ai_medusa import Act
from sparring.combat_flow import CombatFlow, Phase
from sparring.effects import ops_combat
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_attack, human_hand
from test_e2_human_cards import put_adjacent
from test_effects_combat import mk, pair

from conftest import give

TIMINGS = ("immediately", "during", "after")
RANK = {"immediately": 0, "during": 1, "damage": 1.5, "after": 2}


def expected_log(atk_t: str, def_t: str, canceller: str | None = None) -> list[tuple[str, str]]:
    """The rule itself: sort by timing, the defender first on a tie, the damage between DURING and AFTER. A side that cancels
    at IMMEDIATELY stops the rival's effects that were not resolved yet (the rival's own IMMEDIATELY too, if it goes second)."""
    events = [(RANK[def_t], 0, def_t, "def"), (RANK[atk_t], 1, atk_t, "atk"), (RANK["damage"], 0, "damage", "-")]
    out, cancelled = [], None
    for _, _, moment, side in sorted(events):
        if side == cancelled:
            continue
        out.append((moment, side))
        if side == canceller and moment == "immediately":
            cancelled = "atk" if side == "def" else "def"
    return out


@pytest.fixture
def recorded(monkeypatch):
    """Replaces the interpreter's moment runner by a recorder: a side 'has' an effect only at its configured timing, which is
    logged when it resolves (and cancels the rival if it is the canceller). The combat damage is logged too."""
    log, cfg = [], {}

    def run_moment(flow, side, moment):
        if moment == cfg["timing"][side.name]:
            log.append((moment, side.name))
            if cfg.get("canceller") == side.name and moment == "immediately":
                flow.ctx.cancelled.add("atk" if side.name == "def" else "def")
        return None

    real_damage = combat_flow._HOOKS[Phase.DAMAGE]

    def damage(flow):
        log.append(("damage", "-"))
        real_damage(flow)

    monkeypatch.setattr(ops_combat, "run_moment", run_moment)
    monkeypatch.setitem(combat_flow._HOOKS, Phase.DAMAGE, damage)
    return log, cfg


def _fight(bprd, heroes=("liz-sherman", "hellboy")):
    g = mk(bprd, heroes, list(heroes))
    g.turn = 1
    lobster, liz = pair(g, "lobster", heroes[0].split("-")[0])
    return g, lobster, liz


# ---------------------------------------------------------------- 1. the matrix, engine only

@pytest.mark.parametrize("def_t", TIMINGS)
@pytest.mark.parametrize("atk_t", TIMINGS)
def test_the_effects_resolve_in_timing_order_and_the_defender_first_on_a_tie(bprd, recorded, atk_t, def_t):
    log, cfg = recorded
    cfg["timing"] = {"atk": atk_t, "def": def_t}
    g, lobster, liz = _fight(bprd)
    g.attack(lobster, liz, give(g, 1, "Service Pistol"), give(g, 0, "Evade"))
    assert log == expected_log(atk_t, def_t)
    assert log.index(("damage", "-")) == len([e for e in log if RANK[e[0]] < 1.5]), "damage after every DURING, before any AFTER"


@pytest.mark.parametrize("other_t", TIMINGS)
@pytest.mark.parametrize("canceller", ("atk", "def"))
def test_an_immediately_cancel_stops_what_the_rival_had_not_resolved(bprd, recorded, canceller, other_t):
    log, cfg = recorded
    victim = "atk" if canceller == "def" else "def"
    cfg["timing"], cfg["canceller"] = {canceller: "immediately", victim: other_t}, canceller
    g, lobster, liz = _fight(bprd)
    g.attack(lobster, liz, give(g, 1, "Service Pistol"), give(g, 0, "Evade"))
    assert log == expected_log(cfg["timing"]["atk"], cfg["timing"]["def"], canceller)
    survives = other_t == "immediately" and canceller == "atk"      # the defender's IMMEDIATELY went first, before the cancel
    assert ((other_t, victim) in log) == survives


# ---------------------------------------------------------------- 2. real cards, engine only

def test_second_shot_boost_is_settled_before_the_defenders_evade_draws(bprd):
    g, lobster, liz = _fight(bprd)
    shot = give(g, 1, "Second Shot")
    flow = CombatFlow(g, lobster, liz, shot, give(g, 0, "Evade"))
    hand, hp = len(g.players[0].hand) - 1, liz.hp           # the defense card has left the hand
    wait = flow.run()
    assert wait.choice.kind == "boost" and wait.choice.card_id == shot.card_id
    assert len(g.players[0].hand) == hand and liz.hp == hp and flow.phase is Phase.DURING, "no AFTER, no damage yet"
    flow.resume(None)
    assert flow.run() is None
    assert len(g.players[0].hand) == hand + 1, "Evade's AFTER ran once the DURING was over"


def test_two_free_boosts_are_asked_defender_first_and_both_before_any_after(bprd):
    g = mk(bprd, ("baba-yaga", "hellboy"), ["baba-yaga", "hellboy"])
    g.turn = 1
    lobster, baba = pair(g, "lobster", "baba")
    flow = CombatFlow(g, lobster, baba, give(g, 1, "Second Shot"), give(g, 0, "Out Of Time"))
    asked, actions = [], g.actions_left
    while (wait := flow.run()) is not None:
        asked.append((wait.choice.player, flow.phase))
        assert g.actions_left == actions, "Out Of Time's AFTER (end the turn) has not run"
        flow.resume(None)
    assert asked == [(0, Phase.DURING), (1, Phase.DURING)], "the defender's boost first, then the attacker's"
    assert g.actions_left == 0


def test_out_of_time_defends_its_boost_before_the_attackers_after_and_the_damage(bprd):
    g = mk(bprd, ("liz-sherman", "baba-yaga"), ["liz-sherman", "baba-yaga"])
    liz, baba = pair(g, "liz", "baba")
    flow = CombatFlow(g, liz, baba, give(g, 0, "B.P.R.D. Training"), give(g, 1, "Out Of Time"))
    hand, hp = len(g.players[0].hand) - 1, baba.hp          # Training has left the hand
    assert flow.run().choice.kind == "boost"
    assert len(g.players[0].hand) == hand and baba.hp == hp, "Training's draw waits for the boost"
    flow.resume(None)
    flow.run()
    assert len(g.players[0].hand) == hand + 1


def test_a_feint_at_immediately_leaves_no_boost_to_ask(bprd):
    g, lobster, liz = _fight(bprd)
    flow = CombatFlow(g, lobster, liz, give(g, 1, "Second Shot"), give(g, 0, "Feint"))
    assert flow.run() is None and flow.ctx.cancelled == {"atk"}


def test_same_timing_the_defenders_feint_resolves_first_and_cancels_the_attackers(bprd):
    g = mk(bprd, ("liz-sherman", "medusa"), ["liz-sherman", "medusa"])
    g.turn = 1
    medusa, liz = pair(g, "medusa", "liz")
    flow = CombatFlow(g, medusa, liz, give(g, 1, "Feint"), give(g, 0, "Feint"))
    assert flow.run() is None and flow.ctx.cancelled == {"atk"}


# ---------------------------------------------------------------- 3. the session, a human at the table

@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def _bot_defends(session, game, monkeypatch, title):
    chosen = next(c for c in game.players[0].hand if c.title == title)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: chosen)
    return chosen


def _human_boosts(session, table, game, title):
    boost = next(c for c in game.players[1].full_set if c.title == title and c.card_id in table.human_hand)
    table.human_hand.remove(boost.card_id)
    table.human_discard = [*table.human_discard, boost.card_id]
    table.human_count -= 1
    return click(session, table, Event.BOOST)


def _after_applied(msgs) -> bool:
    return any(m.startswith("Aplicado:") or m.startswith("Combate:") for m in msgs)


def _order(msgs, first: str, then: str) -> bool:
    """`first` was said, and `then` after it (a message each)."""
    at = [i for i, m in enumerate(msgs) if first in m]
    later = [i for i, m in enumerate(msgs) if then in m]
    return bool(at and later and at[0] < later[0])


@pytest.mark.parametrize("rig,attacker,foe,bot_card,boost", [
    (("hellboy", "medusa", ("Confront Any Demon or God", "Service Pistol", "Excalibur", "Right Hand Of Doom", "B.P.R.D. Training")),
     "medusa", "hellboy", "Confront Any Demon or God", "Gaze of Stone"),
    (("liz-sherman", "hellboy", ("Evade", "Rekindle", "Fireball", "Feint", "B.P.R.D. Training")),
     "lobster", "liz", "Evade", "Service Pistol"),
], indirect=["rig"], ids=["human-medusa-vs-bot-hellboy", "human-lobster-vs-bot-liz"])
def test_a_human_second_shot_boost_is_settled_before_the_bots_after(rig, monkeypatch, attacker, foe, bot_card, boost):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, attacker, foe)
    _bot_defends(session, game, monkeypatch, bot_card)
    human_hand(table, game, "Second Shot", boost, "Snipe" if attacker == "medusa" else "Excalibur")
    human_attack(session, table, game, attacker, foe, "Second Shot")
    hp = game.fighters[foe].hp
    before = click(session, table, Event.REVEAL)
    assert session.pending is not None and session.pending.boost_wait is not None, "the DURING boost is offered"
    assert not _after_applied(before) and game.fighters[foe].hp == hp, "nothing of the AFTER, no damage, yet"
    msgs = _human_boosts(session, table, game, boost)
    assert session.pending is None and game.fighters[foe].hp < hp
    assert _order(msgs, "Combate:", f"Aplicado: {bot_card}"), f"{bot_card}'s AFTER came after the combat line: {msgs}"


@pytest.mark.parametrize("rig", [("liz-sherman", "baba-yaga",
                                  ("B.P.R.D. Training", "Evade", "Pyrotechnics", "Rekindle", "Searing Clarity"))], indirect=True)
def test_a_human_out_of_time_boost_is_settled_before_the_bots_after_and_the_damage(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "koschei", "liz")
    human_hand(table, game, "Out Of Time", "Exploit", "Iron Teeth")
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")
    bot_turn(session, table, [Act("attack", fid="liz", target="koschei", card=training)])
    oot = card_ids(game, 1, "Out Of Time")[0]
    table.face_down = [{"id": oot, "guid": f"h{oot}"}]
    table.human_hand.remove(oot)
    table.human_count -= 1
    hp, actions = game.fighters["koschei"].hp, game.actions_left
    before = click(session, table, Event.REVEAL)
    assert session.pending is not None and session.pending.wait is not None and not _after_applied(before)
    assert game.fighters["koschei"].hp == hp and game.actions_left == actions, "paused at the DURING boost: nothing resolved yet"
    msgs = _human_boosts(session, table, game, "Exploit")
    assert _order(msgs, "Combate:", "Aplicado: B.P.R.D. Training"), f"Training's AFTER came after the combat line: {msgs}"
    assert game.fighters["koschei"].hp == hp, "5 against 5 with the boost: no damage"


@pytest.mark.parametrize("rig", [("hellboy", "medusa", ("Planned Recklessness", "Confront Any Demon or God", "Service Pistol",
                                                        "Excalibur", "B.P.R.D. Training"))], indirect=True)
def test_a_bot_immediately_cancel_leaves_the_humans_second_shot_without_its_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "medusa", "hellboy")
    _bot_defends(session, game, monkeypatch, "Planned Recklessness")
    human_hand(table, game, "Second Shot", "Gaze of Stone", "Snipe")
    human_attack(session, table, game, "medusa", "hellboy", "Second Shot")
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is None, "cancelled at IMMEDIATELY: no DURING boost to wait for, the combat is resolved"
    assert any(m.startswith("Combate:") and "potencia" not in m for m in msgs), msgs
