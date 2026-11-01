"""Review 11: the bot defends AFTER the human commits (Attack neither places nor announces anything)."""
import pytest

from sparring.tts.ui import Event
from test_batch import brig, click  # noqa: F401
from test_review5_fixes import fresh
from test_session import card, human_plays, rig  # noqa: F401
from sparring import persist

SEEN: dict = {}


def start_attack(session):
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    return session.handle(Event.ATTACK, {"target": "medusa"})


def test_attack_places_nothing_and_announces_no_defense(rig, monkeypatch):
    session, table, game = rig
    called = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: called.append(1))
    msgs = start_attack(session)
    assert called == [] and table.bot_play == [] and table.count("play_card_face_down") == 0
    p = session.pending
    assert p is not None and not p.defended and p.bot_card is None and p.bot_card_guid is None
    text = " ".join(msgs).lower()
    assert "boca abajo" in text and "revelar" in text
    assert "defend" not in text and "defiende" not in text


@pytest.mark.parametrize("title", ["Service Pistol", "Glimpse Of Hell"])
def test_defense_decision_does_not_depend_on_the_human_card(rig, monkeypatch, title):
    session, table, game = rig
    real = session.ai.choose_defense
    st = game.players[1]

    def spy(g, attacker, target):
        SEEN[title] = (attacker.fid, target.fid, sorted(c.card_id for c in g.players[0].hand),
                       sorted(c.card_id for c in st.hand), sorted(c.card_id for c in st.discard),
                       {f: (x.hp, x.pos) for f, x in g.fighters.items()}, g.actions_left, g.rng.getstate())
        return real(g, attacker, target)
    monkeypatch.setattr(session.ai, "choose_defense", spy)
    start_attack(session)
    human_plays(table, game, title)
    assert title not in SEEN
    session.handle(Event.REVEAL)
    assert title in SEEN
    if len(SEEN) == 2:
        a, b = (SEEN[t] for t in ("Service Pistol", "Glimpse Of Hell"))
        assert a == b, "the AI gets the same whatever the human's card is"


def test_reveal_without_a_human_card_does_not_decide_or_place(rig, monkeypatch):
    session, table, game = rig
    called = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: called.append(1))
    start_attack(session)
    msgs = session.handle(Event.REVEAL)
    assert called == [] and table.bot_play == [] and not session.pending.defended
    assert any("ninguna carta" in m for m in msgs)


def test_illegal_human_card_does_not_trigger_the_defense(rig, monkeypatch):
    session, table, game = rig
    called = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: called.append(1))
    start_attack(session)
    human_plays(table, game, "Second Shot")
    session.handle(Event.REVEAL)
    assert called == [] and table.bot_play == [] and not session.pending.defended


def test_reveal_places_the_defense_then_resolves(rig, monkeypatch):
    session, table, game = rig
    dash = card(game, 0, "Dash")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: dash)
    start_attack(session)
    human_plays(table, game, "Service Pistol")
    msgs = session.handle(Event.REVEAL)
    assert table.count("play_card_face_down") == 1 and session.pending is None
    assert any("Combate" in m and "defiende con" in m for m in msgs)


def test_cancel_before_reveal_has_no_bot_card_to_return(rig, monkeypatch):
    session, table, game = rig
    start_attack(session)
    msgs = session.handle(Event.CANCEL)
    assert session.pending is None and table.returned == [] and game.actions_left == 2
    assert any("cancel" in m.lower() for m in msgs)


def test_a_second_attack_click_does_not_open_another_combat(rig):
    session, table, game = rig
    start_attack(session)
    msgs = session.handle(Event.ATTACK, {"target": "medusa"})
    assert session.pending is not None and not session.pending.defended and table.bot_play == []
    assert any("Revelar" in m for m in msgs)


def test_resume_between_attack_and_reveal(rig, monkeypatch):
    session, table, game = rig
    start_attack(session)
    s2 = fresh(session)
    s2.load_dict(session.to_dict())
    assert s2.pending is not None and not s2.pending.defended and s2.pending.bot_card is None
    dash = card(s2.game, 0, "Dash")
    monkeypatch.setattr(s2.ai, "choose_defense", lambda g, a, t: dash)
    human_plays(table, s2.game, "Service Pistol")
    s2.handle(Event.REVEAL)
    assert s2.pending is None and table.count("play_card_face_down") == 1


def test_old_saves_without_the_defended_flag_load_as_defended(rig):
    session, table, game = rig
    start_attack(session)
    d = session.to_dict()
    del d["pending"]["defended"]
    s2 = fresh(session)
    s2.load_dict(d)
    assert s2.pending.defended


def test_batch_reveal_defends_and_resolves_in_few_messages(brig):
    session, table, game, fake = brig
    click(session, table, Event.ATTACKER, {"attacker": "att_hellboy"})
    click(session, table, Event.ATTACK, {"target": "medusa"})
    assert table.bot_play == [] and not session.pending.defended
    human_plays(table, game, "Service Pistol")
    n = fake.lua_messages
    click(session, table, Event.REVEAL)
    assert session.pending is None and fake.lua_messages - n <= 3
