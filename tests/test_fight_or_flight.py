"""ONGOING de Fight Or Flight (Liz): +1 al valor de las cartas de combate de su dueno hasta el inicio de su siguiente
turno, en ataque y en defensa, acumulable, persistente y visible para la IA. El rig es de Hellboy: la carta de plan
Pancakes! hace de Fight Or Flight (mismo recurso que los tests de Flame Lash)."""
import json

from conftest import give, place
from sparring import persist
from sparring.ai_medusa import Act, MedusaAI, Model
from sparring.combat import FIGHT_OR_FLIGHT, resolve_scheme
from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_session import card, human_plays

HB, MED = 1, 0


def adjacent(game):
    place(game, medusa=0, hellboy=1, harpy1=20, harpy2=21, harpy3=22, lobster=27)
    return game.fighters["medusa"], game.fighters["hellboy"]


# ---------- motor ----------
def test_attack_with_the_bonus_adds_one_and_shows_it_in_the_breakdown(game):
    med, hb = adjacent(game)
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    pistol = give(game, HB, "Service Pistol")
    game.turn = HB
    res = game.attack(hb, med, pistol, None, values=(2, 0))
    assert res.atk_value == pistol.value + 1 + 2
    assert res.atk_parts == [f"Service Pistol ({pistol.value})", "Fight Or Flight (+1)", "valor extra (+2)"]


def test_defense_with_the_bonus_adds_one_even_to_a_zero_value_card_and_not_without_a_card(game):
    med, hb = adjacent(game)
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    snipe = give(game, MED, "Snipe")
    zero = next(c for c in game.players[HB].full_set if c.can_defend and not c.value)
    game.players[HB].hand.append(zero)
    res = game.attack(med, hb, snipe, zero, values=(0, 1))
    assert res.def_value == 0 + 1 + 1 and res.def_parts[-2:] == ["Fight Or Flight (+1)", "valor extra (+1)"]
    res = game.attack(med, hb, give(game, MED, "Snipe"), None)
    assert res.def_value == 0, "sin carta de defensa no hay valor al que sumar"


def test_second_copy_stacks_and_it_expires_only_at_the_owners_turn_start(game):
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    assert game.combat_bonus_parts(HB) == [(2, FIGHT_OR_FLIGHT)]
    game.turn = HB
    game.end_turn()
    assert game.begin_turn() == [] and game.turn == MED, "el turno del rival no lo caduca"
    assert game.combat_bonus_total(HB) == 2
    game.end_turn()
    assert game.begin_turn() == [(2, FIGHT_OR_FLIGHT)] and game.combat_bonus_total(HB) == 0


def test_a_bot_playing_it_gets_the_bonus_too(game):
    plan = card(game, HB, "Pancakes!")
    object.__setattr__(plan, "title", FIGHT_OR_FLIGHT)
    resolve_scheme(game, MED, game.hero(MED), plan)
    assert game.combat_bonus_total(MED) == 1


def test_clone_keeps_the_bonus_independent(game):
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    c = game.clone()
    c.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    assert game.combat_bonus_total(HB) == 1 and c.combat_bonus_total(HB) == 2


def test_other_hero_passives_still_add_up_with_it(game):
    med, hb = adjacent(game)
    game.players[HB].discard = [c for c in game.players[HB].full_set if c.destiny][:6]
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    assert game.attack_bonus_parts(hb) == [(2, "ANUNG UN RAMA"), (1, FIGHT_OR_FLIGHT)]


# ---------- guardado ----------
def test_resume_keeps_the_bonus_and_an_old_save_loads_zero(game):
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    data = json.loads(json.dumps(persist.game_to_dict(game)))
    fresh = game.clone()
    fresh.combat_bonus = [[], []]
    persist.apply_game(fresh, data)
    assert fresh.combat_bonus_parts(HB) == [(1, FIGHT_OR_FLIGHT)] and fresh.combat_bonus_total(MED) == 0
    del data["combat_bonus"]                      # guardado de antes de esta carta: sin la clave
    persist.apply_game(fresh, data)
    assert fresh.combat_bonus == [[], []]
    assert "combat_bonus" not in persist.game_to_dict(fresh)


# ---------- IA ----------
def test_the_model_sees_the_rivals_defense_and_attack_bonus(game):
    med, hb = adjacent(game)
    defense = lambda: {round(p, 9): v for p, v in Model(game, MED).defense_dist(hb) if v is not None}
    attack = lambda: [v for _, v in Model(game, MED).attack_dist(hb) if v is not None]
    d0, a0 = defense(), attack()
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    assert defense() == {p: v + 1 for p, v in d0.items()}
    assert sorted(attack()) == sorted(v + 1 for v in a0)


def test_the_bot_attack_evaluation_drops_when_the_rival_defends_with_the_bonus(game):
    med, hb = adjacent(game)
    game.turn = MED
    game.players[HB].hand[:] = [c for c in game.players[HB].full_set if c.can_defend and c.value][:4]
    ai = MedusaAI(MED)
    snipe = give(game, MED, "Snipe")
    base = ai.attack_eval(game, Model(game, MED), med, hb, snipe)[0]
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)
    assert ai.attack_eval(game, Model(game, MED), med, hb, snipe)[0] < base


# ---------- sesion ----------
def play_plan(session, table, game):
    plan = card(game, HB, "Pancakes!")
    object.__setattr__(plan, "title", FIGHT_OR_FLIGHT)
    object.__setattr__(plan, "text", "ONGOING: Add +1 to the value of your combat cards.")
    click(session, table, Event.SCHEME)
    table.human_discard = [plan.card_id]              # el humano deja el plan en la mesa despues de pulsar Plan
    return plan, click(session, table, Event.END_ACTION)


def test_playing_the_plan_announces_and_the_human_attack_shows_the_part(brig):  # noqa: F811
    session, table, game, fake = brig
    plan, msgs = play_plan(session, table, game)
    assert game.combat_bonus_total(HB) == 1
    assert any("Fight Or Flight" in m and "+1 a tus cartas de combate hasta el inicio de tu siguiente turno" in m
               for m in msgs), msgs
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Service Pistol")
    msgs = click(session, table, Event.REVEAL)
    combat = next(m for m in msgs if m.startswith("Combate"))
    assert "Fight Or Flight (+1)" in combat, combat


def test_the_bonus_lasts_through_the_bot_turn_and_expires_with_a_notice(brig, monkeypatch):  # noqa: F811
    session, table, game, fake = brig
    play_plan(session, table, game)
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    during = []
    orig = game.end_turn
    monkeypatch.setattr(game, "end_turn", lambda: (during.append(game.combat_bonus_total(HB)), orig()))
    game.actions_left = 0
    msgs = click(session, table, Event.END_ACTION)
    assert game.turn == HB and game.combat_bonus_total(HB) == 0
    assert during and during[-1] == 1, "seguia viva al terminar el turno del bot"
    assert any("caduca el +1" in m for m in session.messages + msgs)


def test_session_resume_keeps_the_live_bonus(brig):  # noqa: F811
    session, table, game, fake = brig
    play_plan(session, table, game)
    saved = json.loads(json.dumps(session.to_dict()))
    game.combat_bonus = [[], []]
    session.load_dict(saved)
    assert game.combat_bonus_total(HB) == 1
    del saved["game"]["combat_bonus"]
    session.load_dict(saved)
    assert game.combat_bonus_total(HB) == 0


def test_second_shot_boost_and_on_earth_still_work_with_the_bonus(game, ctl):
    med, hb = adjacent(game)
    game.add_combat_bonus(MED, 1, FIGHT_OR_FLIGHT)           # el bonus del atacante suma al valor base
    ss, gaze = give(game, MED, "Second Shot"), give(game, MED, "Gaze of Stone")
    ctl[MED].boost = gaze
    glimpse = give(game, HB, "Glimpse Of Hell")              # versatil de valor 2
    res = game.attack(med, hb, ss, def_card=glimpse)
    assert res.atk_value == 7 + 1 and res.boost_card is gaze and res.damage == 6
    ctl[MED].boost = None
    game.add_combat_bonus(HB, 1, FIGHT_OR_FLIGHT)            # y el defensor tambien suma sobre el valor de On Earth
    game.players[HB].discard = [c for c in game.players[HB].full_set if c.destiny][:4]
    oe = give(game, HB, "On Earth As It Is In Hell")
    res = game.attack(med, hb, give(game, MED, "Second Shot", 1), def_card=oe)
    assert res.def_value == 4 + 1
