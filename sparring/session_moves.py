"""Fighters the human's effects move, moved by the human's own hand (Ivan, 30/10).

The spaces of the board are not numbered, so "Casilla 17" on a panel button told the human nothing. When a card or
hero effect of the human relocates a fighter (his own or the bot's: move, place, revive, summon), the request is
not answered with a button per space: the chat says what to move and the limits, the panel shows Hecho (and "No
mover" when the move is optional), and the human moves the miniature on the table. At Hecho the bot reads the
snapshot and validates it against the engine's own options for that request (the right fighter, within the limit
along a legal path, onto a free space, nothing else moved). A valid move is applied to the engine as the answer; a
wrong one changes nothing, the chat says what is wrong and the panel keeps waiting. The bot never moves a piece for
the human in this flow: the table already shows the piece, so `Session.hand_moved` tells the projection not to
move it again.

The distance of a dropped piece to its nearest space is the only snap information the snapshot has (`dist`): a piece
farther than `off_board_dist` is rejected; two equidistant spaces cannot be told apart from it."""
from __future__ import annotations

from .effects.choose import ChoiceRequest
from .spaces import describe
from .tts.lua import ChatKind

HECHO = "Hecho"
SKIP = "No mover"
THROUGH_TEXT = " (puede atravesar luchadores rivales)"


def manual_request(session) -> ChoiceRequest | None:
    """The pending decision of the human when it asks where a fighter goes."""
    run = session.effect_run
    req = None if run is None else run.awaiting
    if req is None or req.kind != "space" or req.player != session.human:
        return None
    return req if req.extra.get("fighter") in session.game.fighters else None


def _plural(n: int) -> str:
    return f"{n} casilla{'s' if n != 1 else ''}"


def _spot(session, space, exclude=()) -> str:
    return describe(session.game, space, exclude, session._name)


def where_text(session, req: ChoiceRequest) -> str:
    """The spaces a placement allows, in words the human can find on the table."""
    g, where = session.game, req.extra.get("where") or {}

    def who(key):
        return session._name(g.fighters[where[key]]) if where.get(key) in g.fighters else "su heroe"
    if where.get("any"):
        text = "cualquier casilla libre"
    elif "zone_of" in where:
        text = f"la zona de {who('zone_of')}"
    elif "adjacent_to" in where:
        text = f"una casilla libre junto a {who('adjacent_to')}"
    elif "nearest_to" in where:
        text = f"la casilla libre mas cercana a {who('nearest_to')}"
    else:
        text = "donde diga la carta"
    if len(req.options) == 1:
        text += " (" + " o ".join(_spot(session, o, (req.extra["fighter"],)) for o in req.options) + ")"
    return text


def _title(session, req: ChoiceRequest) -> str:
    card = next((c for p in session.game.players for c in p.full_set if c.card_id == req.card_id), None)
    return f"{card.title}: " if card is not None else ""


def instruction(session, req: ChoiceRequest) -> str:
    g, fid = session.game, req.extra["fighter"]
    f = g.fighters[fid]
    name = session._name(f)
    head = _title(session, req)
    optional = " (o pulsa No mover si prefieres dejarla donde esta)" if req.min == 0 else ""
    if req.extra.get("op") == "move":
        steps = req.extra["steps"]
        how = "hasta" if req.extra.get("up_to", True) else "exactamente"
        through = THROUGH_TEXT if req.extra.get("through") else ""
        now = f" Ahora esta en {_spot(session, f.pos, (fid,))}." if f.pos is not None else ""
        return f"{head}Mueve a {name} {how} {_plural(steps)}{through} y pulsa Hecho{optional}.{now}"
    verb = "Pon en el tablero" if req.extra.get("op") in ("revive", "summon") else "Coloca"
    return f"{head}{verb} a {name} en {where_text(session, req)} y pulsa Hecho."


def start(session, req: ChoiceRequest) -> None:
    session.say(instruction(session, req), ChatKind.YOUR_TURN)


def reprompt(session, req: ChoiceRequest) -> str:
    return "Sigue pendiente: " + instruction(session, req)


def status(session, req: ChoiceRequest) -> str:
    name = session._name(session.game.fighters[req.extra["fighter"]])
    verb = "Mueve" if req.extra.get("op") == "move" else "Coloca"
    return f"{verb} a {name} en la mesa y pulsa Hecho"


def view(session, req: ChoiceRequest) -> tuple[dict, dict]:
    """The choice slots while the human moves by hand: Hecho, and No mover when the move may be skipped."""
    from .session_choices import CHOICE_IDS
    states = {ident: (False, False) for ident in CHOICE_IDS}
    labels = {CHOICE_IDS[0]: HECHO}
    states[CHOICE_IDS[0]] = (True, True)
    if req.min == 0:
        states[CHOICE_IDS[1]], labels[CHOICE_IDS[1]] = (True, True), SKIP
    return states, labels


def _why_not_legal(session, req: ChoiceRequest, f, dest: int) -> str:
    g, name = session.game, session._name(f)
    holder = next((o for o in g.fighters.values() if o.alive and o is not f and o.pos == dest), None)
    if holder is not None:
        return (f"Esa casilla esta ocupada por {session._name(holder)} ({_spot(session, dest, (holder.fid, f.fid))}): "
                f"mueve a {name} a una libre.")
    if req.extra.get("op") != "move":
        return f"{name} tiene que quedar en {where_text(session, req)}; ahora esta en {_spot(session, dest, (f.fid,))}."
    steps, d = req.extra["steps"], g.board.distance(f.pos, dest)
    if d > steps:
        return f"{name} se ha movido {_plural(d)}; el maximo es {steps}."
    if not req.extra.get("up_to", True) and d < steps:
        return f"{name} se ha movido {_plural(d)}; tiene que moverse exactamente {steps}."
    if not req.extra.get("through"):
        return (f"Desde donde estaba, {name} no llega a esa casilla en {_plural(steps)} sin atravesar luchadores "
                "rivales (esta carta no lo permite): busca otro camino o otra casilla.")
    return f"{name} no puede acabar en esa casilla."


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
            return None, (f"Se ha movido tambien {session._name(other)}: devuelvelo a su sitio "
                          f"({_spot(session, other.pos, (fid,))}) y pulsa Hecho.")
    info = pieces.get(f.fid) or {}
    if not info.get("found"):
        return None, f"No encuentro la miniatura de {name} en la mesa."
    if not session._on_board(info):
        return None, (f"{name} esta fuera del tablero (a {info['dist']:.1f} de la casilla mas cercana): "
                      "ponla sobre una casilla y pulsa Hecho.")
    dest = info["space"]
    if f.alive and dest == f.pos:
        if dest in req.options:
            return dest, None
        skip = " o pulsa No mover" if req.min == 0 else ""
        return None, f"{name} no se ha movido: muevela{skip}."
    if dest not in req.options:
        return None, _why_not_legal(session, req, f, dest) + " Corrigelo y pulsa Hecho."
    return dest, None


def press(session, paused, index) -> None:
    """A click on the choice buttons while the human moves by hand: 1 is Hecho, 2 is No mover."""
    req = manual_request(session)
    if isinstance(index, float) and index.is_integer():
        index = int(index)
    if index == 1:
        done(session, paused, req)
    elif index == 2 and req.min == 0:
        name = session._name(session.game.fighters[req.extra["fighter"]])
        session._answer_choice(paused, [])
        session.say(f"{name} se queda donde esta.", ChatKind.MOVE)
    else:
        session.say("Ese boton no corresponde a ninguna opcion.", ChatKind.WARNING)


def done(session, paused, req: ChoiceRequest) -> None:
    """Hecho: validate; only a valid table reaches the engine. A wrong one changes nothing and says why."""
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
    session.say(f"{session._name(f)} queda en {_spot(session, dest, (fid,))}.", ChatKind.MOVE)
    session.messages.insert(mark, session.messages.pop())
