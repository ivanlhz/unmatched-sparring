"""The bot's hand is logged at each decision, to the local session log only: never chat, broadcast or messages."""
from sparring.ai_medusa import Act
from test_batch import brig  # noqa: F401


def test_decision_line_goes_to_the_log_and_never_to_the_table(brig, monkeypatch, tmp_path):
    session, table, game, fake = brig
    session.game_log.path = tmp_path / "session.log"
    hand = [c.title for c in game.players[0].hand]
    assert hand
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={"medusa": 0}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.turn, game.actions_left, session.bot_stage = 0, 1, None
    session.messages = []
    session._bot_continue()

    lines = [l for l in session.game_log.path.read_text(encoding="utf-8").splitlines() if "BOT DECISION" in l]
    assert len(lines) == 1
    assert all(title in lines[0] for title in hand) and "maneuver" in lines[0] and f"hero@{game.hero(0).pos}" in lines[0]
    assert not any("BOT DECISION" in str(m) for m in session.messages)
    assert not any("BOT DECISION" in b for b in table.broadcasts)
    assert not any(hand[0] in b for b in table.broadcasts), "the secret hand never reaches the table"
