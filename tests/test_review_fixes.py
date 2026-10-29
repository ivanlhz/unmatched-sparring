import inspect

import pytest

import test_combat
from sparring import sim
from sparring.ai_medusa import MedusaAI, Model
from sparring.board import Board
from sparring.state import ANUNG, DETECTIVE, Game
from conftest import give, place


@pytest.fixture
def ai(game):
    a = MedusaAI(0)
    game.controllers[0] = a
    return a


def fill_hand(game, player, n):
    deck = game.players[player].deck
    while len(game.players[player].hand) < n:
        game.players[player].hand.append(deck.pop(0))


# 1. nunca se pasa: dos acciones siempre
def test_medusa_spends_all_actions_every_turn_over_100_games():
    bad = []

    class Spy(MedusaAI):
        def take_turn(self, game):
            super().take_turn(game)
            if game.winner is None and game.actions_left != 0:
                bad.append((game.turn_no, game.actions_left))

    for seed in range(100):
        sim.play(seed, medusa=Spy(0))
    assert bad == []


def test_candidates_never_include_pass(game, ai):
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 5)
    assert all(a.kind != "pass" for a in ai.candidates(game, Model(game, 0)))


def test_maneuver_options_include_staying_put(game, ai):
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    fill_hand(game, 1, 5)
    give(game, 0, "Snipe")
    acts = [a for a in ai.maneuver_acts(game, Model(game, 0))]
    harpies = ("harpy1", "harpy2", "harpy3")

    def moved(a, fid):
        return a.moves.get(fid, game.fighters[fid].pos) != game.fighters[fid].pos

    assert any(not moved(a, "medusa") and not any(moved(a, h) for h in harpies) for a in acts), "nadie se mueve"
    assert any(moved(a, "medusa") and not any(moved(a, h) for h in harpies) for a in acts), "solo Medusa"
    assert any(not moved(a, "medusa") and any(moved(a, h) for h in harpies) for a in acts), "solo Harpias"


# 2. la habilidad prefiere matar al heroe
def test_ability_kills_hero_before_lobster(game, ai):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    game.fighters["lobster"].hp = 1
    game.fighters["hellboy"].hp = 1
    assert ai.pick_ability_target(game).fid == "hellboy"


# 3. la defensa se decide sabiendo que el rival ha jugado una carta
def test_committed_attack_dist_has_no_empty_mass(game, ai):
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    game.players[1].hand.clear()
    fill_hand(game, 1, 1)
    m = Model(game, 0)
    dist = m.committed_attack_dist(game.fighters["hellboy"])
    assert all(v is not None for _, v in dist)
    assert sum(p for p, _ in dist) == pytest.approx(1.0)
    assert any(v is None for _, v in m.attack_dist(game.fighters["hellboy"]))


def test_choose_defense_uses_committed_distribution(game, ai, monkeypatch):
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    give(game, 0, "Hiss and Slither")
    fill_hand(game, 1, 1)

    def forbidden(self, f):
        raise AssertionError("choose_defense no debe usar la distribucion con masa de 'sin carta'")

    monkeypatch.setattr(Model, "attack_dist", forbidden)
    ai.choose_defense(game, game.fighters["hellboy"], game.fighters["medusa"])


def test_hiss_decisive_exemption_needs_real_block_probability(game, ai):
    """Con 5 destinos descartados, Hiss solo se juega si bloquear es casi seguro dado que hay ataque."""
    place(game, medusa=0, hellboy=1, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    hiss = give(game, 0, "Hiss and Slither")
    fill_hand(game, 1, 1)
    game.players[1].discard = [c for c in game.players[1].full_set if c.destiny][:5]  # incluye Excalibur y RHoD
    model = Model(game, 0)
    dist = model.committed_attack_dist(game.fighters["hellboy"])
    medusa = game.fighters["medusa"]
    assert dist
    strong = [(0.5, 3), (0.5, 7)]  # la mitad de las veces no se bloquea: penalizacion plena
    plain = ai.eval_defense(game, model, strong, medusa, hiss)
    ai_no_pen = ai.eval_defense(game, model, [(1.0, 3)], medusa, hiss)
    assert plain < ai_no_pen - 1.0


# 4. todos los turnos tienen 2 acciones
def test_every_turn_has_two_actions(bprd):
    g = Game.new(bprd, seed=1, controllers={})
    g.begin_turn()
    assert g.turn_no == 1 and g.actions_left == 2


# 5. la forma se recalcula desde el descarte (no es permanente)
def test_form_returns_to_detective_when_destinies_leave_discard(game):
    destiny = [c for c in game.players[1].full_set if c.destiny]
    game.players[1].discard = destiny[:6]
    assert game.form(1) == ANUNG
    game.players[1].discard.remove(destiny[0])  # p. ej. Pancakes! los devuelve al mazo
    assert game.form(1) == DETECTIVE


def test_detective_draws_two_only_on_opponent_start(game):
    game.fx.dsl_heroes.discard("hellboy")        # the wrapper of the legacy path (interpreted: the trigger, test_effects_events)
    hb = game.fighters["hellboy"]
    hb.pos = game.start_spaces[0]
    assert game.hellboy_detective_draw(1) is True and len(game.players[1].hand) == 2
    hb.pos = game.start_spaces[1]
    assert game.hellboy_detective_draw(1) is False


# 6. el plan esperado aplica el dano esperado
def test_apply_expected_attack_applies_damage_and_removes_dead(game, ai):
    place(game, medusa=0, hellboy=1, lobster=2, harpy1=20, harpy2=21, harpy3=22)
    game.players[1].hand.clear()  # sin defensa posible
    ss = give(game, 0, "Second Shot")
    model = Model(game, 0)
    hb, lob = game.fighters["hellboy"], game.fighters["lobster"]
    act = next(a for a in ai.attack_acts(game, model) if a.target == "hellboy" and a.fid == "medusa")
    g2 = ai.apply_expected(game, act)
    assert g2.fighters["hellboy"].hp == hb.hp - 3
    assert hb.hp == 18, "el estado real no cambia"
    lob.hp = 2
    act = next(a for a in ai.attack_acts(game, Model(game, 0)) if a.target == "lobster")
    g3 = ai.apply_expected(game, act)
    assert not g3.fighters["lobster"].alive and g3.fighters["lobster"].pos is None
    assert ss in game.players[0].hand


# 9. nits
def test_every_medusa_title_has_a_behaviour_test():
    expected = {
        "Second Shot": "test_second_shot_boost", "Gaze of Stone": "test_gaze_of_stone",
        "Regroup": "test_regroup_snipe_draws", "Snipe": "test_regroup_snipe_draws",
        "Dash": "test_dash_moves_after_combat", "Feint": "test_feint_cancels_rival_effects",
        "The Hounds of Mighty Zeus": "test_hounds_moves_every_harpy",
        "Clutching Claws": "test_clutching_claws_makes_opponent_discard",
        "Hiss and Slither": "test_hiss_and_slither_defense_makes_opponent_discard",
        "A Momentary Glance": "test_momentary_glance", "Winged Frenzy": "test_winged_frenzy",
    }
    from sparring.cards import load_medusa_deck
    assert {c.title for c in load_medusa_deck()} == set(expected)
    for name in expected.values():
        assert inspect.isfunction(getattr(test_combat, name))


def test_sidekicks_and_harpies_start_in_their_heroes_zone(bprd):
    for key in ("bprd-hq", "azuchi-castle"):
        g = Game.new(Board.load(key), seed=2, controllers={})
        for hero in ("medusa", "hellboy"):
            h = g.fighters[hero]
            for f in g.own(h.owner):
                assert g.board.share_zone(h.pos, f.pos), (key, f.fid)
