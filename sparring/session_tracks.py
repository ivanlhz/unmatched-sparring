"""John Henry's track tokens at the live table (docs/heroes/john-henry.md).

The bot's Henry has the engine decide where each token goes and the session lays the physical one (`session_translators`, intent
`track`). The human's Henry lays his own by hand at the start of his turn (the trigger is physical: the panel waits for End action), so
the table is the source of truth: `sync` reads every track token on the board (they are told apart by the picture of the token, a token
taken out of the stack has neither name nor GUID of its own) and the engine adopts the spaces they stand on. It is called before the
table's positions are read: the track spaces decide what John Henry's walk cost and which spaces his paths are."""
from __future__ import annotations

from . import tracks
from .spaces import describe
from .i18n import t
from .tts import lua
from .tts.client import TTSLuaError
from .tts.hero_table import HeroTableError, load_hero_table
from .tts.lua import ChatKind

SLUG = "john-henry"
TOKEN = "track"


def token_source(slug: str = SLUG) -> str | None:
    """GUID of the stack of track tokens in John Henry's bag (data/tts/john-henry.json), None without table data."""
    try:
        return load_hero_table(slug).tokens.get(TOKEN)
    except HeroTableError:
        return None


def image_key(slug: str = SLUG) -> str | None:
    """The 40 hex digits the picture of the track token ends with: how the table scan recognises one."""
    try:
        url = load_hero_table(slug).token_sources.get(TOKEN, {}).get("image", "")
    except HeroTableError:
        return None
    key = url.rstrip("/").rsplit("/", 1)[-1]
    return key if len(key) == 40 else None


def is_john(session, player: int) -> bool:
    return session.game.hero_def(player).slug == SLUG


def table_spaces(session) -> list[int] | None:
    """The spaces with a track token on the table (one entry per space, at most the supply), None when the table cannot be read."""
    key = image_key()
    if key is None:
        return None
    try:
        found = session.client.call_lua(lua.read_tokens_by_image(session.game.board, key))
    except (TTSLuaError, OSError, TimeoutError, ValueError, TypeError):
        return None
    if not isinstance(found, dict) or "tokens" not in found:
        return None
    spaces: list[int] = []
    for token in found["tokens"]:
        if token.get("dist", 99) <= session.cfg.off_board_dist and token["space"] not in spaces:
            spaces.append(int(token["space"]))
    return spaces[:tracks.SUPPLY]


def sync(session) -> None:
    """The human's John Henry: the engine's track spaces become the table's. A token laid is said in the chat; one taken away is
    forgotten without a word (the human may have picked it up to lay it somewhere else)."""
    g, me = session.game, session.human
    if not is_john(session, me) or session.setup is not None:
        return
    spaces = table_spaces(session)
    if spaces is None:
        return
    now = g.fx.tracks[me]
    if set(spaces) == set(now):
        return
    new = [s for s in spaces if s not in now]
    g.fx.tracks[me] = [s for s in now if s in spaces] + new
    hero = g.hero(me)
    for space in new:
        session.say(t("john.track.seen", name=session._name(hero), where=describe(g, space, (), session._name),
                      n=tracks.left(g, me)), ChatKind.ABILITY)
