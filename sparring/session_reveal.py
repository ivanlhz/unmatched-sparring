"""Revealed cards on the table (Ivan, 2026-11-08, global for every hero): "reveal" in a card text means every player sees those
cards. When an effect reveals one or more cards (Jill Trent's Hypnoray Blaster, Battle of Wits and Insightful Deduction, Doctor
Strange's Mists of Munnopor and No, Really, I'm a Doctor, Houdini's A Magician Never Reveals His Secrets) the bot lays a LARGE COPY
of each one side by side over the board (`lua.reveal_show`) and they stay there until the human presses "Stop revealing" on the
panel (`Event.STOP_REVEAL`); the button exists only while copies do.

  * The game does not wait for that click: play carries on with the copies on show. A new reveal replaces them.
  * The copies are only data copied from the cards (deck, hand or pile): the originals never move and the order of a real deck
    is never touched. They carry the zoom's name and tag (every table read skips them) plus GM notes of their own.
  * Looking is not revealing. When the bot only LOOKS at the human's deck or hand (Golden Bat's Sight Beyond Sight, the bury and
    reorder of Insightful Deduction) nothing is shown and nothing is named: that goes through `lua.deck_reorder`, blind.
  * The copies are removed by the button, by a new reveal, by New game, Restart, Clean table (`lua.clear_markings`) and on resume.

The intents that mean a reveal (the ops report them with `effects.table.intent`):

  * `reveal_top` {player, viewer, cards}: top cards of `player`'s deck (Jill Trent);
  * `reveal_deck` {player, revealed, found, source}: the engine's deck revealed until a card is found (Mists of Munnopor), shown
    when the deck is the bot's (the human reveals their own by hand);
  * `reveal_show` {player, cards}: cards of `player` revealed wherever they lie (a hand, a pile)."""
from __future__ import annotations

from typing import Callable

from .i18n import t
from .session_translators import ERRORS, result_of
from .tts import lua
from .tts.lua import ChatKind

REVEAL_OPS = ("reveal_top", "reveal_deck", "reveal_show")
DOMAIN = "fx"


def reveal_spec(cfg) -> lua.RevealSpec:
    """Where and how big the revealed cards lie: the zoom's rotation (readable from the human's seat), a spot and size of their own."""
    rot = cfg.card_zoom_rot
    if rot is None:
        rot = (0.0, cfg.look_rot_y if cfg.look_rot_y is not None else cfg.bot_discard_rot_y, 0.0)
    return lua.RevealSpec(cfg.reveal_spot, rot, cfg.reveal_scale, cfg.reveal_step)


def revealed_by(session, intents: list[dict]) -> list[tuple[str, list[int]]]:
    """(side, CardIDs) of every card the intents reveal, merged by side in the order they were reported, no repeats."""
    out: dict[str, list[int]] = {}
    for i in intents:
        op = i["op"]
        if op == "reveal_top" or op == "reveal_show":
            holder, ids = i["player"], i["cards"]
        elif op == "reveal_deck" and i["player"] == session.bot:
            holder, ids = i["player"], i["revealed"]
        else:
            continue
        side = "bot" if holder == session.bot else "human"
        have = out.setdefault(side, [])
        have.extend(c for c in ids if c not in have)
    return list(out.items())


def show(session, shown: list[tuple[str, list[int]]]) -> Callable[[], None]:
    """Lays the big copies of the revealed cards (replacing any on show) and returns the check of the write. The panel button
    follows `session.reveal_shown`. A display that cannot be built is not an error of the game: the chat already names the cards."""
    cfg = session.cfg
    if not cfg.reveal_display or not shown:
        return lambda: None
    from .session import SessionError
    try:
        groups = [lua.RevealGroup(tuple(ids), cfg.bot_card_ids if side == "bot" else cfg.human_card_ids,
                                  session._identity(side)) for side, ids in shown]
        script = lua.reveal_show(groups, reveal_spec(cfg), (cfg.bot_seat, cfg.human_seat))
        op = session._w(script, DOMAIN)
    except (SessionError, ValueError, TypeError, *ERRORS):
        session.say(t("reveal.missing", n=sum(len(ids) for _, ids in shown)), ChatKind.WARNING)
        return lambda: None
    session.reveal_shown = True
    session.say(t("reveal.shown"), ChatKind.SCHEME)

    def check() -> None:
        res = result_of(op)
        if res.get("shown") == 0:
            session.reveal_shown = False
        if res.get("missing"):
            session.say(t("reveal.missing", n=len(res["missing"])), ChatKind.WARNING)
    return check


def clear(session, orphans: bool = False) -> None:
    """Removes the copies (the button, a new game, a restart). Nothing is sent when none is on show, except with `orphans` (a resume:
    a run that died may have left copies the session does not know of). Only objects with the reveal GM notes are touched."""
    if not session.reveal_shown and not orphans:
        return
    session.reveal_shown = False
    try:
        session._w(lua.reveal_clear(), DOMAIN)
    except ERRORS:
        pass


def stop(session) -> None:
    """The panel button: the copies go away and so does the button."""
    clear(session)
