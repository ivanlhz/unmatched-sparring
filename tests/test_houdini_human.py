"""Houdini played BY THE HUMAN through the panel (FakeTTS, batch mode): the BOOSTED WITH of the boost cards the human puts in their
discard pile (in a combat and in a Maneuver), two boosts on The Big Reveal, the boost An Illusion lets the human make, the choices
the panel asks (Smoke And Mirrors, the card The Big Reveal returns) and what the table is told to do by hand (the placements of
ESCAPE ARTIST and Grand Escape, the miniature the swap moves). The bot's side of the same cards is in tests/test_houdini_effects.py."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, human_reads, said
from test_e2_human_cards import adjacent_free, bot_defends_with, bot_defends_with_nothing, press, put_adjacent, rig, with_rig  # noqa: F401

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


def attack(session, table, game, attacker, title, target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def spend(table, game, *titles):
    """The human puts these cards (taken from their hand on the table) in their discard pile: a boost."""
    by_id = {c.card_id: c for c in game.players[1].full_set}
    ids = []
    for title in titles:
        i = next(i for i in table.human_hand if by_id[i].title == title and i not in ids)
        ids.append(i)
    for i in ids:
        table.human_hand.remove(i)
    table.human_discard += ids
    table.human_count -= len(ids)
    return ids


def combat_line(msgs):
    return next(m for m in msgs if m.startswith("Combate:"))


# ---------------------------------------------------------------- BOOSTED WITH in a combat

@with_rig("hellboy", "houdini", TRAINING)
def test_flourish_may_boost_and_the_boost_card_draws_a_card_for_you(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "houdini", "hellboy")
    human_hand(table, game, "Flourish", "Flourish", "Sleight of Hand")
    msgs = attack(session, table, game, "houdini", "Flourish")
    assert session.pending is not None and session.pending.wait is not None
    assert said(msgs, "Flourish revelado: si quieres potenciar") and not said(msgs, "Combate:")
    spend(table, game, "Flourish")
    msgs = click(session, table, Event.BOOST)
    assert "total 5" in combat_line(msgs) and "Dano 5" in combat_line(msgs), combat_line(msgs)
    assert said(msgs, "Tu carta: Flourish: robas 1") or said(msgs, "robas 1"), msgs
    assert table.human_deals == [1] and len(game.players[1].hand) == table.human_count     # the bot dealt the drawn card
    assert session.pending is None


@with_rig("hellboy", "houdini", TRAINING)
def test_a_boost_with_misdirection_asks_which_fighter_takes_two_damage(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "houdini", "hellboy")
    human_hand(table, game, "Flourish", "Misdirection")
    attack(session, table, game, "houdini", "Flourish")
    spend(table, game, "Misdirection")
    msgs = click(session, table, Event.BOOST)
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and "lobster" in req.options and "hellboy" in req.options
    assert said(msgs, "Misdirection")
    hp = game.fighters["lobster"].hp
    press(session, table, "lobster")
    assert game.fighters["lobster"].hp == hp - 2 and session.pending is None


@with_rig("hellboy", "houdini", TRAINING)
def test_a_boost_with_all_part_of_the_show_heals_houdini_and_the_dial_follows(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "houdini", "hellboy")
    game.fighters["houdini"].hp = 9
    table.dials[cfg.session_config().dials["houdini"]]["value"] = 9
    session.dials_written[cfg.session_config().dials["houdini"]] = 9
    human_hand(table, game, "Flourish", "All Part of the Show")
    attack(session, table, game, "houdini", "Flourish")
    spend(table, game, "All Part of the Show")
    click(session, table, Event.BOOST)
    assert game.fighters["houdini"].hp == 11
    assert table.dials[cfg.session_config().dials["houdini"]]["value"] == 11


@with_rig("hellboy", "houdini", TRAINING)
def test_the_big_reveal_takes_two_boost_cards_and_gives_one_back_you_choose(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "houdini", "hellboy")
    human_hand(table, game, "The Big Reveal", "Flourish", "Flourish", "Sleight of Hand")
    msgs = attack(session, table, game, "houdini", "The Big Reveal")
    assert said(msgs, "The Big Reveal revelado: puedes potenciarlo hasta 2 veces")
    flourish = spend(table, game, "Flourish", "Flourish")
    msgs = click(session, table, Event.BOOST)
    assert "total 6" in combat_line(msgs), combat_line(msgs)                 # 2 + 2 + 2
    assert table.human_deals == [2] or sum(table.human_deals) == 2           # two BOOSTED WITH draws
    req = session.effect_run.awaiting
    assert req.kind == "cards" and sorted(req.options) == sorted(flourish)
    press(session, table, flourish[0])
    assert flourish[0] in [c.card_id for c in game.players[1].hand] and session.pending is None


@with_rig("hellboy", "houdini", TRAINING)
def test_the_big_reveal_refuses_a_third_boost_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "houdini", "hellboy")
    human_hand(table, game, "The Big Reveal", "Flourish", "Flourish", "Sleight of Hand", "Misdirection")
    attack(session, table, game, "houdini", "The Big Reveal")
    spend(table, game, "Flourish", "Flourish", "Sleight of Hand")
    msgs = click(session, table, Event.BOOST)
    assert said(msgs, "esta carta admite como mucho 2 boosts") and session.pending.wait is not None


@with_rig("hellboy", "houdini", TRAINING)
def test_a_card_without_a_free_boost_is_not_offered_one(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "houdini", "hellboy")
    human_hand(table, game, "For My Next Trick", "Flourish")
    msgs = attack(session, table, game, "houdini", "For My Next Trick")
    assert session.pending is None or session.pending.wait is None
    assert said(msgs, "Combate:")


# ---------------------------------------------------------------- An Illusion Of My Own Design, played by the bot

@with_rig("houdini", "hellboy", "An Illusion of My Own Design", "Flourish")
def test_the_bot_illusion_lets_you_boost_your_defense_even_a_card_without_a_boost_of_its_own(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, TRAINING, "Excalibur", "Service Pistol")
    illusion = next(c for c in game.players[0].hand if c.title == "An Illusion of My Own Design")
    bot_turn(session, table, [Act("attack", fid="houdini", target="hellboy", card=illusion)])
    cid = card_ids(game, 1, TRAINING)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    assert session.pending is not None and session.pending.wait is not None, msgs
    assert said(msgs, "revelado: si quieres potenciar")
    spend(table, game, "Excalibur")
    msgs = click(session, table, Event.BOOST)
    assert "total 6" in combat_line(msgs), combat_line(msgs)               # 3 + Excalibur's boost 3


@with_rig("houdini", "hellboy", "An Illusion of My Own Design", "Flourish")
def test_declining_the_boost_the_illusion_allows_resolves_the_combat(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, TRAINING, "Excalibur")
    illusion = next(c for c in game.players[0].hand if c.title == "An Illusion of My Own Design")
    bot_turn(session, table, [Act("attack", fid="houdini", target="hellboy", card=illusion)])
    cid = card_ids(game, 1, TRAINING)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    msgs = click(session, table, Event.NO_BOOST)
    assert "total 3" in combat_line(msgs)


# ---------------------------------------------------------------- a Maneuver that boosts

@with_rig("hellboy", "houdini", TRAINING)
def test_a_maneuver_boost_runs_its_boosted_with_for_you(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Flourish", "Sleight of Hand")
    click(session, table, Event.MANEUVER)
    spend(table, game, "Flourish")
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "Flourish") and said(msgs, "robas 1"), msgs
    assert table.human_deals == [1, 1] and len(game.players[1].hand) == table.human_count     # the Maneuver's card and the BOOSTED WITH's
    assert game.actions_left == 1


@with_rig("hellboy", "houdini", TRAINING)
def test_a_maneuver_boost_with_bess_gives_the_action_back(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "And the Beautiful Bess!", "Flourish")
    click(session, table, Event.MANEUVER)
    spend(table, game, "And the Beautiful Bess!")
    msgs = click(session, table, Event.END_ACTION)
    assert game.actions_left == 2, msgs


@with_rig("hellboy", "houdini", TRAINING)
def test_a_maneuver_without_a_boost_card_runs_nothing(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Flourish", "Sleight of Hand")
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    assert game.actions_left == 1 and not table.human_deals[1:]


@with_rig("hellboy", "houdini", TRAINING)
def test_escape_artist_the_miniature_the_human_places_anywhere_after_a_boost_is_accepted(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Flourish", "Sleight of Hand")
    houdini = game.fighters["houdini"]
    taken = {f.pos for f in game.fighters.values() if f.alive}
    far = max((s for s in game.board.spaces if s not in taken), key=lambda s: game.board.distance(houdini.pos, s))
    click(session, table, Event.MANEUVER)
    spend(table, game, "Flourish")
    table.positions[cfg.nicknames["houdini"]] = far
    msgs = click(session, table, Event.END_ACTION)
    assert houdini.pos == far
    assert not any("ilegal" in m.lower() for m in msgs)


@with_rig("hellboy", "houdini", TRAINING, "Excalibur", "Service Pistol")
def test_set_the_stage_boosted_in_a_maneuver_asks_for_the_look_at_the_bots_hand(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Set the Stage", "Flourish")
    click(session, table, Event.MANEUVER)
    spend(table, game, "Set the Stage")
    msgs = click(session, table, Event.END_ACTION)
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "cards", msgs
    assert session.effect_run.awaiting.extra.get("of") == 0 and session.effect_run.awaiting.extra.get("purpose") == "discard"
    assert said(msgs, "Set the Stage")


# ---------------------------------------------------------------- the other cards of the human

@with_rig("hellboy", "houdini", "Service Pistol", TRAINING)
def test_smoke_and_mirrors_asks_to_swap_and_the_other_fighter_takes_the_hit(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, "Smoke and Mirrors", "Flourish")
    pistol = next(c for c in game.players[0].hand if c.title == "Service Pistol")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="houdini", card=pistol)])
    cid = card_ids(game, 1, "Smoke and Mirrors")[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    req = session.effect_run.awaiting
    assert req.kind == "optional"
    msgs = press(session, table, True)
    assert said(msgs, "Houdini y Bess") is False and said(msgs, "Bess defiende con Smoke and Mirrors"), msgs     # the other one fights
    assert said(msgs, "intercambia las casillas de houdini y bess")                                          # the miniatures are yours
    assert game.fighters["bess"].hp == 5 - 2 and game.fighters["houdini"].hp == 14 and session.pending is None


@with_rig("hellboy", "houdini", "Excalibur", TRAINING)
def test_all_part_of_the_show_keeps_a_defeated_houdini_in_the_game(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    game.fighters["houdini"].hp = 2
    guid = cfg.session_config().dials["houdini"]
    table.dials[guid]["value"] = 2
    session.dials_written[guid] = 2
    human_hand(table, game, "All Part of the Show", "Flourish")
    excalibur = next(c for c in game.players[0].hand if c.title == "Excalibur")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="houdini", card=excalibur)])
    cid = card_ids(game, 1, "All Part of the Show")[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    assert game.winner is None, msgs
    houdini = game.fighters["houdini"]
    assert houdini.alive and houdini.hp == 4
    assert table.dials[guid]["value"] == 4


@with_rig("hellboy", "houdini", "Horseshoes And Hand Grenades", TRAINING)
def test_grand_escape_won_asks_you_to_place_houdini_anywhere(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, "Grand Escape", "Flourish")
    horseshoes = next(c for c in game.players[0].hand if c.title == "Horseshoes And Hand Grenades")      # value 2: Grand Escape (2) wins the tie
    bot_turn(session, table, [Act("attack", fid="hellboy", target="houdini", card=horseshoes)])
    cid = card_ids(game, 1, "Grand Escape")[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    msgs = click(session, table, Event.NO_BOOST)                  # Grand Escape offers its free BOOST first
    assert said(msgs, "Tu carta: Grand Escape: ") and said(msgs, "en cualquier casilla"), msgs
    assert game.fighters["houdini"].alive and game.winner is None


# ---------------------------------------------------------------- A Magician Never Reveals His Secrets, asked of the human

def bot_confronts_smoke(session, table, game, cfg):
    """The bot's Hellboy attacks with Confront Any Demon or God (3) and your Smoke And Mirrors (3) beats it, so the bot's card
    looks at your hand in its AFTER: you decline the swap and the panel asks about the Magician."""
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, "Smoke and Mirrors", "A Magician Never Reveals His Secrets", "Flourish")
    confront = next(c for c in game.players[0].hand if c.title == "Confront Any Demon or God")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="houdini", card=confront)])
    cid = card_ids(game, 1, "Smoke and Mirrors")[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    assert session.effect_run.awaiting.kind == "optional"
    return press(session, table, False)                      # no swap


@with_rig("hellboy", "houdini", "Confront Any Demon or God", TRAINING)
def test_a_look_at_your_hand_asks_you_about_the_magician_and_revealing_it_cancels_the_look(rig):
    session, table, game, fake, cfg = rig
    reads = len(human_reads(table))
    msgs = bot_confronts_smoke(session, table, game, cfg)
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.extra["shield"] == "A Magician Never Reveals His Secrets"
    assert said(msgs, "Una carta va a mirar tu mano: revelas A Magician Never Reveals His Secrets")
    msgs = press(session, table, True)
    assert session.effect_run is None and len(human_reads(table)) == reads        # the bot never read your hand
    assert [c.title for c in game.players[0].known.cards(game.players[1])] == ["A Magician Never Reveals His Secrets"]
    assert any("revela" in m and "cancela" in m for m in msgs), msgs


@with_rig("hellboy", "houdini", "Confront Any Demon or God", TRAINING)
def test_declining_the_magician_lets_the_bot_look_at_your_hand(rig):
    session, table, game, fake, cfg = rig
    bot_confronts_smoke(session, table, game, cfg)
    press(session, table, False)
    assert len(game.players[0].known.cards(game.players[1])) >= 1 or len(game.players[0].known.seen) >= 1


@with_rig("hellboy", "houdini", "Confront Any Demon or God", TRAINING)
def test_the_magician_in_your_discard_pile_is_not_asked_about(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, "Smoke and Mirrors", "Flourish")
    magician = card_ids(game, 1, "A Magician Never Reveals His Secrets")[0]
    table.human_discard.append(magician)
    session.snap = None
    confront = next(c for c in game.players[0].hand if c.title == "Confront Any Demon or God")
    bot_turn(session, table, [Act("attack", fid="hellboy", target="houdini", card=confront)])
    cid = card_ids(game, 1, "Smoke and Mirrors")[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    click(session, table, Event.REVEAL)
    press(session, table, False)
    assert session.effect_run is None or "shield" not in session.effect_run.awaiting.extra
