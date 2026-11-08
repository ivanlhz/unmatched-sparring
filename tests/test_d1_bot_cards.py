"""D1: the bot plays Hellboy, Abe Sapien, Baba Yaga and Liz Sherman's combat cards through the effects interpreter.

The bot's box hero is interpreted by default (`INTERPRETED_HEROES`; since E2 the human's too, in table mode:
tests/test_e2_human_cards.py). Every combat card of the four heroes is played here by the bot
(player 0) and checked on the game state and on the chat line the bot says (`result.applied`, Spanish). Also:
Ivan's rulings on the bot's side, the anti-cheat tripwire (no evaluation clone ever touches the human's hand), the
save format and the review notes of C5 / E1 / D1-prep (presets used once, attacker's stake, clones without the
panel's choosers)."""
from __future__ import annotations

import json
import random

import pytest

from conftest import Scripted, give, place
from sparring import persist
from sparring.ai_effects import EffectAI, blind_clone
from sparring.ai_medusa import MedusaAI
from sparring.combat_flow import CombatFlow, Phase
from sparring.effects import ongoing
from sparring.effects.choose import ChoiceRequest, worth_paying
from sparring.effects.ops_core import _cost_context
from sparring.effects.run import Ctx, EffectRun
from sparring.effects.state import INTERPRETED_HEROES, default_dsl_heroes
from sparring.search.adapter import card_worth
from sparring.spaces import describe
from sparring.state import Game
from test_effects_combat import Asking, hand_filler, hp, pair
from test_effects_info import HandSpy, set_hand


def at(g, space, fid):
    return describe(g, space, (fid,))


def mk(bprd, bot, human, seed=3):
    """Bot = player 0 with `bot`, human = player 1; bot's turn, empty hands. Nothing forces `fx.dsl_heroes`: the
    default of D1 is what is tested."""
    ctl = {0: Asking(), 1: Asking()}
    g = Game.new(bprd, seed, controllers=ctl, heroes=(bot, human), bot_player=0)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def fight(g, att, tgt, atk_title, def_title=None, values=(0, 0), boost=None):
    a, t = g.fighters[att], g.fighters[tgt]
    return g.attack(a, t, give(g, a.owner, atk_title), give(g, t.owner, def_title) if def_title else None, values, boost)


def zone_spots(g, of):
    """Free spaces of `of`'s zone, lowest first."""
    ref = g.fighters[of].pos
    taken = {f.pos for f in g.fighters.values() if f.alive}
    return [s for s in sorted(g.board.spaces) if s not in taken and g.board.share_zone(ref, s)]


def zone_mate(g, fid, of, adjacent=None):
    """Puts `fid` on a free space of `of`'s zone (adjacent to it, or not, when asked). Returns the space."""
    ref = g.fighters[of].pos
    spots = [s for s in zone_spots(g, of) if adjacent is None or g.board.adjacent(ref, s) == adjacent]
    g.fighters[fid].pos = spots[0]
    return spots[0]


def free_adjacent(g, space, avoid=()):
    taken = {f.pos for f in g.fighters.values() if f.alive} | set(avoid)
    return next(s for s in sorted(g.board.adj[space]) if s not in taken)


def far_from(g, *fids):
    taken = {f.pos for f in g.fighters.values() if f.alive}
    return max((s for s in g.board.spaces if s not in taken),
               key=lambda s: (min(g.board.distance(s, g.fighters[f].pos) for f in fids), -s))


def kill(g, fid):
    f = g.fighters[fid]
    f.died_at, f.alive, f.pos, f.hp = f.pos, False, None, 0


def to_discard(g, player, *titles):
    out = []
    for t in titles:
        c = next(c for c in g.players[player].deck if c.title == t)
        g.players[player].deck.remove(c)
        g.players[player].discard.append(c)
        out.append(c)
    return out


# ---------------------------------------------------------------- the switch

def test_the_box_heroes_and_medusa_are_interpreted_for_both_sides(bprd):
    assert INTERPRETED_HEROES == {"medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman", "leonardo", "donatello", "michelangelo", "raphael", "doctor-strange", "houdini", "bigfoot", "daredevil", "luke-cage", "bullseye", "golden-bat", "jill-trent"}
    g = mk(bprd, "liz-sherman", "hellboy")
    assert g.fx.dsl_heroes == {"liz-sherman", "hellboy"} and g.clone().fx.dsl_heroes == {"liz-sherman", "hellboy"}
    g = Game.new(bprd, 3, controllers={}, heroes=("hellboy", "medusa"), bot_player=1)      # bot in seat 1
    assert g.fx.dsl_heroes == {"hellboy", "medusa"} and default_dsl_heroes(g) == g.fx.dsl_heroes


def test_an_old_save_of_a_box_bot_loads_interpreted_and_an_explicit_off_stays_off(bprd):
    g = mk(bprd, "liz-sherman", "hellboy")
    saved = json.loads(json.dumps(persist.game_to_dict(g)))
    assert "fx" not in saved or "dsl_heroes" not in saved["fx"]           # the default is never written
    loaded = Game.new(bprd, 0, controllers={}, heroes=("liz-sherman", "hellboy"))
    persist.apply_game(loaded, saved)
    assert loaded.fx.dsl_heroes == {"liz-sherman", "hellboy"}
    g.fx.dsl_heroes = set()
    assert persist.game_to_dict(g)["fx"]["dsl_heroes"] == []
    persist.apply_game(loaded, persist.game_to_dict(g))
    assert loaded.fx.dsl_heroes == set()


def test_clones_never_inherit_the_live_choosers(bprd):
    """E1 review: search clones and simulations decide with their own controllers, never with the human's panel."""
    from sparring.effects.choose import PanelChooser
    g = mk(bprd, "abe-sapien", "hellboy")
    g.fx.choosers = {0: PanelChooser(), 1: PanelChooser()}
    assert g.clone().fx.choosers is None
    g.fx.statuses.append({"name": "cannot_draw", "owner": 0, "player": 1, "until": {"event": "end_of_turn"}, "amount": 0, "label": ""})
    assert g.clone().fx.choosers is None and blind_clone(g, 0, random.Random(0)).fx.choosers is None


# ---------------------------------------------------------------- Hellboy

def test_hellboy_cards_without_text_say_nothing(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    pair(g, "hellboy", "liz")
    for title in ("Excalibur", "Service Pistol"):
        res = fight(g, "hellboy", "liz", title)
        assert res.applied == [] and res.bot_notes == [] and res.human_effects == []


def test_right_hand_of_doom_moves_an_adjacent_fighter_and_hellboy_as_detective(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    hb, liz = pair(g, "hellboy", "liz")
    liz_home = liz.pos
    dest = free_adjacent(g, liz.pos, avoid=(hb.pos,))
    g.controllers[0].moves = {"liz": dest, "hellboy": liz_home}     # Hellboy takes the space Liz leaves
    res = fight(g, "hellboy", "liz", "Right Hand Of Doom")
    assert liz.pos == dest and hb.pos == liz_home
    assert res.applied == [f"Right Hand Of Doom: hellboy se mueve a {at(g, liz_home, 'hellboy')}; liz se mueve a {at(g, dest, 'liz')}"]


def test_right_hand_of_doom_as_anung_un_rama_moves_only_the_adjacent_fighter(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    hb, liz = pair(g, "hellboy", "liz")
    to_discard(g, 0, *[c.title for c in g.players[0].deck if c.destiny][:6])
    assert g.form(0) == "ANUNG UN RAMA"
    home = hb.pos
    dest = free_adjacent(g, liz.pos, avoid=(home,))
    g.controllers[0].moves = {"liz": dest, "hellboy": liz.pos}
    res = fight(g, "hellboy", "liz", "Right Hand Of Doom")
    assert liz.pos == dest and hb.pos == home
    assert res.applied == [f"Right Hand Of Doom: liz se mueve a {at(g, dest, 'liz')}"]


def test_horseshoes_hits_every_other_fighter_in_the_zone_own_included(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    hb, liz = pair(g, "hellboy", "liz")
    zone_mate(g, "liz", "hellboy", adjacent=True)
    zone_mate(g, "lobster", "hellboy")
    res = fight(g, "hellboy", "liz", "Horseshoes And Hand Grenades")
    assert res.damage == 2 and liz.hp == 16 - 2 - 1 and g.fighters["lobster"].hp == 5
    assert res.applied == ["Horseshoes And Hand Grenades: lobster -1 PV (5); liz -1 PV (13)"]


def test_second_shot_boost_is_asked_to_the_bots_controller(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    pair(g, "lobster", "liz")
    pistol = give(g, 0, "Service Pistol")
    g.controllers[0].boost = pistol
    res = fight(g, "lobster", "liz", "Second Shot")
    assert res.atk_value == 2 + pistol.boost and res.boost_card is pistol and pistol in g.players[0].discard
    assert res.atk_parts == ["Second Shot (2)", "potencia con Service Pistol (+2)"] and res.applied == []


def test_confront_lost_draws_looks_at_the_hand_and_discards_the_best_card(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    pair(g, "hellboy", "liz")
    theirs = [give(g, 1, "Pyrotechnics"), give(g, 1, "Rekindle")]       # no burning card: Wildfire would take it back
    res = fight(g, "hellboy", "liz", "Confront Any Demon or God", "Evade")        # 3 vs 3: lost
    assert not res.attacker_won and len(g.players[0].hand) == 1
    gone = next(c for c in g.players[1].discard if c.title != "Evade")
    seen = {c for c in theirs + g.players[1].hand + [gone] if c.title != "Evade"}    # what the look showed: Evade's
    assert card_worth(gone) == max(map(card_worth, seen)) and len(g.players[1].hand) == 2   # draw (E2) included
    assert [c.card_id for c in g.players[0].known.cards(g.players[1])] == [c.card_id for c in g.players[1].hand]
    assert res.applied == [f"Confront Any Demon or God: roba 1; descartas {gone.title}; mira tu mano"]


def test_confront_won_only_draws(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    pair(g, "hellboy", "liz")
    give(g, 1, "Fireball")
    res = fight(g, "hellboy", "liz", "Confront Any Demon or God")
    assert res.attacker_won and g.players[0].known.is_empty() and len(g.players[1].hand) == 1
    assert res.applied == ["Confront Any Demon or God: roba 1"]


def test_glimpse_of_hell_draws_two_and_shuffles_one_back_unnamed(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    hb, liz = pair(g, "hellboy", "liz")
    give(g, 0, "Service Pistol")
    glimpse = give(g, 0, "Glimpse Of Hell")
    deck = len(g.players[0].deck)
    res = g.attack(hb, liz, glimpse, None)
    assert len(g.players[0].hand) == 2 and len(g.players[0].deck) == deck - 1
    assert res.applied == ["Glimpse Of Hell: roba 2; devuelve 1 carta de la mano al mazo"]


def test_bprd_training_draws_and_moves_each_friendly_fighter(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    hb, liz = pair(g, "hellboy", "liz")
    lob = g.fighters["lobster"]
    x = free_adjacent(g, hb.pos, avoid=(liz.pos,))
    y = free_adjacent(g, lob.pos, avoid=(x,))
    g.controllers[0].moves = {"hellboy": x, "lobster": y}
    res = fight(g, "hellboy", "liz", "B.P.R.D. Training")
    assert (hb.pos, lob.pos) == (x, y) and len(g.players[0].hand) == 1
    assert res.applied == [f"B.P.R.D. Training: hellboy se mueve a {at(g, x, 'hellboy')}; lobster se mueve a {at(g, y, 'lobster')}; roba 1"]


@pytest.mark.parametrize("anung", [False, True])
def test_planned_recklessness_shields_own_fighters_and_cancels_only_as_detective(bprd, anung):
    g = mk(bprd, "hellboy", "liz-sherman")
    hb, liz = pair(g, "hellboy", "liz")
    if anung:
        to_discard(g, 0, *[c.title for c in g.players[0].deck if c.destiny][:6])
    g.turn = 1
    res = fight(g, "liz", "hellboy", "Fireball", "Planned Recklessness")
    assert ("atk" in res.cancelled) is not anung and res.damage == 5 - 3
    assert g.damage(hb, 1) == 0 and g.damage(g.fighters["lobster"], 1) == 0        # effect damage is shielded
    expected = "Planned Recklessness: hellboy no recibe dano de efectos este turno; lobster no recibe dano de efectos este turno"
    assert res.applied == [expected + ("" if anung else "; cancela los efectos de Fireball")]


def test_posthumous_power_resolves_the_chosen_option(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    lob, liz = pair(g, "lobster", "liz")
    g.controllers[0].queue = [[1], ["liz"]]                          # deal 1 damage, to Liz
    res = fight(g, "lobster", "liz", "Posthumous Power")
    assert liz.hp == 16 - 2 - 1 and res.applied == ["Posthumous Power: liz -1 PV (13)"]
    g = mk(bprd, "hellboy", "liz-sherman")
    lob, liz = pair(g, "lobster", "liz")
    g.fighters["hellboy"].hp, lob.hp = 10, 5
    g.controllers[0].queue = [[0]]                                   # each friendly fighter recovers 1
    res = fight(g, "lobster", "liz", "Posthumous Power")
    assert hp(g, "hellboy", "lobster") == [11, 6]
    assert res.applied == ["Posthumous Power: hellboy recupera 1 PV (11); lobster recupera 1 PV (6)"]


def test_on_earth_in_defense_takes_the_destiny_count_and_heals_two_when_lost(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    hb, liz = pair(g, "hellboy", "liz")
    to_discard(g, 0, *[c.title for c in g.players[0].deck if c.destiny][:3])
    hb.hp = 10
    g.turn = 1
    res = fight(g, "liz", "hellboy", "Fireball", "On Earth As It Is In Hell")
    assert res.def_value == 3 and res.damage == 2 and hb.hp == 10
    assert res.applied == ["On Earth As It Is In Hell: el valor de On Earth As It Is In Hell pasa a 3",
                           "On Earth As It Is In Hell: hellboy recupera 2 PV (10)"]


def test_hellboy_schemes_run_through_the_interpreter_for_the_bot(bprd):
    g = mk(bprd, "hellboy", "liz-sherman")
    crown = give(g, 0, "And Upon His Brow Is Set A Crown Of Flame")
    give(g, 0, "Service Pistol")
    assert g.play_scheme(0, g.hero(0), crown) is None
    assert len(g.players[0].hand) == 2 and g.actions_left == 2 + 2 - 1
    pancakes = give(g, 0, "Pancakes!")
    g.fighters["hellboy"].hp = 10
    g.controllers[0].queue = [[0], [2]]                               # recover 2, draw 2
    g.play_scheme(0, g.hero(0), pancakes)
    assert g.fighters["hellboy"].hp == 12 and len(g.players[0].hand) == 4


# ---------------------------------------------------------------- Abe Sapien

def abe_game(bprd, human="hellboy"):
    g = mk(bprd, "abe-sapien", human)
    abe, foe = pair(g, "abe", g.hero(1).fid)
    return g, abe, foe


def test_faster_stronger_moves_abe_at_once_and_gains_an_action_after(bprd):
    g, abe, hb = abe_game(bprd)
    x = free_adjacent(g, abe.pos, avoid=(hb.pos,))
    g.controllers[0].moves = {"abe": x}
    res = fight(g, "abe", "hellboy", "Faster. Stronger.")
    assert abe.pos == x and g.actions_left == 2 and res.damage == 5
    assert res.applied == [f"Faster. Stronger.: abe se mueve a {at(g, x, 'abe')}", "Faster. Stronger.: gana 1 accion"]


def test_advanced_psychometry_looks_only_when_the_rival_is_adjacent(bprd):
    g, abe, hb = abe_game(bprd)
    give(g, 1, "Service Pistol")
    res = fight(g, "abe", "hellboy", "Advanced Psychometry")
    assert len(g.players[0].known.seen) == 1 and res.applied == ["Advanced Psychometry: mira tu mano"]
    g, abe, hb = abe_game(bprd)
    zone_mate(g, "hellboy", "abe", adjacent=False)                    # same zone, not adjacent: Abe is ranged
    assert not g.board.adjacent(abe.pos, hb.pos)
    res = fight(g, "abe", "hellboy", "Advanced Psychometry")
    assert g.players[0].known.is_empty() and res.applied == ["Advanced Psychometry: sin efecto"]


def test_perfect_shot_is_played_face_down_until_e3_and_a_recorded_prediction_adds_two(bprd):
    g, abe, hb = abe_game(bprd)
    res = fight(g, "abe", "hellboy", "Perfect Shot", "Confront Any Demon or God")
    assert res.atk_value == 3 and res.applied == ["Perfect Shot: sin efecto"]
    g, abe, hb = abe_game(bprd)
    shot, confront = give(g, 0, "Perfect Shot"), give(g, 1, "Confront Any Demon or God")
    flow = CombatFlow(g, abe, hb, shot, confront)
    while flow.phase is not Phase.DURING:
        flow.step()
    flow.runs["immediately:atk"].flags["prediction"] = confront.value      # what E3 will record at play time
    assert flow.run() is None and flow.result.atk_value == 5
    assert flow.result.atk_parts == ["Perfect Shot (3)", "Perfect Shot (+2)"]


def test_secure_the_scene_revives_a_defeated_agent_in_abes_zone_then_moves_a_friend(bprd):
    g, abe, hb = abe_game(bprd)
    zone_mate(g, "agent1", "hellboy", adjacent=True)
    kill(g, "agent3")
    spot = zone_spots(g, "abe")[-1]
    x = free_adjacent(g, abe.pos, avoid=(hb.pos, spot))
    g.controllers[0].queue = [[spot], ["abe"]]                        # revive there; then Abe is the friend who moves
    g.controllers[0].moves = {"abe": x}
    res = fight(g, "agent1", "hellboy", "Secure The Scene")
    a3 = g.fighters["agent3"]
    assert a3.alive and a3.hp == 1 and a3.pos == spot and abe.pos == x
    assert res.applied == [f"Secure The Scene: abe se mueve a {at(g, x, 'abe')}; agent3 vuelve al tablero en {at(g, spot, 'agent3')} con 1 PV"]


def test_secure_the_scene_without_a_defeated_agent_places_a_living_one(bprd):
    g, abe, hb = abe_game(bprd)
    zone_mate(g, "agent1", "hellboy", adjacent=True)
    a2 = g.fighters["agent2"]
    spot = zone_spots(g, "abe")[0]
    g.controllers[0].queue = [["agent2"], [spot], ["abe"]]            # place agent2 there, then move Abe (stays)
    res = fight(g, "agent1", "hellboy", "Secure The Scene")
    assert a2.pos == spot and res.applied == [f"Secure The Scene: agent2 se mueve a {at(g, spot, 'agent2')}"]


def test_leap_away_moves_a_combatant_only_when_won(bprd):
    g, abe, hb = abe_game(bprd)
    dest = max(g.legal_moves(hb, 4, False), key=lambda s: (g.board.distance(s, abe.pos), -s))
    g.controllers[0].queue = [["hellboy"]]
    g.controllers[0].moves = {"hellboy": dest}
    res = fight(g, "abe", "hellboy", "Leap Away")
    assert res.attacker_won and hb.pos == dest and g.board.distance(dest, abe.pos) > 1
    assert res.applied == [f"Leap Away: hellboy se mueve a {at(g, dest, 'hellboy')}"]
    g, abe, hb = abe_game(bprd)
    home = hb.pos
    g.controllers[0].queue = [["hellboy"]]
    res = fight(g, "abe", "hellboy", "Leap Away", values=(0, 5))
    assert not res.attacker_won and hb.pos == home and res.applied == ["Leap Away: sin efecto"]


def test_concussion_device_hits_an_adjacent_enemy_and_pushes_it(bprd):
    g, abe, hb = abe_game(bprd)
    far = free_adjacent(g, hb.pos, avoid=(abe.pos,))
    g.controllers[0].moves = {"hellboy": far}
    res = fight(g, "abe", "hellboy", "Concussion Device")
    assert hb.hp == 18 - 2 - 2 and hb.pos == far
    assert res.applied == [f"Concussion Device: hellboy -2 PV (14); hellboy se mueve a {at(g, far, 'hellboy')}"]


def test_arcane_dampener_in_defense_subtracts_three_from_the_adjacent_attacker(bprd):
    g, abe, hb = abe_game(bprd)
    g.turn = 1
    res = fight(g, "hellboy", "abe", "Service Pistol", "Arcane Dampener")
    assert res.atk_value == 2 and res.damage == 0
    assert res.applied == ["Arcane Dampener: valor de Service Pistol -3"]


def test_abes_bprd_training_moves_the_agents_that_want_to_move(bprd):
    g, abe, hb = abe_game(bprd)
    x = free_adjacent(g, abe.pos, avoid=(hb.pos,))
    g.controllers[0].moves = {"abe": x}
    res = fight(g, "abe", "hellboy", "B.P.R.D. Training")
    assert abe.pos == x and len(g.players[0].hand) == 1
    assert res.applied == [f"B.P.R.D. Training: abe se mueve a {at(g, x, 'abe')}; roba 1"]


def test_shock_and_awe_becomes_four_after_moving_and_the_rival_discards(bprd):
    g, abe, hb = abe_game(bprd)                                       # pair() moved Abe after begin_turn
    theirs = [give(g, 1, "Service Pistol"), give(g, 1, "Glimpse Of Hell")]
    res = fight(g, "abe", "hellboy", "Shock And Awe")
    assert res.atk_value == 4 and len(g.players[1].hand) == 1
    gone = next(c for c in theirs if c in g.players[1].discard)
    assert res.applied == ["Shock And Awe: el valor de Shock And Awe pasa a 4", f"Shock And Awe: descartas {gone.title}"]
    g, abe, hb = abe_game(bprd)
    g.fx.turn_start_pos["abe"] = abe.pos
    res = fight(g, "abe", "hellboy", "Shock And Awe")                 # no move, and nothing to discard
    assert res.atk_value == 2 and res.applied == ["Shock And Awe: sin efecto"]


def test_cold_iron_blocks_the_rivals_draws_and_actions(bprd):
    g, abe, hb = abe_game(bprd)
    res = fight(g, "abe", "hellboy", "Cold Iron And Holy Water")
    assert not g.fx.can_draw(1) and not g.fx.can_gain_actions(1) and g.fx.can_draw(0)
    assert res.applied == ["Cold Iron And Holy Water: no ganas acciones este turno; no robas cartas este turno"]


def test_ward_and_prepare_cancels_the_attack_and_recovers_a_scheme(bprd):
    g, abe, hb = abe_game(bprd)
    shield, = to_discard(g, 0, "Counterhex Shield")
    g.turn = 1
    res = fight(g, "hellboy", "abe", "Horseshoes And Hand Grenades", "Ward And Prepare")
    assert res.cancelled == {"atk"} and shield in g.players[0].hand and res.human_effects == []
    assert res.applied == ["Ward And Prepare: cancela los efectos de Horseshoes And Hand Grenades",
                           "Ward And Prepare: Counterhex Shield vuelve a su mano"]


def test_counterhex_in_play_stops_the_humans_legacy_effect_damage(bprd):
    g, abe, hb = abe_game(bprd)
    ongoing.enter_play(g, 0, give(g, 0, "Counterhex Shield"))
    zone_mate(g, "abe", "hellboy", adjacent=True)
    g.turn = 1
    res = fight(g, "hellboy", "abe", "Horseshoes And Hand Grenades")
    assert abe.hp == 13 - 2 and any("Horseshoes" in line for line in res.human_effects)      # combat damage only


def test_a_preset_answers_the_first_pick_only(bprd):
    """C5 review: B.P.R.D. Utility Belt heals one friend and moves one; the planned target is the heal, the move is
    the chooser's."""
    g, abe, hb = abe_game(bprd)
    abe.hp, g.fighters["agent1"].hp = 10, 1
    y = free_adjacent(g, abe.pos, avoid=(hb.pos,))
    g.controllers[0].queue = [["abe"]]                                # the move: asked, not forced to the preset
    g.controllers[0].moves = {"abe": y}
    assert g.play_scheme(0, abe, give(g, 0, "B.P.R.D. Utility Belt"), target=abe) is None
    assert abe.hp == 11 and abe.pos == y and g.actions_left == 2


# ---------------------------------------------------------------- Baba Yaga

def baba_game(bprd, koschei_in_zone=True):
    g = mk(bprd, "baba-yaga", "liz-sherman")
    baba, liz = pair(g, "baba", "liz")
    if koschei_in_zone:
        zone_mate(g, "koschei", "baba")
    return g, baba, liz


def with_pact(g, title="Pact Of Time"):
    pact = give(g, 0, title)
    ongoing.enter_play(g, 0, pact)
    return pact


def test_the_time_for_deals_hits_everyone_in_the_zone_and_discards_the_pact(bprd):
    g, baba, liz = baba_game(bprd)
    zone_mate(g, "liz", "baba", adjacent=True)
    pact = with_pact(g)
    res = fight(g, "baba", "liz", "The Time For Deals Is Done")
    assert liz.hp == 16 - 5 - 2 and g.fighters["koschei"].hp == 1
    assert g.fx.ongoing_card_id(0) is None and pact in g.players[0].discard
    assert res.applied == ["The Time For Deals Is Done: koschei -2 PV (1); liz -2 PV (9); descarta Pact Of Time"]


def test_iron_teeth_bites_an_adjacent_fighter_and_heals_with_a_pact(bprd):
    g, baba, liz = baba_game(bprd, koschei_in_zone=False)
    baba.hp = 10
    with_pact(g)
    res = fight(g, "baba", "liz", "Iron Teeth")
    assert liz.hp == 16 - 4 - 1 and baba.hp == 12
    assert res.applied == ["Iron Teeth: baba recupera 2 PV (12); liz -1 PV (11)"]


@pytest.mark.parametrize("pays", [True, False])
def test_remove_a_painful_memory_lets_the_rival_discard_or_take_two(bprd, pays):
    g, baba, liz = baba_game(bprd, koschei_in_zone=False)
    with_pact(g)
    theirs = [give(g, 1, "Pyrotechnics"), give(g, 1, "Rekindle")]       # no burning card: Wildfire would take it back
    g.controllers[1].queue = [[pays]]
    res = fight(g, "baba", "liz", "Remove A Painful Memory")
    best = max(theirs, key=card_worth)
    if pays:
        assert best in g.players[1].discard and liz.hp == 16 - 4
        assert res.applied == [f"Remove A Painful Memory: descartas {best.title}; mira tu mano"]
    else:
        assert best in g.players[1].hand and liz.hp == 16 - 4 - 2
        assert res.applied == ["Remove A Painful Memory: liz -2 PV (10); mira tu mano"]


def test_deaths_release_heals_koschei_and_places_him_anywhere(bprd):
    g, baba, liz = baba_game(bprd)
    kos = g.fighters["koschei"]
    g.fighters["koschei"].pos = free_adjacent(g, liz.pos, avoid=(baba.pos,))
    kos.hp = 1
    far = far_from(g, "liz")
    g.controllers[0].placement = far
    res = fight(g, "koschei", "liz", "Death's Release")
    assert kos.hp == 3 and kos.pos == far
    assert res.applied == [f"Death's Release: koschei recupera 2 PV (3); koschei se mueve a {at(g, far, 'koschei')}"]


def test_read_the_bones_takes_the_best_of_the_top_five_and_hides_the_rest_at_the_bottom(bprd):
    g, baba, liz = baba_game(bprd)
    bones = give(g, 0, "Read The Bones")
    deck = list(g.players[0].deck)
    res = g.attack(baba, liz, bones, None)
    kept = max(deck[:5], key=card_worth)
    assert g.players[0].hand == [kept] and len(g.players[0].deck) == len(deck) - 1
    assert set(g.players[0].deck[-4:]) == set(deck[:5]) - {kept} and g.players[0].deck[:-4] == deck[5:]
    assert res.applied == ["Read The Bones: 1 carta del mazo a su mano"]


def test_foul_journey_places_a_combatant_anywhere_and_heals_with_a_pact(bprd):
    g, baba, liz = baba_game(bprd)
    baba.hp = 10
    with_pact(g)
    far = far_from(g, "baba")
    g.controllers[0].queue = [["liz"]]
    g.controllers[0].placement = far
    res = fight(g, "baba", "liz", "Foul Journey")
    assert liz.pos == far and baba.hp == 11
    assert res.applied == [f"Foul Journey: baba recupera 1 PV (11); liz se mueve a {at(g, far, 'liz')}"]


def test_hasten_towards_death_as_attack_hurts_the_attacker_and_fateful_bargains_passes_it_to_koschei(bprd):
    g, baba, liz = baba_game(bprd)
    res = fight(g, "baba", "liz", "Hasten Towards Death")
    assert hp(g, "baba", "koschei") == [13, 2] and g.actions_left == 2
    assert res.applied == ["Hasten Towards Death: koschei -1 PV (2); gana 1 accion"]


def test_hasten_towards_death_in_defense_hurts_the_human_attacker_who_gains_the_action(bprd):
    g, baba, liz = baba_game(bprd, koschei_in_zone=False)
    g.turn = 1
    res = fight(g, "liz", "baba", "Fireball", "Hasten Towards Death")
    assert liz.hp == 15 and g.actions_left == 2 and res.damage == 1
    assert res.applied == ["Hasten Towards Death: liz -1 PV (15); ganas 1 accion"]


def test_out_of_time_boosts_from_the_bots_hand_on_either_side_and_ends_the_turn(bprd):
    g, baba, liz = baba_game(bprd)
    exploit = give(g, 0, "Exploit")
    g.controllers[0].boost = exploit
    res = fight(g, "baba", "liz", "Out Of Time")
    assert res.atk_value == 2 + 3 and exploit in g.players[0].discard and g.actions_left == 0
    assert res.applied == ["Out Of Time: termina el turno"]
    g, baba, liz = baba_game(bprd)
    exploit = give(g, 0, "Exploit")
    g.controllers[0].boost = exploit
    g.turn = 1
    res = fight(g, "liz", "baba", "Fireball", "Out Of Time")
    assert res.def_value == 2 + 3 and res.damage == 0 and exploit in g.players[0].discard
    assert g.actions_left == 0 and g.turn == 1                        # the human's turn is cut short


def test_the_heuristic_bot_boosts_out_of_time_in_defense_when_it_saves_enough(bprd):
    g, baba, liz = baba_game(bprd)
    g.controllers[0] = MedusaAI(0)
    exploit = give(g, 0, "Exploit")                                    # boost 3 against a 7-2 = 5 hit
    g.turn = 1
    res = fight(g, "liz", "baba", "Incinerate", "Out Of Time")
    assert res.boost_card is None and exploit in g.players[0].discard and res.def_value == 5 and res.damage == 2


@pytest.mark.parametrize("dead", [True, False])
def test_deathless_brings_koschei_next_to_baba_with_three_health(bprd, dead):
    g, baba, liz = baba_game(bprd, koschei_in_zone=False)
    kos = g.fighters["koschei"]
    if dead:
        kill(g, "koschei")
    else:
        kos.hp = 1
    res = fight(g, "baba", "liz", "Deathless")
    assert kos.alive and kos.hp == 3 and g.board.distance(baba.pos, kos.pos) == 1
    said = (f"koschei vuelve al tablero en {at(g, kos.pos, 'koschei')} con 3 PV" if dead
            else f"koschei recupera 2 PV (3); koschei se mueve a {at(g, kos.pos, 'koschei')}")
    assert res.applied == [f"Deathless: {said}"]


def test_exploit_draws_one(bprd):
    g, baba, liz = baba_game(bprd)
    res = fight(g, "baba", "liz", "Exploit")
    assert len(g.players[0].hand) == 1 and res.applied == ["Exploit: roba 1"]


def test_bound_in_blood_sends_the_combat_damage_to_koschei_and_says_so(bprd):
    g, baba, liz = baba_game(bprd)
    g.turn = 1
    res = fight(g, "liz", "baba", "Incinerate", "Bound In Blood")
    assert res.damage == 4 and baba.hp == 13 and not g.fighters["koschei"].alive
    assert res.applied == ["Bound In Blood: desvia su dano de combate a Koschei",
                           "koschei recibe el dano de combate en lugar de baba"]


def test_a_pact_played_by_the_bot_enters_play(bprd):
    g, baba, liz = baba_game(bprd)
    zone_mate(g, "liz", "baba")
    peace = give(g, 0, "Pact Of Peace")
    assert g.play_scheme(0, baba, peace) is None
    assert g.fx.ongoing_card_id(0) == peace.card_id and hp(g, "liz", "koschei") == [15, 2] and g.actions_left == 2


# ---------------------------------------------------------------- Liz Sherman

def liz_game(bprd):
    g = mk(bprd, "liz-sherman", "hellboy")
    liz, hb = pair(g, "liz", "hellboy")
    return g, liz, hb


@pytest.mark.parametrize("pays", [True, False])
def test_incinerate_offers_the_rival_two_cards_to_ignore_its_value(bprd, pays):
    g, liz, hb = liz_game(bprd)
    theirs = hand_filler(g, 1, 3)
    g.controllers[1].queue = [[pays]]
    res = fight(g, "liz", "hellboy", "Incinerate")
    if pays:
        gone = [c for c in theirs if c in g.players[1].discard]
        assert res.atk_value == 0 and len(gone) == 2 and len(g.players[1].hand) == 1
        assert res.applied == [f"Incinerate: descartas {gone[0].title} y {gone[1].title}; el valor de Incinerate pasa a 0"]
    else:
        assert res.atk_value == 7 and len(g.players[1].hand) == 3 and res.applied == ["Incinerate: sin efecto"]


def test_fireball_burns_the_enemies_adjacent_to_the_defender(bprd):
    g, liz, hb = liz_game(bprd)
    lob = g.fighters["lobster"]
    lob.pos = free_adjacent(g, hb.pos, avoid=(liz.pos,))
    res = fight(g, "liz", "hellboy", "Fireball")
    assert lob.hp == 5 and hb.hp == 18 - 5 and res.applied == ["Fireball: lobster -1 PV (5)"]


def test_flame_lash_discards_the_bottom_card_adds_its_boost_and_gains_an_action(bprd):
    g, liz, hb = liz_game(bprd)
    deck = g.players[0].deck
    bottom = next(c for c in deck if "burning" not in c.tags and c.boost == 3)
    deck.remove(bottom)
    deck.append(bottom)
    res = fight(g, "liz", "hellboy", "Flame Lash")
    assert res.atk_value == 4 and bottom in g.players[0].discard and g.actions_left == 2
    assert res.applied == [f"Flame Lash: descarta {bottom.title}; valor de Flame Lash +3", "Flame Lash: gana 1 accion"]


def test_flame_lash_with_a_burning_bottom_card_adds_nothing_and_wildfire_returns_it(bprd):
    """Ivan (28/10): the bottom card is the last one; a burning card has no BOOST and comes back to the hand."""
    g, liz, hb = liz_game(bprd)
    deck = g.players[0].deck
    bottom = next(c for c in deck if "burning" in c.tags)
    deck.remove(bottom)
    deck.append(bottom)
    res = fight(g, "liz", "hellboy", "Flame Lash")
    assert res.atk_value == 1 and bottom in g.players[0].hand and bottom not in g.players[0].discard
    assert res.applied == [f"Flame Lash: {bottom.title} vuelve a su mano", "Flame Lash: gana 1 accion"]


def test_flame_lash_with_an_empty_deck_says_nothing_happened(bprd):
    g, liz, hb = liz_game(bprd)
    g.players[0].deck.clear()
    res = fight(g, "liz", "hellboy", "Flame Lash")
    assert res.atk_value == 1 and res.applied == ["Flame Lash: gana 1 accion"]


def test_fleeting_moments_makes_both_discard_at_random_and_draw(bprd):
    g, liz, hb = liz_game(bprd)
    mine = set_hand(g, 0, "Evade", "Feint")                           # not burning: the discard stays discarded
    theirs = set_hand(g, 1, "Service Pistol", "Glimpse Of Hell")
    res = fight(g, "liz", "hellboy", "Fleeting Moments")
    gone_mine = [c for c in mine if c in g.players[0].discard]
    gone_theirs = [c for c in theirs if c in g.players[1].discard]
    assert len(gone_mine) == len(gone_theirs) == 1 and len(g.players[0].hand) == len(g.players[1].hand) == 2
    assert res.applied == [f"Fleeting Moments: roba 1; descarta {gone_mine[0].title}; robas 1; descartas {gone_theirs[0].title}"]


def test_burning_barrier_pins_the_opposing_fighter_and_burns_the_enemies_in_lizs_zone(bprd):
    g, liz, hb = liz_game(bprd)
    zone_mate(g, "hellboy", "liz", adjacent=True)
    res = fight(g, "liz", "hellboy", "Burning Barrier")
    assert not g.fx.can_move(hb) and g.fx.can_move(liz) and hb.hp == 18 - 2 - 1
    assert res.applied == ["Burning Barrier: hellboy no puede dejar su espacio este turno", "Burning Barrier: hellboy -1 PV (15)"]


def test_pyrotechnics_puts_two_cards_from_the_hand_at_the_bottom_unnamed(bprd):
    g, liz, hb = liz_game(bprd)
    mine = hand_filler(g, 0, 3)
    res = fight(g, "liz", "hellboy", "Pyrotechnics")
    assert len(g.players[0].hand) == 1 and set(g.players[0].deck[-2:]) <= set(mine)
    assert res.applied == ["Pyrotechnics: devuelve 2 cartas de la mano al mazo"]


def test_rekindle_shuffles_three_cards_from_the_discard_into_the_deck(bprd):
    g, liz, hb = liz_game(bprd)
    to_discard(g, 0, "Evade", "Feint", "Rekindle")
    pile = list(g.players[0].discard)                                 # Wildfire's start-of-turn discard may be in it
    res = fight(g, "liz", "hellboy", "Rekindle")
    back = [c for c in pile if c in g.players[0].deck]
    assert len(back) == 3 and len(g.players[0].discard) == len(pile) - 3 + 1
    assert res.applied == ["Rekindle: " + "; ".join(f"{c.title} vuelve al mazo" for c in back)]


def test_feint_cancels_the_rivals_defense(bprd):
    g, liz, hb = liz_game(bprd)
    to_discard(g, 1, *[c.title for c in g.players[1].deck if c.destiny][:4])
    hb.hp = 10
    res = fight(g, "liz", "hellboy", "Feint", "On Earth As It Is In Hell")
    assert res.cancelled == {"def"} and res.def_value == 0 and res.damage == 2 and hb.hp == 8    # no value, no heal
    assert res.applied == ["Feint: cancela los efectos de On Earth As It Is In Hell"]


def test_evade_draws_one_in_defense(bprd):
    g, liz, hb = liz_game(bprd)
    g.turn = 1
    res = fight(g, "hellboy", "liz", "Service Pistol", "Evade")
    assert len(g.players[0].hand) == 1 and res.applied == ["Evade: roba 1"]


def test_fight_or_flight_played_by_the_bot_adds_one_to_its_next_combat_card(bprd):
    g, liz, hb = liz_game(bprd)
    far = far_from(g, "hellboy")
    g.controllers[0].moves = {"liz": far}
    fof = give(g, 0, "Fight Or Flight")
    assert g.play_scheme(0, liz, fof) is None
    assert g.fx.ongoing_card_id(0) == fof.card_id and len(g.players[0].hand) == 1
    liz.pos = free_adjacent(g, hb.pos)
    res = fight(g, "liz", "hellboy", "Fireball")
    assert res.atk_value == 6 and "Fight Or Flight (+1)" in res.atk_parts


# ---------------------------------------------------------------- rulings across the two sides

def test_bot_arcane_dampener_before_the_humans_flame_lash_boost_clamps_at_zero_then_adds(bprd):
    """Ivan (28/10): Flame Lash (1) vs Arcane Dampener (-3) is 0, then its bottom-card boost (+3) makes 3."""
    g = mk(bprd, "abe-sapien", "liz-sherman")
    abe, liz = pair(g, "abe", "liz")
    g.turn = 1
    bottom = give(g, 1, max(g.players[1].deck, key=lambda c: c.boost).title)   # the table hands it to the engine
    assert bottom.boost == 3
    res = fight(g, "liz", "abe", "Flame Lash", "Arcane Dampener", boost=bottom)
    assert res.atk_value == 3 and res.atk_parts == ["Flame Lash (1)", "Arcane Dampener (-1)", "Flame Lash (+3)"]


def test_the_attacker_gets_a_stake_for_a_priced_optional(bprd):
    """D1-prep review: `worth_paying` saw `at_stake` 0 for the attacker. Now the stake is what the defense blocks."""
    g, liz, hb = liz_game(bprd)
    flow = CombatFlow(g, liz, hb, give(g, 0, "Incinerate"), give(g, 1, "Confront Any Demon or God"))
    while flow.phase is not Phase.IMMEDIATELY:
        flow.step()
    run = EffectRun([], Ctx(owner=0, this_fid="liz"))
    run.flow = flow
    cost = [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "amount": 2}}]
    attacker = _cost_context(g, run, cost, chooser=0)
    defender = _cost_context(g, run, cost, chooser=1)
    assert attacker == {"cost_cards": 2, "at_stake": 3, "hp": hb.hp - 4} and defender == {"cost_cards": 2, "at_stake": 4, "hp": hb.hp}
    assert not worth_paying(ChoiceRequest("optional", 0, [True, False], extra=attacker))
    hb.hp = 7
    assert worth_paying(ChoiceRequest("optional", 0, [True, False], extra=_cost_context(g, run, cost, chooser=0)))


def test_fateful_bargains_decision_spares_koschei_when_the_blow_would_kill_him(bprd):
    g, baba, liz = baba_game(bprd)
    g.controllers[0] = MedusaAI(0)
    kos = g.fighters["koschei"]
    fight(g, "baba", "liz", "Hasten Towards Death")
    assert hp(g, "baba", "koschei") == [13, 2]                       # a scratch goes to Koschei
    kos.hp = 1
    g.actions_left = 2
    fight(g, "baba", "liz", "Hasten Towards Death")
    assert hp(g, "baba", "koschei") == [12, 1] and kos.alive          # a killing blow stays with Baba


# ---------------------------------------------------------------- the anti-cheat tripwire

class Opaque:
    card_id = 999999

    def __getattr__(self, name):
        raise AssertionError(f"the bot read the human hand ({name})")


def spy_on(g, monkeypatch):
    """The human's hand explodes on any read but its size while the bot DECIDES (`EffectAI.decide`); the engine
    may read it between decisions when a card says so (Confront's look and discard). A `look_hand` reached while
    deciding must be running on a clone, never on the real game."""
    from sparring.effects import ops_core
    spy = HandSpy(g.players[1].hand)
    g.players[1].hand = spy
    decide, real_look = EffectAI.decide, ops_core.OPS["look_hand"]
    decisions = []

    def armed_decide(self, game, req, nested):
        spy.armed = True
        try:
            decisions.append(req.kind)
            return decide(self, game, req, nested)
        finally:
            spy.armed = False

    def look(run, game, spec):
        if spy.armed:
            assert game is not g and game.players[1].hand is not spy
        return real_look(run, game, spec)
    monkeypatch.setattr(EffectAI, "decide", armed_decide)
    monkeypatch.setitem(ops_core.OPS, "look_hand", look)
    return spy, decisions


def test_clone_evaluation_never_touches_the_human_hand(bprd, monkeypatch):
    """Posthumous Power makes EffectAI simulate every option on a blind clone; Confront lost looks at the hand
    through `look_hand` and the bot then picks a card to discard among what it saw: no decision reads the hand."""
    g = mk(bprd, "hellboy", "liz-sherman")
    g.controllers[0] = MedusaAI(0)
    lob, liz = pair(g, "lobster", "liz")
    g.fighters["hellboy"].pos = free_adjacent(g, liz.pos, avoid=(lob.pos,))
    set_hand(g, 1, "Fireball", "Rekindle")
    spy, decisions = spy_on(g, monkeypatch)
    res = fight(g, "lobster", "liz", "Posthumous Power")
    assert res.applied and len(g.players[1].hand) == 2 and "effect" in decisions
    g.fighters["hellboy"].pos = free_adjacent(g, liz.pos, avoid=(lob.pos,))     # the option taken may have moved Liz
    res = fight(g, "hellboy", "liz", "Confront Any Demon or God", "Evade")       # Evade (E2: interpreted) draws 1
    gone = [c for c in g.players[1].discard if c.title != "Evade"]              # a burning card comes back (Wildfire)
    assert not res.attacker_won and len(g.players[1].hand) == 3 - len(gone) and "mira tu mano" in res.applied[0]
    assert not spy.armed


def test_a_look_inside_a_simulation_runs_on_a_blind_clone(bprd, monkeypatch):
    """Every evaluation clone is determinized (`blind_clone`) before any `look_hand` runs on it."""
    g = mk(bprd, "hellboy", "liz-sherman")
    set_hand(g, 1, "Fireball", "Rekindle", "Evade")
    card = next(c for c in g.players[0].full_set if c.title == "Posthumous Power")
    looks = []
    from sparring.effects import ops_core
    real_look = ops_core.OPS["look_hand"]

    def look(run, game, spec):
        looks.append(game)
        return real_look(run, game, spec)
    monkeypatch.setitem(ops_core.OPS, "look_hand", look)
    ops = [{"op": "look_hand", "player": "opponent"}, {"op": "draw", "player": "owner", "amount": 1}]
    monkeypatch.setattr(EffectAI, "_locate", staticmethod(lambda game, req: ({"options": [{"ops": ops}, {"ops": []}]}, card, 0, "after")))
    spy = HandSpy(g.players[1].hand)
    g.players[1].hand = spy
    spy.armed = True
    try:
        answer = EffectAI(0).choose_effect(g, ChoiceRequest("effect", 0, [0, 1], card_id=card.card_id, key="after/0:0"))
    finally:
        spy.armed = False
    assert answer in ([0], [1]) and looks and all(x is not g and x.players[1].hand is not spy for x in looks)
    assert g.players[0].known.is_empty()                              # nothing leaked back into the real game


# ---------------------------------------------------------------- the live session: the human side as E1 left it

def test_in_the_session_a_bot_card_that_asks_the_human_pauses_at_the_panel_and_is_announced(tmp_path, monkeypatch):
    """Bot Liz attacks with Incinerate: the human gets the Si/No buttons of E1, pays with the table's discard
    (owed at End action) and the chat says what the card did."""
    from sparring.ai_medusa import Act
    from sparring.tts.ui import Event
    from test_batch import click
    from test_choice_infra import visible_choices
    from test_multihero_bridge import build
    session, table, game, fake, cfg, client = build(tmp_path, "liz-sherman", "hellboy")
    try:
        liz, hb = game.hero(0), game.hero(1)
        incinerate = next(c for c in game.players[0].hand if c.title == "Incinerate")
        monkeypatch.setattr(session.ai, "plan", lambda g: Act("attack", fid="liz", target="hellboy", card=incinerate))
        monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
        click(session, table, Event.MANEUVER)
        click(session, table, Event.END_ACTION)
        click(session, table, Event.MANEUVER)
        click(session, table, Event.END_ACTION)                       # the bot's turn: it attacks with Incinerate
        assert session.pending is not None and session.pending.kind == "bot_attacks"
        table.face_down = []
        said = click(session, table, Event.REVEAL)
        assert session.pending.flow is not None and session.effect_run.awaiting.kind == "optional"
        assert visible_choices(session) == ["btn_choice_1", "btn_choice_2"]
        assert session.panel_labels()["btn_choice_1"] == "Si" and any("Incinerate" in m for m in said)
        said = click(session, table, Event.CHOICE, {"i": 1})
        assert session.pending is None and session.pending_discard["n"] == 2
        assert any("Aplicado: Incinerate: el valor de Incinerate pasa a 0" in m for m in said)
        assert any(m.startswith("Descarta 2 carta(s) (Incinerate)") for m in said)
        assert hb.hp == hb.max_hp
    finally:
        client.close()
        fake.close()
