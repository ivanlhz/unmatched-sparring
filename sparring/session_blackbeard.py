"""Blackbeard's doubloons at the live table (docs/heroes/blackbeard.md): the bot puts the coins where the engine has them.

The engine's two counters (`doubloons`, `treasury`) are the authority and the chat says every change (`effects/narrate`). The table has the
Treasury tile and a stack of three coins (`treasury_tile`, `doubloon_stack` of data/tts/blackbeard.json): the coins Blackbeard holds lie on the
stack's spot and the Treasury's on the tile. Whoever plays Blackbeard, the BOT moves the coins (`lua_blackbeard.set_doubloons`: the human never
has to touch them, and a ransom the human pays at the panel or a payment the human's Blackbeard makes shows on the table at once). It is
written whenever the engine's count differs from the last one written, and always once at the start of a game and after a resume (the stack
starts whole: the Treasury needs its one coin)."""
from __future__ import annotations

from .effects.plugins_blackbeard import HELD, TREASURY, stock
from .i18n import t
from .session_translators import DOMAIN, ERRORS
from .tts import lua_blackbeard
from .tts.hero_table import HeroTableError, load_hero_table
from .tts.lua import ChatKind

COIN = "Doubloon"            # nickname of the coins (the stack's, and of every token taken out of it)
RISE = 0.25                  # the spots in data/tts are the table's: a coin lies a little above them


def _player(session) -> int | None:
    """The player whose hero is Blackbeard, if any."""
    for player in (session.bot, session.human):
        if session.game.hero_def(player).slug == "blackbeard":
            return player
    return None


def _spots(session, player: int):
    """(held spot, treasury spot) of Blackbeard's side, or None when the data has no resting places."""
    table = load_hero_table("blackbeard")
    side = "bot" if player == session.bot else "human"
    held = table.token_slots.get("doubloon_stack", {}).get(side)
    tile = table.token_slots.get("treasury_tile", {}).get(side)
    if not held or not tile:
        return None
    return held[0][0], tile[0][0], table.tokens["doubloon_stack"]


def put_coins(session, player: int) -> None:
    """Writes the engine's count on the table and checks the table's answer later in the step (a coin that is not there is said once)."""
    game, c = session.game, session.cfg
    try:
        found = _spots(session, player)
        if found is None:
            return
        held, tile, stack = found
        script = lua_blackbeard.set_doubloons(COIN, stack, (held[0], held[1], held[2]), (tile[0], tile[1], tile[2]),
                                              stock(game, player, TREASURY), [c.human_seat, c.bot_seat])
    except (HeroTableError, KeyError, TypeError, ValueError):
        return
    op = session._w(script, DOMAIN)
    name = game.hero(player).name

    def check() -> None:
        try:
            res = op.result or {}
        except ERRORS:
            session.say(t("blackbeard.coins_failed", name=name), ChatKind.WARNING)
            return
        if int(res.get("total") or 0) < 3:
            session.say(t("blackbeard.coins_missing", name=name, found=int(res.get("total") or 0)), ChatKind.WARNING)
    session._post.append(check)


def track(session, announce: bool = False) -> None:
    """Moves the coins when the engine's count changed since the last time they were written (`announce`: also the first time, the start of a
    game or a resume). Nothing happens when nobody plays Blackbeard."""
    player = _player(session)
    if player is None:
        return
    now = (stock(session.game, player, HELD), stock(session.game, player, TREASURY))
    written = session.__dict__.get("_coins_written")
    session.__dict__["_coins_written"] = now
    if written == now or (written is None and not announce):          # the first look only notes the count: the start of a game writes it (`announce`)
        return
    put_coins(session, player)


def forget(session) -> None:
    """A restart or a table adoption: the next look writes the coins again."""
    session.__dict__.pop("_coins_written", None)
