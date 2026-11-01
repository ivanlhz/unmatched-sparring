"""The bot's known hand in the live session: the paths of session.py that move the human's cards without going
through Game.discard_card (reconciliation with the table, rollback of a failed Reveal) leave no phantom cards."""
from sparring.tts.ui import Event
from test_session import card, human_plays, rig  # noqa: F401


def test_a_seen_card_discarded_physically_leaves_the_known_hand_on_reconcile(rig):
    """Reviewer's scenario: the bot saw Excalibur; the human discards it on the table; End action reconciles it."""
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
    st.discard.append(excalibur)                               # without card_left_hand
    known, pool, missing = game.hidden_hand(0)
    assert known == [] and excalibur not in pool and missing == len(st.hand)


def test_a_failed_reveal_does_not_forget_seen_cards(rig):
    session, table, game = rig
    seen = card(game, 1, "Right Hand Of Doom")
    game.observe_hand(0, [seen])
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    human_plays(table, game, "Second Shot")                    # only Lobster Johnson's: Reveal fails
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
    table.human_count = 1                                      # the real hand goes down: the NOT seen ones are trimmed
    session.handle(Event.END_ACTION)
    assert st.hand == [seen] and [c.title for c in game.hidden_hand(0)[0]] == ["Pancakes!"]
