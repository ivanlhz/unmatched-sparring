"""The first turn's start-of-turn ability (report of 6/11: a bot hero that starts did not use it). The game is built
before the table is set, so its first `begin_turn` must not fire Wildfire / ANUNG UN RAMA in the engine only: the
session fires them once the game really begins, and the bot's are shown on the table like any later turn."""
from sparring import play
from test_liz_wildfire_scene import liz_session, lupa  # noqa: F401
from test_multihero_bridge import config_for


def test_building_the_game_does_not_run_the_first_turn_triggers(tmp_path):
    cfg = config_for(tmp_path, "liz-sherman", "hellboy")
    g = play.build_game(cfg, "bot", 0)
    st = g.players[g.turn]
    assert g.actions_left == 2
    assert not st.discard and len(st.deck) + len(st.hand) == len(st.full_set), "Wildfire did not discard yet"


def test_the_bot_that_starts_uses_its_start_of_turn_ability_on_the_table(tmp_path, monkeypatch):
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=True)
    deck0 = len(game.players[0].deck)
    session.first_turn_pending, game.turn_no = True, 1
    session._start_first_turn()
    session.bot_stage = "start"
    session._bot_continue()
    assert len(game.players[0].deck) == deck0 - 1
    heads = [h for ops in table.msglog for h in ops]
    assert heads.index("discard_cards") < heads.index("return_card_to_hand"), "the Wildfire scene reaches the table"
    assert card.card_id in table.bot_hand
    assert any(t.startswith("Wildfire:") for t in table.broadcasts)
    client.close()


def test_a_human_that_starts_gets_its_triggers_once(tmp_path, monkeypatch):
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=False)
    calls = []
    monkeypatch.setattr(game, "start_first_turn", lambda: calls.append(game.turn))
    game.turn = 1
    session.first_turn_pending, game.turn_no = True, 1
    session._start_first_turn()
    session._start_first_turn()
    assert calls == [1] and not session.first_turn_pending
    client.close()


def test_a_table_error_before_the_first_trigger_fires_it_on_the_bot_retry(tmp_path, monkeypatch):
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=True)
    deck0 = len(game.players[0].deck)
    session.first_turn_pending, session.bot_stage, game.turn_no = True, "start", 1    # the game start failed before firing it
    session._bot_continue()                                           # End action's retry
    assert len(game.players[0].deck) == deck0 - 1 and card.card_id in table.bot_hand
    assert not session.first_turn_pending
    client.close()


def test_the_pending_first_turn_survives_a_save(tmp_path, monkeypatch):
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=True)
    session.first_turn_pending, game.turn_no = True, 1
    d = session.to_dict()
    session.first_turn_pending = False
    session.load_dict(d)
    assert session.first_turn_pending is True
    client.close()


def test_a_pending_first_turn_does_not_fire_again_on_a_later_bot_turn(tmp_path, monkeypatch):
    """Human first, a table error at start left the flag set: the bot's next turn change fires its triggers once."""
    session, table, game, fake, cfg, card, client = liz_session(tmp_path, monkeypatch, burning=True)
    game.turn, game.turn_no = 1, 1
    session.first_turn_pending = True
    game.end_turn()
    session.start_bot_turn()
    assert sum(t.startswith("Wildfire:") for t in table.broadcasts) == 1, "Wildfire runs once, not twice"
    assert not session.first_turn_pending
    client.close()
