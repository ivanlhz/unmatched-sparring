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


def make_known(game, player: int, card, keep: tuple = ()) -> None:
    """The table player's hand is virtual: when a card is seen (played, boosted, put on their discard pile) it is
    swapped with one of the virtual hand (never with those of `keep`, already known in this same step)."""
    st = game.players[player]
    if card in st.hand:
        return
    if card in st.discard:                    # the card is face down on the table: the discard read was old
        st.discard.remove(card)
    elif card in st.deck:
        st.deck.remove(card)
    known = game.players[1 - player].known.seen
    spare = [c for c in st.hand if c not in keep and c.card_id not in known] or [c for c in st.hand if c not in keep]
    if spare:
        st.hand.remove(spare[-1])
        st.deck.append(spare[-1])
    st.hand.append(card)


def take_from_deck(game, player: int, card) -> None:
    """A card of the table player's REAL deck went into play or onto a pile (a blind boost, a card a reveal found): the
    engine's copy of the deck is placeholders, so it gives up that card; if it stands in the virtual hand, a placeholder of
    the deck takes its place there (the hand did not change). What the rival knew of their top card is stale."""
    st = game.players[player]
    known = game.players[1 - player].known
    if card in st.deck:
        st.deck.remove(card)
    elif card in st.hand:
        st.hand.remove(card)
        spare = next((c for c in reversed(st.deck) if c.card_id not in known.seen), None) or (st.deck[-1] if st.deck else None)
        if spare is not None:
            st.deck.remove(spare)
            st.hand.append(spare)
    elif card in st.discard:
        st.discard.remove(card)
    known.clear_top()


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
        if where.get("other"):
            return t("tbl.where.zone_hero_other") if who == "hero" else t("tbl.where.zone_other", who=who)
        return t("tbl.where.zone_hero") if who in ("hero", "this") else t("tbl.where.zone", who=who)
    if "no_zone_of" in where:
        who = where["no_zone_of"]
        return t("tbl.where.no_zone_hero") if who in ("hero", "this") else t("tbl.where.no_zone", who=who)
    if "nearest_to" in where:
        who = where["nearest_to"]
        return t("tbl.where.nearest_hero") if who in ("hero", "this") else t("tbl.where.nearest", who=who)
    if "next_to_nearest_foe" in where:
        return t("tbl.where.next_to_foe")
    if "adjacent_to" in where:
        return t("tbl.where.adjacent")
    return t("tbl.where.default")


def line(n: dict) -> str:
    op = n["op"]
    if op == "move":
        how = t("tbl.up_to" if n.get("up_to", True) else "tbl.exactly")
        through = t("tbl.through") if n.get("through") else ""
        return t("tbl.move", fid=n["fid"], how=how, squares=plural(n["amount"], "noun.space"), through=through)
    if op == "move_none":
        return t("tbl.move_none", fid=n["fid"], squares=plural(n["amount"], "noun.space"))
    if op == "place":
        return t("tbl.place", fid=n["fid"], where=_where(n.get("where")))
    if op == "swap":
        return t("tbl.swap", fid=n["fid"], other=n["other"])
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
    if op == "shuffle_deck":
        return t("tbl.shuffle_deck")
    if op == "look_foreign_deck":
        return t("tbl.look_foreign_deck")
    if op == "search_deck":
        look = t("tbl.look.all") if n["look"] == "all" else t("tbl.look.first", n=n["look"])
        rest = t({"bottom_random": "tbl.rest.bottom_random", "bottom_ordered": "tbl.rest.bottom_ordered",
                  "top_ordered": "tbl.rest.top_ordered", "shuffle": "tbl.rest.shuffle"}.get(n["rest"], "tbl.rest.bottom"))
        return t("tbl.search", look=look, take=plural(n["take"], "noun.card"), rest=rest)
    return op


def lines(run) -> list[str]:
    return [line(n) for n in notes(run)]
