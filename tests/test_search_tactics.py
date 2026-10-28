"""IsmctsMedusa: sin trampas (misma decision con la mano rival cambiada), posiciones tacticas construidas y tiempo
por decision. Presupuesto por iteraciones en los tests para que sean deterministas y rapidos."""
import time

import pytest

from sparring.ai_medusa import MedusaAI
from sparring.search.controller import IsmctsMedusa, make_bot_ai
from sparring.search.ismcts import SearchConfig
from conftest import give, place

ITER = 600


def medusa_hand(game, *titles):
    seen = {}
    for t in titles:
        seen[t] = seen.get(t, -1) + 1
        give(game, 0, t, seen[t])


def rival_hand(game, n):
    deck = game.players[1].deck
    while len(game.players[1].hand) < n:
        game.players[1].hand.append(deck.pop(0))


def swap_rival_hand(game):
    """Misma partida con otra mano oculta del rival (mismo conteo, mismo descarte)."""
    other = game.clone()
    p = other.players[1]
    n = len(p.hand)
    p.hand, p.deck = p.deck[:n], p.hand + p.deck[n:]
    assert [c.card_id for c in p.hand] != [c.card_id for c in game.players[1].hand]
    return other


def act_key(a):
    return (a.kind, a.fid, a.target, a.card and a.card.title, a.boost and a.boost.title, tuple(sorted(a.moves.items())), a.spot)


def strike_steps(board, hb_pos, target_pos):
    return min(board.distance(hb_pos, s) for s in board.adj[target_pos])


@pytest.fixture
def ai():
    return IsmctsMedusa(0, SearchConfig(iterations=ITER, seed=11))


# ---------- sin trampas ----------

def test_plan_is_identical_with_another_hidden_rival_hand(game, ai):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Gaze of Stone", "Dash", "Regroup", "A Momentary Glance")
    rival_hand(game, 5)
    other = swap_rival_hand(game)
    a = ai.plan(game)
    b = IsmctsMedusa(0, SearchConfig(iterations=ITER, seed=11)).plan(other)
    assert act_key(a) == act_key(b)
    assert ai.last_report.iterations == ITER


def test_defense_is_identical_with_another_hidden_rival_hand(game, ai):
    place(game, medusa=4, hellboy=3, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Hiss and Slither", "Feint", "Second Shot")
    rival_hand(game, 5)
    game.turn, game.actions_left = 1, 1
    other = swap_rival_hand(game)
    hb, medusa = game.fighters["hellboy"], game.fighters["medusa"]
    a = ai.choose_defense(game, hb, medusa)
    b = IsmctsMedusa(0, SearchConfig(iterations=ITER, seed=11)).choose_defense(other, other.fighters["hellboy"],
                                                                                other.fighters["medusa"])
    assert (a and a.title) == (b and b.title)


def test_search_never_reads_the_rival_hand_objects(game, ai, monkeypatch):
    """Tripwire: las cartas de la mano real del rival explotan si alguien las consulta durante la busqueda."""
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Gaze of Stone", "Dash")
    rival_hand(game, 5)

    class Mine:
        card_id = 999999
        destiny = False

        def __getattr__(self, name):
            raise AssertionError(f"la busqueda leyo la mano real del rival ({name})")

    game.players[1].hand[:] = [Mine() for _ in range(5)]
    ai.plan(game)


# ---------- tacticas ----------

def test_finishes_the_hero_when_damage_is_lethal(game, ai):
    """Hellboy a 3 PV sin cartas (no puede defender): el ataque de 3 gana la partida."""
    place(game, medusa=4, hellboy=2, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Gaze of Stone", "Regroup", "A Momentary Glance", "Winged Frenzy")
    game.fighters["hellboy"].hp = 3
    assert len(game.players[1].hand) == 0
    act = ai.plan(game)
    assert act.kind == "attack" and act.target == "hellboy", act_key(act)
    ai.execute(game, act)
    assert game.winner == 0, "el ataque elegido tenia que ser letal (Second Shot 3, o Gaze of Stone: gana y suma 8)"


def test_takes_the_certain_kill_of_a_sidekick(game, ai):
    """Lobster a 2 PV en la zona de Medusa: A Momentary Glance lo mata seguro; un ataque podria ser defendido."""
    place(game, medusa=4, hellboy=27, lobster=2, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "A Momentary Glance", "Second Shot", "Regroup")
    rival_hand(game, 5)
    game.fighters["lobster"].hp = 2
    act = ai.plan(game)
    assert act.kind == "glance" and act.target == "lobster", act_key(act)


def test_does_not_walk_into_an_avoidable_lethal(game, ai):
    """Medusa a 1 PV lejos de Hellboy, con ataques que no matan: no acaba el turno a su alcance sin boost."""
    b = game.board
    place(game, medusa=30, hellboy=3, lobster=0, harpy1=28, harpy2=29, harpy3=31)
    medusa_hand(game, "Second Shot", "Second Shot", "Dash", "Snipe", "Regroup")
    rival_hand(game, 5)
    game.fighters["medusa"].hp = 1
    for fid in ("harpy1", "harpy2", "harpy3"):
        game.fighters[fid].alive, game.fighters[fid].pos, game.fighters[fid].hp = False, None, 0
    assert strike_steps(b, 3, 30) > 2
    ai.take_turn(game)
    medusa, hb = game.fighters["medusa"], game.fighters["hellboy"]
    assert medusa.alive
    assert strike_steps(b, hb.pos, medusa.pos) > 2, f"Medusa termino a tiro de Hellboy sin boost (casilla {medusa.pos})"


def test_defends_with_the_strongest_card_when_a_hit_would_kill(game, ai):
    place(game, medusa=4, hellboy=3, lobster=27, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Hiss and Slither", "Feint", "Second Shot")
    rival_hand(game, 5)
    game.fighters["medusa"].hp = 3
    game.turn, game.actions_left = 1, 1
    card = ai.choose_defense(game, game.fighters["hellboy"], game.fighters["medusa"])
    assert card is not None and card.title == "Hiss and Slither"


# ---------- integracion ----------

def test_full_turn_with_the_engine(game, ai):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Dash", "Winged Frenzy", "Clutching Claws", "Regroup")
    rival_hand(game, 5)
    ai.take_turn(game)
    assert game.actions_left == 0 or game.winner is not None
    assert len(game.players[0].discard) >= 1


def test_make_bot_ai_defaults_to_the_heuristic():
    assert isinstance(make_bot_ai({}), MedusaAI)
    assert isinstance(make_bot_ai({"ai": "heuristic"}), MedusaAI)
    ai = make_bot_ai({"ai": "ismcts", "ai_time_budget": 0.2, "ai_seed": 4}, bot=1)
    assert isinstance(ai, IsmctsMedusa) and ai.me == 1
    assert ai.config.time_budget == 0.2 and ai.config.seed == 4 and ai.config.iterations is None
    with pytest.raises(ValueError):
        make_bot_ai({"ai": "magic"})


def test_default_budget_decides_under_two_seconds(game):
    place(game, medusa=4, hellboy=2, lobster=3, harpy1=20, harpy2=21, harpy3=22)
    medusa_hand(game, "Second Shot", "Gaze of Stone", "Dash", "Regroup", "A Momentary Glance", "Feint", "Winged Frenzy")
    rival_hand(game, 5)
    ai = make_bot_ai({"ai": "ismcts"})
    t0 = time.perf_counter()
    ai.plan(game)
    elapsed = time.perf_counter() - t0
    assert elapsed < 2.0, f"{elapsed:.2f}s"
    assert ai.last_report.iterations > 500, ai.last_report.iterations
