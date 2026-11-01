from pathlib import Path

import pytest

from sparring.board import Board
from sparring.controller import Controller
from sparring.state import Game


class Scripted(Controller):
    """Controller for tests: prepared answers."""

    def __init__(self):
        self.defense = None
        self.boost = None
        self.moves: dict[str, int] = {}
        self.discards: list = []
        self.placement = None

    def take_turn(self, game):
        pass

    def choose_defense(self, game, attacker, target, attack_card=None):
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
    """Medusa = player 0, Hellboy = 1, Medusa starts, empty hands to place cards by hand."""
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
    """No test may connect to the real TTS ports (the user has a game open)."""
    monkeypatch.setattr(_socket.socket, "connect", _guarded_connect)


REAL_BIND = _socket.socket.bind


def _guarded_bind(self, address):
    refuse_real_ports(address)
    return REAL_BIND(self, address)


@pytest.fixture(autouse=True)
def _never_bind_real_ports(monkeypatch):
    """Nor may a test listen on the real ports: it would step on the live TTS listener."""
    monkeypatch.setattr(_socket.socket, "bind", _guarded_bind)


ROOT_DIR = Path(__file__).resolve().parent.parent
STATE_DIRS = (ROOT_DIR / "state", ROOT_DIR / "estado")   # current and legacy locations of the real save


def snapshot_dir(path) -> dict[str, tuple[int, int]]:
    """Relative path -> (size, mtime_ns) of every file under `path` (empty if it does not exist)."""
    root = Path(path)
    if not root.exists():
        return {}
    return {str(p.relative_to(root)): (p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted(root.rglob("*")) if p.is_file()}


def assert_dir_untouched(path, before: dict) -> None:
    after = snapshot_dir(path)
    changed = sorted(k for k in before.keys() | after.keys() if before.get(k) != after.get(k))
    assert not changed, f"the test wrote to {path} (the real game save): {', '.join(changed)}"


@pytest.fixture(autouse=True)
def _never_touch_the_real_resume_file():
    """No test may write under the project's state\ (or the legacy estado\) folder: the real game save lives there."""
    before = [snapshot_dir(d) for d in STATE_DIRS]
    yield
    for d, snap in zip(STATE_DIRS, before):
        assert_dir_untouched(d, snap)


@pytest.fixture(autouse=True)
def _default_state_goes_to_tmp(tmp_path, monkeypatch):
    """A test that forgets --state writes to its tmp_path, not to state\."""
    from sparring import play
    monkeypatch.setattr(play, "DEFAULT_STATE", tmp_path / "default-state" / "session.json")
    monkeypatch.setattr(play, "LEGACY_STATE", tmp_path / "legacy-state" / "sesion.json")


TEST_IDENT = (("https://img.test/face", "https://img.test/back"),)


@pytest.fixture(autouse=True)
def _decks_have_a_known_identity(monkeypatch):
    """Test sessions start with the deck identities already read (as after `start`); the reading tests empty it
    on purpose."""
    from sparring.session import Session
    real = Session.__init__

    def init(self, *a, **kw):
        real(self, *a, **kw)
        self._deck_ident = {"bot": TEST_IDENT, "human": TEST_IDENT}
    monkeypatch.setattr(Session, "__init__", init)


@pytest.fixture
def retitled_card_data(monkeypatch):
    """A test that retitles one hero's card to stand for another's (Pancakes! plays Fight Or Flight): the scheme path
    of a hero outside the interpreter reads the DSL of the title, wherever it is defined."""
    from sparring.effects import ongoing
    real = ongoing.scheme_traits
    monkeypatch.setattr(ongoing, "scheme_traits", lambda slug, title: real(slug, title) or next(
        (t for s in ("liz-sherman", "hellboy") if (t := real(s, title))), {}))


def _shims():
    import functools
    from sparring.tts import lua
    scope = lua.Scope(("Green", "White"), ("906a7a", "b7a0b8"), ((6.0, -18.0), (-2.0, -18.0), (11.5, 12.0)))
    return {"t_deal_cards": functools.partial(lua.deal_cards, identity=TEST_IDENT),
            "t_discard_cards": functools.partial(lua.discard_cards, identity=TEST_IDENT, scope=scope),
            "t_reset_deck": functools.partial(lua.reset_deck, identity=TEST_IDENT, scope=scope),
            "t_return_hand_to_deck": functools.partial(lua.return_hand_to_deck, identity=TEST_IDENT),
            "t_shuffle_deck": functools.partial(lua.shuffle_deck, identity=TEST_IDENT),
            "t_play_card_face_down": functools.partial(lua.play_card_face_down, identity=TEST_IDENT),
            "t_flip_card": functools.partial(lua.flip_card, identity=TEST_IDENT),
            "t_reset_plan": functools.partial(lua.reset_plan, scope=scope)}


globals().update(_shims())


@pytest.fixture(autouse=True)
def _spanish_by_default():
    """The player-facing language is process-wide: every test starts (and leaves) it in Spanish."""
    from sparring import i18n
    i18n.set_language("es")
    yield
    i18n.set_language("es")
