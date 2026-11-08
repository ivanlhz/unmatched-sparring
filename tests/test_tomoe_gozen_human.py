"""Tomoe Gozen on the table through the panel (FakeTTS, batch mode), both seats: the human's Witness My Last Battle (refused against a
fighter that is not adjacent, played face up so the bot defends seeing it, the turn ends), the human's Deeds Of Valor (a cap of 2
combat damage), Five Against Thousands coming back to the human's hand, and the ATTACK OF OPPORTUNITY of the bot's Tomoe Gozen on a
human hero that walks out of her zone by hand (the chat says it, the dial follows). The bot's side of the same cards is in
tests/test_tomoe_gozen_effects.py.

Her deck is sheet 176 like the other nine: every id the table reports is resolved against the owner's deck."""
from __future__ import annotations

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, card_ids, human_attack, human_hand, said
from test_e2_human_cards import (adjacent_free, bot_defends_with_nothing, human_scheme, press, put_adjacent,  # noqa: F401
                                 rig, with_rig)

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3


def attack(session, table, game, title, attacker="tomoe", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def put_at(game, table, cfg, fid, space):
    game.fighters[fid].pos = space
    table.positions[cfg.nicknames[fid]] = space


def zone_exit(game, a):
    """(inside, outside) for a hero standing on `a`: a free space in its zone and a free one that shares none, within 2 spaces of `inside`."""
    board = game.board
    taken = {f.pos for f in game.fighters.values() if f.alive}
    for inside in sorted(board.spaces):
        if inside in taken or not board.share_zone(a, inside):
            continue
        for outside in sorted(board.spaces):
            if outside not in taken and not board.share_zone(a, outside) and board.distance(inside, outside) <= 2:
                return inside, outside
    raise AssertionError("no zone exit")


# ---------------------------------------------------------------- Witness My Last Battle, played by the human

@with_rig("hellboy", "tomoe-gozen", TRAINING)
def test_witness_against_a_fighter_that_is_not_adjacent_is_refused(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    tomoe, hellboy = game.fighters["tomoe"], game.fighters["hellboy"]
    far = next(s for s in sorted(game.board.spaces) if game.board.share_zone(hellboy.pos, s) and s not in game.board.adj[hellboy.pos]
               and s != hellboy.pos and all(f.pos != s for f in game.fighters.values() if f.alive))
    put_at(game, table, cfg, "tomoe", far)
    assert game.can_attack(tomoe, hellboy)                                  # she is ranged: other cards reach
    human_hand(table, game, "Witness My Last Battle", "Piercing Shot")
    hp = hellboy.hp
    msgs = attack(session, table, game, "Witness My Last Battle")
    assert said(msgs, "solo puede atacar a un luchador adyacente"), msgs
    assert hellboy.hp == hp and not said(msgs, "Combate:")


@with_rig("hellboy", "tomoe-gozen", TRAINING)
def test_witness_is_played_face_up_the_bot_defends_seeing_it_and_the_turn_ends(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    seen = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: seen.append(attack_card))
    put_adjacent(game, table, cfg, "tomoe", "hellboy")
    human_hand(table, game, "Witness My Last Battle", "Piercing Shot")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Witness My Last Battle")
    assert len(seen) == 1 and seen[0] is not None and seen[0].title == "Witness My Last Battle", seen
    assert game.fighters["hellboy"].hp == hp - 7, msgs
    assert said(msgs, "se juega boca arriba"), msgs
    assert game.actions_left == 0 or game.turn == 0                          # AFTER COMBAT: end the turn


@with_rig("hellboy", "tomoe-gozen", TRAINING)
def test_a_plain_attack_is_not_shown_to_the_bots_defense(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    seen = []
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: seen.append(attack_card))
    put_adjacent(game, table, cfg, "tomoe", "hellboy")
    human_hand(table, game, "Piercing Shot", "Skirmish")
    attack(session, table, game, "Piercing Shot")
    assert seen == [None]


# ---------------------------------------------------------------- the bot plays Witness against the human

@with_rig("tomoe-gozen", "hellboy", "Witness My Last Battle")
def test_the_bots_witness_is_flipped_face_up_and_says_so(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "tomoe", "hellboy")
    witness = next(c for c in game.players[0].hand if c.title == "Witness My Last Battle")
    human_hand(table, game, TRAINING)
    msgs = bot_turn(session, table, [Act("attack", fid="tomoe", target="hellboy", card=witness)])
    assert said(msgs, "Witness My Last Battle se juega boca arriba (valor 7)"), msgs


# ---------------------------------------------------------------- Deeds Of Valor, played by the human

@with_rig("hellboy", "tomoe-gozen", "Excalibur")
def test_deeds_of_valor_caps_the_combat_damage_the_bot_deals_the_human(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "tomoe", "hellboy")
    human_hand(table, game, "Deeds of Valor", "Piercing Shot")
    attacker = next(c for c in game.players[0].hand if c.title == "Excalibur")
    hp = game.fighters["tomoe"].hp
    bot_turn(session, table, [Act("attack", fid="hellboy", target="tomoe", card=attacker)])
    cid = card_ids(game, 1, "Deeds of Valor")[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    lost = hp - game.fighters["tomoe"].hp
    assert (attacker.value or 0) - 2 > 2, "the bot's attack must be worth capping"
    assert lost == 2, (lost, msgs)
    assert said(msgs, "recibe como mucho 2 de dano de combate"), msgs


# ---------------------------------------------------------------- ATTACK OF OPPORTUNITY on a human hero

@with_rig("tomoe-gozen", "hellboy")
def test_a_human_hero_that_walks_out_of_the_bots_zone_by_hand_takes_one_damage_and_the_dial_follows(rig):
    session, table, game, fake, cfg = rig
    tomoe, hellboy = game.fighters["tomoe"], game.fighters["hellboy"]
    inside, outside = zone_exit(game, tomoe.pos)
    put_at(game, table, cfg, "hellboy", inside)
    hp = hellboy.hp
    table.positions[cfg.nicknames["hellboy"]] = outside                    # the human drags the miniature out
    click(session, table, Event.END_ACTION)
    assert game.fighters["hellboy"].pos == outside
    assert game.fighters["hellboy"].hp == hp - 1
    assert cfg.session_config().dials["hellboy"] in {g for g, _ in table.dial_writes}


@with_rig("tomoe-gozen", "hellboy")
def test_a_human_hero_that_moves_inside_the_zone_takes_nothing(rig):
    session, table, game, fake, cfg = rig
    tomoe, hellboy = game.fighters["tomoe"], game.fighters["hellboy"]
    inside, _ = zone_exit(game, tomoe.pos)
    put_at(game, table, cfg, "hellboy", inside)
    hp = hellboy.hp
    other = next(s for s in sorted(game.board.adj[inside]) if game.board.share_zone(tomoe.pos, s) and s != tomoe.pos
                 and all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["hellboy"]] = other
    click(session, table, Event.END_ACTION)
    assert game.fighters["hellboy"].hp == hp


# ---------------------------------------------------------------- Lord Kiso's Final Stand and Five Against Thousands, played by the human

@with_rig("hellboy", "tomoe-gozen", TRAINING)
def test_lord_kisos_final_stand_leaves_the_move_through_sidekicks_to_the_human_then_asks_the_choice(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Lord Kiso's Final Stand", "Piercing Shot")
    game.fighters["tomoe"].hp = 10
    msgs = human_scheme(session, table, game, "Lord Kiso's Final Stand")
    assert said(msgs, "Elige un efecto") and session.effect_run.awaiting.kind == "effect", msgs
    msgs = press(session, table, 0)                                                # the first option: she recovers 2 health
    assert game.fighters["tomoe"].hp == 12, msgs
    assert said(msgs, "mueve a tomoe hasta 3 casillas (puede atravesar sidekicks)") or said(msgs, "puede atravesar sidekicks"), msgs
    assert session.effect_run is None and game.actions_left == 1


@with_rig("hellboy", "tomoe-gozen", TRAINING)
def test_five_against_thousands_asks_the_human_and_goes_back_to_the_hand_when_paid(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "tomoe", "hellboy")
    human_hand(table, game, "Five Against Thousands", "Piercing Shot", "Skirmish")
    msgs = attack(session, table, game, "Five Against Thousands")
    assert said(msgs, "Usas el efecto de Five Against Thousands?") and session.effect_run.awaiting.kind == "optional"
    msgs = press(session, table, True)
    assert said(msgs, "Descarta 1 carta(s)") and said(msgs, "Five Against Thousands vuelve a tu mano"), msgs
    five = next(c for c in game.players[1].full_set if c.title == "Five Against Thousands")
    assert five in game.players[1].hand and five not in game.players[1].discard
