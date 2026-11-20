"""Sun Wukong on the table through the panel (FakeTTS, batch mode), both seats: the human's CLONES ability (a yes/no, 1 damage on the dial,
the Clone put on the table by hand and read from it), Sly Monkey (the Clone and Wukong placed by hand), Golden Chain Mail, Bewilderment, Phoenix
Form, Fiery Eyes That See (the bot shows its hand, the human chooses) and Taunting Laughter; and the bot's Wukong: its Clones come out of the
bag onto the table by GUID. The bot's side of the same cards is in tests/test_sun_wukong_effects.py.

The Clones are three Custom_Token in the save, which real TTS may report as "Tile": nothing that reads or moves a piece looks at the type."""
from __future__ import annotations

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with, bot_defends_with_nothing, by_hand, press, put_adjacent, rig, with_rig  # noqa: F401

HAND = ("Excalibur", "B.P.R.D. Training", "Service Pistol", "Right Hand Of Doom")
TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3
CLONES = ["clone1", "clone2", "clone3"]


def dial(session, cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


def attack(session, table, game, title, attacker="wukong", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def start(rig):
    """The human's turn opens with the CLONES question (the rig begins it): declined, so each test summons on purpose."""
    session, table, game, fake, cfg = rig
    press(session, table, False)
    assert session.effect_run is None and not game.fighters["clone1"].alive


def free_next_to(game, fid, exclude=()):
    taken = {f.pos for f in game.fighters.values() if f.alive} | set(exclude)
    return [s for s in sorted(game.board.adj[game.fighters[fid].pos]) if s not in taken]


def put_clone(game, table, cfg, fid, space):
    """A Clone already on the board (engine and table): the human summoned it earlier."""
    f = game.fighters[fid]
    f.alive, f.hp, f.pos = True, 1, space
    table.positions[cfg.nicknames[fid]] = space


def bot_attacks(session, table, game, title, fid, target, human_title=None):
    """The bot's `fid` attacks `target` with `title`; the human answers with `human_title` face down (None: no defense)."""
    from sparring.ai_medusa import Act
    from test_d3_table_effects import bot_turn
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


# ---------------------------------------------------------------- the ability, for the human

@with_rig("hellboy", "sun-wukong", *HAND)
def test_the_turn_opens_with_the_clones_question(rig):
    session, table, game, fake, cfg = rig
    assert game.turn == 1 and session.effect_run.awaiting.kind == "optional"
    assert dial(session, cfg, table, "wukong") == 17 and not any(game.fighters[c].alive for c in CLONES)


@with_rig("hellboy", "sun-wukong", *HAND)
def test_yes_takes_one_damage_on_the_dial_and_the_human_puts_the_clone_where_they_want(rig):
    session, table, game, fake, cfg = rig
    msgs = press(session, table, True)
    w, c = game.fighters["wukong"], game.fighters["clone1"]
    assert w.hp == 16 and dial(session, cfg, table, "wukong") == 16 and c.alive and c.hp == 1
    assert said(msgs, "wukong -1 PV (16)") and said(msgs, "pon a Clone 1 en el tablero (una casilla adyacente) con 1 PV"), msgs
    assert game.placing == {"clone1"}
    spot = free_next_to(game, "wukong")[-1]
    table.positions[cfg.nicknames["clone1"]] = spot                 # the human takes the Clone out of the bag and puts it there
    click(session, table, Event.END_ACTION)
    assert c.pos == spot and game.placing == set() and spot in game.board.adj[w.pos]


@with_rig("hellboy", "sun-wukong", *HAND)
def test_no_costs_nothing_and_summons_nothing(rig):
    session, table, game, fake, cfg = rig
    press(session, table, False)
    assert game.fighters["wukong"].hp == 17 and dial(session, cfg, table, "wukong") == 17
    assert not any(game.fighters[c].alive for c in CLONES) and session.pending is None


# ---------------------------------------------------------------- Sly Monkey

@with_rig("hellboy", "sun-wukong", *HAND)
def test_sly_monkey_summons_a_clone_in_his_space_and_the_human_places_both(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    start(rig)
    put_adjacent(game, table, cfg, "wukong", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Sly Monkey", "Golden Chain Mail")
    w = game.fighters["wukong"]
    old = w.pos
    msgs = attack(session, table, game, "Sly Monkey")
    assert said(msgs, "pon a Clone 1 en el tablero") and said(msgs, "coloca a wukong en la zona de tu heroe"), msgs
    assert game.fighters["clone1"].alive and game.placing == {"clone1", "wukong"}
    new = next(s for s in sorted(game.board.spaces) if s != old and game.board.share_zone(old, s) and s not in {f.pos for f in game.fighters.values() if f.alive})
    table.positions[cfg.nicknames["wukong"]] = new                  # Wukong moves, the Clone takes the space he left
    table.positions[cfg.nicknames["clone1"]] = old
    click(session, table, Event.END_ACTION)
    assert w.pos == new and game.fighters["clone1"].pos == old and "wukong" not in game.placing      # the Clone went where the engine had put it
    assert game.fighters["hellboy"].hp == 18 - 2


# ---------------------------------------------------------------- Golden Chain Mail, Bewilderment, Phoenix Form

@with_rig("hellboy", "sun-wukong", *HAND)
def test_golden_chain_mail_sends_the_bots_blow_back_to_the_bots_hero(rig):
    session, table, game, fake, cfg = rig
    start(rig)
    put_adjacent(game, table, cfg, "wukong", "hellboy")
    human_hand(table, game, "Golden Chain Mail", "Sly Monkey")
    msgs = bot_attacks(session, table, game, "Excalibur", "hellboy", "wukong", "Golden Chain Mail")
    assert game.fighters["wukong"].hp == 17 and dial(session, cfg, table, "wukong") == 17
    assert game.fighters["hellboy"].hp == 18 - 2 and dial(session, cfg, table, "hellboy") == 16, msgs      # 6 - 4 lands on the attacker


@with_rig("hellboy", "sun-wukong", *HAND)
def test_bewilderment_prevents_the_damage_and_the_human_may_place_wukong_by_hand(rig):
    session, table, game, fake, cfg = rig
    start(rig)
    put_adjacent(game, table, cfg, "wukong", "hellboy")
    human_hand(table, game, "Bewilderment", "Sly Monkey")
    bot_attacks(session, table, game, "Excalibur", "hellboy", "wukong", "Bewilderment")
    assert game.fighters["wukong"].hp == 17 and game.fighters["hellboy"].hp == 18
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "optional"
    press(session, table, False)
    assert session.effect_run is None and game.fighters["wukong"].hp == 17


@with_rig("hellboy", "sun-wukong", *HAND)
def test_phoenix_form_heals_one_per_clone_and_writes_the_dial(rig):
    session, table, game, fake, cfg = rig
    start(rig)
    w = game.fighters["wukong"]
    w.hp = 10
    table.dials[cfg.session_config().dials["wukong"]]["value"] = session.dials_written[cfg.session_config().dials["wukong"]] = 10
    spots = free_next_to(game, "wukong")
    put_clone(game, table, cfg, "clone1", spots[0])
    put_clone(game, table, cfg, "clone2", spots[1])
    human_hand(table, game, "Phoenix Form", "Sly Monkey")
    from test_e2_human_cards import human_scheme
    human_scheme(session, table, game, "Phoenix Form")
    assert w.hp == 12 and dial(session, cfg, table, "wukong") == 12
