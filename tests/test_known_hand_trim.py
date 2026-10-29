"""Live-session routes where a card leaves the human hand face down, or the virtual hand is trimmed: what the bot
saw degrades to "possible" (never a ghost outside the hand), and Ivan's Wildfire exception for the hand limit."""
from sparring.heroes import load_hero
from sparring.tts.ui import Event
from test_review3 import maneuver_plan
from test_session import Act, rig  # noqa: F401


def test_a_hand_that_shrinks_on_the_table_without_a_discard_degrades_the_seen_cards(rig):
    """Glimpse Of Hell / Pyrotechnics on the table: the real hand lost a card face down."""
    session, table, game = rig
    hand = list(game.players[1].hand)
    game.observe_hand(0, hand)
    table.human_count = len(hand) - 1
    session.handle(Event.END_ACTION)
    known = game.players[0].known
    assert game.hidden_hand(0)[0] == [] and sorted(known.possible) == sorted(c.card_id for c in hand)
    assert (known.possible_lo, known.possible_hi) == (len(hand) - 1, len(hand) - 1)
    assert len(game.players[1].hand) == len(hand) - 1


def test_limit_waived_trim_degrades_instead_of_keeping_a_ghost(rig, monkeypatch):
    session, table, game = rig
    st = game.players[1]
    for c in list(st.deck)[:4]:
        st.deck.remove(c)
        st.hand.append(c)
    table.human_count = len(st.hand)
    n = len(st.hand)
    game.observe_hand(0, list(st.hand))
    session.limit_waived = True
    table.human_count = 7                      # the table shows the hand at the limit the human waived to
    game.turn, game.actions_left = 1, 0
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    session._after_human_action()
    known = game.players[0].known
    assert n > 7 and len(st.hand) == 7 and game.hidden_hand(0)[0] == []
    assert (known.possible_lo, known.possible_hi) == (7, 7)


def test_burning_card_discarded_for_the_hand_limit_stays_in_the_discard_under_wildfire(rig, monkeypatch):
    """The session neither offers the 'it came back to my hand' leniency for the hand limit nor accepts it."""
    session, table, game = rig
    game.players[1].hero = load_hero("liz-sherman")
    table.human_count = 9
    maneuver_plan(session, monkeypatch)
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert session.pending_discard["kind"] == "limit" and not any("Wildfire" in m for m in msgs)
    for _ in range(3):
        msgs = session.handle(Event.END_ACTION)
        assert session.pending_discard is not None and any("Aun falta" in m for m in msgs)
        assert not any("Wildfire" in m or "otra vez" in m for m in msgs)
