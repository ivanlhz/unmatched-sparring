"""La mano conocida del bot en la sesion en vivo: las vias de session.py que mueven cartas del humano sin pasar
por Game.discard_card (reconciliacion con la mesa, rollback de un Revelar fallido) no dejan cartas fantasma."""
from sparring.tts.ui import Event
from test_session import card, human_plays, rig  # noqa: F401


def test_a_seen_card_discarded_physically_leaves_the_known_hand_on_reconcile(rig):
    """Escenario del reviewer: el bot vio Excalibur; el humano la descarta en la mesa; Fin de accion la reconcilia."""
    session, table, game = rig
    excalibur = card(game, 1, "Excalibur")
    game.observe_hand(0, [excalibur])
    assert [c.title for c in game.hidden_hand(0)[0]] == ["Excalibur"]
    table.human_discard = [excalibur.card_id]
    session.handle(Event.END_ACTION)
    assert excalibur in game.players[1].discard
    assert game.players[0].known.seen == [] and game.players[0].known.turn_no is None
    known, pool, missing = game.hidden_hand(0)
    assert known == [] and excalibur not in pool and missing == len(game.players[1].hand)


def test_the_engine_defends_itself_even_if_a_card_is_moved_behind_its_back(rig):
    session, table, game = rig
    excalibur = card(game, 1, "Excalibur")
    game.observe_hand(0, [excalibur])
    st = game.players[1]
    if excalibur in st.hand:
        st.hand.remove(excalibur)
    elif excalibur in st.deck:
        st.deck.remove(excalibur)
    st.discard.append(excalibur)                               # sin card_left_hand
    known, pool, missing = game.hidden_hand(0)
    assert known == [] and excalibur not in pool and missing == len(st.hand)


def test_a_failed_reveal_does_not_forget_seen_cards(rig):
    session, table, game = rig
    seen = card(game, 1, "Right Hand Of Doom")
    game.observe_hand(0, [seen])
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Second Shot")                    # solo de Lobster Johnson: Revelar falla
    msgs = session.handle(Event.REVEAL)
    assert any("ilegal" in m for m in msgs) and session.pending is not None
    assert game.players[0].known.seen == [seen.card_id]
    assert [c.title for c in game.hidden_hand(0)[0]] == ["Right Hand Of Doom"]


def test_the_virtual_hand_keeps_seen_cards_when_it_is_trimmed(rig):
    session, table, game = rig
    seen = card(game, 1, "Pancakes!")
    game.observe_hand(0, [seen])
    st = game.players[1]
    if seen not in st.hand:
        (st.deck if seen in st.deck else st.discard).remove(seen)
        st.hand.append(seen)
    table.human_count = 1                                      # la mano real baja: se recortan las NO vistas
    session.handle(Event.END_ACTION)
    assert st.hand == [seen] and [c.title for c in game.hidden_hand(0)[0]] == ["Pancakes!"]
