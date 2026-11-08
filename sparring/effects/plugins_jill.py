"""Jill Trent's plugins (docs/effects-dsl.md section 33): what her cards and gadgets do with the top cards of the decks.

  * `jill:hypnoray`: Hypnoray Blaster (and Sisters in Arms, which lends it to Daisy): reveal the top card of the opponent's
    deck and add its BOOST value to the value of the owner's card in the running combat.
  * `jill:reveal_tops` + the test `higher_boost` (Battle of Wits): reveal the top card of both decks; the test says whether the
    owner's card has the higher BOOST value.
  * `jill:insightful_deduction`: reveal the top 3 cards of the opponent's deck, put one on the bottom and the rest on top in
    the order the owner says.

Whose deck is real. The engine's player (the bot, a simulation, a search clone) has the deck order in the engine: its top
cards are read from it. The table player's deck is physical and the engine's copy of it is placeholders: its top cards are
read from the table through `Game.deck_reader(player, n)` (`session_peek.read_top`), and a table that cannot be read (a clone,
a failed read) shows nothing, so the effect does nothing rather than guess. The bot never reads a card of the human's deck
unless one of these effects says so, at the moment it resolves. What the owner saw is kept only as `KnownHand.top_of_deck`,
which the next draw or shuffle of that deck erases.

Table side: a reveal is said in the chat (intent `reveal_top`); a reorder of the bot's deck by the human is pinned in the
session (intent `deck_order`, `session_jill`), a reorder of the human's deck by the bot is told to the human, who does it by
hand (the real deck is theirs)."""
from __future__ import annotations

from ..i18n import t
from . import modifiers, table
from .model import EffectError
from .ops_core import plugin, plugin_condition

TOP = 3          # Insightful Deduction looks at this many cards


def top_cards(game, player: int, n: int) -> list:
    """The first `n` cards of `player`'s deck, top first: the engine's for the engine's player, the table's for the table
    player. [] when they cannot be known."""
    st = game.players[player]
    n = min(n, len(st.deck))
    if n <= 0:
        return []
    if not table.physical(game, player):
        return list(st.deck[:n])
    reader = game.deck_reader
    ids = None if reader is None else reader(player, n)
    ids = [ids] if isinstance(ids, int) else list(ids or [])
    cards = [next((c for c in st.full_set if c.card_id == i), None) for i in ids[:n]]
    return cards if all(c is not None for c in cards) else []


def show(game, viewer: int, holder: int, cards: list) -> None:
    """`viewer` sees the top cards of `holder`'s deck (the chat says which; the viewer's knowledge of that deck is the
    revealed prefix). Revealing one's own deck tells the rival."""
    ids = [c.card_id for c in cards]
    seer = game.players[viewer if viewer != holder else 1 - holder].known
    seer.set_top(ids)
    table.intent(game, op="reveal_top", player=holder, viewer=viewer, cards=ids)


def _side(run) -> str:
    return "atk" if run.ctx.played_as == "attack" else "def"


@plugin("jill:hypnoray")
def _hypnoray(run, game, spec):
    """Reveal the top card of the opponent's deck; the owner's card is worth its BOOST value more in this combat."""
    flow = getattr(run, "flow", None)
    if flow is None:
        raise EffectError("jill:hypnoray: only inside a combat")
    seen = top_cards(game, 1 - run.ctx.owner, 1)
    if not seen:
        return
    show(game, run.ctx.owner, 1 - run.ctx.owner, seen)
    modifiers.add_value(flow, _side(run), seen[0].boost, t("fx.jill.hypnoray", title=seen[0].title))


@plugin("jill:reveal_tops")
def _reveal_tops(run, game, spec):
    """Reveal the top card of the owner's deck and of the opponent's; their BOOST values wait for the test `higher_boost`."""
    owner = run.ctx.owner
    mine, theirs = top_cards(game, owner, 1), top_cards(game, 1 - owner, 1)
    for holder, cards in ((owner, mine), (1 - owner, theirs)):
        if cards:
            show(game, owner, holder, cards)
    run.flags["tops"] = [mine[0].boost if mine else None, theirs[0].boost if theirs else None]


@plugin_condition("jill:reveal_tops")
def _higher_boost(game, run, key: str) -> bool:
    """`higher_boost`: both top cards were revealed and the owner's has the strictly higher BOOST value."""
    if key != "higher_boost":
        raise EffectError(f"jill:reveal_tops: unknown key {key!r}")
    mine, theirs = (run.flags.get("tops") or [None, None])
    return mine is not None and theirs is not None and mine > theirs


@plugin("jill:insightful_deduction")
def _insightful_deduction(run, game, spec):
    """Reveal the top 3 cards of the opponent's deck, put one on the bottom and the rest on top in any order. Every decision
    is asked before the first mutation (the run may be repeated after a pause)."""
    owner, rival = run.ctx.owner, 1 - run.ctx.owner
    seen = top_cards(game, rival, TOP)
    if not seen:
        return
    ids = [c.card_id for c in seen]
    bottom = run.ask(game, "cards", owner, ids, 1, 1, "put one on the bottom", zone="deck", purpose="bottom", of=rival)[0]
    rest = [i for i in ids if i != bottom]
    top = rest if len(rest) < 2 else run.ask(game, "order", owner, rest, len(rest), len(rest), "order the rest",
                                              ordered=True, zone="deck", purpose="order", of=rival, position="top")
    show(game, owner, rival, seen)
    by_id = {c.card_id: c for c in seen}
    st = game.players[rival]
    if not table.physical(game, rival):
        for c in seen:
            st.deck.remove(c)
        st.deck[:0] = [by_id[i] for i in top]
        st.deck.append(by_id[bottom])
        game.players[owner].known.set_top(list(top))
    else:
        game.players[owner].known.set_top(list(top))
    table.intent(game, op="deck_order", player=rival, top=list(top), bottom=bottom, owner=owner)
