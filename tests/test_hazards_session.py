"""A piece the human moved by hand across a hazard edge: the engine charges it and the chat says so."""
from __future__ import annotations

from sparring.board import edge_key
from test_session import NICK, rig  # noqa: F401  (the fixture)


def test_a_human_move_across_a_hazard_is_charged_and_announced(rig, monkeypatch):    # noqa: F811
    session, table, game = rig
    monkeypatch.setattr(game.board, "hazards", {edge_key(1, 2): 1, edge_key(1, 0): 1, edge_key(1, 15): 1})
    hb = game.fighters["hellboy"]
    hp = hb.hp
    table.positions["Hellboy"] = 15
    session.snap = None
    session.sync_positions()
    assert hb.pos == 15 and hb.hp == hp - 1
    said = [str(m) for m in session.messages]
    assert any("(1-15)" in m and "de 18 a 17" in m for m in said), said
    table.positions["Hellboy"] = 1                                        # back over the same edge: free this turn
    session.snap = None
    session.sync_positions()
    assert hb.pos == 1 and hb.hp == hp - 1


def lobster_neighbour(game):
    lob = game.fighters["lobster"]
    taken = {f.pos for f in game.fighters.values() if f.alive}
    return lob, next(n for n in sorted(game.board.moves[lob.pos]) if n not in taken)


def put_on_table(session, table, nick, space):
    table.positions[nick] = space
    session.snap = None
    session.sync_positions()


def test_the_setup_placement_of_a_piece_is_never_charged(rig, monkeypatch):    # noqa: F811
    session, table, game = rig
    lob, nb = lobster_neighbour(game)
    start = lob.pos
    monkeypatch.setattr(game.board, "hazards", {edge_key(start, nb): 2})
    session.setup = {"stage": "wait_human"}
    hp = lob.hp
    put_on_table(session, table, NICK["lobster"], nb)
    assert lob.pos == nb and lob.hp == hp and not game.hazard_taken
    session.setup = None                                                   # once the game runs, walking back is a move
    put_on_table(session, table, NICK["lobster"], start)
    assert lob.hp == hp - 2


def test_a_piece_put_down_by_hand_by_an_effect_is_not_charged_but_the_next_move_is(rig, monkeypatch):    # noqa: F811
    from sparring.effects.run import Ctx, EffectRun
    session, table, game = rig
    lob, nb = lobster_neighbour(game)
    start = lob.pos
    monkeypatch.setattr(game.board, "hazards", {edge_key(start, nb): 2})
    game.controllers[1].human = True                                       # the table player puts their own pieces down by hand
    run = EffectRun([{"op": "place", "target": {"side": "own", "name": "Lobster Johnson"}, "where": {"any": True}, "chooser": "owner"}],
                    Ctx(owner=1, this_fid="hellboy"))
    run.run(game, game.fx.choosers[1])
    assert "lobster" in game.placing
    hp = lob.hp
    put_on_table(session, table, NICK["lobster"], nb)
    assert lob.pos == nb and lob.hp == hp and "lobster" not in game.placing
    put_on_table(session, table, NICK["lobster"], start)
    assert lob.hp == hp - 2, "an ordinary move afterwards is charged again"


def test_the_hero_that_places_itself_with_a_boosted_maneuver_is_never_charged(rig, monkeypatch):    # noqa: F811
    session, table, game = rig
    hb = game.fighters["hellboy"]
    nb = next(n for n in sorted(game.board.moves[hb.pos]) if n not in {f.pos for f in game.fighters.values() if f.alive})
    monkeypatch.setattr(game.board, "hazards", {edge_key(hb.pos, nb): 2})
    monkeypatch.setattr(type(game.fx), "hero_rule", lambda self, player, rule: rule == "maneuver_boost_places_hero")
    hp = hb.hp
    put_on_table(session, table, "Hellboy", nb)
    assert hb.pos == nb and hb.hp == hp


def test_a_hand_move_over_two_hazards_is_charged_and_announced_once(rig, monkeypatch):    # noqa: F811
    session, table, game = rig
    hb = game.fighters["hellboy"]
    b = game.board
    taken = {f.pos for f in game.fighters.values() if f.alive}
    mid, dst = next((m, d) for m in sorted(b.moves[hb.pos]) if m not in taken for d in sorted(b.moves[m])
                    if d not in taken and d != hb.pos and d not in b.moves[hb.pos])
    monkeypatch.setattr(b, "hazards", {edge_key(hb.pos, mid): 1, edge_key(mid, dst): 2})
    hp = hb.hp
    put_on_table(session, table, "Hellboy", dst)
    said = [str(m) for m in session.messages if "peligroso" in str(m)]
    assert len(said) == 1, "one hurt per turn in all: the second hazard on the way is free"
    assert f"de {hp:g} a {hp - 1:g}" in said[0], said


def test_a_move_the_engine_makes_in_a_human_effect_is_announced_and_the_dials_written_at_once(rig, monkeypatch):    # noqa: F811
    session, table, game = rig
    lob, nb = lobster_neighbour(game)
    monkeypatch.setattr(game.board, "hazards", {edge_key(lob.pos, nb): 2})
    written = []
    monkeypatch.setattr(session, "_write_dials", lambda *a, **k: written.append(1))
    hp = lob.hp
    game.move_fighter(lob, nb, 1)                                          # what a move op of an effect does
    assert game.hazard_hits == [], "announced the moment it happened, not queued for later"
    assert any("peligroso" in str(m) and f"de {hp:g} a {hp - 2:g}" in str(m) for m in session.messages)
    assert written


def test_a_fatal_hazard_in_an_engine_move_ends_the_game_at_once(rig, monkeypatch):    # noqa: F811
    session, table, game = rig
    med = game.fighters["medusa"]
    nb = next(n for n in sorted(game.board.moves[med.pos]) if n not in {f.pos for f in game.fighters.values() if f.alive})
    monkeypatch.setattr(game.board, "hazards", {edge_key(med.pos, nb): 3})
    med.hp = 2
    game.move_fighter(med, nb, 1)
    assert game.winner == 1 and any("Fin de partida" in str(m) for m in session.messages)
