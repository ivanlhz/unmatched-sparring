from pathlib import Path

import pytest

from sparring.board import Board
from sparring.controller import Controller
from sparring.state import Game


class Scripted(Controller):
    """Controlador para tests: respuestas preparadas."""

    def __init__(self):
        self.defense = None
        self.boost = None
        self.moves: dict[str, int] = {}
        self.discards: list = []
        self.placement = None

    def take_turn(self, game):
        pass

    def choose_defense(self, game, attacker, target):
        return self.defense

    def choose_combat_boost(self, game, ctx):
        return self.boost

    def choose_discard(self, game, player, n, reason):
        if self.discards:
            return self.discards[:n]
        return game.players[player].hand[-n:]

    def choose_move(self, game, fighter, steps, through_enemies=False):
        return self.moves.get(fighter.fid)

    def choose_placement(self, game, fighter, options):
        return self.placement if self.placement is not None else (options[0] if options else None)


@pytest.fixture(scope="session")
def bprd():
    return Board.load("bprd-hq")


@pytest.fixture(scope="session")
def azuchi():
    return Board.load("azuchi-castle")


@pytest.fixture
def ctl():
    return {0: Scripted(), 1: Scripted()}


@pytest.fixture
def game(bprd, ctl):
    """Medusa = jugador 0, Hellboy = 1, empieza Medusa, manos vacias para colocar cartas a mano."""
    g = Game.new(bprd, seed=3, controllers=ctl)
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    return g


def card(game, player, title, nth=0, pool="full_set"):
    cards = [c for c in getattr(game.players[player], pool) if c.title == title]
    return cards[nth]


def give(game, player, title, nth=0):
    c = card(game, player, title, nth)
    game.players[player].deck.remove(c) if c in game.players[player].deck else None
    game.players[player].hand.append(c)
    return c


def place(game, **where):
    for fid, space in where.items():
        game.fighters[fid].pos = space


import socket as _socket

REAL_CONNECT = _socket.socket.connect
REAL_PORTS = (39999, 39998)


def refuse_real_ports(address) -> None:
    if isinstance(address, tuple) and address[1] in REAL_PORTS:
        raise AssertionError(f"un test intento conectar con el TTS real: {address}")


def _guarded_connect(self, address):
    refuse_real_ports(address)
    return REAL_CONNECT(self, address)


@pytest.fixture(autouse=True)
def _never_touch_real_tts(monkeypatch):
    """Ningun test puede conectar con los puertos reales de TTS (el usuario tiene una partida abierta)."""
    monkeypatch.setattr(_socket.socket, "connect", _guarded_connect)


REAL_BIND = _socket.socket.bind


def _guarded_bind(self, address):
    refuse_real_ports(address)
    return REAL_BIND(self, address)


@pytest.fixture(autouse=True)
def _never_bind_real_ports(monkeypatch):
    """Tampoco se puede escuchar en los puertos reales: un test ahi pisaria el listener del TTS vivo."""
    monkeypatch.setattr(_socket.socket, "bind", _guarded_bind)


ESTADO = Path(__file__).resolve().parent.parent / "estado"


def snapshot_dir(path) -> dict[str, tuple[int, int]]:
    """Ruta relativa -> (tamano, mtime_ns) de todo fichero bajo `path` (vacio si no existe)."""
    root = Path(path)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def assert_dir_untouched(path, before: dict) -> None:
    after = snapshot_dir(path)
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    assert not changed, f"el test escribio en {path} (guardado real de la partida): {', '.join(changed)}"


@pytest.fixture(autouse=True)
def _never_touch_the_real_resume_file():
    """Ningun test puede escribir bajo estado\ del proyecto: ahi vive el guardado de la partida real."""
    before = snapshot_dir(ESTADO)
    yield
    assert_dir_untouched(ESTADO, before)


@pytest.fixture(autouse=True)
def _default_state_goes_to_tmp(tmp_path, monkeypatch):
    """Un test que olvide --state escribe en su tmp_path, no en estado\."""
    from sparring import play
    monkeypatch.setattr(play, "DEFAULT_STATE", tmp_path / "default-state" / "sesion.json")
