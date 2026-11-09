"""Eredin on the table through the panel (FakeTTS, batch mode), both seats: the human's Icy Guile (the price of a Red Rider and which one,
by the miniatures' names), Backhand (the bot's card goes on top of its deck, or to its pile when enraged), Unyielding Hordes (the
Red Rider comes back where the human puts it), Foul Purpose at any range and Implacable as an attack (only while enraged), Portal
Defense (the human swaps by hand and the Red Rider takes the blow), Might Of The Aen Elle and Close For The Kill; and the bot's Eredin:
Backhand (the human is told to put a card on top of their deck), Wild Hunt (the dials follow), Icy Guile (the fallen Red Rider leaves the
table), the rage's longer move. The bot's side of the same cards is in tests/test_eredin_effects.py.

His deck is sheet 176 like Medusa's and the turtles': every id the table reports is resolved against the owner's deck. The four Red Riders
are Custom_Token in the save, which real TTS reports as "Tile": nothing that reads or moves a piece looks at the type."""
from __future__ import annotations

from sparring import enraged
from sparring.ai_medusa import Act
from sparring.tts import lua
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with, bot_defends_with_nothing, human_scheme, labels, press, put_adjacent, rig, with_rig  # noqa: F401
from test_review9 import rt, run  # noqa: F401

RIDERS = ["rider1", "rider2", "rider3", "rider4"]
TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3
HAND = ("Excalibur", TRAINING, "Service Pistol", "Right Hand Of Doom")


def enrage(game):
    for fid in RIDERS:
        game.defeat(game.fighters[fid])


def attack(session, table, game, title, attacker="eredin", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


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


def dial(session, cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


# ---------------------------------------------------------------- Icy Guile, played by the human

@with_rig("hellboy", "eredin", *HAND)
def test_icy_guile_asks_the_price_and_which_red_rider_by_the_name_of_its_miniature(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Icy Guile", "Backhand", "Skirmish")
    msgs = attack(session, table, game, "Icy Guile")
    assert session.effect_run.awaiting.kind == "optional" and said(msgs, "Usas el efecto de Icy Guile"), msgs
    msgs = press(session, table, True)
    assert session.effect_run.awaiting.kind == "fighter" and labels(session) == ["Maxwell", "Aleksei", "Adrian", "Norman"], labels(session)
    assert said(msgs, "1: Maxwell, 2: Aleksei, 3: Adrian, 4: Norman"), msgs                  # four "Red Rider" buttons would be the same button
    msgs = press(session, table, "Aleksei")
    assert not game.fighters["rider2"].alive and all(game.fighters[f].alive for f in ("rider1", "rider3", "rider4"))
    assert said(msgs, "rider2 abatido; el valor de B.P.R.D. Training pasa a 0"), msgs
    assert said(msgs, "Aleksei cae: lo he apartado"), msgs                                    # the miniature leaves the board
    assert session.pending is None and game.fighters["hellboy"].hp == 18 - 2


@with_rig("hellboy", "eredin", *HAND)
def test_icy_guile_declined_costs_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Icy Guile", "Backhand", "Skirmish")
    attack(session, table, game, "Icy Guile")
    press(session, table, False)
    assert all(game.fighters[f].alive for f in RIDERS) and game.fighters["hellboy"].hp == 18


@with_rig("hellboy", "eredin", *HAND)
def test_the_last_red_rider_paid_for_icy_guile_enrages_the_human_and_the_card_gets_the_bonus(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    for fid in RIDERS[1:]:
        game.defeat(game.fighters[fid])
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Icy Guile", "Backhand", "Skirmish")
    attack(session, table, game, "Icy Guile")
    press(session, table, True)                                  # the only Red Rider: no question about which
    assert enraged.is_enraged(game, 1) and game.fighters["eredin"].move == 3
    assert game.fighters["hellboy"].hp == 18 - 3                 # 2 printed + 1 from KING OF THE WILD HUNT, against a value that is ignored


# ---------------------------------------------------------------- Backhand, played by the human

@with_rig("hellboy", "eredin", *HAND)
def test_backhand_puts_a_random_card_of_the_bots_hand_on_top_of_its_deck(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Backhand", "Skirmish")
    hand, deck = len(game.players[0].hand), len(game.players[0].deck)
    msgs = attack(session, table, game, "Backhand")
    assert len(game.players[0].hand) == hand - 1 and len(game.players[0].deck) == deck + 1
    assert game.players[0].deck[0].card_id not in table.bot_hand
    assert table.hand_moves[-1][0] == "top" and len(table.hand_moves[-1][1]) == 1, table.hand_moves     # on top, not shuffled in
    assert said(msgs, "El bot pone 1 carta de su mano encima de su mazo"), msgs


@with_rig("hellboy", "eredin", *HAND)
def test_backhand_while_enraged_makes_the_bot_discard_the_card_instead(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    enrage(game)
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Backhand", "Skirmish")
    hand, deck, pile = len(game.players[0].hand), len(game.players[0].deck), len(game.players[0].discard)
    attack(session, table, game, "Backhand")
    assert len(game.players[0].hand) == hand - 1 and len(game.players[0].deck) == deck and len(game.players[0].discard) == pile + 1
    assert game.fighters["hellboy"].hp == 18 - 5                 # 4 printed + the rage


# ---------------------------------------------------------------- Unyielding Hordes, played by a human Red Rider

@with_rig("hellboy", "eredin", *HAND)
def test_unyielding_hordes_returns_a_fallen_rider_for_the_human_to_place_and_counts_it(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "rider1", "hellboy")
    game.defeat(game.fighters["rider2"])
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Unyielding Hordes", "Backhand", "Skirmish")
    msgs = attack(session, table, game, "Unyielding Hordes", attacker="rider1")
    rider = game.fighters["rider2"]
    assert rider.alive and rider.hp == 1 and "rider2" in game.placing
    assert said(msgs, "pon a rider2 en el tablero (cualquier casilla) con 1 PV"), msgs      # your miniature: you place it by hand
    assert not said(msgs, "lo he movido yo"), msgs                                           # and the bot does not move it too
    assert rider.pos in game.board.adj[game.fighters["hellboy"].pos]                         # counted next to the target: +1 for it
    assert game.fighters["hellboy"].hp == 18 - (1 + 2)                                       # 1 printed + Eredin and the returned rider2, both next to the target


# ---------------------------------------------------------------- Foul Purpose and Implacable, by the human

@with_rig("hellboy", "eredin", *HAND)
def test_foul_purpose_against_a_far_fighter_is_refused_while_the_human_is_not_enraged(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Foul Purpose", "Backhand")
    far = game.fighters["lobster"]
    assert not game.board.share_zone(game.fighters["eredin"].pos, far.pos)
    click(session, table, Event.ATTACKER, {"attacker": "att_eredin"})
    msgs = click(session, table, Event.ATTACK, {"target": "lobster"})
    assert said(msgs, "eredin no alcanza a lobster"), msgs
    assert session.pending is None and far.hp == far.max_hp


@with_rig("hellboy", "eredin", *HAND)
def test_foul_purpose_far_away_with_the_card_of_the_wrong_kind_is_refused_at_the_reveal_even_enraged(rig, monkeypatch):
    """Enraged, the human may name a far fighter before the card is on the table; a card that is not Foul Purpose is refused then."""
    session, table, game, fake, cfg = rig
    enrage(game)
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Backhand", "Foul Purpose")
    hp = game.fighters["lobster"].hp
    msgs = attack(session, table, game, "Backhand", target="lobster")
    assert said(msgs, "Carta ilegal") and said(msgs, "eredin no alcanza a lobster") and game.fighters["lobster"].hp == hp, msgs


@with_rig("hellboy", "eredin", *HAND)
def test_foul_purpose_enraged_hits_a_fighter_in_any_space_and_the_bot_defends_seeing_it(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    enrage(game)
    seen = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: seen.append(attack_card))
    human_hand(table, game, "Foul Purpose", "Backhand")
    lobster = game.fighters["lobster"]
    assert not game.board.share_zone(game.fighters["eredin"].pos, lobster.pos)
    hp = lobster.hp
    msgs = attack(session, table, game, "Foul Purpose", target="lobster")
    assert len(seen) == 1 and seen[0] is not None and seen[0].title == "Foul Purpose", seen      # face up: the defense may know it
    assert lobster.hp == hp - 4 and said(msgs, "se juega boca arriba"), msgs                     # 3 printed + the rage


@with_rig("hellboy", "eredin", *HAND)
def test_foul_purpose_in_reach_is_not_shown_face_up(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    enrage(game)
    seen = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: seen.append(attack_card))
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    human_hand(table, game, "Foul Purpose", "Backhand")
    attack(session, table, game, "Foul Purpose")
    assert seen == [None]


@with_rig("hellboy", "eredin", *HAND)
def test_implacable_is_refused_as_an_attack_while_the_human_is_not_enraged(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Implacable", "Backhand")
    msgs = attack(session, table, game, "Implacable")
    assert said(msgs, "Carta ilegal: Implacable es de tipo defense"), msgs
    assert game.fighters["hellboy"].hp == 18


@with_rig("hellboy", "eredin", *HAND)
def test_implacable_attacks_while_enraged_and_the_panel_offers_its_free_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    enrage(game)
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Implacable", "Backhand")
    msgs = attack(session, table, game, "Implacable")
    assert said(msgs, "Implacable revelado: si quieres potenciar"), msgs
    click(session, table, Event.NO_BOOST)
    assert game.fighters["hellboy"].hp == 18 - 4 and session.pending is None                 # 3 printed + the rage


# ---------------------------------------------------------------- Portal Defense, played by the human

@with_rig("hellboy", "eredin", *HAND)
def test_portal_defense_swaps_the_humans_miniatures_by_hand_and_the_red_rider_takes_the_blow(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "eredin")
    put_adjacent(game, table, cfg, "rider1", "eredin")
    human_hand(table, game, "Portal Defense", "Backhand", "Skirmish")
    msgs = bot_attacks(session, table, game, "Excalibur", "hellboy", "eredin", "Portal Defense")
    assert said(msgs, "intercambia las casillas de eredin y rider1"), msgs                   # both miniatures are yours
    assert said(msgs, "Maxwell defiende con Portal Defense"), msgs
    assert not game.fighters["rider1"].alive and game.fighters["eredin"].hp == 14
    assert said(msgs, "Maxwell cae"), msgs


@with_rig("hellboy", "eredin", *HAND)
def test_portal_defense_with_nobody_adjacent_defends_with_eredin(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "eredin")
    human_hand(table, game, "Portal Defense", "Backhand", "Skirmish")
    msgs = bot_attacks(session, table, game, "Excalibur", "hellboy", "eredin", "Portal Defense")
    assert game.fighters["eredin"].hp == 14 - 6 and all(game.fighters[f].alive for f in RIDERS)
    assert not said(msgs, "intercambia"), msgs


# ---------------------------------------------------------------- the schemes, played by the human

@with_rig("hellboy", "eredin", *HAND)
def test_might_of_the_aen_elle_draws_gains_the_action_and_shields_eredin_from_effect_damage(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Might Of The Aen Elle", "Backhand", "Skirmish")
    msgs = human_scheme(session, table, game, "Might Of The Aen Elle")
    assert said(msgs, "Aplico Might Of The Aen Elle: robas 1; ganas 1 accion"), msgs
    assert said(msgs, "queda en juego"), msgs
    assert game.fx.ongoing_card_id(1) is not None and game.actions_left == 2
    eredin = game.fighters["eredin"]
    assert game.damage(eredin, 3, "effect") == 0 and game.damage(game.fighters["rider1"], 1, "effect") == 1
    assert game.damage(eredin, 3, "combat") == 3


@with_rig("hellboy", "eredin", *HAND)
def test_close_for_the_kill_draws_two_and_leaves_every_move_to_the_human(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Close For The Kill", "Backhand", "Skirmish")
    msgs = human_scheme(session, table, game, "Close For The Kill")
    assert said(msgs, "Aplico Close For The Kill: robas 2"), msgs
    for fid in ["eredin", *RIDERS]:
        assert said(msgs, f"mueve a {fid} hasta 3 casillas (puede atravesar rivales)"), msgs
    assert game.actions_left == 1 and session.effect_run is None


# ---------------------------------------------------------------- the rage, on the human's side

@with_rig("hellboy", "eredin", *HAND)
def test_the_human_enraged_attack_carries_the_bonus_and_the_combat_line_says_so(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    enrage(game)
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    bot_defends_with_nothing(session, monkeypatch)
    human_hand(table, game, "Brutal Strike", "Backhand")
    msgs = attack(session, table, game, "Brutal Strike")
    assert said(msgs, "KING OF THE WILD HUNT (+1)"), msgs
    assert game.fighters["hellboy"].hp == 18 - 3


# ---------------------------------------------------------------- the bot plays Eredin against the human

BOT_HAND = ("Backhand", "Wild Hunt", "Icy Guile", "Foul Purpose", "Skirmish", "Brutal Strike")


@with_rig("eredin", "hellboy", *BOT_HAND)
def test_the_bots_backhand_tells_the_human_to_put_a_random_card_on_top_of_their_deck(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    human_hand(table, game, TRAINING, "Right Hand Of Doom", "Service Pistol")
    msgs = bot_attacks(session, table, game, "Backhand", "eredin", "hellboy")
    assert said(msgs, "Aplicado: Backhand: en la mesa: pon 1 carta de tu mano encima de tu mazo"), msgs


@with_rig("eredin", "hellboy", *BOT_HAND)
def test_the_bots_backhand_enraged_makes_the_human_discard_it(rig):
    session, table, game, fake, cfg = rig
    for fid in RIDERS:
        game.defeat(game.fighters[fid])
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    human_hand(table, game, TRAINING, "Right Hand Of Doom", "Service Pistol")
    msgs = bot_attacks(session, table, game, "Backhand", "eredin", "hellboy")
    assert said(msgs, "al azar: la carta") and said(msgs, "Descarta 1 carta(s) (Backhand"), msgs


@with_rig("eredin", "hellboy", *BOT_HAND)
def test_the_bots_wild_hunt_hurts_every_human_fighter_next_to_a_red_rider_and_the_dials_follow(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    put_adjacent(game, table, cfg, "lobster", "hellboy")
    human_hand(table, game, TRAINING, "Right Hand Of Doom", "Service Pistol")
    msgs = bot_attacks(session, table, game, "Wild Hunt", "eredin", "hellboy", TRAINING)
    assert said(msgs, "Aplicado: Wild Hunt: hellboy -1 PV (17); lobster -1 PV (5)"), msgs
    assert dial(session, cfg, table, "hellboy") == 17 and dial(session, cfg, table, "lobster") == 5


@with_rig("eredin", "hellboy", *BOT_HAND)
def test_the_bots_icy_guile_defeats_a_red_rider_and_it_leaves_the_table(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    human_hand(table, game, TRAINING, "Right Hand Of Doom", "Service Pistol")
    msgs = bot_attacks(session, table, game, "Icy Guile", "eredin", "hellboy", TRAINING)
    fallen = [f.fid for f in game.own(0, alive_only=False) if not f.hero and not f.alive]
    assert len(fallen) == 1 and said(msgs, f"Aplicado: Icy Guile: {fallen[0]} abatido; el valor de B.P.R.D. Training pasa a 0"), msgs
    assert said(msgs, "cae: la he apartado fuera del tablero"), msgs


@with_rig("eredin", "hellboy", *BOT_HAND)
def test_the_enraged_bot_hero_walks_three_spaces(rig):
    session, table, game, fake, cfg = rig
    for fid in RIDERS:
        game.defeat(game.fighters[fid])
    assert game.fighters["eredin"].move == 3
    reach = game.legal_moves(game.fighters["eredin"], game.fighters["eredin"].move)
    assert max(game.board.distance(game.fighters["eredin"].pos, s) for s in reach) == 3


# ---------------------------------------------------------------- the pieces

def test_the_red_rider_tokens_are_found_by_their_names_whatever_type_real_tts_reports(rt):  # noqa: F811
    """Custom_Token in the save, "Tile" on the real table (Jill Trent's gadget was the first): the lookup by name and the removal of a
    token take a Tile, and a colour tag in the name does not matter."""
    rt.execute("mkobj({guid = 'a954e5', type = 'Tile', name = 'Maxwell', pos = {x = 0, y = 1, z = 0}, rot = {x = 0, y = 0, z = 0}})")
    rt.execute("mkobj({guid = 'bb3949', type = 'Tile', name = '[6f2176]Aleksei', pos = {x = 0, y = 1, z = 0}, rot = {x = 0, y = 0, z = 0}})")
    found = run(rt, lua.find_pieces_by_name(["maxwell", "aleksei"]))
    assert found == {"maxwell": [{"guid": "a954e5", "type": "Tile"}], "aleksei": [{"guid": "bb3949", "type": "Tile"}]}
    assert run(rt, lua.remove_token("a954e5")) == {"removed": True}


@with_rig("eredin", "hellboy", *BOT_HAND)
def test_the_bots_foul_purpose_that_goes_back_to_its_hand_is_taken_back_on_the_table_too(rig):
    """Its AFTER defeats a Red Rider (the bot pays when two or fewer are left) and the card goes from the combat spot back to the bot's
    hand: engine and table agree afterwards (the end of the bot's action reconciles hand and discard pile)."""
    session, table, game, fake, cfg = rig
    for fid in RIDERS[2:]:
        game.defeat(game.fighters[fid])
    put_adjacent(game, table, cfg, "eredin", "hellboy")
    human_hand(table, game, TRAINING, "Right Hand Of Doom", "Service Pistol")
    foul = next(c for c in game.players[0].hand if c.title == "Foul Purpose")
    msgs = bot_attacks(session, table, game, "Foul Purpose", "eredin", "hellboy", TRAINING)
    assert foul in game.players[0].hand and foul not in game.players[0].discard, msgs
    assert foul.card_id in table.bot_hand and foul.card_id not in table.bot_discard
    assert said(msgs, "El bot recupera Foul Purpose") or said(msgs, "recupera Foul Purpose"), msgs
    assert sorted(table.bot_hand) == sorted(c.card_id for c in game.players[0].hand)
