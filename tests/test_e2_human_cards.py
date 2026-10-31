"""E2: the human's box hero on the interpreter, in table mode (`sparring/session_effects.py`, `effects/table.py`).

FakeTTS sessions (batch mode) with the HUMAN playing each box hero against a bot. Per card played by the human:
the engine state matches the card and the chat says what the engine applied ("Tu carta: ..." / "Aplico ...") and
what the human does on the table themselves ("en la mesa: ..."): picks out of their own hand, the order of their
deck, their own miniatures. The bot's side of a human card (its discards, its hand and deck moves, its pieces the
human relocates) reaches the table through the step's script, as the bot's own effects do (D3).
"""
from __future__ import annotations

import json

import pytest

from sparring.ai_medusa import Act
from sparring.session import Session
from sparring.state import Game, RuleError
from sparring.tts.ui import Event
from sparring.ai_medusa import MedusaAI
from test_batch import click
from test_choice_infra import visible_choices
from test_d3_table_effects import build, card_ids, human_attack, human_hand, said, to_bot_discard


ONGOING_SPOTS = {"bot_ongoing_spot": [6.0, 1.7, -22.0], "human_ongoing_spot": [-2.0, -22.0]}


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand, over = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, **over)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(bot, human, *hand, **over):
    return pytest.mark.parametrize("rig", [(bot, human, hand, over)], indirect=True)


def bot_defends_with(session, game, title, monkeypatch):
    card = next(c for c in game.players[0].hand if c.title == title)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: card)
    return card


def bot_defends_with_nothing(session, monkeypatch):
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: None)


def human_scheme(session, table, game, title):
    """Plan, the card appears face up in the human's discard, Fin de accion recognizes it."""
    click(session, table, Event.SCHEME)
    cid = card_ids(game, 1, title)[0]
    table.human_discard.append(cid)
    table.human_count -= 1
    return click(session, table, Event.END_ACTION)


def labels(session) -> list[str]:
    lab = session.panel_labels()
    return [lab[i] for i in visible_choices(session)]


def press(session, table, option):
    """Clicks the choice button whose option value (or label prefix) is `option`."""
    req = session.effect_run.awaiting
    if option in req.options:
        i = req.options.index(option) + 1
    else:
        i = next(k for k, text in enumerate(labels(session), 1) if text.startswith(option))
    return click(session, table, Event.CHOICE, {"i": i})


def by_hand(session, table, cfg, fid, space):
    """The human puts the miniature of `fid` on `space` by hand and presses Hecho (button 1)."""
    table.positions[cfg.nicknames[fid]] = space
    return click(session, table, Event.CHOICE, {"i": 1})


def adjacent_free(game, fid, avoid=()):
    pos = game.fighters[fid].pos
    taken = {f.pos for f in game.fighters.values() if f.alive} | set(avoid)
    return next(s for s in sorted(game.board.adj[pos]) if s not in taken)


def put_adjacent(game, table, cfg, fid, to):
    """`fid` on a free space adjacent to `to` and in its zone (so zone effects reach both)."""
    pos = game.fighters[to].pos
    taken = {f.pos for f in game.fighters.values() if f.alive}
    space = next(s for s in sorted(game.board.adj[pos]) if s not in taken and game.board.share_zone(pos, s))
    game.fighters[fid].pos = space
    table.positions[cfg.nicknames[fid]] = space
    return space


# ---------------------------------------------------------------- Hellboy (human) vs Abe (bot)

HELLBOY_VS_ABE = ("abe-sapien", "hellboy", "Faster. Stronger.", "Arcane Dampener", "Cold Iron And Holy Water",
                  "Shock And Awe", "Leap Away")


@with_rig(*HELLBOY_VS_ABE)
def test_horseshoes_hurts_the_bot_fighters_in_the_zone_and_the_dials_follow(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "abe")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Horseshoes And Hand Grenades", "Excalibur")
    human_attack(session, table, game, "hellboy", "abe", "Horseshoes And Hand Grenades")
    abe = game.fighters["abe"]
    msgs = click(session, table, Event.REVEAL)
    assert abe.hp == 13 - 2 - 1 and "Tu carta: Horseshoes And Hand Grenades: abe -1 PV (10)" in msgs
    assert cfg.session_config().dials["abe"] in {g for g, _ in table.dial_writes}


@with_rig(*HELLBOY_VS_ABE)
def test_right_hand_of_doom_asks_the_fighter_moves_the_bots_piece_and_leaves_yours_to_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "abe")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Right Hand Of Doom", "Excalibur")
    human_attack(session, table, game, "hellboy", "abe", "Right Hand Of Doom")
    put_adjacent(game, table, cfg, "lobster", "hellboy")
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is not None and session.effect_run.awaiting.kind == "fighter"
    assert set(session.effect_run.awaiting.options) == {"abe", "lobster"} and said(msgs, "Elige un luchador - Right Hand Of Doom")
    press(session, table, "abe")                                # the bot's piece: where it goes is asked
    req = session.effect_run.awaiting
    assert req.kind == "space" and req.extra["fighter"] == "abe"
    assert session.panel_labels() == {"btn_choice_1": "Hecho", "btn_choice_2": "No mover"}     # no space buttons
    dest = req.options[0]
    msgs = by_hand(session, table, cfg, "abe", dest)
    assert session.pending is None and game.fighters["abe"].pos == dest
    nick = cfg.nicknames["abe"]
    assert not any(m[0] == nick for m in table.moves), "the human moved it: the bot does not touch the miniature"
    assert any("Tu carta: Right Hand Of Doom: abe se mueve a" in m and "en la mesa: mueve a hellboy hasta 1 casilla" in m
               for m in msgs), msgs


@with_rig(*HELLBOY_VS_ABE)
def test_planned_recklessness_cancels_the_bots_card_and_shields_your_fighters(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "abe")
    human_hand(table, game, "Planned Recklessness", "Excalibur")
    pr = card_ids(game, 1, "Planned Recklessness")[0]
    dampener = next(c for c in game.players[0].hand if c.title == "Arcane Dampener")
    from test_d3_table_effects import bot_turn
    bot_turn(session, table, [Act("attack", fid="abe", target="hellboy", card=dampener)])
    table.face_down = [{"id": pr, "guid": f"h{pr}"}]
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is None and game.fighters["hellboy"].hp == 18
    assert any("Tu carta: Planned Recklessness: hellboy no recibe dano de efectos este turno; lobster no recibe dano de "
               "efectos este turno; cancela los efectos de Arcane Dampener" in m for m in msgs), msgs
    assert game.damage(game.fighters["hellboy"], 1, "effect") == 0        # the shield holds this turn


@with_rig(*HELLBOY_VS_ABE)
def test_posthumous_power_buttons_appear_only_when_played_and_the_heal_reaches_the_dials(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    assert visible_choices(session) == []
    put_adjacent(game, table, cfg, "lobster", "abe")                 # Posthumous Power is the Lobster's card
    bot_defends_with_nothing(session, monkeypatch)
    game.fighters["hellboy"].hp = 10
    human_hand(table, game, "Posthumous Power", "Excalibur")
    human_attack(session, table, game, "lobster", "abe", "Posthumous Power")
    click(session, table, Event.REVEAL)
    assert len(visible_choices(session)) == 3 and labels(session)[0].startswith("each friendly fighter")
    msgs = press(session, table, "each friendly")
    assert session.pending is None and game.fighters["hellboy"].hp == 11 and game.fighters["lobster"].hp == 6
    assert any("Tu carta: Posthumous Power: hellboy recupera 1 PV (11)" in m for m in msgs)
    assert visible_choices(session) == []


@with_rig(*HELLBOY_VS_ABE)
def test_glimpse_of_hell_draws_in_the_engine_and_the_shuffle_back_is_yours(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "abe")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Glimpse Of Hell", "Excalibur", "Service Pistol")
    human_attack(session, table, game, "hellboy", "abe", "Glimpse Of Hell")
    msgs = click(session, table, Event.REVEAL)
    assert len(game.players[1].hand) == 3 - 1 + 2, "the engine draws (counted placeholders), it never picks the return"
    assert any("Tu carta: Glimpse Of Hell: robas 2; en la mesa: pon 1 carta de tu mano en tu mazo y baraja" in m for m in msgs)
    assert said(msgs, "Te he dado 2 cartas (efectos del combate)") and table.human_deals == [2]
    assert not any("Carta " in lab for lab in labels(session))             # no placeholder of your hand is ever named


@with_rig(*HELLBOY_VS_ABE)
def test_on_earth_takes_the_destiny_count_and_heals_when_lost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "abe")
    destiny = [c.card_id for c in game.players[1].full_set if "destiny" in c.tags][:3]
    table.human_discard = list(destiny)
    game.fighters["hellboy"].hp = 10
    human_hand(table, game, "On Earth As It Is In Hell", "Excalibur")
    oe = card_ids(game, 1, "On Earth As It Is In Hell")[0]
    faster = next(c for c in game.players[0].hand if c.title == "Faster. Stronger.")
    from test_d3_table_effects import bot_turn
    bot_turn(session, table, [Act("attack", fid="abe", target="hellboy", card=faster)])
    table.face_down = [{"id": oe, "guid": f"h{oe}"}]
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    combat = next(m for m in msgs if m.startswith("Combate:"))
    assert "On Earth As It Is In Hell (3)" in combat and game.fighters["hellboy"].hp == 10 - (5 - 3) + 2
    assert any("Tu carta: On Earth As It Is In Hell: hellboy recupera 2 PV (10)" in m for m in msgs)


@with_rig(*HELLBOY_VS_ABE)
def test_crown_of_flame_discards_your_hand_for_you_draws_and_grants_the_actions(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "And Upon His Brow Is Set A Crown Of Flame", "Excalibur", "Service Pistol")
    msgs = human_scheme(session, table, game, "And Upon His Brow Is Set A Crown Of Flame")
    assert game.actions_left == 3
    assert said(msgs, "Aplico And Upon His Brow Is Set A Crown Of Flame: robas 2; descartas Excalibur y Service Pistol; ganas 2 acciones")
    assert said(msgs, "Descarto tu mano (2 cartas) por And Upon His Brow Is Set A Crown Of Flame")
    assert session.pending_discard is None and not said(msgs, "Descarta 2 carta(s)")
    assert said(msgs, "Te he dado 2 cartas (efecto de And Upon His Brow Is Set A Crown Of Flame).")
    assert table.hand_discards == [2] and table.human_deals == [2]
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and len(game.players[1].hand) == 2


@with_rig(*HELLBOY_VS_ABE)
def test_pancakes_asks_two_effects_and_a_save_at_the_pause_resumes(rig):
    session, table, game, fake, cfg = rig
    game.fighters["hellboy"].hp = 10
    human_hand(table, game, "Pancakes!", "Excalibur")
    msgs = human_scheme(session, table, game, "Pancakes!")
    assert said(msgs, "Detecto Pancakes!: la carta te pide una eleccion") and len(visible_choices(session)) == 3
    assert game.actions_left == 1 and session.effect_run.awaiting.kind == "effect"
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["game"]["fx"]["parked"] and saved["game"]["fx"]["parked"][0]["flags"]["step"]
    other = Session(Game.new(game.board, seed=3, controllers={}, heroes=cfg.heroes), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(saved)
    assert other.effect_run is not None and other.effect_run.awaiting.key == session.effect_run.awaiting.key
    for s in (session, other):
        s.snap = None
        press(s, table, "Hellboy recovers")
        msgs = press(s, table, "draw 2")
        assert s.effect_run is None and s.game.fighters["hellboy"].hp == 12
        assert said(msgs, "Aplico Pancakes!: hellboy recupera 2 PV (12); robas 2"), msgs
        assert said(msgs, "Efecto resuelto")
    assert other.game.fx.parked == [] and visible_choices(other) == []


@with_rig(*HELLBOY_VS_ABE)
def test_cancel_during_a_forced_choice_is_refused_and_during_an_optional_declines(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Pancakes!", "Excalibur")
    human_scheme(session, table, game, "Pancakes!")
    msgs = click(session, table, Event.CANCEL)
    assert said(msgs, "Esta eleccion es obligatoria") and session.effect_run is not None
    press(session, table, "draw 2")
    press(session, table, "Hellboy recovers")
    assert session.effect_run is None
    # an optional: Hellboy's detective draw is physical, so a Pyrotechnics-like optional is built by hand
    from sparring.effects.run import Ctx, EffectRun
    run = EffectRun([{"op": "optional", "chooser": "owner", "ops": [{"op": "draw", "player": "owner", "amount": 1}]}],
                    Ctx(owner=1, this_fid="hellboy", card_id=None), label="test")
    n = len(game.players[1].hand)
    session.play_effect(run)
    assert session.effect_run is not None and labels(session) == ["Si", "No"]
    msgs = click(session, table, Event.CANCEL)
    assert said(msgs, "Eleccion cancelada: se resuelve sin hacer nada") and session.effect_run is None
    assert len(game.players[1].hand) == n


# ---------------------------------------------------------------- Abe (human) vs Hellboy (bot)

ABE_VS_HELLBOY = ("hellboy", "abe-sapien", "Glimpse Of Hell", "Right Hand Of Doom", "Horseshoes And Hand Grenades",
                  "Second Shot", "Pancakes!")


@with_rig(*ABE_VS_HELLBOY)
def test_cold_iron_blocks_the_bots_draws_and_actions_this_turn(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "abe", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Cold Iron And Holy Water", "Faster. Stronger.")
    human_attack(session, table, game, "abe", "hellboy", "Cold Iron And Holy Water")
    msgs = click(session, table, Event.REVEAL)
    assert any("Tu carta: Cold Iron And Holy Water: no gana acciones este turno; no roba cartas este turno" in m for m in msgs)
    assert not game.fx.can_draw(0) and not game.fx.can_gain_actions(0)
    assert game.draw(0) == [], "the bot's draws are refused by the engine"
    game.fx.emit("end_of_turn", 1)
    assert game.fx.can_draw(0)


@with_rig(*ABE_VS_HELLBOY)
def test_arcane_dampener_lowers_the_bots_value_and_never_below_zero(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "abe", "hellboy")
    bot_defends_with(session, game, "Glimpse Of Hell", monkeypatch)
    human_hand(table, game, "Arcane Dampener", "Faster. Stronger.")
    human_attack(session, table, game, "abe", "hellboy", "Arcane Dampener")
    msgs = click(session, table, Event.REVEAL)
    combat = next(m for m in msgs if m.startswith("Combate:"))
    assert "Glimpse Of Hell (2), Arcane Dampener (-2): total 0" in combat and game.fighters["hellboy"].hp == 18 - 2
    assert any("Tu carta: Arcane Dampener: valor de Glimpse Of Hell -2" in m for m in msgs)


@with_rig(*ABE_VS_HELLBOY)
def test_ward_and_prepare_cancels_and_recovers_a_scheme_you_pick_from_your_public_pile(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "abe", "hellboy")
    human_hand(table, game, "Ward And Prepare", "Faster. Stronger.")
    shield, belt = card_ids(game, 1, "Counterhex Shield", "B.P.R.D. Utility Belt")
    table.human_discard = [shield, belt]
    ward = card_ids(game, 1, "Ward And Prepare")[0]
    rhod = next(c for c in game.players[0].hand if c.title == "Right Hand Of Doom")
    from test_d3_table_effects import bot_turn
    bot_turn(session, table, [Act("attack", fid="hellboy", target="abe", card=rhod)])
    table.face_down = [{"id": ward, "guid": f"h{ward}"}]
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    assert session.effect_run.awaiting.kind == "cards" and sorted(labels(session)) == ["B.P.R.D. Utility Belt", "Counterhex Shield"]
    msgs = press(session, table, shield)
    st = game.players[1]
    assert shield in [c.card_id for c in st.hand] and shield not in [c.card_id for c in st.discard]
    assert "Tu carta: Ward And Prepare: cancela los efectos de Right Hand Of Doom" in msgs          # IMMEDIATELY
    assert "Tu carta: Ward And Prepare: Counterhex Shield vuelve a tu mano" in msgs                  # AFTER
    assert said(msgs, "Recoge Counterhex Shield de tu descarte a tu mano (efectos del combate)"), msgs
    assert shield in game.players[0].known.seen, "a public card in your hand: the bot knows it"


@with_rig(*ABE_VS_HELLBOY)
def test_shock_and_awe_makes_the_bot_discard_a_card_it_chooses_and_the_pile_follows(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "abe", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Shock And Awe", "Faster. Stronger.")
    before = len(game.players[0].hand)
    human_attack(session, table, game, "abe", "hellboy", "Shock And Awe")
    msgs = click(session, table, Event.REVEAL)
    assert len(game.players[0].hand) == before - 1 and len(table.bot_discard) == 1
    gone = game.players[0].discard[-1]
    assert said(msgs, f"El bot descarta {gone.title} por efecto") and gone.card_id in table.bot_discard
    assert any(m.startswith("Tu carta: Shock And Awe: ") and f"descarta {gone.title}" in m for m in msgs)


@with_rig(*ABE_VS_HELLBOY, human_ongoing_spot=None, bot_ongoing_spot=None)       # no ONGOING zone: the pile route
def test_counterhex_shield_stays_in_play_on_your_pile_and_stops_the_bots_effect_damage(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Counterhex Shield", "Faster. Stronger.")
    msgs = human_scheme(session, table, game, "Counterhex Shield")
    shield = card_ids(game, 1, "Counterhex Shield")[0]
    assert game.fx.ongoing_card_id(1) == shield and game.actions_left == 1 + 1
    assert said(msgs, "Counterhex Shield queda en juego: dejala a la vista en tu descarte")
    assert said(msgs, "Aplico Counterhex Shield: robas 1; ganas 1 accion")
    click(session, table, Event.MANEUVER)                       # the sync sees it on the pile and leaves it in play
    assert game.fx.ongoing_card_id(1) == shield and shield not in [c.card_id for c in game.players[1].discard]
    put_adjacent(game, table, cfg, "abe", "hellboy")
    hero = game.fighters["abe"]
    hp = hero.hp
    horseshoes = next(c for c in game.players[0].hand if c.title == "Horseshoes And Hand Grenades")
    from test_d3_table_effects import bot_turn
    table.positions[cfg.nicknames["abe"]] = hero.pos
    bot_turn(session, table, [Act("attack", fid="hellboy", target="abe", card=horseshoes)])
    table.face_down = []
    click(session, table, Event.REVEAL)
    assert hero.hp == hp - 2, "combat damage only: the shield stops the effect damage"


@with_rig(*ABE_VS_HELLBOY)
def test_concussion_device_hurts_and_moves_the_bots_piece_where_you_say(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "abe", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Concussion Device", "Faster. Stronger.")
    human_attack(session, table, game, "abe", "hellboy", "Concussion Device")
    click(session, table, Event.REVEAL)
    hb = game.fighters["hellboy"]
    assert hb.hp == 18 - 2 - 2 and session.effect_run.awaiting.kind == "space"
    dest = session.effect_run.awaiting.options[1]
    msgs = by_hand(session, table, cfg, "hellboy", dest)
    assert hb.pos == dest and not any(m[0] == "Hellboy" for m in table.moves)
    assert any("Tu carta: Concussion Device: hellboy -2 PV (14); hellboy se mueve a" in m for m in msgs)


@with_rig(*ABE_VS_HELLBOY)
def test_secure_the_scene_revives_your_agent_for_you_to_place_and_your_moves_are_yours(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "agent1", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    agent = game.fighters["agent2"]
    agent.died_at, agent.alive, agent.pos, agent.hp = agent.pos, False, None, 0
    human_hand(table, game, "Secure The Scene", "Faster. Stronger.")
    human_attack(session, table, game, "agent1", "hellboy", "Secure The Scene")
    msgs = click(session, table, Event.REVEAL)
    assert session.effect_run.awaiting.kind == "fighter", "which friendly fighter moves is still your call"
    msgs = press(session, table, "abe")
    assert session.pending is None and agent.alive and agent.hp == 1 and agent.pos is not None
    assert any("agent2 vuelve al tablero" in m and "en la mesa: pon a agent2 en el tablero (la zona de tu heroe) con 1 PV, "
               "mueve a abe hasta 2 casillas" in m for m in msgs), msgs
    assert visible_choices(session) == []


@with_rig(*ABE_VS_HELLBOY)
def test_utility_belt_scheme_heals_a_fighter_you_pick_and_boosts_your_next_attack(rig):
    session, table, game, fake, cfg = rig
    game.fighters["abe"].hp = 10
    human_hand(table, game, "B.P.R.D. Utility Belt", "Faster. Stronger.")
    msgs = human_scheme(session, table, game, "B.P.R.D. Utility Belt")
    assert session.effect_run.awaiting.kind == "fighter"
    press(session, table, "abe")
    assert session.effect_run.awaiting.kind == "fighter"           # the move: whose, then yours on the table
    msgs = press(session, table, "abe")
    assert session.effect_run is None and game.fighters["abe"].hp == 11 and game.actions_left == 2
    assert any("Aplico B.P.R.D. Utility Belt: abe recupera 1 PV (11); ganas 1 accion; +1 a tu proximo ataque; "
               "en la mesa: mueve a abe hasta 1 casilla" in m for m in msgs), msgs


# ---------------------------------------------------------------- Baba Yaga (human) vs Liz (bot)

BABA_VS_LIZ = ("liz-sherman", "baba-yaga", "Burning Barrier", "Evade", "Pyrotechnics", "Rekindle", "Searing Clarity")


@with_rig(*BABA_VS_LIZ)
def test_fateful_bargains_asks_only_when_the_bots_effect_damage_hits_baba_beside_koschei(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "baba", "liz")
    put_adjacent(game, table, cfg, "koschei", "baba")
    human_hand(table, game, "Exploit", "Iron Teeth")
    exploit = card_ids(game, 1, "Exploit")[0]
    barrier = next(c for c in game.players[0].hand if c.title == "Burning Barrier")
    from test_d3_table_effects import bot_turn
    bot_turn(session, table, [Act("attack", fid="liz", target="baba", card=barrier)])
    table.face_down = [{"id": exploit, "guid": f"h{exploit}"}]
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is not None and labels(session) == ["Si", "No"]
    assert said(msgs, "Koschei recibe el dano (1) en lugar de Baba Yaga? - Burning Barrier"), msgs
    baba, koschei = game.fighters["baba"], game.fighters["koschei"]
    press(session, table, True)
    assert koschei.hp == 3 - 1 - 1 and baba.hp == 13 and session.pending is None    # his own 1 of the zone, and hers
    assert cfg.session_config().dials["koschei"] in {g for g, _ in table.dial_writes}


@with_rig(*BABA_VS_LIZ)
def test_fateful_bargains_is_not_asked_without_koschei_in_her_zone(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "baba", "liz")
    human_hand(table, game, "Exploit", "Iron Teeth")
    exploit = card_ids(game, 1, "Exploit")[0]
    barrier = next(c for c in game.players[0].hand if c.title == "Burning Barrier")
    from test_d3_table_effects import bot_turn
    bot_turn(session, table, [Act("attack", fid="liz", target="baba", card=barrier)])
    table.face_down = [{"id": exploit, "guid": f"h{exploit}"}]
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    assert session.pending is None and game.fighters["baba"].hp == 13 - 1 and visible_choices(session) == []


@with_rig(*BABA_VS_LIZ)
def test_pact_of_secrecy_moves_the_bots_hand_through_the_bridge_and_leaves_yours_to_you(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Pact Of Secrecy", "Iron Teeth", "Exploit", "Deathless")
    msgs = human_scheme(session, table, game, "Pact Of Secrecy")
    assert session.effect_run.awaiting.kind == "amount" and labels(session) == ["0", "1", "2"]   # yours: by count
    msgs = press(session, table, 2)
    bot = game.players[0]
    assert len(bot.hand) == 2 and len(table.bot_hand) == 2 and table.hand_moves[-1][0] == "shuffle"
    assert said(msgs, "El bot pone 5 cartas de su mano en su mazo y lo baraja"), msgs
    assert session.effect_run is None and game.fx.ongoing_card_id(1) == card_ids(game, 1, "Pact Of Secrecy")[0]
    assert any("Aplico Pact Of Secrecy: " in m and "robas 2" in m and "en la mesa: quedate con 2 cartas de tu mano, "
               "pon el resto de tu mano en tu mazo y baraja" in m for m in msgs), msgs
    assert not any(lab.startswith("Carta ") for lab in labels(session))
    table.human_count = 2
    click(session, table, Event.END_ACTION)                     # the sync follows the count you kept
    assert len(game.players[1].hand) == 2
    assert game.fx.hand_limit(1, 7) == 3 and game.fx.hand_limit(0, 7) == 3


@with_rig(*BABA_VS_LIZ)
def test_pact_of_time_shuffles_what_each_player_picks_from_their_discard(rig):
    session, table, game, fake, cfg = rig
    bot_ids = to_bot_discard(session, table, game, "Feint", "Flame Lash")
    teeth, exploit = card_ids(game, 1, "Iron Teeth", "Exploit")
    table.human_discard = [teeth, exploit]
    human_hand(table, game, "Pact Of Time", "Deathless")
    msgs = human_scheme(session, table, game, "Pact Of Time")
    assert session.effect_run.awaiting.kind == "cards" and sorted(labels(session))[:2] == ["Exploit", "Iron Teeth"]
    press(session, table, teeth)
    msgs = press(session, table, "Confirmar")
    assert len(table.bot_discard) == 0 and set(bot_ids) <= set(table.bot_deck)
    assert said(msgs, "El bot baraja Feint y Flame Lash de su descarte en su mazo"), msgs
    st = game.players[1]
    assert teeth in [c.card_id for c in st.deck] and exploit in [c.card_id for c in st.discard]
    assert said(msgs, "Meto Iron Teeth en tu mazo y lo barajo (efecto de Pact Of Time)")
    assert table.human_deck == [teeth] and teeth not in table.human_discard      # the bot moved it (Ivan 29/10)
    assert not game.fx.can_gain_actions(0) and not game.fx.can_gain_actions(1)


@with_rig(*BABA_VS_LIZ)
def test_pact_of_freedom_places_a_hero_the_bots_through_the_table_and_blocks_the_first_attack(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Pact Of Freedom", "Deathless")
    msgs = human_scheme(session, table, game, "Pact Of Freedom")
    assert session.effect_run.awaiting.kind == "fighter" and set(session.effect_run.awaiting.options) == {"baba", "liz"}
    press(session, table, "liz")
    assert session.effect_run.awaiting.kind == "space"
    far = session.effect_run.awaiting.options[1]
    msgs = by_hand(session, table, cfg, "liz", far)
    assert game.fighters["liz"].pos == far and not any(m[0] == cfg.nicknames["liz"] for m in table.moves)
    assert said(msgs, "robas 2") and session.effect_run is None
    game.fx.taken = 0                                           # as the first action of a turn: nobody may attack
    assert not game.fx.may_attack(1) and not game.fx.may_attack(0 if game.turn == 0 else 1)
    assert "att_baba" in session._blocked_buttons()             # the panel hides your attack buttons


@with_rig(*BABA_VS_LIZ)
def test_deaths_release_heals_koschei_and_his_placement_is_yours(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "koschei", "liz")
    bot_defends_with_nothing(session, monkeypatch)
    koschei = game.fighters["koschei"]
    koschei.hp = 1
    human_hand(table, game, "Death's Release", "Iron Teeth")
    human_attack(session, table, game, "koschei", "liz", "Death's Release")
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is None and koschei.hp == 3 and visible_choices(session) == []
    assert any("Tu carta: Death's Release: koschei recupera 2 PV (3); en la mesa: coloca a koschei en cualquier casilla" in m
               for m in msgs), msgs


@with_rig(*BABA_VS_LIZ)
def test_deathless_revives_koschei_in_the_engine_and_you_put_him_beside_baba(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "baba", "liz")
    bot_defends_with_nothing(session, monkeypatch)
    koschei = game.fighters["koschei"]
    koschei.died_at, koschei.alive, koschei.pos, koschei.hp = koschei.pos, False, None, 0
    human_hand(table, game, "Deathless", "Iron Teeth")
    human_attack(session, table, game, "baba", "liz", "Deathless")
    msgs = click(session, table, Event.REVEAL)
    assert koschei.alive and koschei.hp == 3 and koschei.pos is not None
    assert any("en la mesa: pon a koschei en el tablero (lo mas cerca posible de tu heroe) con 3 PV" in m for m in msgs), msgs


@with_rig(*BABA_VS_LIZ)
def test_read_the_bones_is_yours_the_engine_never_orders_your_deck(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "baba", "liz")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Read The Bones", "Iron Teeth")
    human_attack(session, table, game, "baba", "liz", "Read The Bones")
    msgs = click(session, table, Event.REVEAL)
    assert len(game.players[1].hand) == 1 and visible_choices(session) == []      # nothing taken by the engine
    assert any("Tu carta: Read The Bones: en la mesa: mira las 5 primeras cartas de tu mazo, pon 1 carta en tu mano y el "
               "resto al fondo en orden aleatorio" in m for m in msgs), msgs
    table.human_count += 1                                      # you took one: the sync counts it
    click(session, table, Event.END_ACTION)
    assert len(game.players[1].hand) == 2


@with_rig(*BABA_VS_LIZ)
def test_out_of_time_ends_the_turn_and_hasten_gives_the_attacker_the_action(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "baba", "liz")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Hasten Towards Death", "Out Of Time")
    human_attack(session, table, game, "baba", "liz", "Hasten Towards Death")
    msgs = click(session, table, Event.REVEAL)
    assert game.fighters["baba"].hp == 13 - 1 and game.actions_left == 2
    assert any("Tu carta: Hasten Towards Death: baba -1 PV (12); ganas 1 accion" in m for m in msgs)


# ---------------------------------------------------------------- Liz (human) vs Hellboy (bot)

LIZ_VS_HELLBOY = ("hellboy", "liz-sherman", "Glimpse Of Hell", "Right Hand Of Doom", "Excalibur", "Second Shot", "Pancakes!")


@with_rig(*LIZ_VS_HELLBOY)
def test_fireball_burns_the_bots_fighters_beside_the_defender(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    put_adjacent(game, table, cfg, "lobster", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Fireball", "Evade")
    human_attack(session, table, game, "liz", "hellboy", "Fireball")
    msgs = click(session, table, Event.REVEAL)
    assert game.fighters["lobster"].hp == 6 - 1 and game.fighters["hellboy"].hp == 18 - 5
    assert any("Tu carta: Fireball: lobster -1 PV (5)" in m for m in msgs)


@with_rig(*LIZ_VS_HELLBOY)
def test_burning_barrier_pins_the_bots_fighter_and_burns_its_zone(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Burning Barrier", "Evade")
    human_attack(session, table, game, "liz", "hellboy", "Burning Barrier")
    msgs = click(session, table, Event.REVEAL)
    hb = game.fighters["hellboy"]
    assert not game.fx.can_move(hb) and game.legal_moves(hb, 2) == {hb.pos} and hb.hp == 18 - 2 - 1
    assert any("Tu carta: Burning Barrier: hellboy no puede dejar su espacio este turno" in m for m in msgs)
    assert any("Tu carta: Burning Barrier: hellboy -1 PV (15)" in m for m in msgs)


@with_rig(*LIZ_VS_HELLBOY)
def test_flame_lash_takes_the_real_bottom_card_you_put_in_the_discard(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Flame Lash", "Evade")
    human_attack(session, table, game, "liz", "hellboy", "Flame Lash")
    msgs = click(session, table, Event.REVEAL)
    assert session.pending.wait is not None and session.pending.wait.deck and said(msgs, "carta del FONDO de tu mazo")
    rekindle = card_ids(game, 1, "Rekindle")[0]                 # BOOST 3, the real bottom card
    table.human_discard.append(rekindle)
    msgs = click(session, table, Event.BOOST)
    combat = next(m for m in msgs if m.startswith("Combate:"))
    assert "Flame Lash (1) y Flame Lash (+3): total 4" in combat and game.actions_left == 2
    st = game.players[1]
    assert rekindle in [c.card_id for c in st.discard] and rekindle not in [c.card_id for c in st.deck]
    assert any("Tu carta: Flame Lash: descartas Rekindle; valor de Flame Lash +3" in m for m in msgs), msgs


@with_rig(*LIZ_VS_HELLBOY)
def test_flame_lash_with_a_burning_bottom_card_adds_nothing_and_wildfire_returns_it(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Flame Lash", "Evade")
    human_attack(session, table, game, "liz", "hellboy", "Flame Lash")
    click(session, table, Event.REVEAL)
    fireball = card_ids(game, 1, "Fireball")[0]
    table.human_discard.append(fireball)
    msgs = click(session, table, Event.BOOST)
    combat = next(m for m in msgs if m.startswith("Combate:"))
    assert "Flame Lash (1): total 1" in combat
    st = game.players[1]
    assert fireball in [c.card_id for c in st.hand] and fireball in game.players[0].known.seen
    assert said(msgs, "Tu carta: Flame Lash: descartas Fireball (Wildfire la devuelve a tu mano)"), msgs   # one line (Ivan)
    assert not said(msgs, "Tu habilidad")


@with_rig(*LIZ_VS_HELLBOY)
def test_incinerate_against_the_bot_lets_the_bot_decide_to_pay_two_cards(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    bot_defends_with(session, game, "Glimpse Of Hell", monkeypatch)
    game.fighters["hellboy"].hp = 5                              # the blow would kill: worth two cards
    human_hand(table, game, "Incinerate", "Evade")
    human_attack(session, table, game, "liz", "hellboy", "Incinerate")
    before = len(game.players[0].hand)
    msgs = click(session, table, Event.REVEAL)
    combat = next(m for m in msgs if m.startswith("Combate:"))
    assert "Incinerate (-7): total 0" in combat and game.fighters["hellboy"].hp == 5
    assert len(game.players[0].hand) == before - 3 + 1          # the defense, two cards paid; Glimpse drew 2, returned 1
    assert len(table.bot_discard) == 3 and visible_choices(session) == []


@with_rig(*LIZ_VS_HELLBOY)
def test_pyrotechnics_is_an_optional_you_answer_and_the_cards_are_yours_to_move(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Pyrotechnics", "Evade", "Fireball")
    human_attack(session, table, game, "liz", "hellboy", "Pyrotechnics")
    click(session, table, Event.REVEAL)
    assert labels(session) == ["Si", "No"]
    n = len(game.players[1].hand)
    msgs = press(session, table, True)
    assert len(game.players[1].hand) == n and session.pending is None
    assert any("Tu carta: Pyrotechnics: en la mesa: pon hasta 2 cartas de tu mano en el fondo de tu mazo en el orden que "
               "quieras" in m for m in msgs), msgs
    table.human_count -= 2
    click(session, table, Event.END_ACTION)
    assert len(game.players[1].hand) == n - 2


@with_rig(*LIZ_VS_HELLBOY)
def test_rekindle_picks_from_your_public_pile_and_you_shuffle_them_in(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    fireball, evade = card_ids(game, 1, "Fireball", "Evade")
    table.human_discard = [fireball, evade]
    human_hand(table, game, "Rekindle", "Pyrotechnics")
    click(session, table, Event.MANEUVER)
    table.positions[cfg.nicknames["liz"]] = game.fighters["liz"].pos
    click(session, table, Event.END_ACTION)
    human_attack(session, table, game, "liz", "hellboy", "Rekindle")
    click(session, table, Event.REVEAL)
    assert session.effect_run.awaiting.kind == "cards" and session.effect_run.awaiting.max == 2
    press(session, table, fireball)
    press(session, table, evade)
    msgs = press(session, table, "Confirmar")
    st = game.players[1]
    assert {fireball, evade} <= {c.card_id for c in st.deck} and session.pending is None
    assert said(msgs, "Meto Fireball y Evade en tu mazo y lo barajo (efectos del combate)")
    assert sorted(table.human_deck) == sorted([fireball, evade]) and table.human_discard == []


@with_rig(*LIZ_VS_HELLBOY, human_ongoing_spot=None, bot_ongoing_spot=None)       # no ONGOING zone: the pile route
def test_fight_or_flight_enters_play_on_your_pile_adds_to_your_cards_and_expires_at_your_next_turn(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Fight Or Flight", "Evade", "Fireball")
    msgs = human_scheme(session, table, game, "Fight Or Flight")
    fof = card_ids(game, 1, "Fight Or Flight")[0]
    assert game.fx.ongoing_card_id(1) == fof and game.combat_bonus_total(1) == 1
    assert said(msgs, "Fight Or Flight queda en juego: dejala a la vista en tu descarte")
    assert said(msgs, "No hay human_ongoing_spot en la configuracion: reconozco tu ONGOING en tu descarte")
    assert any("Aplico Fight Or Flight: robas 1; en la mesa: mueve a liz hasta 5 casillas (puede atravesar rivales)" in m
               for m in msgs), msgs
    put_adjacent(game, table, cfg, "liz", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_attack(session, table, game, "liz", "hellboy", "Fireball")
    msgs = click(session, table, Event.REVEAL)
    assert "Fight Or Flight (+1)" in next(m for m in msgs if m.startswith("Combate:"))
    assert game.fx.ongoing_card_id(1) == fof                    # still in play after the sync of the combat
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    msgs = click(session, table, Event.END_ACTION)              # no actions left: the bot's turn, then yours
    assert game.turn == 1 and game.fx.ongoing_card_id(1) is None
    assert said(msgs, "Fight Or Flight deja de estar en juego (caduca): queda en tu descarte")
    assert not said(msgs, "Descarta el plan") and session.pending_discard is None
    assert said(msgs, "WILDFIRE: descarta la carta del fondo de tu mazo") and session.ability_wait is not None


@with_rig(*LIZ_VS_HELLBOY)
def test_a_burning_card_put_in_the_discard_as_a_maneuver_boost_is_warned(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Fireball", "Evade")
    click(session, table, Event.MANEUVER)
    table.human_discard.append(card_ids(game, 1, "Fireball")[0])
    table.human_count = len(table.human_hand)
    table.positions[cfg.nicknames["liz"]] = game.fighters["liz"].pos
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "Fireball no tiene valor de impulso: no cuenta como potenciacion de la Maniobra")
    assert session.maneuver_baseline is None


@with_rig(*LIZ_VS_HELLBOY)
def test_a_physical_draw_under_cold_iron_is_warned_once_and_counted(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    from sparring.effects import modifiers
    modifiers.add_status(game.fx, "cannot_draw", owner=0, until={"event": "end_of_turn"}, player=1)
    human_hand(table, game, "Fireball", "Evade")
    click(session, table, Event.END_ACTION)                     # the engine's hand follows the table: 2 cards
    table.human_count += 1                                      # ...and then you draw by hand anyway
    msgs = click(session, table, Event.MANEUVER)
    assert said(msgs, "Tu mano ha crecido y un efecto en juego te impide robar") and len(game.players[1].hand) == 3
    table.positions[cfg.nicknames["liz"]] = game.fighters["liz"].pos
    msgs = click(session, table, Event.END_ACTION)
    assert not said(msgs, "Tu mano ha crecido")


# ---------------------------------------------------------------- Confront by the human: one discard, no look button (review of E2)

@with_rig(*HELLBOY_VS_ABE)
def test_confront_lost_asks_the_bots_card_once_at_the_panel_and_grants_no_look_button(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "abe")
    bot_defends_with(session, game, "Arcane Dampener", monkeypatch)
    human_hand(table, game, "Confront Any Demon or God", "Excalibur")
    human_attack(session, table, game, "hellboy", "abe", "Confront Any Demon or God", value=-3)   # 0 vs 2: lost
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "cards" and req.extra["of"] == 0 and set(req.options) <= {c.card_id for c in game.players[0].hand}
    assert not session.look_granted and session.panel_view()[1]["btn_look"] == (False, False)
    pick = req.options[0]
    assert session.panel_labels() == {"btn_choice_1": "Hecho"}  # look-and-discard: you act on the table, then Hecho
    table.bot_hand.remove(pick)
    table.bot_discard.append(pick)
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    assert session.pending is None and pick in [c.card_id for c in game.players[0].discard]
    assert len(game.players[0].discard) == 2                    # the defense and the one you put on the pile
    assert not session.look_granted and session.panel_view()[1]["btn_look"] == (False, False)
    assert any(m.startswith("Tu carta: Confront Any Demon or God: robas 1; el bot descarta") or
               m.startswith("Tu carta: Confront Any Demon or God: robas 1; descarta") for m in msgs), msgs


@with_rig(*HELLBOY_VS_ABE)
def test_confront_won_only_draws_and_grants_no_look(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "abe")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Confront Any Demon or God", "Excalibur")
    human_attack(session, table, game, "hellboy", "abe", "Confront Any Demon or God")
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is None and visible_choices(session) == [] and not session.look_granted
    assert session.panel_view()[1]["btn_look"] == (False, False) and len(game.players[0].discard) == 0
    assert said(msgs, "Tu carta: Confront Any Demon or God: robas 1")


# ---------------------------------------------------------------- the ONGOING zone (Ivan, 29/10)

@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_your_ongoing_scheme_is_recognized_on_your_ongoing_spot_and_owed_to_the_pile_when_it_leaves_play(rig):
    session, table, game, fake, cfg = rig
    assert cfg.session_config().human_ongoing_spot == (-2.0, -22.0)
    human_hand(table, game, "Fight Or Flight", "Evade", "Fireball")
    fof = card_ids(game, 1, "Fight Or Flight")[0]
    table.card_to_discard_fails = True                          # the bot cannot move it itself: the manual flow (the bot's own move: test_tts_translators)
    click(session, table, Event.SCHEME)
    table.human_ongoing.append(fof)                             # face up on your ONGOING zone, not on the pile
    table.human_count -= 1
    msgs = click(session, table, Event.END_ACTION)
    assert game.fx.ongoing_card_id(1) == fof and game.combat_bonus_total(1) == 1
    assert said(msgs, "Fight Or Flight queda en juego: dejala en tu zona ONGOING") and not said(msgs, "No hay human_ongoing_spot")
    assert fof not in [c.card_id for c in game.players[1].hand] and len(game.players[1].hand) == 3    # 3 - 1 + the draw
    table.human_count += 1
    click(session, table, Event.MANEUVER)
    table.positions[cfg.nicknames["liz"]] = game.fighters["liz"].pos
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    msgs = click(session, table, Event.END_ACTION)              # the bot's turn, then yours: the card expires
    assert game.turn == 1 and game.fx.ongoing_card_id(1) is None
    assert said(msgs, "Fight Or Flight deja de estar en juego (caduca): pasala de tu zona ONGOING a tu descarte y pulsa Fin de accion")
    assert session.pending_discard["cards"] == [fof] and session.ability_wait is not None
    msgs = click(session, table, Event.END_ACTION)              # the ability is done, the card is still on the spot
    assert session.ability_wait is None and said(msgs, "Aun no veo en tu descarte Fight Or Flight")
    assert fof in [c.card_id for c in game.players[1].discard]
    table.human_ongoing.remove(fof)
    table.human_discard.append(fof)
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and fof in [c.card_id for c in game.players[1].discard]


@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_a_scheme_that_is_not_ongoing_on_your_ongoing_spot_is_ignored_and_you_are_told(rig):
    """Ivan, 29/10: only ONGOING cards count on the ONGOING zone."""
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Searing Clarity", "Evade", "Fireball")
    clarity = card_ids(game, 1, "Searing Clarity")[0]
    click(session, table, Event.SCHEME)
    table.human_ongoing.append(clarity)                            # left on the ONGOING zone by mistake
    table.human_count -= 1
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "Searing Clarity no es un ONGOING: no la cuento en tu zona ONGOING")
    assert game.fx.ongoing_card_id(1) is None and clarity not in [c.card_id for c in game.players[1].discard]


@with_rig("liz-sherman", "hellboy", "Fight Or Flight", "Evade", "Fireball", "Rekindle", "Pyrotechnics", **ONGOING_SPOTS)
def test_the_bots_ongoing_scheme_goes_face_up_on_its_spot_and_to_its_discard_when_it_leaves_play(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Excalibur", "Service Pistol")      # a small hand: the maneuvers' draws stay under the limit
    fof = next(c for c in game.players[0].hand if c.title == "Fight Or Flight")
    from test_d3_table_effects import bot_turn
    msgs = bot_turn(session, table, [Act("frenzy", card=fof)])
    assert game.fx.ongoing_card_id(0) == fof.card_id and table.bot_ongoing == [fof.card_id]
    assert fof.card_id not in table.bot_hand and "place_card_face_up" in [op for step in table.msglog for op in step]
    assert said(msgs, "El bot deja Fight Or Flight en juego: la pone boca arriba en su zona ONGOING")
    assert game.turn == 1 and session.ability_wait is None    # Hellboy in OCCULT DETECTIVE away from the rival start
    click(session, table, Event.MANEUVER)
    table.positions[cfg.nicknames["liz"]] = game.fighters["liz"].pos
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    table.positions[cfg.nicknames["liz"]] = game.fighters["liz"].pos
    click(session, table, Event.END_ACTION)                     # the bot's next turn: the card expires at its start
    assert game.fx.ongoing_card_id(0) is None and fof.card_id in table.bot_discard and table.bot_ongoing == []


# ---------------------------------------------------------------- the start-of-turn ability gate (Ivan, 29/10)

@with_rig(*LIZ_VS_HELLBOY)
def test_your_start_of_turn_ability_blocks_every_button_but_fin_de_accion_until_done_and_survives_a_resume(rig):
    session, table, game, fake, cfg = rig
    from test_d3_table_effects import bot_turn
    msgs = bot_turn(session, table, [])
    assert game.turn == 1 and session.ability_wait is not None and said(msgs, "WILDFIRE: descarta la carta del fondo de tu mazo")
    assert said(msgs, "Hazlo en la mesa y pulsa Fin de accion: hasta entonces el resto de botones espera")
    states = session.panel_view()[1]
    assert states["btn_end"] == (True, True) and states["btn_maneuver"] == (False, False) and states["att_liz"] == (False, False)
    assert states["hpm_hellboy"][1] is True and "habilidad de inicio de turno" in session.panel_view()[0]
    msgs = click(session, table, Event.MANEUVER)
    assert said(msgs, "Primero tu habilidad de inicio de turno") and game.actions_left == 2
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["ability_wait"] == session.ability_wait
    other = Session(Game.new(game.board, seed=3, controllers={}, heroes=cfg.heroes), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(saved)
    other.snap = None
    msgs = other.resume()
    assert other.ability_wait is not None and said(msgs, "Tu habilidad de inicio de turno sigue pendiente")
    click(session, table, Event.HP, {"fighter": "hellboy", "delta": -1})       # the burning card's damage, by hand
    msgs = click(session, table, Event.END_ACTION)
    assert session.ability_wait is None and said(msgs, "Habilidad de inicio de turno hecha") and said(msgs, "Te quedan 2 accion")
    assert session.panel_view()[1]["btn_maneuver"] == (True, True) and "ability_wait" not in session.to_dict()


@with_rig(*HELLBOY_VS_ABE)
def test_hellboy_anung_start_waits_for_the_discard_and_the_move(rig):
    session, table, game, fake, cfg = rig
    destiny = [c.card_id for c in game.players[1].full_set if "destiny" in c.tags][:6]
    table.human_discard = list(destiny)
    human_hand(table, game, "Excalibur", "Service Pistol")
    from test_d3_table_effects import bot_turn
    msgs = bot_turn(session, table, [])
    assert game.turn == 1 and said(msgs, "Tu turno (forma: ANUNG UN RAMA)")
    assert session.ability_wait is not None and said(msgs, "ANUNG UN RAMA: descarta 1 carta (obligatorio) y mueve a Hellboy")
    table.human_discard.append(card_ids(game, 1, "Service Pistol")[0])
    table.human_count -= 1
    table.positions["Hellboy"] = next(s for s in sorted(game.board.adj[game.fighters["hellboy"].pos])
                                      if all(f.pos != s for f in game.fighters.values()))
    msgs = click(session, table, Event.END_ACTION)
    assert session.ability_wait is None and game.fighters["hellboy"].pos == table.positions["Hellboy"]
    assert len(game.players[1].hand) == table.human_count and said(msgs, "Habilidad de inicio de turno hecha")
    assert said(msgs, "Te quedan 2 accion") and game.actions_left == 2


@with_rig(*HELLBOY_VS_ABE)
def test_hellboy_in_detective_away_from_the_rival_start_has_no_ability_to_wait_for(rig):
    session, table, game, fake, cfg = rig
    from test_d3_table_effects import bot_turn
    bot_turn(session, table, [])
    assert game.turn == 1 and session.ability_wait is None and session.panel_view()[1]["btn_maneuver"] == (True, True)


# ---------------------------------------------------------------- after the merge with E3

ABE_HUMAN_HAND = ("Service Pistol", "Right Hand Of Doom", "Excalibur", "Second Shot", "Pancakes!")


@pytest.fixture
def e3rig(tmp_path):
    from test_e3_hidden_info import E3Table
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", "abe-sapien", ABE_HUMAN_HAND, table_cls=E3Table)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def test_every_possible_angle_as_a_recognized_scheme_moves_the_bots_card_once(e3rig):
    """E3's row puts the picked card on top of the bot's deck; the projection of the scheme's step must not move
    it again (no `hand_to_deck`)."""
    session, table, game, fake, cfg = e3rig
    human_hand(table, game, "Every Possible Angle", "Faster. Stronger.")
    msgs = human_scheme(session, table, game, "Every Possible Angle")
    assert session.look is not None and session.look["mode"] == "pick" and said(msgs, "El bot pone su mano boca arriba")
    chosen = session.look["ids"][1]
    msgs = click(session, table, Event.LOOK_PING, {"guid": f"g{chosen}"})
    assert table.bot_deck[0] == chosen and chosen not in table.bot_hand and session.look is None
    assert session.effect_run is None and said(msgs, "en la mesa: mueve a abe hasta 3 casillas")   # Abe's move: yours
    assert "hand_to_deck" not in [op for step in table.msglog for op in step]
    assert sorted(c.card_id for c in game.players[0].hand) == sorted(table.bot_hand)
    assert not said(msgs, "El bot pone 1 carta de su mano")


@pytest.fixture
def abe_bot_rig(tmp_path):
    from test_e3_hidden_info import E3Table
    session, table, game, fake, cfg, client = build(tmp_path, "abe-sapien", "hellboy",
                                                   ("Arcane Dampener", "Leap Away", "Concussion Device", "B.P.R.D. Training"),
                                                   table_cls=E3Table)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def test_a_cancelled_attack_on_bot_abe_does_not_spend_intuition_twice_when_repeated(abe_bot_rig, monkeypatch):
    """Ivan (29/10): a refused Revelar then Cancelar keeps the token spent and the card drawn; the same attack again
    carries the declaration (face up, nothing fires twice); another target declares normally."""
    session, table, game, fake, cfg = abe_bot_rig
    put_adjacent(game, table, cfg, "hellboy", "abe")
    put_adjacent(game, table, cfg, "lobster", "agent1")
    game.fx.set_counter(0, "intuition", 1)
    seen = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: seen.append(attack_card))
    human_hand(table, game, "Service Pistol", "Excalibur", "Right Hand Of Doom")
    human_attack(session, table, game, "hellboy", "abe", "Service Pistol")
    real = game.begin_attack
    calls = []

    def refuse_once(*a, **kw):
        if not calls:
            calls.append(1)
            raise RuleError("rechazo simulado")
        return real(*a, **kw)
    monkeypatch.setattr(game, "begin_attack", refuse_once)
    hand_before = len(table.bot_hand)
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "rechazo simulado") and session.pending is not None and session.pending.declared is not None
    assert game.fx.counter_value(0, "intuition") == 0 and len(table.bot_hand) == hand_before + 1   # spent, drew
    msgs = click(session, table, Event.CANCEL)
    assert session.pending is None and said(msgs, "UNCANNY INTUITION ya se aplico a este ataque")
    assert session.declared_carry["attacker"] == "hellboy" and "declared_carry" in session.to_dict()
    table.face_down = []
    human_attack(session, table, game, "hellboy", "abe", "Service Pistol")   # the same attack again
    assert session.pending.declared is not None and session.declared_carry is None
    assert said(session.messages, "UNCANNY INTUITION ya aplicada a este ataque")
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is None and game.fx.counter_value(0, "intuition") == 0 and len(table.bot_hand) == hand_before + 1
    assert [c.title for c in seen] == ["Service Pistol"] * 2, "the defense (chosen at each Revelar) sees the face-up attack"
    assert said(msgs, "UNCANNY INTUITION: tu ataque se juega boca arriba: Service Pistol")
    # a different target after a cancel: the earlier spend stands, the new attack declares normally
    game.fx.set_counter(0, "intuition", 1)
    click(session, table, Event.END_ACTION)
    human_hand(table, game, "Excalibur", "Right Hand Of Doom")
    human_attack(session, table, game, "hellboy", "abe", "Excalibur")
    calls.clear()
    click(session, table, Event.REVEAL)                         # refused again: declared, token spent
    assert game.fx.counter_value(0, "intuition") == 0
    click(session, table, Event.CANCEL)
    table.face_down = []
    human_attack(session, table, game, "lobster", "agent1", "Right Hand Of Doom")
    assert session.pending.declared is None and session.declared_carry is None
    assert game.fx.counter_value(0, "intuition") == 0, "the earlier spend stands"


def test_game_maneuver_checks_before_spending(bprd):
    from conftest import Scripted, give
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Scripted()}, heroes=("hellboy", "liz-sherman"))
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    dud = give(g, 1, "Fireball")
    before = (g.actions_left, len(g.players[1].hand), len(g.players[1].deck))
    with pytest.raises(RuleError):
        g.maneuver(1, {}, boost_card=dud)
    with pytest.raises(RuleError):
        g.maneuver(1, {"hellboy": 3})
    assert (g.actions_left, len(g.players[1].hand), len(g.players[1].deck)) == before


def searing_clarity_pick(session, table, game, incinerate):
    human_hand(table, game, "Searing Clarity", "Evade")
    human_scheme(session, table, game, "Searing Clarity")
    assert session.effect_run.awaiting.kind == "cards"
    return press(session, table, incinerate)                   # max 1: the pick resolves it


@with_rig(*LIZ_VS_HELLBOY)
def test_searing_clarity_pick_is_moved_by_the_bot_into_the_human_deck_and_shuffled(rig):
    session, table, game, fake, cfg = rig
    incinerate, fireball = card_ids(game, 1, "Incinerate", "Fireball")
    table.human_discard = [incinerate, fireball]
    msgs = searing_clarity_pick(session, table, game, incinerate)
    assert said(msgs, "Meto Incinerate en tu mazo y lo barajo"), msgs
    assert not any("Baraja Incinerate" in m or "hazlo tu" in m for m in msgs), msgs
    assert table.deck_moves[-1] == ("shuffle", [incinerate])
    assert table.human_deck == [incinerate] and fireball in table.human_discard and incinerate not in table.human_discard
    assert incinerate in {c.card_id for c in game.players[1].deck}
    click(session, table, Event.END_ACTION)                     # the sync does not fight the move
    assert incinerate in {c.card_id for c in game.players[1].deck}


@with_rig(*LIZ_VS_HELLBOY)
def test_searing_clarity_pick_already_moved_by_the_human_is_not_an_error(rig):
    session, table, game, fake, cfg = rig
    incinerate, fireball = card_ids(game, 1, "Incinerate", "Fireball")
    table.human_discard = [incinerate, fireball]
    human_hand(table, game, "Searing Clarity", "Evade")
    human_scheme(session, table, game, "Searing Clarity")
    table.human_discard.remove(incinerate)                       # the human put it in their deck first
    msgs = press(session, table, incinerate)
    assert said(msgs, "Incinerate ya no esta en tu descarte"), msgs
    assert table.deck_moves == [] and not any(m.startswith("No puedo") for m in msgs)
    assert incinerate in {c.card_id for c in game.players[1].deck}


@with_rig(*LIZ_VS_HELLBOY)
def test_panel_title_of_a_card_pick_has_no_parentheses(rig):
    session, table, game, fake, cfg = rig
    incinerate, fireball = card_ids(game, 1, "Incinerate", "Fireball")
    table.human_discard = [incinerate, fireball]
    human_hand(table, game, "Searing Clarity", "Evade")
    human_scheme(session, table, game, "Searing Clarity")
    from sparring.session_choices import PROMPTS, prompt_text
    req = session.effect_run.awaiting
    assert "(" not in PROMPTS["cards"] and prompt_text(game, req).startswith("Elige una carta")
    status = session._status_text()
    assert status.startswith("Elige una carta") and "(" not in status and ")" not in status


@with_rig(*LIZ_VS_HELLBOY)
def test_incinerate_the_bot_pays_two_cards_and_the_chat_names_them(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    bot_defends_with(session, game, "Glimpse Of Hell", monkeypatch)
    game.fighters["hellboy"].hp = 5                              # lethal: the bot is offered the price and pays
    human_hand(table, game, "Incinerate", "Evade")
    human_attack(session, table, game, "liz", "hellboy", "Incinerate")
    msgs = click(session, table, Event.REVEAL)
    line = next(m for m in msgs if m.startswith("Tu carta: Incinerate"))
    assert "el bot descarta Pancakes! y Second Shot para ignorar el valor de Incinerate (queda a 0; el dano seria letal)" in line, line
    assert "sin efecto" not in line and len(table.bot_discard) == 3


@with_rig(*LIZ_VS_HELLBOY)
def test_incinerate_the_bot_declines_when_it_is_not_worth_it_and_says_so(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "liz", "hellboy")
    bot_defends_with(session, game, "Glimpse Of Hell", monkeypatch)
    human_hand(table, game, "Incinerate", "Evade")
    human_attack(session, table, game, "liz", "hellboy", "Incinerate")
    msgs = click(session, table, Event.REVEAL)
    line = next(m for m in msgs if m.startswith("Tu carta: Incinerate"))
    assert line == "Tu carta: Incinerate: el bot no paga (descartar 2): prefiere recibir 5 de dano a perder 2 cartas", line
    assert game.fighters["hellboy"].hp == 13 and len(table.bot_discard) == 1
