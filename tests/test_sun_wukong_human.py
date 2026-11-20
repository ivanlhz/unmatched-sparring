"""Sun Wukong on the table through the panel (FakeTTS, batch mode), both seats: the human's CLONES ability (a yes/no, 1 damage on the dial,
the Clone put on the table by hand and read from it), Sly Monkey (the Clone and Wukong placed by hand), Golden Chain Mail, Bewilderment, Phoenix
Form, Fiery Eyes That See (the bot shows its hand, the human chooses) and Taunting Laughter; and the bot's Wukong: its Clones come out of the
bag onto the table by GUID. The bot's side of the same cards is in tests/test_sun_wukong_effects.py.

The Clones are three Custom_Token in the save, which real TTS may report as "Tile": nothing that reads or moves a piece looks at the type."""
from __future__ import annotations

from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with, bot_defends_with_nothing, by_hand, labels, press, put_adjacent, rig, with_rig  # noqa: F401

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
    assert said(msgs, "Sun Wukong -1 PV (16)") and said(msgs, "Clone 1 es invocado con 1 PV") and not said(msgs, "pegada a") and said(msgs, "pon a Clone 1 en el tablero (una casilla adyacente) con 1 PV"), msgs
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


def bot_taunts(rig):
    """The bot's Sun Wukong, next to Hellboy, attacks with Taunting Laughter; the human defends with B.P.R.D. Training (3)."""
    session, table, game, fake, cfg = rig
    h = game.fighters["hellboy"]
    spot = next(s for s in sorted(game.board.adj[h.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    game.fighters["wukong"].pos = spot
    table.positions[cfg.nicknames["wukong"]] = spot
    human_hand(table, game, TRAINING, "Excalibur", "Service Pistol", "Glimpse Of Hell", "Right Hand Of Doom")
    return bot_attacks(session, table, game, "Taunting Laughter", "wukong", "hellboy", TRAINING)


@with_rig("sun-wukong", "hellboy", *BOT_HAND)
def test_the_bots_taunting_laughter_asks_the_human_to_discard_or_lose_the_value_of_their_card(rig):
    session, table, game, fake, cfg = rig
    msgs = bot_taunts(rig)
    assert session.effect_run.awaiting.kind == "optional" and session.effect_run.awaiting.extra["cost_cards"] == 1
    assert said(msgs, "Taunting Laughter") and said(msgs, "Your opponent may discard 1 card from their hand"), msgs
    press(session, table, False)
    assert game.fighters["hellboy"].hp == 18 - 3 and session.effect_run is None      # declined: the 3 of Training is ignored, the attack of 3 lands


@with_rig("sun-wukong", "hellboy", *BOT_HAND)
def test_paying_the_card_keeps_the_value_of_the_humans_defense(rig):
    session, table, game, fake, cfg = rig
    bot_taunts(rig)
    msgs = press(session, table, True)
    assert session.effect_run is None or session.effect_run.awaiting.kind != "optional", msgs
    assert game.fighters["hellboy"].hp == 18                                         # the 3 ties the 3: the defender wins, nothing lands


# ---------------------------------------------------------------- the setup: the Clones stay in the bag

def setup_wukong(tmp_path, monkeypatch, first):
    """The game-start gate (draw, placement, Ready) with Sun Wukong as the human: the table has no Clone on it, as after Prepare."""
    import dataclasses
    from sparring.ai_medusa import Act
    from test_d3_table_effects import build
    from test_review5_fixes import GOODH, deck_with_first
    session, table, game, fake, cfg, client = build(tmp_path, "medusa", "sun-wukong", ())
    session.cfg = dataclasses.replace(session.cfg, setup=True, mulligan_bot=True)
    session.first_mode = "random"
    game.turn = first
    table.bot_hand, table.bot_deck, table.human_count = [], deck_with_first(game, GOODH), 0
    fids = [f for f, g in game.fighters.items() if not f.startswith("clone")]
    table.positions = {cfg.nicknames[f]: 10 + i for i, f in enumerate(fids)}          # scrambled, off the start spaces; no Clone on the table
    table.dial_ignores_writes = False
    game.fx.parked.clear()                       # build() opened the harness game's first turn: its CLONES question is not the setup's
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    return session, table, game, fake, cfg, client


def test_the_human_wukong_is_never_asked_to_place_the_clones_that_are_in_the_bag(tmp_path, monkeypatch):
    session, table, game, fake, cfg, client = setup_wukong(tmp_path, monkeypatch, first=0)
    try:
        out = session.start()
        assert session.setup["stage"] == "wait_human" and not any("Clon" in m or "Clone" in m for m in out), out
        start = game.start_spaces[1]
        table.positions[cfg.nicknames["wukong"]] = start
        table.human_count = 5
        out = session.handle(Event.READY)
        assert not any("Falta colocar" in m for m in out), out
        assert session.setup is None and any("Preparacion terminada" in m for m in out), out
        assert not any(game.fighters[c].alive for c in CLONES)
    finally:
        client.close()
        fake.close()


def test_the_bot_wukong_keeps_its_clones_in_the_bag_through_the_setup(tmp_path, monkeypatch):
    import dataclasses
    from sparring.ai_medusa import Act
    from test_d3_table_effects import build
    from test_review5_fixes import GOODH, deck_with_first
    session, table, game, fake, cfg, client = build(tmp_path, "sun-wukong", "hellboy", ())
    try:
        session.cfg = dataclasses.replace(session.cfg, setup=True, mulligan_bot=True)
        session.first_mode = "random"
        game.turn = 0
        table.bot_hand, table.bot_deck, table.human_count = [], deck_with_first(game, ("Ox Form", "Sly Monkey", "Wily Fighting", "Tortoise Form", "Infinite Strikes")), 0
        fids = [f for f in game.fighters if not f.startswith("clone")]
        table.positions = {cfg.nicknames[f]: 10 + i for i, f in enumerate(fids)}
        monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={}))
        monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
        session.start()
        assert not any(game.fighters[c].alive for c in CLONES)
        assert all(cfg.nicknames[c] not in table.positions for c in CLONES), "the bot never puts a Clone on the table at the start"
    finally:
        client.close()
        fake.close()


# ---------------------------------------------------------------- the text of the question, Medusa's gaze, the chat after Yes

@with_rig("hellboy", "sun-wukong", *HAND)
def test_the_clones_prompt_names_the_hero_and_tells_what_the_engine_does(rig):
    session, table, game, fake, cfg = rig
    said_now = []
    session.say = lambda text, kind=None: said_now.append(text)
    session._announce_human_start()
    text = " ".join(said_now)
    assert "{hero}" not in text and "Sun Wukong" in text, text
    assert "no pulses -1" in text and "End action" in text.replace("Fin de accion", "End action"), text      # the engine writes the dial itself


def test_the_human_medusas_gaze_is_still_the_tables_to_do(bprd):
    """CLONES is run by the engine for the table player; nothing else changed: Medusa's GAZE (optional + damage) still waits on the table."""
    from sparring.effects import table as fx_table
    from sparring.effects.model import load_effects
    from sparring.state import Game
    from test_effects_combat import Asking
    ctl = {0: Asking(), 1: Asking()}
    ctl[1].human = True
    g = Game.new(bprd, 3, controllers=ctl, heroes=("hellboy", "medusa"), bot_player=0)
    gaze = next(t for t in load_effects("medusa").triggers if t["id"] == "medusa_gaze")
    assert fx_table.physical(g, 1)
    if gaze["when"]["event"] == "start_of_turn":
        assert fx_table.start_of_turn_is_physical(g, 1, gaze)
    clones = next(t for t in load_effects("sun-wukong").triggers if t["id"] == "clone_summon")
    g2 = Game.new(bprd, 3, controllers={0: Asking(), 1: Asking()}, heroes=("hellboy", "sun-wukong"), bot_player=0)
    g2.controllers[1].human = True
    assert not fx_table.start_of_turn_is_physical(g2, 1, clones)


# ---------------------------------------------------------------- save and resume

def reload(session, table, bprd_game_cls=None):
    """The session as a save brings it back: a fresh Session loaded from the saved dict, then resumed against the same table."""
    import json
    from sparring.ai_medusa import MedusaAI
    from sparring.session import Session
    from sparring.state import Game
    saved = json.loads(json.dumps(session.to_dict()))
    other = Session(Game.new(session.game.board, seed=3, controllers={}, bot_player=session.bot, heroes=tuple(p.hero.slug for p in session.game.players)), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(saved)
    other.snap = None
    other.resume()
    return other


@with_rig("hellboy", "sun-wukong", *HAND)
def test_resume_during_the_clones_question_asks_it_again_with_names(rig):
    session, table, game, fake, cfg = rig
    other = reload(session, table)
    assert other.effect_run is not None and other.effect_run.awaiting.kind == "optional"
    assert any("Elige" in m or "eleccion" in m.lower() or "CLONES" in m for m in other.messages), other.messages
    press(other, table, True)
    assert other.game.fighters["clone1"].alive and other.game.fighters["wukong"].hp == 16


@with_rig("hellboy", "sun-wukong", *HAND)
def test_resume_while_the_clone_is_waiting_to_be_placed_does_not_call_it_missing(rig):
    session, table, game, fake, cfg = rig
    press(session, table, True)
    assert game.placing == {"clone1"}
    table.positions.pop(cfg.nicknames["clone1"], None)           # the Clone is still in the bag
    other = reload(session, table)
    assert other.game.placing == {"clone1"} and other.game.fighters["clone1"].alive
    assert not any("No encuentro la pieza" in m for m in other.messages), other.messages
    spot = free_next_to(other.game, "wukong")[-1]
    table.positions[cfg.nicknames["clone1"]] = spot
    click(other, table, Event.END_ACTION)
    assert other.game.fighters["clone1"].pos == spot


# ---------------------------------------------------------------- Sly Monkey with the three Clones out (Ivan 2026-11-20, W5)

@with_rig("hellboy", "sun-wukong", *HAND)
def test_sly_monkey_with_three_clones_out_asks_which_one_moves_and_the_human_places_both(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    start(rig)
    put_adjacent(game, table, cfg, "wukong", "hellboy")
    far = [s for s in sorted(game.board.spaces, reverse=True) if all(f.pos != s for f in game.fighters.values() if f.alive)
           and not game.board.share_zone(game.fighters["wukong"].pos, s)]
    for fid, s in zip(CLONES, far):
        put_clone(game, table, cfg, fid, s)
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Sly Monkey", "Golden Chain Mail")
    w = game.fighters["wukong"]
    old = w.pos
    msgs = attack(session, table, game, "Sly Monkey")
    assert session.effect_run.awaiting.kind == "fighter" and sorted(session.effect_run.awaiting.options) == CLONES, msgs
    press(session, table, "Clone 2")
    assert game.placing >= {"clone2", "wukong"}, game.placing
    new = next(s for s in sorted(game.board.spaces) if s != old and game.board.share_zone(old, s) and s not in {f.pos for f in game.fighters.values() if f.alive})
    table.positions[cfg.nicknames["wukong"]] = new
    table.positions[cfg.nicknames["clone2"]] = old
    click(session, table, Event.END_ACTION)
    assert w.pos == new and game.fighters["clone2"].pos == old and len([c for c in CLONES if game.fighters[c].alive]) == 3


# ---------------------------------------------------------------- Ox Form and Tortoise Form: the BOOST they grant, DURING as printed (Ivan 2026-11-20, W6)

def spend(table, game, *titles):
    from test_houdini_human import spend as _spend
    return _spend(table, game, *titles)


def combat_line(msgs):
    return next(m for m in msgs if m.startswith("Combate:"))


def bot_ox_form(rig):
    session, table, game, fake, cfg = rig
    h = game.fighters["hellboy"]
    spot = next(s for s in sorted(game.board.adj[h.pos]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    game.fighters["wukong"].pos = spot
    table.positions[cfg.nicknames["wukong"]] = spot
    human_hand(table, game, TRAINING, "Excalibur", "Service Pistol")
    return bot_attacks(session, table, game, "Ox Form", "wukong", "hellboy", TRAINING)


@with_rig("sun-wukong", "hellboy", *BOT_HAND)
def test_the_bots_ox_form_lets_the_human_defender_boost_after_the_bots_during(rig):
    session, table, game, fake, cfg = rig
    msgs = bot_ox_form(rig)
    assert session.pending is not None and session.pending.wait is not None, msgs        # the question comes from the attacker's DURING
    assert said(msgs, "revelado: si quieres potenciar"), msgs
    spend(table, game, "Excalibur")
    msgs = click(session, table, Event.BOOST)
    assert "total 6" in combat_line(msgs), combat_line(msgs)                              # 3 + Excalibur's boost 3
    assert game.fighters["hellboy"].hp == 18 - 1                                            # Ox Form's 7 against 6


@with_rig("sun-wukong", "hellboy", *BOT_HAND)
def test_declining_the_boost_ox_form_grants_resolves_the_combat(rig):
    session, table, game, fake, cfg = rig
    bot_ox_form(rig)
    msgs = click(session, table, Event.NO_BOOST)
    assert "total 3" in combat_line(msgs) and game.fighters["hellboy"].hp == 18 - 4


@with_rig("hellboy", "sun-wukong", *HAND)
def test_the_humans_ox_form_lets_the_bot_defender_boost_if_it_wants(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    start(rig)
    put_adjacent(game, table, cfg, "wukong", "hellboy")
    training = bot_defends_with(session, game, TRAINING, monkeypatch)
    spare = next(c for c in game.players[0].hand if c.title == "Excalibur")
    monkeypatch.setattr(session.ai, "choose_combat_boost", lambda g, ctx: spare)       # the bot takes the BOOST Ox Form grants it
    human_hand(table, game, "Ox Form", "Sly Monkey")
    msgs = attack(session, table, game, "Ox Form")
    assert game.fighters["hellboy"].hp == 18 - 1, msgs                  # 7 against 3 + Excalibur's boost 3 = 6
    assert spare in game.players[0].discard and session.pending is None


# ---------------------------------------------------------------- grants_boost: only a grant to the RIVAL's card

def test_grants_boost_counts_the_grants_to_the_rival_and_never_a_boost_of_the_cards_own(bprd):
    from sparring.effects.modifiers import grants_boost
    from sparring.state import Game
    g = Game.new(bprd, 3, controllers={}, heroes=("sun-wukong", "chupacabra"), bot_player=0)
    mine = {c.title: c for c in g.players[0].full_set}
    theirs = {c.title: c for c in g.players[1].full_set}
    assert grants_boost(mine["Ox Form"]) and grants_boost(mine["Tortoise Form"])
    assert not grants_boost(theirs["Blood in the Air"])                     # its own free BOOST (card: this)
    assert not grants_boost(mine["Infinite Strikes"])


def test_the_bots_blood_in_the_air_gives_the_human_defender_no_boost_prompt(tmp_path, monkeypatch):
    from sparring.ai_medusa import Act
    from test_d3_table_effects import bot_turn, build
    session, table, game, fake, cfg, client = build(tmp_path, "chupacabra", "hellboy", ("Blood in the Air",))
    try:
        put_adjacent(game, table, cfg, "hellboy", "chupacabra")
        human_hand(table, game, TRAINING, "Excalibur", "Service Pistol")
        card = next(c for c in game.players[0].hand if c.title == "Blood in the Air")
        bot_turn(session, table, [Act("attack", fid="chupacabra", target="hellboy", card=card)])
        cid = card_ids(game, 1, TRAINING)[0]
        table.face_down = [{"id": cid, "guid": f"h{cid}"}]
        table.human_hand.remove(cid)
        table.human_count -= 1
        msgs = click(session, table, Event.REVEAL)
        assert not said(msgs, "si quieres potenciar") and (session.pending is None or session.pending.wait is None), msgs
    finally:
        client.close()
        fake.close()


def gate_script(session) -> str:
    """The Lua the pre-game panel (table_reset.Gate.show) sends: set_panel lists every element it sets, all hidden except Clean, Prepare
    and Start."""
    from sparring.table_reset import Gate
    sent = []
    gate = object.__new__(Gate)
    gate.session, gate.client = session, type("C", (), {"call_lua": lambda self, s: sent.append(s)})()
    gate._panel = lambda: None
    gate.show("gate.status.ready", prep=False, start=True)
    return "".join(sent)


@with_rig("hellboy", "sun-wukong", *HAND)
def test_the_pre_game_panel_hides_the_buttons_of_the_clones_still_in_the_bag(rig):
    """Live 20/11: before Start the panel showed "Ataca Clone 1..3" and their -1/+1/Retirar rows (the Clones start in the bag, not
    alive, and the gate only hid the living fighters' elements)."""
    session, table, game, fake, cfg = rig
    for fid in CLONES:
        game.fighters[fid].alive, game.fighters[fid].died_at = False, None
    script = gate_script(session)
    for fid in CLONES:
        for ident in (f"att_{fid}", f"hpm_{fid}", f"hpp_{fid}", f"rm_{fid}"):
            assert ident in script, ident


@with_rig("hellboy", "sun-wukong", *HAND)
def test_the_chosen_card_goes_from_the_row_to_the_bottom_while_the_table_is_slow_to_take_cards_into_the_hand(rig):
    """Live bug (20/11): the row gave the chosen card back to the hand and the hand-to-deck move ran before the table had taken it in:
    'No he podido mover Excalibur de la mano del bot a su mazo'. The row now sends it under the deck itself."""
    from test_e2_human_cards import human_scheme
    session, table, game, fake, cfg = rig
    start(rig)
    human_hand(table, game, "Fiery Eyes That See", "Sly Monkey")
    human_scheme(session, table, game, "Fiery Eyes That See")
    chosen = session.look["ids"][0]
    title = next(c.title for c in game.players[0].full_set if c.card_id == chosen)
    table.lag = 3                                # a card put back in the hand needs more than one read to show there
    msgs = click(session, table, Event.LOOK_PING, {"guid": f"g{chosen}"})
    table.lag = 0
    assert not said(msgs, "No he podido mover") and not said(msgs, "se queda"), msgs
    assert not any(said(msgs, bad) for bad in ("no cerro la fila", "Aviso: la mesa", "No he podido confirmar el reparto", "FakeTTS")), msgs
    assert said(msgs, f"{title} va al fondo del mazo del bot"), msgs
    assert not any(chosen in ids for kind, ids in table.hand_moves), table.hand_moves      # moved once, by the row
    assert table.bot_deck[-1] == chosen and chosen not in table.bot_hand
    resolve = next(s for s in table.scripts if s.startswith("-- sparring:resolve_hand_row"))
    assert "bury(" in resolve


# ---------------------------------------------------------------- Sly Monkey defends against Right Hand Of Doom (live, Ivan 2026-11-20)

def sly_monkey_then_right_hand(rig):
    """The bot's Hellboy hits the human's Wukong with Right Hand Of Doom; Wukong answers with Sly Monkey and the human places the
    Clone on Wukong's old space and Wukong in his zone, by hand. Returns what the table must show after End action."""
    session, table, game, fake, cfg = rig
    start(rig)
    put_adjacent(game, table, cfg, "wukong", "hellboy")
    human_hand(table, game, "Sly Monkey", "Golden Chain Mail")
    w = game.fighters["wukong"]
    old = w.pos
    bot_attacks(session, table, game, "Right Hand Of Doom", "hellboy", "wukong", "Sly Monkey")
    clone = next(c for c in CLONES if game.fighters[c].alive)
    assert clone in game.placing and "wukong" in game.placing, game.placing
    new = next(s for s in sorted(game.board.spaces) if s != old and game.board.share_zone(old, s)
               and s not in {f.pos for f in game.fighters.values() if f.alive})
    table.positions[cfg.nicknames["wukong"]] = new
    return clone, old, new


@with_rig("hellboy", "sun-wukong", *HAND)
def test_right_hand_of_doom_after_sly_monkey_moves_the_clone_not_wukong(rig):
    session, table, game, fake, cfg = rig
    clone, old, new = sly_monkey_then_right_hand(rig)
    table.positions[cfg.nicknames[clone]] = old
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["wukong"].pos == new
    assert not said(msgs, "Sun Wukong se mueve") and not said(msgs, "Wukong se mueve"), msgs
    h = game.fighters["hellboy"]
    assert table.positions[cfg.nicknames["hellboy"]] == h.pos
    for fid, f in game.fighters.items():
        if f.alive:
            assert table.positions[cfg.nicknames[fid]] == f.pos, (fid, f.pos, table.positions[cfg.nicknames[fid]], msgs)
    assert len({f.pos for f in game.fighters.values() if f.alive}) == len([f for f in game.fighters.values() if f.alive])


@with_rig("hellboy", "sun-wukong", *HAND)
def test_right_hand_of_doom_after_sly_monkey_with_another_clone_token(rig):
    session, table, game, fake, cfg = rig
    clone, old, new = sly_monkey_then_right_hand(rig)
    other = next(c for c in CLONES if c != clone)
    clone_guid, other_guid = session.cfg.pieces[clone], session.cfg.pieces[other]
    table.positions[cfg.nicknames[other]] = old
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["wukong"].pos == new and not said(msgs, "Wukong se mueve"), msgs
    assert game.fighters[clone].alive and game.fighters[other].pos is None, msgs      # the engine's records did not change hands
    assert session.cfg.pieces[clone] == other_guid and session.cfg.pieces[other] == clone_guid     # the fid follows the token on the table
    assert not said(msgs, "cae"), msgs                                                  # nobody left the table
    assert table.positions[cfg.nicknames[other]] == game.fighters[clone].pos != old, msgs  # the bot moved that very token
    assert len({f.pos for f in game.fighters.values() if f.alive}) == len([f for f in game.fighters.values() if f.alive])


@with_rig("hellboy", "sun-wukong", *HAND)
def test_another_clone_token_on_a_different_space_gives_the_clone_its_space(rig):
    """The human chose where the token goes: the engine's Clone takes the space the token was read on, not the guessed one."""
    session, table, game, fake, cfg = rig
    clone, old, new = sly_monkey_then_right_hand(rig)
    other = next(c for c in CLONES if c != clone)
    taken = {f.pos for f in game.fighters.values() if f.alive} | {new}
    elsewhere = next(s for s in sorted(game.board.spaces) if s not in taken and s != old)
    table.positions[cfg.nicknames[other]] = elsewhere
    session.game.hand_moves.clear()
    session._settle_placements()
    assert game.fighters[clone].pos == elsewhere and clone not in game.placing, game.placing


@with_rig("hellboy", "sun-wukong", *HAND)
def test_a_same_name_sidekick_is_not_an_interchangeable_token(rig):
    """Only a reserve token (Wukong's Clones) is adopted: Hellboy's own kind of sidekick pair never trades GUIDs."""
    session, table, game, fake, cfg = rig
    start(rig)
    assert session.reserve_kin(game.fighters["hellboy"]) == [] and session.reserve_kin(game.fighters["lobster"]) == []
    assert {o.fid for o in session.reserve_kin(game.fighters["clone1"])} == {"clone2", "clone3"}


@with_rig("hellboy", "george-washington", *HAND)
def test_named_sidekick_tokens_of_other_heroes_are_not_interchangeable(rig):
    session, table, game, fake, cfg = rig
    sidekicks = [f for f in game.own(1, alive_only=False) if not f.hero]
    assert sidekicks and all(session.reserve_kin(f) == [] for f in sidekicks)
