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


# ---------------------------------------------------------------- the bot's Wukong

BOT_HAND = ("Fiery Eyes That See", "Sly Monkey", "Taunting Laughter", "Ox Form")


def bot_turn_with_hand(session, table, game, acts, *titles):
    """Like `bot_turn`, but the table's hand is set to `titles` (as many as the engine's hand holds after the two maneuvers) before the bot plays,
    so a look at the hand finds what the engine believes is there."""
    from sparring.ai_medusa import Act
    plan = list(acts)
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    human_hand(table, game, *titles)
    return click(session, table, Event.END_ACTION)


SEVEN = ("Service Pistol", "Excalibur", "Glimpse Of Hell", "B.P.R.D. Training", "Right Hand Of Doom", "Second Shot", "Confront Any Demon or God")


@with_rig("sun-wukong", "hellboy", *BOT_HAND)
def test_the_bots_fiery_eyes_looks_once_and_names_the_card_for_the_bottom_of_your_deck(rig):
    from sparring.ai_medusa import Act
    from test_d3_table_effects import human_reads
    session, table, game, fake, cfg = rig
    card = next(c for c in game.players[0].hand if c.title == "Fiery Eyes That See")
    msgs = bot_turn_with_hand(session, table, game, [Act("frenzy", card=card)], *SEVEN)
    assert len(human_reads(table)) == 1
    assert said(msgs, "Pon Excalibur de tu mano en el fondo de tu mazo (efecto del bot)"), msgs
    assert said(msgs, "Te he dado 1 carta (efecto del bot)"), msgs
    assert not said(msgs, "las eliges tu"), msgs                      # the bot chose the card, not the human
    known = game.players[0].known
    assert card_ids(game, 1, "Excalibur")[0] not in known.seen         # it left the hand it had seen
    assert len(game.players[1].hand) == 7


@with_rig("sun-wukong", "hellboy", *BOT_HAND)
def test_the_bots_clone_is_taken_from_the_bag_and_put_on_the_table_by_the_bot(rig):
    from test_d3_table_effects import bot_turn
    session, table, game, fake, cfg = rig
    msgs = bot_turn(session, table, [])
    w, c = game.fighters["wukong"], game.fighters["clone1"]
    assert said(msgs, "Clone 1 vuelve al juego: la he colocado yo"), msgs
    assert c.alive and w.hp == 16 and c.hp == 1 and c.pos in game.board.adj[w.pos]
    assert table.positions[cfg.nicknames["clone1"]] == c.pos           # the table follows the engine: the bot moved the Clone itself
    assert dial(session, cfg, table, "wukong") == 16


# ---------------------------------------------------------------- Fiery Eyes That See and Taunting Laughter, played by the human

@with_rig("hellboy", "sun-wukong", *HAND)
def test_the_humans_fiery_eyes_shows_the_bots_hand_and_the_chosen_card_goes_to_the_bottom_of_its_deck(rig):
    from test_e2_human_cards import human_scheme
    session, table, game, fake, cfg = rig
    start(rig)
    human_hand(table, game, "Fiery Eyes That See", "Sly Monkey")
    bot_before = len(game.players[0].hand)
    msgs = human_scheme(session, table, game, "Fiery Eyes That See")
    assert session.look is not None and session.look["mode"] == "pick" and said(msgs, "El bot pone su mano boca arriba"), msgs
    chosen = session.look["ids"][0]
    msgs = click(session, table, Event.LOOK_PING, {"guid": f"g{chosen}"})
    assert table.bot_deck[-1] == chosen and chosen not in table.bot_hand and session.look is None, msgs      # at the bottom, not on top
    assert len(game.players[0].hand) == bot_before and chosen not in [c.card_id for c in game.players[0].hand]   # one card less, one drawn
    assert session.effect_run is None, msgs


@with_rig("hellboy", "sun-wukong", *HAND)
def test_taunting_laughter_the_bot_decides_whether_to_discard_and_the_value_follows(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    start(rig)
    put_adjacent(game, table, cfg, "wukong", "hellboy")
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Taunting Laughter", "Sly Monkey")
    msgs = attack(session, table, game, "Taunting Laughter")
    hp = game.fighters["hellboy"].hp
    assert hp in (18, 18 - 3), (hp, msgs)        # the bot paid a card (its 3 ties the 3: no damage) or declined (its value is ignored: 3 damage)
    assert session.pending is None
