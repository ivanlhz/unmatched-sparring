"""Fighters the human's effects move, moved by the human's own hand (Ivan, 30/10).

The spaces of the board are not numbered, so "Space 17" on a panel button told the human nothing. When a card or
hero effect of the human relocates a fighter (his own or the bot's: move, place, revive, summon), the request is
not answered with a button per space: the chat says what to move and the limits, the panel shows Done (and "Don't
move" when the move is optional), and the human moves the miniature on the table. At Done the bot reads the
snapshot and validates it against the engine's own options for that request (the right fighter, within the limit
along a legal path, onto a free space, nothing else moved). A valid move is applied to the engine as the answer; a
wrong one changes nothing, the chat says what is wrong and the panel keeps waiting. The bot never moves a piece for
the human in this flow: the table already shows the piece, so `Session.hand_moved` tells the projection not to
move it again.

The distance of a dropped piece to its nearest space is the only snap information the snapshot has (`dist`): a piece
farther than `off_board_dist` is rejected; two equidistant spaces cannot be told apart from it."""
from __future__ import annotations

from .effects.choose import ChoiceRequest
from .i18n import t, tn
from .session_choices import panel_text, request_card
from .spaces import describe
from .tts.lua import ChatKind


def manual_request(session) -> ChoiceRequest | None:
    """The pending decision of the human when it asks where a fighter goes."""
    run = session.effect_run
    req = None if run is None else run.awaiting
    if req is None or req.kind != "space" or req.player != session.human:
        return None
    return req if req.extra.get("fighter") in session.game.fighters else None


def _plural(n: int) -> str:
    return tn("moves.squares", n)


def _spot(session, space, exclude=()) -> str:
    return describe(session.game, space, exclude, session._name)


def where_text(session, req: ChoiceRequest) -> str:
    """The spaces a placement allows, in words the human can find on the table."""
    g, where = session.game, req.extra.get("where") or {}

    def who(key):
        return session._name(g.fighters[where[key]]) if where.get(key) in g.fighters else t("moves.his_hero")
    if where.get("any"):
        text = t("moves.where.any")
    elif "zone_of" in where:
        text = t("moves.where.zone", who=who("zone_of"))
    elif "next_to_nearest_foe" in where:
        text = t("moves.where.next_to_foe")
    elif "no_zone_of" in where:
        text = t("moves.where.no_zone", who=who("no_zone_of"))
    elif "adjacent_to" in where:
        text = t("moves.where.adjacent", who=who("adjacent_to"))
    elif "nearest_to" in where:
        text = t("moves.where.nearest", who=who("nearest_to"))
    else:
        text = t("moves.where.default")
    if len(req.options) == 1:
        text += " (" + t("common.or").join(_spot(session, o, (req.extra["fighter"],)) for o in req.options) + ")"
    return text


def _title(session, req: ChoiceRequest) -> str:
    card = request_card(session.game, req)
    return f"{card.title}: " if card is not None else ""


def instruction(session, req: ChoiceRequest) -> str:
    g, fid = session.game, req.extra["fighter"]
    f = g.fighters[fid]
    name = session._name(f)
    head = _title(session, req)
    optional = t("moves.optional") if req.min == 0 else ""
    if req.extra.get("op") == "move":
        steps = req.extra["steps"]
        how = t("moves.how.up_to" if req.extra.get("up_to", True) else "moves.how.exactly")
        through = t("moves.through") if req.extra.get("through") else ""
        now = t("moves.now", spot=_spot(session, f.pos, (fid,))) if f.pos is not None else ""
        return t("moves.move", head=head, name=name, how=how, squares=_plural(steps), through=through,
                 optional=optional, now=now)
    tag = "moves.put" if req.extra.get("op") in ("revive", "summon") else "moves.place"
    return t(tag, head=head, name=name, where=where_text(session, req))


def start(session, req: ChoiceRequest) -> None:
    session.say(instruction(session, req), ChatKind.YOUR_TURN)


def reprompt(session, req: ChoiceRequest) -> str:
    return t("common.still_pending", text=instruction(session, req))


def status(session, req: ChoiceRequest) -> str:
    name = session._name(session.game.fighters[req.extra["fighter"]])
    return panel_text(t("moves.status.move" if req.extra.get("op") == "move" else "moves.status.place", name=name))


def view(session, req: ChoiceRequest) -> tuple[dict, dict]:
    """The choice slots while the human moves by hand: Done, and Don't move when the move may be skipped."""
    from .session_choices import CHOICE_IDS
    states = {ident: (False, False) for ident in CHOICE_IDS}
    labels = {CHOICE_IDS[0]: panel_text(t("btn.done"), 40)}
    states[CHOICE_IDS[0]] = (True, True)
    if req.min == 0:
        states[CHOICE_IDS[1]], labels[CHOICE_IDS[1]] = (True, True), panel_text(t("btn.skip"), 40)
    return states, labels


def _why_not_legal(session, req: ChoiceRequest, f, dest: int) -> str:
    g, name = session.game, session._name(f)
    holder = next((o for o in g.fighters.values() if o.alive and o is not f and o.pos == dest), None)
    if holder is not None:
        return t("moves.occupied", holder=session._name(holder), spot=_spot(session, dest, (holder.fid, f.fid)), name=name)
    if req.extra.get("op") != "move":
        return t("moves.must_end", name=name, where=where_text(session, req), spot=_spot(session, dest, (f.fid,)))
    steps, d = req.extra["steps"], g.board.distance(f.pos, dest)
    if d > steps:
        return t("moves.too_far", name=name, squares=_plural(d), steps=steps)
    if not req.extra.get("up_to", True) and d < steps:
        return t("moves.too_short", name=name, squares=_plural(d), steps=steps)
    if not req.extra.get("through"):
        return t("moves.no_path", name=name, squares=_plural(steps))
    return t("moves.cannot_end", name=name)


def verdict(session, req: ChoiceRequest) -> tuple[int | None, str | None]:
    """(destination, None) when the table shows exactly the one allowed move, else (None, what is wrong). Reads the
    snapshot only; the engine's positions are the baseline (nothing has been applied yet)."""
    g = session.game
    f = g.fighters[req.extra["fighter"]]
    name = session._name(f)
    pieces = session._table_pieces()
    for fid, other in g.fighters.items():
        if other is f or not other.alive or other.pos is None:
            continue
        info = pieces.get(fid) or {}
        if session._on_board(info) and info.get("space") != other.pos:
            return None, t("moves.also_moved", other=session._name(other), spot=_spot(session, other.pos, (fid,)))
    info = pieces.get(f.fid) or {}
    if not info.get("found"):
        return None, t("moves.not_found", name=name)
    if not session._on_board(info):
        return None, t("moves.off_board", name=name, dist=f"{info['dist']:.1f}")
    dest = info["space"]
    if f.alive and dest == f.pos:
        if dest in req.options:
            return dest, None
        skip = t("moves.skip_or") if req.min == 0 else ""
        return None, t("moves.not_moved", name=name, skip=skip)
    if dest not in req.options:
        return None, _why_not_legal(session, req, f, dest) + t("moves.fix_suffix")
    return dest, None


def press(session, paused, index) -> None:
    """A click on the choice buttons while the human moves by hand: 1 is Done, 2 is Don't move."""
    req = manual_request(session)
    if isinstance(index, float) and index.is_integer():
        index = int(index)
    if index == 1:
        done(session, paused, req)
    elif index == 2 and req.min == 0:
        name = session._name(session.game.fighters[req.extra["fighter"]])
        session._answer_choice(paused, [])
        session.say(t("moves.stays", name=name), ChatKind.MOVE)
    else:
        session.say(t("choice.no_such_button"), ChatKind.WARNING)


def done(session, paused, req: ChoiceRequest) -> None:
    """Done: validate; only a valid table reaches the engine. A wrong one changes nothing and says why."""
    dest, why = verdict(session, req)
    if dest is None:
        session.say(why, ChatKind.WARNING)
        return
    fid = req.extra["fighter"]
    session.hand_moved[fid] = dest              # the table already shows it: the projection must not move it again
    mark = len(session.messages)
    session._answer_choice(paused, [dest])
    again = manual_request(session)
    if again is not None and again.key == req.key:     # refused (rolled back): still waiting, nothing moved
        session.hand_moved.pop(fid, None)
        return
    f = session.game.fighters[fid]
    session.say(t("moves.lands", name=session._name(f), spot=_spot(session, dest, (fid,))), ChatKind.MOVE)
    session.messages.insert(mark, session.messages.pop())
