"""Elektra on the table through the panel (FakeTTS, batch mode), both seats. The human as Elektra: the bot's attack takes her out, her miniature and the
four Hand leave the board but she is NOT defeated, the game goes on, and at the start of her next turn the Resurrect asks the human to put the
miniatures down, one to a zone, and flips the dial. The human as the OPPONENT of the bot's Elektra: the same state seen from the other side (the bot
sets its pieces aside, nothing is won, and the bot places them again).

Save/resume in the middle of anything that waits for the human is tested here too. The bot's side of the same cards is in tests/test_elektra_effects.py."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_hand, said
from test_e2_human_cards import labels, press, put_adjacent, rig, with_rig  # noqa: F401

HANDS = ["hand1", "hand2", "hand3", "hand4"]
HUMAN_HAND = ("Sai", "Intercept", "Mesmerize", "Ninjitsu", "Whirlwind")
BOT_HAND = ("Excalibur", "B.P.R.D. Training", "Service Pistol", "Right Hand Of Doom", "Second Shot")


def life(game, player):
    from sparring.effects.select import counter_value
    return counter_value(game, player, "life")


def dial(session, cfg, table, fid):
    return table.dials[session.cfg.dials[fid]]["value"]


def bot_attacks(session, table, game, title, fid, target, human_title=None):
    """The bot's `fid` attacks `target` with `title`; the human answers with `human_title` face down (None: no defense)."""
    card = next(c for c in game.players[0].hand if c.title == title)
    bot_turn(session, table, [Act("attack", fid=fid, target=target, card=card)])
    if human_title:
        cid = card_ids(game, 1, human_title)[0]
        table.face_down = [{"id": cid, "guid": f"h{cid}"}]
        table.human_hand.remove(cid)
        table.human_count -= 1
    else:
        table.face_down = []
    return click(session, table, Event.REVEAL)


def next_to_the_human(session, table, game, cfg, bot_fid="hellboy", human_fid="elektra"):
    h = game.fighters[human_fid]
    spot = next(s for s in sorted(game.board.adj[h.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    game.fighters[bot_fid].pos = spot
    table.positions[cfg.nicknames[bot_fid]] = spot


# ---------------------------------------------------------------- the human as Elektra

@with_rig("hellboy", "elektra", *BOT_HAND)
def test_the_bots_blow_takes_the_humans_elektra_off_the_board_and_nobody_wins(rig):
    session, table, game, fake, cfg = rig
    e = game.fighters["elektra"]
    e.hp = 1
    next_to_the_human(session, table, game, cfg)
    msgs = bot_attacks(session, table, game, "Service Pistol", "hellboy", "elektra", None)
    assert game.winner is None and life(game, 1) == 1
    assert all(not game.fighters[f].alive and game.fighters[f].off_board for f in ["elektra"] + HANDS)
    print(msgs)


def remove_and_pass_the_turn(session, table, game, cfg):
    """The bot's blow takes the human's Elektra off the board; the human closes the step and the bot ends its turn: the human's Resurrect is next."""
    game.fighters["elektra"].hp = 1
    next_to_the_human(session, table, game, cfg)
    removal = bot_attacks(session, table, game, "Service Pistol", "hellboy", "elektra", None)
    return removal, click(session, table, Event.END_ACTION)


def apart_spaces(game, table, n=5):
    """n empty spaces, each in a zone of its own, that no miniature stands on or next to (the pieces set aside rest on the spaces nearest to the fallen zone)."""
    taken, out = {f.pos for f in game.fighters.values() if f.alive} | set(table.positions.values()), []
    for s in sorted(game.board.spaces):
        if s not in taken and all(not game.board.share_zone(s, o) for o in out):
            out.append(s)
        if len(out) == n:
            return out
    raise AssertionError("the board has no five zones")


def put_down(table, cfg, fid, spot):
    """The human puts the miniature of the fighter on the spot (a piece the bot had set aside is no longer far from every space)."""
    table.positions[cfg.nicknames[fid]] = spot
    table.piece_dist.pop(cfg.nicknames[fid], None)


def flip_dial_on_the_table(table, cfg):
    table.dials["c32f50"] = {"found": True, "name": "Elektra Resurrected", "value": 9, "max": 9}


@with_rig("hellboy", "elektra", *BOT_HAND)
def test_the_chat_says_elektra_leaves_the_board_without_being_defeated_and_the_pieces_are_set_aside(rig):
    session, table, game, fake, cfg = rig
    game.fighters["elektra"].hp = 1
    next_to_the_human(session, table, game, cfg)
    removal = bot_attacks(session, table, game, "Service Pistol", "hellboy", "elektra", None)
    assert said(removal, "Elektra sale del tablero (no esta derrotada)") and said(removal, "The Hand 4 sale del tablero (no esta derrotada)"), removal
    assert not said(removal, " cae") and not said(removal, "Fin de la partida") and game.winner is None
    assert all(game.fighters[f].off_board and game.fighters[f].pos is None for f in ["elektra", *HANDS])
    assert life(game, 1) == 1 and dial(session, cfg, table, "elektra") == 0, "the dial of a fighter that is away shows 0"


@with_rig("hellboy", "elektra", *BOT_HAND)
def test_while_she_is_away_the_bot_plays_its_turn_and_the_human_is_not_asked_for_anything(rig):
    session, table, game, fake, cfg = rig
    flip_dial_on_the_table(table, cfg)
    _, turn = remove_and_pass_the_turn(session, table, game, cfg)
    assert game.turn == 1 and game.winner is None


@with_rig("hellboy", "elektra", *BOT_HAND)
def test_the_resurrect_tells_the_human_to_put_the_five_pieces_down_one_to_a_zone_then_the_engine_adopts_where_they_are(rig):
    session, table, game, fake, cfg = rig
    flip_dial_on_the_table(table, cfg)
    _, msgs = remove_and_pass_the_turn(session, table, game, cfg)
    assert said(msgs, "RESURRECT") and said(msgs, "pon a Elektra en el tablero (cualquier casilla) con 9 PV"), msgs
    assert said(msgs, "pon a The Hand 1 en el tablero (en una zona donde no este ninguno de tus otros luchadores) con 1 PV"), msgs
    assert game.placing == {"elektra", *HANDS} and life(game, 1) == 2
    spots = apart_spaces(game, table)
    for fid, spot in zip(["elektra", *HANDS], spots):
        put_down(table, cfg, fid, spot)
    click(session, table, Event.END_ACTION)
    assert {fid: game.fighters[fid].pos for fid in ["elektra", *HANDS]} == dict(zip(["elektra", *HANDS], spots)) and game.placing == set()
    assert all(game.fighters[f].alive for f in ["elektra", *HANDS]) and game.fighters["elektra"].hp == 9


@with_rig("hellboy", "elektra", *BOT_HAND)
def test_the_dial_of_the_resurrected_side_takes_over_and_shows_nine(rig):
    session, table, game, fake, cfg = rig
    flip_dial_on_the_table(table, cfg)
    _, msgs = remove_and_pass_the_turn(session, table, game, cfg)
    assert said(msgs, "Elektra resucita: dale la vuelta a tu dial de vida"), msgs
    assert session.cfg.dials["elektra"] == "c32f50" and dial(session, cfg, table, "elektra") == 9
    game.damage(game.fighters["elektra"], 2, "effect")
    session._write_dials()
    assert dial(session, cfg, table, "elektra") == 7 and table.dials["aace96"]["value"] != 7


# ---------------------------------------------------------------- the bot's Elektra against the human

ELEKTRA_HAND = ("Sai", "Intercept", "Mesmerize", "Ninjitsu", "Whirlwind")
HELLBOY_HAND = ("Excalibur", "B.P.R.D. Training", "Service Pistol", "Right Hand Of Doom", "Second Shot")


def human_hits_bots_elektra(session, table, game, cfg, monkeypatch):
    """The human's Hellboy attacks the bot's Elektra (1 health left) and she does not defend."""
    from test_e2_human_cards import bot_defends_with_nothing
    from test_d3_table_effects import human_attack
    e = game.fighters["elektra"]
    e.hp = 1
    put_adjacent(game, table, cfg, "elektra", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Excalibur", "B.P.R.D. Training")
    human_attack(session, table, game, "hellboy", "elektra", "Excalibur")
    return click(session, table, Event.REVEAL)


def end_the_humans_turn(session, table):
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    return click(session, table, Event.END_ACTION)


@with_rig("elektra", "hellboy", *ELEKTRA_HAND)
def test_the_humans_blow_takes_the_bots_elektra_off_the_board_the_bot_sets_its_five_pieces_aside_and_nobody_wins(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    msgs = human_hits_bots_elektra(session, table, game, cfg, monkeypatch)
    assert said(msgs, "Elektra sale del tablero (no esta derrotada): lo he sacado del tablero"), msgs
    assert said(msgs, "The Hand 1 sale del tablero (no esta derrotada)") and not said(msgs, " cae") and not said(msgs, "Fin de la partida"), msgs
    assert game.winner is None and life(game, 0) == 1 and all(game.fighters[f].off_board for f in ["elektra", *HANDS])


@with_rig("elektra", "hellboy", *ELEKTRA_HAND)
def test_at_the_start_of_the_bots_next_turn_the_bot_flips_the_dial_and_places_the_five_pieces_one_to_a_zone(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    flip_dial_on_the_table(table, cfg)
    human_hits_bots_elektra(session, table, game, cfg, monkeypatch)
    msgs = end_the_humans_turn(session, table)
    assert life(game, 0) == 2 and game.winner is None, msgs
    assert said(msgs, "Elektra resucita: le doy la vuelta al dial de vida"), msgs
    assert all(game.fighters[f].alive and not game.fighters[f].off_board for f in ["elektra", *HANDS]) and game.fighters["elektra"].hp == 9
    spots = [game.fighters[f].pos for f in ["elektra", *HANDS]]
    assert len(set(spots)) == 5
    assert all(not game.board.share_zone(a, b) for i, a in enumerate(spots) for b in spots[i + 1:]), spots
    assert all(table.positions[cfg.nicknames[f]] == game.fighters[f].pos for f in ["elektra", *HANDS]), "the bot moved every miniature to the space the engine chose"
    assert dial(session, cfg, table, "elektra") == 9 and session.cfg.dials["elektra"] == "c32f50"
    assert said(msgs, "vuelve al juego: la he colocado yo"), msgs


# ---------------------------------------------------------------- save and resume

def reload(session, table):
    """The session as a save brings it back, with a configuration as the launcher reads it again (the dials as the data gives them: the flip is the session's, not the file's)."""
    from test_sun_wukong_human import reload as resume
    session.cfg.dials.update(session._dial_origin)
    return resume(session, table)

@with_rig("hellboy", "elektra", *BOT_HAND)
def test_resume_while_she_is_off_the_board_keeps_her_away_and_the_game_going(rig):
    session, table, game, fake, cfg = rig
    flip_dial_on_the_table(table, cfg)
    game.fighters["elektra"].hp = 1
    next_to_the_human(session, table, game, cfg)
    bot_attacks(session, table, game, "Service Pistol", "hellboy", "elektra", None)
    other = reload(session, table)
    g = other.game
    assert g.winner is None and life(g, 1) == 1
    assert all(g.fighters[f].off_board and not g.fighters[f].alive and g.fighters[f].pos is None for f in ["elektra", *HANDS])
    assert not any("Fin de la partida" in m or "cae" in m.split() for m in other.messages), other.messages
    msgs = click(other, table, Event.END_ACTION)
    assert life(g, 1) == 2 and g.placing == {"elektra", *HANDS}, msgs


@with_rig("hellboy", "elektra", *BOT_HAND)
def test_resume_while_the_five_pieces_wait_to_be_put_down_does_not_call_them_missing_and_still_adopts_them(rig):
    session, table, game, fake, cfg = rig
    flip_dial_on_the_table(table, cfg)
    remove_and_pass_the_turn(session, table, game, cfg)
    assert game.placing == {"elektra", *HANDS}
    other = reload(session, table)
    assert other.game.placing == {"elektra", *HANDS} and life(other.game, 1) == 2
    assert other.cfg.dials["elektra"] == "c32f50" and other.game.fighters["elektra"].max_hp == 9
    spots = apart_spaces(other.game, table)
    for fid, spot in zip(["elektra", *HANDS], spots):
        put_down(table, cfg, fid, spot)
    click(other, table, Event.END_ACTION)
    assert {f: other.game.fighters[f].pos for f in ["elektra", *HANDS]} == dict(zip(["elektra", *HANDS], spots)) and other.game.placing == set()


@with_rig("elektra", "hellboy", *ELEKTRA_HAND)
def test_resume_after_the_bots_resurrect_keeps_the_flipped_dial_and_the_nine_health(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    flip_dial_on_the_table(table, cfg)
    human_hits_bots_elektra(session, table, game, cfg, monkeypatch)
    end_the_humans_turn(session, table)
    other = reload(session, table)
    assert life(other.game, 0) == 2 and other.game.fighters["elektra"].hp == 9 and other.cfg.dials["elektra"] == "c32f50"
    assert not any("marca" in m and "motor" in m for m in other.messages), other.messages


# ---------------------------------------------------------------- the human's cards

@with_rig("hellboy", "elektra", *BOT_HAND)
def test_snakeroot_clan_asks_yes_no_then_which_hand_and_that_hand_takes_the_blow_far_away(rig):
    session, table, game, fake, cfg = rig
    next_to_the_human(session, table, game, cfg)
    human_hand(table, game, "Snakeroot Clan", "Sai")
    e, far = game.fighters["elektra"], game.fighters["hand3"]
    e_pos, far_pos = e.pos, far.pos
    bot_attacks(session, table, game, "Service Pistol", "hellboy", "elektra", "Snakeroot Clan")
    assert session.effect_run.awaiting.kind == "optional" and labels(session) == ["Si", "No"]
    press(session, table, True)
    assert session.effect_run.awaiting.kind == "fighter" and labels(session) == ["The Hand 1", "The Hand 2", "The Hand 3", "The Hand 4"]
    msgs = press(session, table, "hand3")
    assert e.pos == far_pos and far.died_at == e_pos and not far.alive and e.alive and e.hp == 7, (e.pos, far.pos, far.alive, e.hp)
    assert game.winner is None


@with_rig("hellboy", "elektra", *BOT_HAND)
def test_intercept_resurrected_asks_the_human_whether_they_reveal_a_sai_and_yes_makes_it_5(rig):
    from sparring import off_board
    session, table, game, fake, cfg = rig
    off_board.release(game, 1)                                            # she is already resurrected (the dial flip is the session's, tested above)
    game.fx.set_counter(1, "life", off_board.RESURRECTED)
    next_to_the_human(session, table, game, cfg)
    human_hand(table, game, "Intercept", "Sai")
    msgs = bot_attacks(session, table, game, "Service Pistol", "hellboy", "elektra", "Intercept")
    req = session.effect_run.awaiting
    assert req.kind == "optional" and said(msgs, "Usas el efecto de Intercept") and said(msgs, 'reveal a card named "Sai"'), msgs
    msgs = press(session, table, True)
    assert said(msgs, "Elektra defiende con Intercept (5)") or said(msgs, "defiende con Intercept (5)"), msgs
    assert game.fighters["elektra"].hp == 7 - 0 and game.winner is None


@with_rig("hellboy", "elektra", *BOT_HAND)
def test_intercept_before_the_resurrect_asks_nothing_and_is_3(rig):
    session, table, game, fake, cfg = rig
    next_to_the_human(session, table, game, cfg)
    human_hand(table, game, "Intercept", "Sai")
    msgs = bot_attacks(session, table, game, "Service Pistol", "hellboy", "elektra", "Intercept")
    assert session.effect_run is None and said(msgs, "Intercept (3)"), msgs


@with_rig("hellboy", "elektra", *BOT_HAND)
def test_the_resurrect_tells_the_human_to_shuffle_their_discard_pile_into_their_deck(rig):
    session, table, game, fake, cfg = rig
    flip_dial_on_the_table(table, cfg)
    cids = card_ids(game, 1, "Sai", "Whirlwind")
    for cid in cids:
        card = next(c for c in game.players[1].full_set if c.card_id == cid)
        if card in game.players[1].deck:
            game.players[1].deck.remove(card)
        game.players[1].discard.append(card)
        table.human_discard.append(cid)
    _, msgs = remove_and_pass_the_turn(session, table, game, cfg)
    assert said(msgs, "Meto Sai y Whirlwind en tu mazo y lo barajo"), msgs          # the bot does it: the pile is public and it moves the human's cards
    assert game.players[1].discard == [] and {c.title for c in game.players[1].deck} >= {"Sai", "Whirlwind"}
