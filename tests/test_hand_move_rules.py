"""The human's own miniature walked by hand by an effect (`move` without `await_destination`) is checked against the
rules of that effect when the table is read (F-EFFECT-MOVE-THROUGH, Iván 9/11: Skirmish moved Tomoe Gozen through an
enemy and the bot accepted it). A move that crosses a rival the card does not let it cross, or that is too far, changes
nothing and the chat says why; Hoax ("through spaces containing opposing fighters") still accepts the same walk."""
from __future__ import annotations

from sparring import i18n
from sparring.tts.ui import Event
from test_batch import click
from test_bigfoot_human import TRAINING, attack, rig  # noqa: F401
from test_d3_table_effects import human_hand, said
from test_e2_human_cards import bot_defends_with_nothing, press, with_rig


def corridor(board, taken_by):
    """(a, m, d): `m` is the only space between `a` and `d` (two spaces apart), and none of the three is taken."""
    for a in sorted(board.spaces):
        for d in sorted(board.spaces):
            if board.distance(a, d) != 2 or a in taken_by or d in taken_by:
                continue
            mids = [m for m in board.adj[a] if d in board.adj[m]]
            if len(mids) == 1 and mids[0] not in taken_by and board.share_zone(a, mids[0]):
                return a, mids[0], d
    raise AssertionError("no corridor")


def stage(game, table, cfg):
    """Bigfoot on `a`, Hellboy (the rival) on the only space between `a` and `d`; every other fighter far away."""
    board = game.board
    a, m, d = corridor(board, set())
    others = [f for f in game.fighters.values() if f.alive and f.fid not in ("bigfoot", "hellboy")]
    far = [s for s in sorted(board.spaces, reverse=True) if board.distance(a, s) > 3 and s != d]
    for f, s in zip(others, far):
        f.pos = s
        table.positions[cfg.nicknames[f.fid]] = s
    for fid, s in (("bigfoot", a), ("hellboy", m)):
        game.fighters[fid].pos = s
        table.positions[cfg.nicknames[fid]] = s
    return a, m, d


def walk(table, cfg, fid, space):
    table.positions[cfg.nicknames[fid]] = space


@with_rig("hellboy", "bigfoot", TRAINING)
def test_skirmish_through_a_rival_is_refused_and_changes_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    a, m, d = stage(game, table, cfg)
    human_hand(table, game, "Skirmish", "Hoax")
    attack(session, table, game, "bigfoot", "Skirmish")
    press(session, table, "bigfoot")
    assert game.hand_moves["bigfoot"] == {"steps": 2, "up_to": True, "through": False}
    walk(table, cfg, "bigfoot", d)                                  # 2 spaces, but across Hellboy
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["bigfoot"].pos == a and game.actions_left == 1, msgs
    assert said(msgs, "sin atravesar luchadores rivales"), msgs
    assert "bigfoot" in game.hand_moves                             # still waiting for the right walk


@with_rig("hellboy", "bigfoot", TRAINING)
def test_skirmish_two_free_spaces_is_accepted(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    a, m, d = stage(game, table, cfg)
    human_hand(table, game, "Skirmish", "Hoax")
    attack(session, table, game, "bigfoot", "Skirmish")
    press(session, table, "bigfoot")
    board = game.board
    taken = {f.pos for f in game.fighters.values() if f.alive}
    legal = next(s for s in sorted(game.legal_moves(game.fighters["bigfoot"], 2)) if s not in taken)
    assert legal != d and board.distance(a, legal) <= 2
    walk(table, cfg, "bigfoot", legal)
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["bigfoot"].pos == legal and "bigfoot" not in game.hand_moves, msgs
    assert not said(msgs, "sin atravesar")


@with_rig("hellboy", "bigfoot", TRAINING)
def test_skirmish_too_far_is_refused(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    a, m, d = stage(game, table, cfg)
    human_hand(table, game, "Skirmish", "Hoax")
    attack(session, table, game, "bigfoot", "Skirmish")
    press(session, table, "bigfoot")
    taken = {f.pos for f in game.fighters.values() if f.alive}
    far = next(s for s in sorted(game.board.spaces) if s not in taken and game.board.distance(a, s) == 3)
    walk(table, cfg, "bigfoot", far)
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["bigfoot"].pos == a and said(msgs, "el maximo es 2"), msgs


@with_rig("hellboy", "bigfoot", TRAINING)
def test_hoax_may_cross_the_same_rival(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    a, m, d = stage(game, table, cfg)
    human_hand(table, game, "Hoax", "Skirmish")
    attack(session, table, game, "bigfoot", "Hoax")
    assert game.hand_moves["bigfoot"] == {"steps": 5, "up_to": True, "through": True}
    walk(table, cfg, "bigfoot", d)
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["bigfoot"].pos == d and "bigfoot" not in game.hand_moves, msgs
    assert not said(msgs, "sin atravesar")


@with_rig("hellboy", "bigfoot", TRAINING)
def test_a_later_plain_move_is_not_held_to_a_spent_permission(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    a, m, d = stage(game, table, cfg)
    human_hand(table, game, "Skirmish", "Hoax")
    attack(session, table, game, "bigfoot", "Skirmish")
    press(session, table, "bigfoot")
    click(session, table, Event.END_ACTION)                         # the human did not move at all
    assert game.hand_moves == {}


# ---------------------------------------------------------------- several pieces moved by one effect

WINGED = {"steps": 3, "up_to": True, "through": True}


def two_pieces(game, table, cfg):
    """Bigfoot on `a`, the Jackalope on `m` (next to each other); the rest of the bot far away. Returns (a, m, free)."""
    board = game.board
    a, m, _ = corridor(board, set())
    for fid, s in (("bigfoot", a), ("jackalope", m)):
        game.fighters[fid].pos = s
        table.positions[cfg.nicknames[fid]] = s
    others = [f for f in game.fighters.values() if f.alive and f.fid not in ("bigfoot", "jackalope")]
    far = [s for s in sorted(board.spaces, reverse=True) if board.distance(a, s) > 4]
    for f, s in zip(others, far):
        f.pos = s
        table.positions[cfg.nicknames[f.fid]] = s
    free = next(s for s in sorted(board.adj[m]) if s not in (a, m) and all(f.pos != s for f in game.fighters.values() if f.alive))
    game.hand_moves.update({"bigfoot": dict(WINGED), "jackalope": dict(WINGED)})
    return a, m, free


@with_rig("hellboy", "bigfoot", TRAINING)
def test_two_pieces_that_swap_places_are_both_accepted(rig):
    session, table, game, fake, cfg = rig
    a, m, _ = two_pieces(game, table, cfg)
    walk(table, cfg, "bigfoot", m)
    walk(table, cfg, "jackalope", a)
    msgs = click(session, table, Event.END_ACTION)
    assert (game.fighters["bigfoot"].pos, game.fighters["jackalope"].pos) == (m, a), msgs
    assert game.hand_moves == {}


@with_rig("hellboy", "bigfoot", TRAINING)
def test_a_piece_that_enters_the_space_another_one_leaves_is_accepted(rig):
    session, table, game, fake, cfg = rig
    a, m, free = two_pieces(game, table, cfg)
    walk(table, cfg, "bigfoot", m)
    walk(table, cfg, "jackalope", free)
    msgs = click(session, table, Event.END_ACTION)
    assert (game.fighters["bigfoot"].pos, game.fighters["jackalope"].pos) == (m, free), msgs
    assert not session.illegal_hand_moves


@with_rig("hellboy", "bigfoot", TRAINING)
def test_two_pieces_ending_on_the_same_space_are_refused(rig):
    session, table, game, fake, cfg = rig
    a, m, free = two_pieces(game, table, cfg)
    walk(table, cfg, "bigfoot", free)
    walk(table, cfg, "jackalope", free)
    msgs = click(session, table, Event.END_ACTION)
    assert (game.fighters["bigfoot"].pos, game.fighters["jackalope"].pos) == (a, m), msgs
    assert said(msgs, "esta ocupada"), msgs
    assert set(game.hand_moves) == {"bigfoot", "jackalope"}


# ---------------------------------------------------------------- during the bot's turn

@with_rig("hellboy", "bigfoot", TRAINING)
def test_a_walk_read_outside_end_action_is_refused_in_the_chat_and_survives_the_turn_change(rig):
    session, table, game, fake, cfg = rig
    a, m, d = stage(game, table, cfg)
    game.hand_moves["bigfoot"] = {"steps": 2, "up_to": True, "through": False}
    walk(table, cfg, "bigfoot", d)
    n = len(session.messages)
    session.sync_positions()                                        # a read in the bot's turn, not an End action
    assert game.fighters["bigfoot"].pos == a
    assert any("sin atravesar luchadores rivales" in text for text in session.messages[n:]), session.messages[n:]
    session._begin_turn(game)
    assert "bigfoot" in game.hand_moves                             # kept until the piece is put right
    walk(table, cfg, "bigfoot", a)
    session.sync_positions()
    assert not session.illegal_hand_moves


@with_rig("hellboy", "bigfoot", TRAINING)
def test_a_legal_walk_read_outside_end_action_spends_the_permission(rig):
    """A read in the bot's turn sees the walk the effect allowed: it is accepted and the permission is gone with it, so a
    second walk read later is a plain move, not a second use of the same effect (nor judged by its limits)."""
    session, table, game, fake, cfg = rig
    a, m, d = stage(game, table, cfg)
    game.hand_moves["bigfoot"] = {"steps": 2, "up_to": True, "through": False}
    taken = {f.pos for f in game.fighters.values() if f.alive}
    near = next(s for s in sorted(game.legal_moves(game.fighters["bigfoot"], 2)) if s not in taken)
    walk(table, cfg, "bigfoot", near)
    session.sync_positions()
    assert game.fighters["bigfoot"].pos == near and "bigfoot" not in game.hand_moves
    far = next(s for s in sorted(game.board.spaces) if s not in taken and game.board.distance(near, s) == 3)
    walk(table, cfg, "bigfoot", far)
    n = len(session.messages)
    session.sync_positions()
    assert game.fighters["bigfoot"].pos == far and not session.illegal_hand_moves, session.messages[n:]


# ---------------------------------------------------------------- the permission outlives the turn change, not the next action

def refused_walk(session, table, game, cfg):
    a, m, d = stage(game, table, cfg)
    game.hand_moves["bigfoot"] = {"steps": 2, "up_to": True, "through": False}
    walk(table, cfg, "bigfoot", d)
    return a, m, d


@with_rig("hellboy", "bigfoot", TRAINING)
def test_a_fixed_piece_is_not_judged_by_the_old_effect_in_the_next_maneuver(rig):
    session, table, game, fake, cfg = rig
    a, m, d = refused_walk(session, table, game, cfg)
    session.sync_positions()
    assert session.illegal_hand_moves
    walk(table, cfg, "bigfoot", a)                                   # put right, no read before the turn change
    session._begin_turn(game)
    game.turn = session.human
    click(session, table, Event.MANEUVER)
    assert "bigfoot" not in game.hand_moves                          # a piece left in place closes the window
    taken = {f.pos for f in game.fighters.values() if f.alive}
    three = next(s for s in sorted(game.board.spaces) if s not in taken and game.board.distance(a, s) == 3)
    walk(table, cfg, "bigfoot", three)
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["bigfoot"].pos == three and not said(msgs, "el maximo"), msgs


@with_rig("hellboy", "bigfoot", TRAINING)
def test_a_walk_after_the_last_action_of_the_bots_turn_is_refused_at_the_next_action(rig):
    session, table, game, fake, cfg = rig
    a, m, d = refused_walk(session, table, game, cfg)
    session._begin_turn(game)                                        # the turn changed before any read
    assert "bigfoot" in game.hand_moves
    game.turn = session.human
    left = game.actions_left
    msgs = click(session, table, Event.MANEUVER)
    assert game.fighters["bigfoot"].pos == a and game.actions_left == left, msgs
    assert said(msgs, "sin atravesar luchadores rivales"), msgs
    walk(table, cfg, "bigfoot", a)
    click(session, table, Event.MANEUVER)
    assert game.actions_left == left - 1


@with_rig("hellboy", "bigfoot", TRAINING)
def test_a_sidekick_pass_uses_the_table_spots_of_the_rivals(rig):
    from sparring import session_moves as moves
    session, table, game, fake, cfg = rig
    a, m, d = stage(game, table, cfg)
    game.fighters["hellboy"].pos = next(s for s in sorted(game.board.spaces, reverse=True) if game.board.distance(a, s) > 4)
    move = {"steps": 2, "up_to": True, "through": "sidekicks"}
    bigfoot = game.fighters["bigfoot"]
    assert not moves.hand_move_legal(game, bigfoot, d, move, {"hellboy": m})      # a rival hero in the way blocks
    assert moves.hand_move_legal(game, bigfoot, d, move, {"lobster": m})         # a sidekick the table shows there is crossed


# ---------------------------------------------------------------- an exact move, the save, the clone, the AFTER gate

@with_rig("hellboy", "bigfoot", TRAINING)
def test_an_exact_move_that_stops_short_is_refused(rig):
    """"Move 2 spaces" (not "up to"): one space is too short, two are right."""
    from sparring import session_moves as moves
    session, table, game, fake, cfg = rig
    a, m, d = stage(game, table, cfg)
    game.fighters["hellboy"].pos = next(s for s in sorted(game.board.spaces, reverse=True) if game.board.distance(a, s) > 4)
    table.positions[cfg.nicknames["hellboy"]] = game.fighters["hellboy"].pos
    exact = {"steps": 2, "up_to": False, "through": False}
    bigfoot = game.fighters["bigfoot"]
    assert not moves.hand_move_legal(game, bigfoot, m, exact)
    assert moves.hand_move_legal(game, bigfoot, d, exact)
    assert moves.hand_move_legal(game, bigfoot, m, {**exact, "up_to": True})
    game.hand_moves["bigfoot"] = dict(exact)
    walk(table, cfg, "bigfoot", m)
    n = len(session.messages)
    session.sync_positions()
    assert bigfoot.pos == a and "bigfoot" in session.illegal_hand_moves
    assert any("tiene que moverse exactamente 2" in text for text in session.messages[n:]), session.messages[n:]
    walk(table, cfg, "bigfoot", d)
    session.sync_positions()
    assert bigfoot.pos == d and not session.illegal_hand_moves


@with_rig("hellboy", "bigfoot", TRAINING)
def test_the_permission_survives_a_save(rig):
    import json
    from sparring.persist import apply_game, game_to_dict
    session, table, game, fake, cfg = rig
    assert "hand_moves" not in game_to_dict(game)
    game.hand_moves["bigfoot"] = {"steps": 2, "up_to": False, "through": "sidekicks"}
    saved = json.loads(json.dumps(game_to_dict(game)))
    game.hand_moves.clear()
    apply_game(game, saved)
    assert game.hand_moves == {"bigfoot": {"steps": 2, "up_to": False, "through": "sidekicks"}}
    del saved["hand_moves"]                                         # a save from before the permission existed
    apply_game(game, saved)
    assert game.hand_moves == {}


@with_rig("hellboy", "bigfoot", TRAINING)
def test_a_clone_carries_its_own_copy_of_the_permission(rig):
    session, table, game, fake, cfg = rig
    game.hand_moves["bigfoot"] = {"steps": 2, "up_to": True, "through": False}
    clone = game.clone()
    assert clone.hand_moves == game.hand_moves
    clone.hand_moves["bigfoot"]["steps"] = 9
    del clone.hand_moves["bigfoot"]
    assert game.hand_moves == {"bigfoot": {"steps": 2, "up_to": True, "through": False}}


@with_rig("liz-sherman", "hellboy", "Fleeting Moments", "Evade", "Fireball", "Pyrotechnics", "Rekindle")
def test_a_bad_walk_keeps_the_after_gate_closed_until_it_is_put_right(rig):
    """The combat waits at an AFTER gate for the human's step on their hand; End action reads the table there too."""
    from test_after_gate import fleeting_into_glimpse
    session, table, game, fake, cfg = rig
    fleeting_into_glimpse(session, table, game, cfg)
    assert session._table_gate(session.pending)
    hellboy = game.fighters["hellboy"]
    home = hellboy.pos
    game.hand_moves["hellboy"] = {"steps": 1, "up_to": True, "through": False}
    taken = {f.pos for f in game.fighters.values() if f.alive}
    far = next(s for s in sorted(game.board.spaces) if s not in taken and game.board.distance(home, s) == 3)
    walk(table, cfg, "hellboy", far)
    table.human_count -= 1                                          # Glimpse's card went back to the deck: the hand step is done
    msgs = click(session, table, Event.END_ACTION)
    assert session._table_gate(session.pending), "the next effect does not run over a walk the card does not allow"
    assert hellboy.pos == home and said(msgs, "el maximo es 1"), msgs
    assert not said(msgs, "Fleeting Moments, al azar")
    walk(table, cfg, "hellboy", home)
    msgs = click(session, table, Event.END_ACTION)
    assert not session._table_gate(session.pending) and said(msgs, "Fleeting Moments, al azar"), msgs
    assert game.hand_moves == {}
