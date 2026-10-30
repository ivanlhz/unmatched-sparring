"""Table mode (E2): the human's cards on the interpreter.

The human plays at a real table, so an op that touches what only they can see or hold is not performed by the
engine: a pick out of their hand (the engine's copy of it is virtual), a card their deck's order decides (Read The
Bones), the destination of their own miniature (they move it by hand). Those ops leave a JSON-safe note in
`run.flags["table"]` (`note`) and the session says it in Spanish (`lines`); the table sync reconciles the engine
afterwards (hand counts, the discard pile, the miniatures' spaces). Everything else runs in the engine: damage and
heals (the dials), the bot's cards and pieces, statuses, values, draws (counted; the session deals the real cards to
the human's hand, `Session._deal_owed_draws`).

Who is "the table player" is what the engine already knew: the player whose controller decides at the table
(`Controller.human`); a simulation or a search clone has none, so there every card is fully resolved."""
from __future__ import annotations


def table_player(game) -> int | None:
    for player, ctrl in game.controllers.items():
        if getattr(ctrl, "human", False):
            return player
    return None


def physical(game, player: int) -> bool:
    return table_player(game) == player


def hand_pick_is_physical(game, run, sel) -> bool:
    """A choice out of the table player's own hand at their own choice, at random or of all of it: the engine never
    names those cards (its copy of the hand is placeholders), the table settles it."""
    from .select import player_of
    if not isinstance(sel, dict) or sel["zone"] != "hand":
        return False
    player = player_of(game, run, sel["player"])
    if not physical(game, player):
        return False
    pick = sel.get("pick", "chosen")
    if pick == "chosen":
        return player_of(game, run, sel.get("chooser", "owner")) == player
    return pick in ("random", "all")


def piece_is_physical(game, chooser: int, fighter) -> bool:
    """The table player decides where their own miniature goes: they move it by hand. A rival effect that moves it
    (the bot chooses) or their own effect on a bot's piece runs in the engine."""
    return physical(game, chooser) and fighter.owner == chooser


def start_of_turn_is_physical(game, player: int, trig: dict) -> bool:
    """The table player's start-of-turn ability (Hellboy's ANUNG discard and move, Wildfire's bottom card) reads their
    real hand or an unknown discard: it is theirs on the table, announced by the session. A trigger that only draws
    (OCCULT DETECTIVE's optional draw) is not: the engine asks on the panel and the session deals the cards."""
    from .model import walk_ops
    only_draws = all(o["op"] in ("optional", "draw") for o in walk_ops(trig["ops"]))
    return physical(game, player) and trig["when"]["event"] == "start_of_turn" and not only_draws


def intent(game, **fields) -> None:
    """What an op just did to the table, for the session's translators (`session_translators`): {"op", ...}. Only a
    game a session listens to keeps them (`fx.intents` is None in a clone); the session drains them at each
    projection and checks them against the before/after diff."""
    if game.fx.intents is not None:
        game.fx.intents.append(fields)


def note(run, **fields) -> None:
    run.flags.setdefault("table", []).append(fields)


def notes(run) -> list[dict]:
    return list(run.flags.get("table") or [])


# ---------------------------------------------------------------- what the chat says (Spanish)

def _n(n: int, word: str = "carta") -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _where(where) -> str:
    if not isinstance(where, dict):
        return "donde diga la carta"
    if where.get("any"):
        return "cualquier casilla"
    if "zone_of" in where:
        who = where["zone_of"]
        return "la zona de tu heroe" if who in ("hero", "this") else f"la zona de {who}"
    if "nearest_to" in where:
        who = where["nearest_to"]
        return "lo mas cerca posible de tu heroe" if who in ("hero", "this") else f"lo mas cerca posible de {who}"
    if "adjacent_to" in where:
        return "una casilla adyacente"
    return "donde diga la carta"


def line(n: dict) -> str:
    op = n["op"]
    if op == "move":
        how = "hasta " if n.get("up_to", True) else "exactamente "
        through = " (puede atravesar rivales)" if n.get("through") else ""
        return f"mueve a {n['fid']} {how}{_n(n['amount'], 'casilla')}{through}"
    if op == "place":
        return f"coloca a {n['fid']} en {_where(n.get('where'))}"
    if op in ("revive", "summon"):
        return f"pon a {n['fid']} en el tablero ({_where(n.get('where'))}) con {n['hp']:g} PV"
    if op == "choose":
        return f"quedate con {_n(n['amount'])} de tu mano"
    if op == "return_to_deck":
        where = {"top": "encima de tu mazo", "bottom": "en el fondo de tu mazo"}.get(n["position"], "en tu mazo y baraja")
        if n.get("rest"):
            what = "el resto de tu mano"
        elif n.get("all"):
            what = "toda tu mano"
        else:
            what = ("hasta " if n.get("up_to") else "") + _n(n["amount"]) + " de tu mano"
        order = " en el orden que quieras" if n.get("ordered") and n.get("amount", 1) != 1 else ""
        return f"pon {what} {where}{order}"
    if op == "search_deck":
        look = "todo tu mazo" if n["look"] == "all" else f"las {n['look']} primeras cartas de tu mazo"
        rest = {"bottom_random": "el resto al fondo en orden aleatorio", "bottom_ordered": "el resto al fondo en el orden que quieras",
                "top_ordered": "el resto encima en el orden que quieras", "shuffle": "baraja el mazo"}.get(n["rest"], "el resto al fondo")
        return f"mira {look}, pon {_n(n['take'])} en tu mano y {rest}"
    return op


def lines(run) -> list[str]:
    return [line(n) for n in notes(run)]
