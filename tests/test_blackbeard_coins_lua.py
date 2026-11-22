"""Blackbeard's doubloons on the table: the Lua builder `lua_blackbeard.set_doubloons` on the lupa stub. The coins are three tokens in one stack (a
Custom_Token_Stack nicknamed "Doubloon"); a token taken out of it gets a new GUID, so the script finds them by nickname. The ones Blackbeard holds
lie on the stack's spot, the Treasury's on the Treasury tile; the script leaves exactly the engine's count on the tile and moves the least it can."""
from __future__ import annotations

from sparring.tts import lua_blackbeard
from test_effects_bridge import rt, run, table_py  # noqa: F401  (rt is a fixture)

HELD = (1.7, 1.64, 20.4)
TREASURY = (1.8, 1.64, 18.0)


def stack(rt, qty=3, guid="a3b09d"):
    """The doubloon stack at the held spot: `takeObject` gives a new coin (new GUID) and leaves the stack one coin shorter."""
    rt.execute(f"""STACK_QTY = {qty}
local s = mkobj({{guid = '{guid}', type = 'Custom_Token_Stack', name = 'Doubloon', pos = Vector({HELD[0]}, {HELD[1]}, {HELD[2]})}})
s.getQuantity = function() return STACK_QTY end
s.takeObject = function(t)
  STACK_QTY = STACK_QTY - 1
  return mkobj({{guid = 'coin' .. STACK_QTY, type = 'Custom_Token', name = 'Doubloon', pos = Vector(t.position)}})
end""")


def coin(rt, guid, spot, k=0):
    rt.execute(f"mkobj({{guid = '{guid}', type = 'Custom_Token', name = 'Doubloon', pos = Vector({spot[0]}, {spot[1] + 0.25 * k}, {spot[2]})}})")


def spots(rt):
    """(coins on the Treasury tile, coins on the held spot, coins elsewhere), counted off the table."""
    return table_py(rt, f"""(function()
  local out = {{0, 0, 0}}
  for _, o in ipairs(getObjects()) do
    if o.name == 'Doubloon' then
      local q = o.getQuantity and o.getQuantity() or 0
      if q < 1 then q = 1 end
      local dt = math.sqrt((o.pos.x - {TREASURY[0]}) ^ 2 + (o.pos.z - {TREASURY[2]}) ^ 2)
      local dh = math.sqrt((o.pos.x - {HELD[0]}) ^ 2 + (o.pos.z - {HELD[2]}) ^ 2)
      local k = dt < 1 and 1 or (dh < 1 and 2 or 3)
      out[k] = out[k] + q
    end
  end
  return out
end)()""")


def put(rt, treasury):
    return run(rt, lua_blackbeard.set_doubloons("Doubloon", "a3b09d", HELD, TREASURY, treasury, ["Blue"]))


def test_a_whole_stack_at_the_start_gives_the_treasury_its_one_coin(rt):
    stack(rt)
    rt.execute("SEATED = {Blue = true}")
    out = put(rt, 1)
    assert (out["total"], out["treasury"], out["held"], out["moved"]) == (3, 1, 2, 1)
    assert spots(rt) == [1, 2, 0]


def test_a_coin_already_where_it_belongs_is_left_alone(rt):
    coin(rt, "c1", TREASURY)
    coin(rt, "c2", HELD)
    coin(rt, "c3", HELD, 1)
    rt.execute("SEATED = {Blue = true}")
    out = put(rt, 1)
    assert (out["moved"], out["guids"]) == (0, []) and spots(rt) == [1, 2, 0]


def test_a_coin_goes_from_the_treasury_to_blackbeard_and_back(rt):
    coin(rt, "c1", TREASURY)
    coin(rt, "c2", HELD)
    coin(rt, "c3", HELD, 1)
    out = put(rt, 0)
    assert (out["treasury"], out["held"], out["moved"]) == (0, 3, 1) and spots(rt) == [0, 3, 0]
    out = put(rt, 3)
    assert (out["treasury"], out["held"], out["moved"]) == (3, 0, 3) and spots(rt) == [3, 0, 0]


def test_a_coin_lying_somewhere_else_is_gathered_to_the_held_spot(rt):
    coin(rt, "c1", TREASURY)
    coin(rt, "c2", HELD)
    coin(rt, "c3", (9.0, 1.6, 9.0))
    out = put(rt, 1)
    assert spots(rt) == [1, 2, 0] and out["moved"] == 1


def test_no_coin_on_the_table_changes_nothing(rt):
    out = put(rt, 1)
    assert (out["total"], out["moved"]) == (0, 0)


def test_the_moved_coins_are_pinged_one_after_another(rt):
    coin(rt, "c1", HELD)
    coin(rt, "c2", HELD, 1)
    coin(rt, "c3", HELD, 2)
    rt.execute("SEATED = {Blue = true}")
    put(rt, 2)
    rt.execute("for _, f in ipairs(TIMERS) do f() end TIMERS = {}")
    pings = table_py(rt, "PINGS")
    assert len(pings) == 2 and all(p["color"] == "Blue" for p in pings)


def test_the_treasury_is_between_zero_and_three():
    for bad in (-1, 4, True, 1.5):
        try:
            lua_blackbeard.set_doubloons("Doubloon", "a3b09d", HELD, TREASURY, bad, ["Blue"])
        except ValueError:
            continue
        raise AssertionError(bad)
