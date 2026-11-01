"""Table mode (E2): the human's cards on the interpreter.

The human plays at a real table, so an op that touches what only they can see or hold is not performed by the
engine: a pick out of their hand (the engine's copy of it is virtual), a card their deck's order decides (Read The
Bones), the destination of their own miniature (they move it by hand). Those ops leave a JSON-safe note in
`run.flags["table"]` (`note`) and the session says it in the chat's language (`lines`); the table sync reconciles the engine
afterwards (hand counts, the discard pile, the miniatures' spaces). Everything else runs in the engine: damage and
heals (the dials), the bot's cards and pieces, statuses, values, draws (counted; the session deals the real cards to
the human's hand, `Session._deal_owed_draws`).

Who is "the table player" is what the engine already knew: the player whose controller decides at the table
(`Controller.human`); a simulation or a search clone has none, so there every card is fully resolved."""
from __future__ import annotations

from ..i18n import plural, t


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


HAND_OPS = ("choose", "return_to_deck", "search_deck")


def hand_step_pending(run) -> bool:
    """The run left the human a step on their own hand or deck (a card to put back, a pile to look through, a discard
    they owe): what a later effect reads of that hand has to wait until they have done it."""
    return bool(run.flags.get("physical_discard")) or any(n["op"] in HAND_OPS for n in notes(run))


# ---------------------------------------------------------------- what the chat says

def _where(where) -> str:
    if not isinstance(where, dict):
        return t("tbl.where.default")
    if where.get("any"):
        return t("tbl.where.any")
    if "zone_of" in where:
        who = where["zone_of"]
        return t("tbl.where.zone_hero") if who in ("hero", "this") else t("tbl.where.zone", who=who)
    if "nearest_to" in where:
        who = where["nearest_to"]
        return t("tbl.where.nearest_hero") if who in ("hero", "this") else t("tbl.where.nearest", who=who)
    if "adjacent_to" in where:
        return t("tbl.where.adjacent")
    return t("tbl.where.default")


def line(n: dict) -> str:
    op = n["op"]
    if op == "move":
        how = t("tbl.up_to" if n.get("up_to", True) else "tbl.exactly")
        through = t("tbl.through") if n.get("through") else ""
        return t("tbl.move", fid=n["fid"], how=how, squares=plural(n["amount"], "noun.space"), through=through)
    if op == "place":
        return t("tbl.place", fid=n["fid"], where=_where(n.get("where")))
    if op in ("revive", "summon"):
        return t("tbl.put", fid=n["fid"], where=_where(n.get("where")), hp=f"{n['hp']:g}")
    if op == "choose":
        return t("tbl.keep", cards=plural(n["amount"], "noun.card"))
    if op == "return_to_deck":
        where = t({"top": "tbl.deck.top", "bottom": "tbl.deck.bottom"}.get(n["position"], "tbl.deck.shuffle"))
        if n.get("rest"):
            what = t("tbl.what.rest")
        elif n.get("all"):
            what = t("tbl.what.all")
        else:
            what = t("tbl.what.amount", upto=t("tbl.up_to") if n.get("up_to") else "", cards=plural(n["amount"], "noun.card"))
        order = t("tbl.ordered") if n.get("ordered") and n.get("amount", 1) != 1 else ""
        return t("tbl.return", what=what, where=where, order=order)
    if op == "look_deck":
        return t("tbl.look_deck.top" if n.get("top", True) else "tbl.look_deck.bottom", cards=plural(n["amount"], "noun.card"))
    if op == "deck_to_bottom":
        return t("tbl.deck_to_bottom", cards=plural(n["amount"], "noun.card"))
    if op == "search_deck":
        look = t("tbl.look.all") if n["look"] == "all" else t("tbl.look.first", n=n["look"])
        rest = t({"bottom_random": "tbl.rest.bottom_random", "bottom_ordered": "tbl.rest.bottom_ordered",
                  "top_ordered": "tbl.rest.top_ordered", "shuffle": "tbl.rest.shuffle"}.get(n["rest"], "tbl.rest.bottom"))
        return t("tbl.search", look=look, take=plural(n["take"], "noun.card"), rest=rest)
    return op


def lines(run) -> list[str]:
    return [line(n) for n in notes(run)]
