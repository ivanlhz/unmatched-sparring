"""Bloody Mary on the table through the panel (FakeTTS, batch mode), both seats."""
from __future__ import annotations

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, human_attack, human_hand, said
from test_doctor_strange_human import StrangeTable
from test_donatello_session import SPOTS
from test_e2_human_cards import by_hand, human_scheme, press, put_adjacent


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=StrangeTable, **SPOTS)
    table.human_card_spot = tuple(cfg.session_config().human_card_spot)
    table.human_deck = []
    table.hand_returns = []
    table.top_discards = []
    put_adjacent(game, table, cfg, game.hero(1).fid, game.hero(0).fid)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(*bot_hand, bot="hellboy", human="bloody-mary"):
    return pytest.mark.parametrize("rig", [(bot, human, bot_hand)], indirect=True)


# ---------------------------------------------------------------- the ability: exactly 3 cards at the start of the turn

@with_rig()
def test_the_humans_turn_with_exactly_three_cards_in_hand_has_three_actions_and_the_chat_says_why(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Evade")                          # the two Maneuvers that end the previous turn deal two more: 3 at the start
    msgs = bot_turn(session, table, [])
    assert len(game.players[1].hand) == 3 and game.turn == 1
    assert game.actions_left == 3
    assert said(session.messages_all if hasattr(session, "messages_all") else msgs, "empieza el turno con exactamente 3 cartas"), msgs
    assert not said(msgs, "THREE CARDS ONE ACTION")


@with_rig()
def test_the_humans_turn_with_another_hand_size_has_two_actions(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Evade", "Feint")                 # 4 at the start
    bot_turn(session, table, [])
    assert len(game.players[1].hand) == 4 and game.actions_left == 2


@with_rig("Evade", "Feint", "Jump Scare", bot="bloody-mary", human="hellboy")
def test_the_bots_turn_with_exactly_three_cards_in_hand_has_three_actions(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Excalibur")
    msgs = bot_turn(session, table, [])                         # the bot maneuvers whenever it has an action: 3 of them
    assert game.turn == 1 and len(game.players[0].hand) == 3 + 3
    assert said(msgs, "Bloody Mary empieza el turno con exactamente 3 cartas: gana 1 accion"), msgs


# ---------------------------------------------------------------- the human plays her cards

def no_defense(session, monkeypatch):
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)


def attack(session, table, game, title, attacker="mary", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def dial(cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


@with_rig("Excalibur", "Service Pistol")
def test_out_of_the_mirror_makes_the_bot_discard_a_random_card_and_adds_its_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Out Of The Mirror", "Feint")
    before, hp = len(game.players[0].hand), game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Out Of The Mirror")
    gone = game.players[0].discard[-1]
    assert len(game.players[0].hand) == before - 1 and gone.card_id in table.bot_discard, msgs
    assert game.fighters["hellboy"].hp == hp - (1 + gone.boost), msgs


@with_rig()
def test_the_third_action_of_the_humans_turn_makes_speak_three_times_worth_seven(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Closer Than She Appears", "Speak Three Times", "Feint")
    human_scheme(session, table, game, "Closer Than She Appears")                 # an action spent and one gained
    assert game.fx.taken == 1 and game.actions_left == 2
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    assert game.fx.taken == 2 and game.actions_left == 1
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Speak Three Times")
    assert game.fx.taken == 3 and game.fighters["hellboy"].hp == hp - 7, msgs


# ---------------------------------------------------------------- Stolen Memories (a look at the bot's hand, then discard it or take its BOOST)

from test_e3_hidden_info import HELLBOY_HAND, human_reads, row_ids, rig_for     # noqa: E402
from sparring.effects.run import Ctx, EffectRun       # noqa: E402


@pytest.fixture
def hidden_rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = rig_for(tmp_path, bot, human, hand)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def hidden_rig_for(*param):
    return pytest.mark.parametrize("hidden_rig", [param], indirect=True)


def human_stolen_memories(session, game):
    card = next(c for c in game.players[1].full_set if c.title == "Stolen Memories")
    run = EffectRun.for_card("bloody-mary", "Stolen Memories", "scheme", Ctx(owner=1, this_fid="mary", card_id=card.card_id))
    session.snap = None
    return session.play_effect(run)


@hidden_rig_for("hellboy", "bloody-mary", HELLBOY_HAND)
@pytest.mark.parametrize("bot_discards", [True, False])
def test_stolen_memories_by_the_human_the_bot_discards_the_named_card_or_its_hero_takes_the_boost(hidden_rig, monkeypatch, bot_discards):
    from test_d3_table_effects import answers
    session, table, game, fake, cfg = hidden_rig
    monkeypatch.setattr(session.ai, "choose_effect", answers(optional=[bot_discards]))
    msgs = human_stolen_memories(session, game)
    assert session.look is not None and session.look["mode"] == "pick" and said(msgs, "El bot pone su mano boca arriba")
    hb = game.fighters["hellboy"]
    hp = hb.hp
    chosen = row_ids(session)[0]
    named = next(c for c in game.players[0].full_set if c.card_id == chosen)
    msgs = click(session, table, Event.LOOK_PING, {"guid": f"g{chosen}"})
    st = game.players[0]
    assert session.look is None and session.pending is None
    if bot_discards:
        assert chosen in [c.card_id for c in st.discard] and chosen in table.bot_discard and hb.hp == hp
    else:
        assert chosen in [c.card_id for c in st.hand] and chosen in table.bot_hand and hb.hp == hp - named.boost
        assert named.boost > 0
    assert human_reads(table) == []


@hidden_rig_for("bloody-mary", "hellboy", ("Stolen Memories", "Evade", "Feint", "Jump Scare", "Mirror Image"))
def test_the_bots_stolen_memories_names_a_card_of_the_humans_hand_and_offers_discard_or_take_its_boost(hidden_rig):
    session, table, game, fake, cfg = hidden_rig
    memories = next(c for c in game.players[0].hand if c.title == "Stolen Memories")
    human_hand(table, game, "Service Pistol", "Excalibur", "Glimpse Of Hell")
    plan = [Act("scheme", fid="mary", card=memories)]
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)
    req = session.effect_run.awaiting
    assert req.kind == "optional" and len(req.extra["discards"]) == 1
    named = next(c for c in game.players[1].full_set if c.card_id == req.extra["discards"][0])
    assert named.card_id in table.human_hand and req.extra["else_damage"] == named.boost
    assert session.panel_labels() == {"btn_choice_1": f"Descartar {named.title}", "btn_choice_2": f"Coger {named.boost}"}
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.CHOICE, {"i": 2})
    assert game.fighters["hellboy"].hp == hp - named.boost and session.pending is None and session.pending_discard is None
    assert len(human_reads(table)) == 1


# ---------------------------------------------------------------- the bot plays Bloody Mary: Out Of The Mirror against the human

TRAINING = "B.P.R.D. Training"


def awaiting(session):
    return session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting


def lay_on_pile(table, game, title):
    """The human discards the named card of their hand onto their discard pile by hand (what the bot's Out Of The Mirror waits for)."""
    by_id = {c.card_id: c for c in game.players[1].full_set}
    i = next(i for i in table.human_hand if by_id[i].title == title)
    table.human_hand.remove(i)
    table.human_discard.append(i)
    table.human_count -= 1
    return i


@with_rig("Out Of The Mirror", "Feint", bot="bloody-mary", human="hellboy")
def test_the_bots_out_of_the_mirror_names_a_position_and_reads_the_card_the_human_lays_on_their_pile(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, TRAINING, "Excalibur", "Service Pistol")
    card = next(c for c in game.players[0].hand if c.title == "Out Of The Mirror")
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
    bot_turn(session, table, [Act("attack", fid="mary", target="hellboy", card=card)])
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "al azar: la carta"), msgs
    req = awaiting(session)
    assert req.kind == "cards" and req.extra["pile_mode"] == "reveal" and req.extra["ambush"] and (req.min, req.max) == (1, 1)
    hp = game.fighters["hellboy"].hp
    lay_on_pile(table, game, "Excalibur")                                  # BOOST 3
    click(session, table, Event.CHOICE, {"i": 1})                          # Done
    assert session.pending is None
    assert game.fighters["hellboy"].hp == hp - (1 + 3)
    assert any(c.title == "Excalibur" for c in game.players[1].discard)


# ---------------------------------------------------------------- the rest of her cards, played by the human

def pid(game, title):
    return card_ids_of(game, title)[0]


def card_ids_of(game, title):
    return [c.card_id for c in game.players[1].full_set if c.title == title]


def to_discard(table, game, title):
    i = pid(game, title)
    table.human_hand.remove(i)
    table.human_discard = [*table.human_discard, i]
    table.human_count -= 1
    return i


@with_rig("Excalibur", "Service Pistol")
def test_mirror_image_defends_with_the_printed_value_of_the_bots_attack(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Mirror Image", "Feint")
    excalibur = next(c for c in game.players[0].hand if c.title == "Excalibur")             # printed 6
    bot_turn(session, table, [Act("attack", fid="hellboy", target="mary", card=excalibur)])
    mirror = pid(game, "Mirror Image")
    table.face_down = [{"id": mirror, "guid": f"h{mirror}"}]
    table.human_hand.remove(mirror)
    table.human_count -= 1
    hp = game.fighters["mary"].hp
    msgs = click(session, table, Event.REVEAL)
    assert game.fighters["mary"].hp == hp and any("Mirror Image (6)" in m for m in msgs), msgs


@with_rig()
def test_ghostly_touch_offers_its_free_boost_and_the_boost_card_adds_its_value(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Ghostly Touch", "Trick of the Light", "Feint")
    attack_msgs = attack(session, table, game, "Ghostly Touch")
    assert session.pending is not None and session.pending.wait is not None, attack_msgs
    hp = game.fighters["hellboy"].hp
    to_discard(table, game, "Trick of the Light")                                           # BOOST 3
    click(session, table, Event.BOOST)
    assert game.fighters["hellboy"].hp == hp - (1 + 3)


@with_rig()
def test_jump_scare_after_walking_out_of_her_zone_is_a_six(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Jump Scare", "Feint")
    mary, hell = game.fighters["mary"], game.fighters["hellboy"]
    game.fx.turn_start_pos["mary"] = next(s for s in sorted(game.board.spaces) if not game.board.share_zone(s, mary.pos) and s != hell.pos)
    hp = hell.hp
    attack(session, table, game, "Jump Scare")
    assert game.fighters["hellboy"].hp == hp - 6


@with_rig()
def test_trick_of_the_light_asks_and_the_human_places_her_by_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Trick of the Light", "Feint")
    attack(session, table, game, "Trick of the Light")
    assert session.effect_run is not None and session.effect_run.awaiting.kind == "optional"
    press(session, table, False)
    assert session.effect_run is None and session.pending is None


@with_rig()
def test_infinity_mirror_asks_which_fighter_of_the_combat_moves(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Infinity Mirror", "Feint")
    attack(session, table, game, "Infinity Mirror")
    req = session._paused()[2].awaiting if session._paused() else session.effect_run.awaiting
    assert req.kind == "fighter" and set(req.options) == {"mary", "hellboy"}


@with_rig()
def test_broken_glass_offers_plus_one_minus_one_and_zero(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Broken Glass", "Feint")
    attack(session, table, game, "Broken Glass")
    assert list(session.panel_labels().values())[:3] == ["+1", "-1", "0"], session.panel_labels()
    hp = game.fighters["hellboy"].hp
    click(session, table, Event.CHOICE, {"i": 1})
    if session.effect_run is not None:
        click(session, table, Event.CHOICE, {"i": 1})
    assert game.fighters["hellboy"].hp == hp - 4


@with_rig("B.P.R.D. Training")
def test_bloody_requiem_second_attack_is_worth_the_printed_value_of_the_card_it_met(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    training = next(c for c in game.players[0].hand if c.title == "B.P.R.D. Training")        # printed 3
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: training)
    human_hand(table, game, "Bloody Requiem", "Feint")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "Bloody Requiem")
    click(session, table, Event.END_ACTION)
    assert session.pending is not None and session.pending.second is not None and session.pending.second["value"] == 3
    table.face_down = []
    click(session, table, Event.REVEAL)                                                          # the bot has nothing left to defend with
    assert game.fighters["hellboy"].hp == hp - 3 and session.pending is None


# ---------------------------------------------------------------- save and resume in the middle of her choices, and the shared CardID range

def bot_plays_stolen_memories(session, table, game, *human_cards):
    memories = next(c for c in game.players[0].hand if c.title == "Stolen Memories")
    human_hand(table, game, *human_cards)
    plan = [Act("scheme", fid="mary", card=memories)]
    session.ai.plan = lambda g: plan.pop(0) if plan else Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    return click(session, table, Event.END_ACTION)


@hidden_rig_for("bloody-mary", "hellboy", ("Stolen Memories", "Evade", "Feint", "Jump Scare", "Mirror Image"))
def test_the_question_of_the_bots_stolen_memories_survives_a_save_and_is_answered_after_the_resume(hidden_rig):
    from test_d3_table_effects import twin_session
    session, table, game, fake, cfg = hidden_rig
    bot_plays_stolen_memories(session, table, game, "Excalibur", "Service Pistol")
    req = session.effect_run.awaiting
    assert req.kind == "optional" and req.extra["else_damage"] == next(c for c in game.players[1].full_set if c.card_id == req.extra["discards"][0]).boost
    twin = twin_session(session, cfg, session.to_dict())
    again = twin.effect_run.awaiting
    assert again.kind == "optional" and again.extra["discards"] == req.extra["discards"] and again.extra["else_damage"] == req.extra["else_damage"]
    hp = twin.game.fighters["hellboy"].hp
    twin.client = session.client
    click(twin, table, Event.CHOICE, {"i": 2})
    assert twin.game.fighters["hellboy"].hp == hp - req.extra["else_damage"]


@hidden_rig_for("bloody-mary", "golden-bat", ("Stolen Memories", "Evade", "Feint", "Jump Scare", "Mirror Image"))
def test_stolen_memories_against_a_hero_of_the_same_card_range_reads_the_boost_of_the_card_in_their_hand(hidden_rig):
    """Alpine Fortress is CardID 17627 in Golden Bat's deck and Closer Than She Appears is 17627 in hers: the BOOST must be the named card's (3, not 2)."""
    session, table, game, fake, cfg = hidden_rig
    bot_plays_stolen_memories(session, table, game, "Alpine Fortress")
    req = session.effect_run.awaiting
    named = req.extra["discards"][0]
    assert named in table.human_hand and next(c for c in game.players[1].full_set if c.card_id == named).title == "Alpine Fortress"
    assert req.extra["else_damage"] == 3 and session.panel_labels()["btn_choice_2"] == "Coger 3"
    hp = game.fighters["bat"].hp
    click(session, table, Event.CHOICE, {"i": 2})
    assert game.fighters["bat"].hp == hp - 3


@with_rig("Out Of The Mirror", "Feint", bot="bloody-mary", human="hellboy")
def test_the_question_of_the_bots_out_of_the_mirror_survives_a_save_and_is_answered_after_the_resume(rig):
    from test_d3_table_effects import twin_session
    session, table, game, fake, cfg = rig
    human_hand(table, game, TRAINING, "Excalibur", "Service Pistol")
    card = next(c for c in game.players[0].hand if c.title == "Out Of The Mirror")
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
    bot_turn(session, table, [Act("attack", fid="mary", target="hellboy", card=card)])
    click(session, table, Event.REVEAL)
    assert awaiting(session).extra["ambush"]
    twin = twin_session(session, cfg, session.to_dict())
    assert awaiting(twin).extra["ambush"] and awaiting(twin).extra["which"] == awaiting(session).extra["which"]
    hp = game.fighters["hellboy"].hp
    lay_on_pile(table, game, "Service Pistol")                                              # BOOST 2
    twin.client = session.client
    click(twin, table, Event.CHOICE, {"i": 1})
    assert twin.game.fighters["hellboy"].hp == hp - (1 + 2)


# ---------------------------------------------------------------- a "+" in a button label reaches the live panel (live_ui writes it through lua.set_panel)

@pytest.mark.parametrize("labels", [{"btn_choice_1": "+1", "btn_choice_2": "-1", "btn_choice_3": "0"},
                                    {"btn_choice_1": "Hand card to bottom: +1 action"}])
def test_the_live_panel_accepts_plus_in_a_button_label(labels):
    from sparring.tts import lua
    script = lua.set_panel("Elige", {}, labels=labels)
    for text in labels.values():
        assert f'"text", "{text}")' in script


@with_rig()
def test_broken_glass_labels_pass_the_live_panel_check(rig, monkeypatch):
    from sparring.tts import lua
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Broken Glass", "Feint")
    attack(session, table, game, "Broken Glass")
    labels = {k: v for k, v in session.panel_labels().items() if k.startswith("btn_choice")}
    assert "+1" in labels.values()
    assert "text" in lua.set_panel("Elige", {}, labels=labels)
