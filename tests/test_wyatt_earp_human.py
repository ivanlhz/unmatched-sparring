"""Wyatt Earp on the table through the panel (FakeTTS, batch mode), both seats: SHOWDOWN as buttons after the human's winning attack, the
free action to attack (a Maneuver or a scheme cannot spend it), In Vino Veritas dealing cards to the human, You Die First on the bot's
fighters, Better Swear Me In and Bring 'Em To Justice reading the bot's deck, and the bot's Wyatt playing the same cards against a human.
The bot's side of the same cards is in tests/test_wyatt_earp_effects.py.

His deck is on sheet 187 with George Washington's and John Henry's: every id the table reports is resolved against the owner's deck."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with, bot_defends_with_nothing, by_hand, human_scheme, labels, press, put_adjacent
from test_jill_trent_human import JillTable

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3
STAND = "You Just Gonna Stand There And Bleed?"
SHOWDOWN = ["Draw 1 card", "Gain 1 free action to attack", "Move your fighter up to 1 space"]


@pytest.fixture
def mine(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", "wyatt-earp", (TRAINING,), table_cls=JillTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def attack(session, table, game, title, attacker="wyatt", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


# ---------------------------------------------------------------- SHOWDOWN on the human's win

def test_winning_an_attack_puts_the_three_effects_on_the_panel(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "wyatt", "hellboy")
    human_hand(table, game, STAND, "Second Shot")
    attack(session, table, game, STAND)
    req = session.effect_run.awaiting
    assert req.kind == "effect" and req.extra["tag"] == "showdown" and labels(session) == SHOWDOWN


def test_draw_deals_a_card_to_the_human(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "wyatt", "hellboy")
    human_hand(table, game, STAND, "Second Shot")
    attack(session, table, game, STAND)
    msgs = press(session, table, 0)
    assert table.human_deals == [1] and said(msgs, "Te he dado 1 carta"), msgs
    assert game.fx.counter_value(1, "showdown_draw", 0) == 1 and session.effect_run is None


def test_the_free_action_can_only_attack_and_the_panel_says_so(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "wyatt", "hellboy")
    human_hand(table, game, STAND, "Second Shot", "Fan The Hammer")
    attack(session, table, game, STAND)
    msgs = press(session, table, 1)
    assert game.free_attacks == [None] and (game.actions_left, game.paid_actions) == (2, 1)
    assert said(msgs, "ganas 1 accion gratis para atacar"), msgs
    msgs = click(session, table, Event.END_ACTION)
    assert said(msgs, "Te quedan 2 accion(es), 1 gratis y solo para atacar"), msgs
    click(session, table, Event.MANEUVER)                                   # the one ordinary action
    click(session, table, Event.END_ACTION)
    assert (game.actions_left, game.paid_actions) == (1, 0)
    msgs = click(session, table, Event.MANEUVER)
    assert said(msgs, "solo quedan acciones gratis") and game.actions_left == 1 and not session.moving, msgs
    msgs = click(session, table, Event.SCHEME)
    assert said(msgs, "solo quedan acciones gratis") and game.actions_left == 1 and not session.moving, msgs
    attack(session, table, game, "Fan The Hammer")                          # the free action is spent on an attack
    assert game.free_attacks == [] and game.actions_left == 0
    assert session.effect_run.awaiting.options == [0, 2]                    # the free action effect is used: draw or move


def test_the_move_effect_leaves_the_step_of_the_attacker_to_the_human(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "wyatt", "hellboy")
    human_hand(table, game, STAND, "Second Shot")
    attack(session, table, game, STAND)
    msgs = press(session, table, 2)
    assert session.effect_run is None and said(msgs, "mueve a wyatt"), msgs
    start = game.fighters["wyatt"].pos
    dest = next(s for s in sorted(game.board.adj[start]) if all(f.pos != s for f in game.fighters.values() if f.alive))
    table.positions[cfg.nicknames["wyatt"]] = dest
    click(session, table, Event.END_ACTION)
    assert game.fighters["wyatt"].pos == dest and game.fx.counter_value(1, "showdown_move", 0) == 1


def test_in_vino_veritas_deals_cards_up_to_four_and_gives_a_free_attack(mine):
    session, table, game, fake, cfg = mine
    human_hand(table, game, "In Vino Veritas", "Second Shot")
    msgs = human_scheme(session, table, game, "In Vino Veritas")
    assert table.human_deals == [3] and said(msgs, "Te he dado 3 cartas"), msgs
    assert len(game.players[1].hand) == 4 and game.free_attacks == [None] and (game.actions_left, game.paid_actions) == (2, 1), msgs
    assert said(msgs, "ganas 1 accion gratis para atacar"), msgs


def test_you_die_first_asks_the_rival_fighter_and_where_and_binds_the_free_attack_to_it(mine):
    session, table, game, fake, cfg = mine
    human_hand(table, game, "You Die First", "Second Shot")
    click(session, table, Event.SCHEME)
    cid = card_ids(game, 1, "You Die First")[0]
    table.human_discard.append(cid)
    table.human_count -= 1
    click(session, table, Event.END_ACTION)
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and set(req.options) == {"hellboy", "lobster"} and req.extra["purpose"] == "die_first"
    press(session, table, "lobster")
    req = session.effect_run.awaiting
    assert req.kind == "space" and req.extra["fighter"] == "lobster" and req.extra["steps"] == 1
    dest = req.options[0]
    by_hand(session, table, cfg, "lobster", dest)
    assert session.effect_run is None and game.fighters["lobster"].pos == dest and game.free_attacks == ["lobster"]
    assert (game.actions_left, game.paid_actions) == (2, 1)


# ---------------------------------------------------------------- the bot's deck revealed by the human's cards

def test_better_swear_me_in_reveals_the_bots_top_card_and_the_human_may_bury_it(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    put_adjacent(game, table, cfg, "wyatt", "hellboy")
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Better Swear Me In", "Second Shot")
    top = game.players[0].deck[0]
    msgs = attack(session, table, game, "Better Swear Me In")                     # 2 against Training's 3: lost, no SHOWDOWN
    assert said(msgs, f"Reveladas arriba de mi mazo: {top.title}"), msgs
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.extra["bury_rival"] == top.card_id
    msgs = press(session, table, True)
    assert game.players[0].deck[-1] is top and game.players[0].deck[0] is not top, msgs
    assert session.peek_pins["bottom"] == [top.card_id] and said(msgs, "va debajo de mi mazo"), msgs


def test_better_swear_me_in_declined_leaves_the_card_on_top(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    put_adjacent(game, table, cfg, "wyatt", "hellboy")
    bot_defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, "Better Swear Me In", "Second Shot")
    top = game.players[0].deck[0]
    attack(session, table, game, "Better Swear Me In")
    press(session, table, False)
    assert game.players[0].deck[0] is top and session.peek_pins["bottom"] == []


# ---------------------------------------------------------------- the bot plays Wyatt against the human

def bots_attack(tmp_path, title, *others, human_cards=(TRAINING, "Excalibur"), attacker="wyatt"):
    """A rig with the bot's Wyatt holding `title` (and `others`), a rival Hellboy holding `human_cards`, both next to each other."""
    session, table, game, fake, cfg, client = build(tmp_path, "wyatt-earp", "hellboy", (title, *others), table_cls=JillTable)
    put_adjacent(game, table, cfg, attacker, "hellboy")
    human_hand(table, game, *human_cards)
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
    return session, table, game, fake, cfg, client


def run_bot_attack(session, table, game, title, attacker="wyatt"):
    card = next(c for c in game.players[0].hand if c.title == title)
    first = bot_turn(session, table, [Act("attack", fid=attacker, target="hellboy", card=card)])
    return [*first, *click(session, table, Event.REVEAL)]       # the human leaves no defense on the table and reveals


@pytest.fixture
def pick(monkeypatch):
    """The effect the bot's SHOWDOWN takes (its own choice is `tests/test_wyatt_earp_ai.py`'s business)."""
    from sparring import ai_wyatt
    chosen = {"k": 0}
    monkeypatch.setattr(ai_wyatt, "pick_showdown", lambda ai, game, me, options, attacker: chosen["k"] if chosen["k"] in options else options[0])
    return chosen


def test_the_bots_showdown_draw_deals_a_card_to_its_table_hand(tmp_path, pick):
    session, table, game, fake, cfg, client = bots_attack(tmp_path, STAND, "Second Shot")
    try:
        was = list(table.bot_hand)
        msgs = run_bot_attack(session, table, game, STAND)
        drawn = [i for i in table.bot_hand if i not in was]
        assert len(drawn) == 1 and game.fx.counter_value(0, "showdown_draw", 0) == 1, msgs
        assert said(msgs, "roba 1"), msgs
    finally:
        client.close()
        fake.close()


def test_the_bots_showdown_free_action_buys_a_third_attack_in_the_turn(tmp_path, pick):
    pick["k"] = 1
    session, table, game, fake, cfg, client = bots_attack(tmp_path, STAND, "Fan The Hammer", "Second Shot")
    try:
        wyatt_cards = {c.title: c for c in game.players[0].hand}
        plan = [Act("attack", fid="wyatt", target="hellboy", card=wyatt_cards[t]) for t in (STAND, "Fan The Hammer", "Second Shot")]
        session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
        session.ai.pick_ability_target = lambda g: None
        click(session, table, Event.MANEUVER)
        click(session, table, Event.END_ACTION)
        click(session, table, Event.MANEUVER)
        click(session, table, Event.END_ACTION)
        for _ in range(12):
            if game.turn != 0:
                break
            click(session, table, Event.REVEAL if session.pending is not None else Event.END_ACTION)
        assert plan == [] and game.fighters["hellboy"].hp == 18 - 5 - 1 - 2, game.log[-8:]
        assert game.turn == 1 and game.free_attacks == [] and game.fx.counter_value(0, "showdown_attack", 0) == 1
    finally:
        client.close()
        fake.close()


def test_the_bots_in_vino_veritas_deals_it_cards_up_to_four(tmp_path):
    session, table, game, fake, cfg, client = bots_attack(tmp_path, "In Vino Veritas", attacker="doc")
    try:
        was = len(table.bot_hand)
        card = next(c for c in game.players[0].hand if c.title == "In Vino Veritas")
        plan = [Act("scheme", fid="doc", card=card)]
        session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
        session.ai.pick_ability_target = lambda g: None
        click(session, table, Event.MANEUVER)
        click(session, table, Event.END_ACTION)
        click(session, table, Event.MANEUVER)
        click(session, table, Event.END_ACTION)
        assert was == 1 and len(game.players[0].hand) >= 3, game.log[-6:]
    finally:
        client.close()
        fake.close()


def test_the_bots_swear_me_in_reads_your_top_card_and_buries_it_blind(tmp_path, pick, monkeypatch):
    from sparring import ai_wyatt
    monkeypatch.setattr(ai_wyatt, "bury_rival", lambda game, me, card_id: True)
    session, table, game, fake, cfg, client = bots_attack(tmp_path, "Better Swear Me In")
    try:
        table.human_deck = [c.card_id for c in game.players[1].deck[5:9]]       # none of them in the engine's virtual hand
        top = table.human_deck[0]
        before = list(table.human_deck)
        msgs = run_bot_attack(session, table, game, "Better Swear Me In")
        title = next(c.title for c in game.players[1].full_set if c.card_id == top)
        assert said(msgs, f"Reveladas arriba de tu mazo: {title}"), msgs
        assert len(table.reorders) == 1 and table.reorders[0][0] == [top] and table.reorders[0][2] == [top], table.reorders
        assert table.human_deck[-1] == top and sorted(table.human_deck) == sorted(before)
        assert said(msgs, "he reordenado") and not any(f"debajo de tu mazo: {title}" in m for m in msgs), msgs
    finally:
        client.close()
        fake.close()


def test_the_bots_swear_me_in_leaves_your_top_card_when_it_is_not_worth_burying(tmp_path, pick, monkeypatch):
    from sparring import ai_wyatt
    monkeypatch.setattr(ai_wyatt, "bury_rival", lambda game, me, card_id: False)
    session, table, game, fake, cfg, client = bots_attack(tmp_path, "Better Swear Me In")
    try:
        table.human_deck = [c.card_id for c in game.players[1].deck[5:9]]
        before = list(table.human_deck)
        run_bot_attack(session, table, game, "Better Swear Me In")
        assert table.reorders == [] and table.human_deck == before
        assert game.players[0].known.top_of_deck == [before[0]]
    finally:
        client.close()
        fake.close()


def test_bring_em_to_justice_adds_twice_the_boost_of_the_top_card_of_the_bots_deck(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    wyatt = game.fighters["wyatt"]
    put_adjacent(game, table, cfg, "wyatt", "hellboy")
    attack_card = next(c for c in game.players[0].hand if c.title == TRAINING)
    top = game.players[0].deck[0]
    game.turn = 0
    game.begin_turn()
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("attack", fid="hellboy", target="wyatt", card=attack_card))
    human_hand(table, game, "Bring 'Em To Justice", "Second Shot")
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    assert session.pending is not None and session.pending.kind == "bot_attacks", msgs
    cid = card_ids(game, 1, "Bring 'Em To Justice")[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, f"Reveladas arriba de mi mazo: {top.title}"), msgs
    assert wyatt.hp == 15 - max(0, 3 - 2 * top.boost), msgs            # the bot's Training is 3 against 0 + twice the BOOST of its own top card


# ---------------------------------------------------------------- the rest of the human's cards

def test_fan_the_hammer_goes_back_to_the_humans_hand_when_it_defeats_the_fighter(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "wyatt", "lobster")
    game.fighters["lobster"].hp = 1
    human_hand(table, game, "Fan The Hammer", "Second Shot")
    fan = card_ids(game, 1, "Fan The Hammer")[0]
    attack(session, table, game, "Fan The Hammer", target="lobster")
    msgs = press(session, table, 0)                                             # SHOWDOWN first: the draw; then the card's own AFTER
    assert not game.fighters["lobster"].alive and said(msgs, "vuelve a tu mano"), msgs
    assert fan not in [c.card_id for c in game.players[1].discard]


def test_youre_a_daisy_deals_two_cards_to_the_human(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "doc", "hellboy")
    human_hand(table, game, "You're A Daisy If You Do", "Second Shot")
    attack(session, table, game, "You're A Daisy If You Do", attacker="doc")
    press(session, table, 2)                                                    # SHOWDOWN: the step, so the deals are Daisy's alone
    assert table.human_deals == [2]


def test_gunfight_asks_the_human_for_the_first_and_third_hit_and_the_bot_picks_the_others(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "wyatt", "hellboy")
    human_hand(table, game, "Gunfight At The O.K. Corral", "Second Shot")
    hp = {fid: f.hp for fid, f in game.fighters.items()}
    attack(session, table, game, "Gunfight At The O.K. Corral")
    press(session, table, 2)                                                    # SHOWDOWN first (the step)
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and set(req.options) == set(game.fighters) and req.extra["op"] == "damage"
    press(session, table, "hellboy")
    req = session.effect_run.awaiting
    assert req.kind == "fighter" and req.player == 1                            # the third hit is the human's again
    press(session, table, "hellboy")
    assert session.effect_run is None
    dealt = {fid: hp[fid] - f.hp for fid, f in game.fighters.items() if hp[fid] != f.hp}
    assert dealt["hellboy"] >= 2 + 2 and sum(dealt.values()) >= 2 + 4, dealt     # 2 combat damage... and the four hits: two ours, two theirs


def test_the_free_action_of_you_die_first_refuses_an_attack_on_any_other_fighter(mine, monkeypatch):
    session, table, game, fake, cfg = mine
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "wyatt", "hellboy")
    put_adjacent(game, table, cfg, "doc", "hellboy")
    game.actions_left, game.free_attacks = 1, ["lobster"]                     # only the free action at the lobster is left
    human_hand(table, game, STAND, "Second Shot")
    human_attack(session, table, game, "wyatt", "hellboy", STAND)
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "solo puede atacar a lobster"), msgs
    assert game.actions_left == 1 and game.free_attacks == ["lobster"] and game.fighters["hellboy"].hp == game.fighters["hellboy"].max_hp, msgs

