"""Little Red at the table: the loose Basket card and the order of her pile (docs/heroes/little-red-riding-hood.md, Table).

  * The Basket (a card of her bag, CardID 17600 like the first card of every sheet-176 deck) lies in her discard zone. It is told from a card by its GUID,
    never by its CardID: `strip` takes it out of every read of a pile, so no flow that counts the pile (a manual discard from the bot's hand, a ruse,
    the adoption of a table) calls it foreign or counts it. It is found by GUID inside a Deck too: the GUID of a card in a Deck is kept in the Deck's data.
  * `aside` puts it back on its own resting spot before a restart (`lua_little_red.basket_aside`), taking it out of a Deck first.
  * `landed` marks cards that reached the table player's pile in one step when their order is unknown: the next line that reads the basket asks which one
    is on top (`plugins_little_red.ambiguous_top`)."""
from __future__ import annotations

from .effects.plugins_little_red import symbol_of
from .i18n import t
from .tts import lua_little_red
from .tts.hero_table import load_hero_table
from .tts.lua import ChatKind

SLUG = "little-red-riding-hood"
TOKEN = "basket"


def _sides(session) -> list[tuple[str, str]]:
    """(side, hero slug) of each side that plays Little Red."""
    g = session.game
    return [("bot" if p == session.bot else "human", g.players[p].hero.slug) for p in (0, 1) if g.players[p].hero.slug == SLUG]


def basket_guids(session) -> frozenset[str]:
    return frozenset(load_hero_table(slug).tokens[TOKEN] for _, slug in _sides(session))


def strip(session, rows):
    """`rows` of a read of a discard pile without the Basket (by GUID)."""
    guids = basket_guids(session)
    if not guids or not isinstance(rows, list):
        return rows
    return [r for r in rows if not (isinstance(r, dict) and r.get("guid") in guids)]


def aside(session) -> None:
    """Before a restart: the Basket of each side back on its own spot, outside every Deck. A Basket that is nowhere is said, the restart goes on
    (it is not a card: the game does not need it)."""
    for side, slug in _sides(session):
        table = load_hero_table(slug)
        slot = (table.token_slots.get(TOKEN, {}).get(side) or [None])[0]
        if slot is None:
            continue
        (pos, rot) = slot
        res = session._w(lua_little_red.basket_aside(table.tokens[TOKEN], tuple(pos), tuple(rot)), "cards").result
        if not isinstance(res, dict) or not res.get("found"):
            session.say(t("lr.basket_missing", side=t("sess.side.bot" if side == "bot" else "sess.side.human")), ChatKind.WARNING)


def landed(session, cards: list) -> None:
    """Cards that came onto the table player's pile in the same step: when two of them show different symbols the engine cannot know which one is on top."""
    g = session.game
    if g.players[session.human].hero.slug != SLUG or len(cards) < 2:
        return
    if len({symbol_of(c) for c in cards}) >= 2:
        g.fx.pile_unsure[session.human] = [c.card_id for c in cards]


def start(session) -> None:
    """The first turn of a game: a human Little Red is told where to keep the Basket (off the stacking cards of her pile)."""
    if any(side == "human" for side, _ in _sides(session)):
        session.say(t("lr.basket_keep"), ChatKind.WARNING)
