"""A RESTART with the Basket merged into her pile's Deck, on the lupa stub of TTS. `reset_plan` and `reset_deck` count a Deck only when EVERY card in it is the
side's, so a pile Deck that holds the Basket (a card that is nobody's) is neither counted nor gathered: the plan says 1 card short and the restart is
refused. `basket_aside` takes the Basket out first, so the same pile is 29 ours and the restart gathers all 30."""
from __future__ import annotations

from sparring.tts import lua, lua_little_red
from test_review9 import BOT_ID, SCOPE, rt, run  # noqa: F401  (rt is a fixture)

BASKET = "51f3b8"
SPOT = (20.8, 2.0, -14.0)


def table_with_the_basket_in_the_pile(rt):
    rt.execute(f"""
local pile = {{{{cid = 17600, guid = '{BASKET}', owner = 'basket'}}}}
for i = 1, 29 do table.insert(pile, {{cid = 17600 + i, guid = 'p' .. i, owner = 'medusa'}}) end
mkobj({{guid = 'pile01', type = 'Deck', cards = pile, pos = {{x = 14, y = 1, z = 6}}}})
mkobj({{guid = 'd42056', type = 'Card', cid = 17600, owner = 'medusa', pos = {{x = 11.5, y = 1, z = 12}}}})
""")


def plan(rt):
    return run(rt, lua.reset_plan([("d42056", (11.5, 12.0), lua.BOT_CARD_IDS, BOT_ID)], scope=SCOPE))[0]


def test_with_the_basket_in_the_pile_deck_the_plan_is_short_and_the_pile_is_not_gathered(rt):
    table_with_the_basket_in_the_pile(rt)
    assert plan(rt)["total"] == 1
    res = run(rt, lua.reset_deck("d42056", (11.5, 12.0), lua.BOT_CARD_IDS, identity=BOT_ID, scope=SCOPE))
    assert res["quantity"] == 1


def test_after_the_basket_is_taken_out_the_plan_counts_the_thirty_and_the_reset_gathers_them(rt):
    table_with_the_basket_in_the_pile(rt)
    assert run(rt, lua_little_red.basket_aside(BASKET, SPOT, (0, 90, 0))) == {"found": True, "taken": True, "moved": True}
    assert plan(rt)["total"] == 30
    res = run(rt, lua.reset_deck("d42056", (11.5, 12.0), lua.BOT_CARD_IDS, identity=BOT_ID, scope=SCOPE))
    assert res["quantity"] == 30
    basket = rt.globals().getObjectFromGUID(BASKET)
    assert basket is not None and round(basket.pos.x, 2) == SPOT[0]            # still on its own spot: it did not go into the draw deck
