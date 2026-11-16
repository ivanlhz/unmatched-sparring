"""The bottom card of bot-Liz's deck is the TABLE's, not the engine's (live 16/11: Wildfire burnt Fight Or Flight and then
Searing Clarity twice in a row, the last copies of her card list that were in no hand and no pile, while other cards lay at the
bottom of the real deck: a burning card back in the hand every turn). The engine's deck is rebuilt at every hand read in the
order of the card list; the real deck was shuffled. So the bot reads the bottom card of its real deck exactly when WILDFIRE or
Flame Lash is about to discard it, and at no other moment (Ivan's rule: a hidden card is only looked at when a card says so).

Batch sessions against the fake table with the ISMCTS bot, the path that runs live; the Lua on `lua_stub.lua`."""
import functools

import test_d3_table_effects as d3
from sparring import session_peek as peek
from sparring import sim
from sparring.ai_medusa import Act
from sparring.tts import lua
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import FxTable, bot_turn, human_hand
from test_effects_bridge import X_IDENT, X_IDS, deck, rt, run  # noqa: F401  (rt is a fixture)

HAND = ("Pyrotechnics", "Rekindle", "Fleeting Moments", "Evade", "Flame Lash")
bottom = functools.partial(lua.peek_deck_bottom, id_range=X_IDS, identity=X_IDENT)


class UnreadableDeck(FxTable):
    def do_peek_deck_bottom(self, s):
        return {"found": False, "deck": False}


def liz(tmp_path, monkeypatch, *physical_bottom, table_cls=FxTable, hellboy_far=True, bot="liz-sherman"):
    """Liz (ISMCTS bot) against Hellboy. The engine deck is in the order of the card list; the real deck holds the same
    cards with the ones titled in `physical_bottom` last (the last one is the bottom card)."""
    monkeypatch.setattr(d3, "MedusaAI", lambda me: sim.make_bot("ismcts", iterations=4, seed=1))
    session, table, game, fake, cfg, client = d3.build(tmp_path, bot, "hellboy", HAND if bot == "liz-sherman" else (),
                                                       table_cls=table_cls)
    session.cfg.wildfire_hold = 3.0
    assert session.cfg.batch
    st = game.players[0]
    used: set[int] = set()
    for title in physical_bottom:
        c = next(c for c in st.deck if c.title == title and c.card_id not in used)
        used.add(c.card_id)
        table.bot_deck.remove(c.card_id)
        table.bot_deck.append(c.card_id)
    if hellboy_far:
        game.fighters["hellboy"].pos = sorted(game.board.spaces)[-2]
        table.positions[cfg.nicknames["hellboy"]] = game.fighters["hellboy"].pos
    return session, table, game, fake, cfg, client


def end_human_turn(session, table):
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    return click(session, table, Event.END_ACTION)


def test_wildfire_discards_the_real_bottom_card_not_the_last_of_the_card_list(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = liz(tmp_path, monkeypatch, "Feint")
    feint, engine_last = table.bot_deck[-1], game.players[0].deck[-1]
    assert "burning" in engine_last.tags or engine_last.title == "Fight Or Flight", "her card list ends with those two"
    end_human_turn(session, table)
    assert feint in table.bot_discard and feint not in table.bot_hand
    assert feint in [c.card_id for c in game.players[0].discard]
    assert engine_last.card_id in table.bot_deck, "the card the engine had last is still in the real deck"
    liz_name = cfg.nicknames["liz"]
    assert f"Wildfire: {liz_name} descarta la carta del fondo: Feint" in " ".join(table.broadcasts)
    assert not [b for b in table.broadcasts if b.startswith("Es de fuego")]
    assert [b for b in table.broadcasts if b.startswith(f"No es de fuego: {liz_name} se ")], "not burning: Liz moves"
    assert table.sent.count("peek_deck_bottom") == 1, "one look at the bottom, when Wildfire asks for it"
    client.close()


def test_a_burning_bottom_card_on_the_table_returns_to_the_hand(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = liz(tmp_path, monkeypatch, "Fireball")
    fireball, engine_last = table.bot_deck[-1], game.players[0].deck[-1]
    end_human_turn(session, table)
    assert f"Wildfire: {cfg.nicknames['liz']} descarta la carta del fondo: Fireball" in " ".join(table.broadcasts)
    assert "Es de fuego: vuelve a la mano de " + cfg.nicknames["liz"] in " ".join(table.broadcasts)
    assert fireball not in table.bot_deck and fireball not in table.bot_discard
    assert engine_last.card_id not in table.bot_discard
    client.close()


def test_a_deck_that_cannot_be_read_falls_back_to_the_engine_order_and_says_so(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = liz(tmp_path, monkeypatch, "Feint", table_cls=UnreadableDeck)
    feint, engine_last = table.bot_deck[-1], game.players[0].deck[-1]
    msgs = end_human_turn(session, table)
    assert any("No he podido leer la carta del fondo de mi mazo" in m for m in msgs)
    assert f"Wildfire: {cfg.nicknames['liz']} descarta la carta del fondo: {engine_last.title}" in " ".join(table.broadcasts)
    assert feint in table.bot_deck
    client.close()


def test_the_bottom_is_not_read_when_the_deck_is_one_card(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = liz(tmp_path, monkeypatch)
    st = game.players[0]
    last = st.deck[-1]
    for c in st.deck[:-1]:
        d3.to_bot_discard(session, table, game, ids=[c.card_id])
    assert table.bot_deck == [last.card_id]
    end_human_turn(session, table)
    assert "peek_deck_bottom" not in table.sent, "a lone card is the bottom: nothing to look at"
    assert f"Wildfire: {cfg.nicknames['liz']} descarta la carta del fondo: {last.title}" in " ".join(table.broadcasts)
    client.close()


def test_a_bot_whose_cards_never_use_the_bottom_never_looks_at_it(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = liz(tmp_path, monkeypatch, bot="abe-sapien")
    end_human_turn(session, table)
    assert game.turn_no > 2 and "peek_deck_bottom" not in table.sent
    client.close()


def test_flame_lash_boosts_with_the_real_bottom_card(tmp_path, monkeypatch):
    """Wildfire burns the bottom card (Evade), then Flame Lash discards the card that is the bottom now (Feint, BOOST 3),
    not the last card of the engine's own order."""
    session, table, game, fake, cfg, client = liz(tmp_path, monkeypatch, "Feint", "Evade", hellboy_far=False)
    feint, evade = table.bot_deck[-2:]
    lash = next(c for c in game.players[0].hand if c.title == "Flame Lash")
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell")
    bot_turn(session, table, [Act("attack", fid="liz", target="hellboy", card=lash)])
    assert evade in table.bot_discard and feint in table.bot_deck, "Wildfire took only the bottom card"
    assert table.sent.count("peek_deck_bottom") == 1, "Flame Lash's card is not looked at before the combat resolves"
    table.face_down = []
    hp = game.hero(1).hp
    click(session, table, Event.REVEAL)
    assert table.sent.count("peek_deck_bottom") == 2
    assert feint in table.bot_discard and feint not in table.bot_deck
    assert game.hero(1).hp == hp - 4, "Flame Lash 1 + the BOOST 3 of the real bottom card"
    assert session.peek_pins["bottom"] == [], "the card left the deck: nothing stays known about its bottom"
    client.close()


def test_flame_lash_on_a_burning_bottom_card_takes_that_very_card_back_to_the_hand(tmp_path, monkeypatch):
    """The burning card adds nothing and Wildfire returns it: the table moves THAT card from under the deck to the hand,
    it does not deal the top card in its place."""
    session, table, game, fake, cfg, client = liz(tmp_path, monkeypatch, "Fireball", "Evade", hellboy_far=False)
    fireball, top = table.bot_deck[-2], table.bot_deck[0]
    lash = next(c for c in game.players[0].hand if c.title == "Flame Lash")
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell")
    bot_turn(session, table, [Act("attack", fid="liz", target="hellboy", card=lash)])
    table.face_down = []
    hp = game.hero(1).hp
    msgs = click(session, table, Event.REVEAL)
    assert fireball in table.bot_hand and fireball not in table.bot_deck and fireball not in table.bot_discard
    assert top == table.bot_deck[0], "the top card stays on the deck"
    assert fireball in [c.card_id for c in game.players[0].hand]
    assert game.hero(1).hp == hp - 1, "a burning card has no BOOST"
    assert any("El bot descarta Fireball de su mazo y vuelve a su mano." in m for m in msgs)
    assert not any("No pude sacar" in m or "no coincide" in m for m in msgs)
    client.close()


def test_the_card_read_for_a_combat_stays_last_through_a_hand_read_and_is_forgotten_after_it(tmp_path, monkeypatch):
    """A combat that stops at a choice reads the hand again (the engine deck is rebuilt) before Flame Lash's DURING runs."""
    session, table, game, fake, cfg, client = liz(tmp_path, monkeypatch, "Feint")
    feint, engine_last = table.bot_deck[-1], game.players[0].deck[-1]
    assert peek.read_bottom(session, pin=True) == feint
    session.read_bot_hand()
    assert game.players[0].deck[-1].card_id == feint
    peek.forget_bottom(session, feint)
    session.read_bot_hand()
    assert game.players[0].deck[-1] is engine_last and session.peek_pins["bottom"] == []
    client.close()


# ---------- the Lua (lupa, on the minimal table of lua_stub) ----------
def test_the_bottom_card_is_the_last_of_the_deck_and_nothing_moves(rt):
    deck(rt, n=4)
    assert run(rt, bottom("deck01")) == {"found": True, "id": 104, "quantity": 4}
    assert rt.eval('getObjectFromGUID("deck01").getQuantity()') == 4


def test_a_lone_card_is_its_own_bottom(rt):
    rt.execute("mkobj({guid = 'last', type = 'Card', cid = 105, owner = 'x', is_face_down = true})")
    assert run(rt, bottom("last")) == {"found": True, "id": 105, "quantity": 1}


def test_a_missing_deck_and_a_deck_with_a_foreign_card_read_nothing(rt):
    assert run(rt, bottom("nodeck")) == {"found": False, "deck": False}
    rt.execute("mkobj({guid = 'hdeck', type = 'Deck', cards = {{cid = 101, guid = 'h1', owner = 'x'}, {cid = 202, guid = 'h2', owner = 'h'}}})")
    assert run(rt, bottom("hdeck"))["found"] is False, "a deck with a card that is not ours is nobody's deck"
