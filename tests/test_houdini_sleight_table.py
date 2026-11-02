"""Sleight Of Hand on the table (FakeTTS, batch mode), both seats. The bot's Houdini announces, takes the card from its combat spot back to
its hand by GUID and puts the card it plays face up there; the human's Houdini is asked Yes / No after Reveal, takes the card back and
puts the new one on their combat spot, and the bot reads it (wrong cards refused by name, a save at the pause resumes). The engine and
the decision of the bot are in tests/test_houdini_sleight.py."""
from __future__ import annotations

import json
import re

import pytest

from sparring.ai_medusa import Act
from sparring.session import Session
from sparring.tts.ui import Event
from test_batch import click
from test_choice_infra import visible_choices
from test_d3_table_effects import FxTable, bot_turn, build, card_ids, human_attack, human_hand, said
from test_e2_human_cards import bot_defends_with_nothing, put_adjacent

SLEIGHT = "Sleight of Hand"


class SleightTable(FxTable):
    """FxTable plus what the Sleight Of Hand scripts do: a card placed face up at the bot's combat spot (not its ONGOING spot), the
    human's face-up combat spot readable and a card of theirs taken back to their hand by GUID."""

    bot_spot_z = 5.0
    human_spot = (-20.0, 4.0)
    refuse_placing = False
    refuse_returning = False

    def do_place_card_face_up(self, s):
        z = float(re.search(r"setPosition\(Vector\([-\d.]+, [-\d.]+, ([-\d.]+)\)\)", s).group(1))
        if abs(z - self.bot_spot_z) > 0.01:
            return super().do_place_card_face_up(s)
        i = int(re.search(r"CardID == (\d+)", s).group(1))
        if self.refuse_placing or i not in self.bot_hand:
            return {"placed": False}
        self.bot_hand.remove(i)
        self.bot_play.append(i)
        return {"placed": f"g{i}"}

    def do_read_cards_at(self, s):
        x = float(re.search(r"p\.x - (-?[\d.]+)\)", s).group(1))
        z = float(re.search(r"p\.z - (-?[\d.]+)\)", s).group(1))
        if (x, z) == tuple(self.human_spot):
            return list(self.face_down)
        return super().do_read_cards_at(s)

    def do_return_card_to_hand(self, s):
        guid = re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1)
        if guid.startswith("h") and 'Player["Red"]' in s:                 # the human's card back to their hand
            i = int(guid[1:])
            if self.refuse_returning or i not in {r["id"] for r in self.face_down}:
                return {"returned": False}
            self.face_down = [r for r in self.face_down if r["id"] != i]
            self.human_hand.append(i)
            self.human_count += 1
            return {"returned": guid}
        if self.refuse_returning:
            return {"returned": False}
        return super().do_return_card_to_hand(s)


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=SleightTable)
    table.human_spot = tuple(cfg.session_config().human_card_spot)
    table.bot_spot_z = cfg.session_config().bot_card_spot[2]
    table.human_deck = []
    session.cfg.action_announce_hold = 2.0
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(bot, human, *hand):
    return pytest.mark.parametrize("rig", [(bot, human, hand)], indirect=True)


def answer_swap(session, monkeypatch, game, title, boost=False):
    """The bot plays `title` instead of Sleight Of Hand (None keeps it); it boosts only when `boost` (the returned Sleight Of Hand
    is in its hand again, a boost of 3 that the real AI likes)."""
    card = None if title is None else next(c for c in game.players[0].hand if c.title == title)
    if not boost:
        monkeypatch.setattr(session.ai, "choose_combat_boost", lambda g, ctx: None)
    real = session.ai.choose_effect
    monkeypatch.setattr(session.ai, "choose_effect", lambda g, req: (
        ([] if card is None else [card.card_id]) if req.extra.get("purpose") == "swap_attack" else real(g, req)))
    return card


def bot_sleight_attack(session, table, game, cfg):
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    sleight = next(c for c in game.players[0].hand if c.title == SLEIGHT)
    bot_turn(session, table, [Act("attack", fid="houdini", target="hellboy", card=sleight)])
    table.face_down = []
    return sleight


# ---------------------------------------------------------------- the bot's Houdini

@with_rig("houdini", "hellboy", SLEIGHT, "Flourish", "Vanishing Act", "Grand Escape")
def test_the_bot_announces_then_takes_sleight_back_to_its_hand_and_plays_the_other_card_face_up(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    flourish = answer_swap(session, monkeypatch, game, "Flourish")
    sleight = bot_sleight_attack(session, table, game, cfg)
    assert sleight.card_id in table.bot_play
    hp = game.fighters["hellboy"].hp
    msgs = click(session, table, Event.REVEAL)
    heads = [h for ops in table.msglog for h in ops]
    assert heads.index("hold") < heads.index("place_card_face_up") and "return_card_to_hand" in heads
    line = next(m for m in msgs if "Sleight of Hand: el bot la recoge en su mano" in m)
    assert "Flourish" in line and table.holds[-3:].count(2.0) >= 1
    assert sleight.card_id in table.bot_hand and sleight.card_id not in table.bot_play        # back in the bot's hand on the table
    assert flourish.card_id in table.bot_discard or flourish.card_id in table.bot_play
    assert game.fighters["hellboy"].hp == hp - 3 and sleight in game.players[0].hand
    assert said(msgs, "Houdini ataca con Flourish (3)") or said(msgs, "con Flourish (3)")
    assert sorted(game.players[0].hand, key=lambda c: c.card_id) and len(game.players[0].hand) == len(table.bot_hand)
    assert session.pending is None


@with_rig("houdini", "hellboy", SLEIGHT, "Flourish", "Vanishing Act", "Grand Escape")
def test_the_returned_sleight_can_be_the_boost_of_the_card_it_made_room_for(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    flourish = answer_swap(session, monkeypatch, game, "Flourish", boost=True)
    sleight = bot_sleight_attack(session, table, game, cfg)
    hp = game.fighters["hellboy"].hp
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "Houdini ataca con Flourish (3) y potencia con Sleight of Hand (+3)") and game.fighters["hellboy"].hp == hp - 6
    assert sleight.card_id in table.bot_discard and flourish.card_id in table.bot_discard
    assert len(game.players[0].hand) == len(table.bot_hand)


@with_rig("houdini", "hellboy", SLEIGHT, "Flourish", "Vanishing Act", "Grand Escape")
def test_the_card_zoom_shows_the_card_it_plays_instead(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    session.cfg.card_zoom = True
    session.cfg.card_zoom_spot = (0.0, 5.0, 0.0)
    flourish = answer_swap(session, monkeypatch, game, "Flourish")
    bot_sleight_attack(session, table, game, cfg)
    click(session, table, Event.REVEAL)
    placed = [s for s in table.scripts if s.startswith("-- sparring:place_card_face_up") and f"CardID == {flourish.card_id}" in s]
    assert placed and "sparringZoom" in placed[-1]


@with_rig("houdini", "hellboy", SLEIGHT, "Flourish", "Vanishing Act", "Grand Escape")
def test_when_the_bot_keeps_sleight_nothing_moves_on_the_table(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    answer_swap(session, monkeypatch, game, None)
    sleight = bot_sleight_attack(session, table, game, cfg)
    msgs = click(session, table, Event.REVEAL)
    heads = [h for ops in table.msglog for h in ops]
    assert "place_card_face_up" not in heads and not said(msgs, "la recoge en su mano")
    assert sleight.card_id in table.bot_discard and game.players[0].discard[-1] is sleight


@with_rig("houdini", "hellboy", SLEIGHT, "Flourish", "Vanishing Act", "Grand Escape")
def test_a_table_that_refuses_the_swap_says_what_to_move_by_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    answer_swap(session, monkeypatch, game, "Flourish")
    bot_sleight_attack(session, table, game, cfg)
    table.refuse_placing = True
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "No he podido hacerlo en la mesa: recoge Sleight of Hand de la zona de combate del bot en su mano y pon Flourish boca arriba")


@with_rig("houdini", "hellboy", SLEIGHT, "Flourish", "Vanishing Act", "Grand Escape")
def test_the_bot_swaps_against_the_defense_it_sees_and_the_human_card_stays_where_it_is(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    flourish = answer_swap(session, monkeypatch, game, "Flourish")
    put_adjacent(game, table, cfg, "hellboy", "houdini")
    human_hand(table, game, "B.P.R.D. Training", "Service Pistol")
    sleight = next(c for c in game.players[0].hand if c.title == SLEIGHT)
    bot_turn(session, table, [Act("attack", fid="houdini", target="hellboy", card=sleight)])
    block = card_ids(game, 1, "B.P.R.D. Training")[0]
    table.face_down = [{"id": block, "guid": f"h{block}"}]
    table.human_hand.remove(block)
    table.human_count -= 1
    hp = game.fighters["hellboy"].hp
    msgs = click(session, table, Event.REVEAL)
    assert said(msgs, "Sleight of Hand: el bot la recoge en su mano y pone Flourish")
    assert game.fighters["hellboy"].hp == hp and flourish in game.players[0].discard         # 3 against 3: nothing gets through
    assert sleight.card_id in table.bot_hand


# ---------------------------------------------------------------- the human's Houdini

HUMAN_HAND = (SLEIGHT, "Flourish", "Vanishing Act", "Grand Escape", "The Big Reveal")


def sleight_attack(session, table, game, cfg, monkeypatch):
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "houdini", "hellboy")
    human_hand(table, game, *HUMAN_HAND)
    human_attack(session, table, game, "houdini", "hellboy", SLEIGHT)
    return click(session, table, Event.REVEAL)


def labels(session):
    lab = session.panel_labels()
    return [lab[i] for i in visible_choices(session)]


def done(session, table):
    return click(session, table, Event.CHOICE, {"i": 1})


def hid(game, title, n=0):
    return [c.card_id for c in game.players[1].full_set if c.title == title][n]


def swap_on_table(table, game, old_title, new_title):
    """What the human does: Sleight Of Hand back to the hand, the new card face up on the combat spot."""
    old, new = hid(game, old_title), hid(game, new_title)
    table.face_down = [{"id": new, "guid": f"h{new}"}]
    table.human_hand = [i for i in table.human_hand if i != new] + [old]
    return old, new


@with_rig("hellboy", "houdini")
def test_after_reveal_the_panel_asks_yes_or_no_and_only_then(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_nothing(session, monkeypatch)
    put_adjacent(game, table, cfg, "houdini", "hellboy")
    human_hand(table, game, *HUMAN_HAND)
    human_attack(session, table, game, "houdini", "hellboy", SLEIGHT)
    assert visible_choices(session) == [] and not session.panel_labels()                    # hidden until the card is revealed
    msgs = click(session, table, Event.REVEAL)
    run = session._paused()[2]
    assert run.awaiting.kind == "optional" and run.awaiting.extra["sleight"]["def_value"] == 0
    assert labels(session) == ["Si", "No"] and session.pending is not None
    assert not said(msgs, "Combate:")


@with_rig("hellboy", "houdini")
def test_no_keeps_sleight_of_hand_as_the_attack(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    sleight_attack(session, table, game, cfg, monkeypatch)
    hp = game.fighters["hellboy"].hp
    msgs = click(session, table, Event.CHOICE, {"i": 2})
    assert game.fighters["hellboy"].hp == hp - 1 and "Houdini ataca con Sleight of Hand (1)" in " ".join(msgs)
    assert session.pending is None and visible_choices(session) == []


@with_rig("hellboy", "houdini")
def test_yes_tells_what_to_do_and_the_bot_reads_the_new_card_and_continues_with_it(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    sleight_attack(session, table, game, cfg, monkeypatch)
    msgs = click(session, table, Event.CHOICE, {"i": 1})
    req = session.effect_run.awaiting
    assert req.kind == "cards" and req.extra["pile_mode"] == "play" and req.extra["sleight"] and req.min == 0 and req.max == 1
    assert said(msgs, "Sleight of Hand: recogela en tu mano y pon boca arriba en tu zona de combate")
    assert session.panel_view()[0].startswith("Recogela en tu mano, pon la carta nueva")
    assert labels(session) == ["Hecho"] or len(labels(session)) == 1                          # one Done button
    old, new = swap_on_table(table, game, SLEIGHT, "Vanishing Act")
    hp = game.fighters["hellboy"].hp
    msgs = done(session, table)
    assert said(msgs, "Sleight of Hand: vuelve a tu mano y juegas Vanishing Act en su lugar")
    assert "Houdini ataca con Vanishing Act (2)" in " ".join(msgs)
    assert game.fighters["hellboy"].hp == hp - 2
    sleight = next(c for c in game.players[1].full_set if c.card_id == old)
    assert sleight in game.players[1].hand and sleight not in game.players[1].discard
    assert len(game.players[1].hand) == table.human_count
    assert session.combat_guids == {new: f"h{new}"}


@with_rig("hellboy", "houdini")
def test_the_new_cards_own_after_effect_is_resolved_as_normal(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    sleight_attack(session, table, game, cfg, monkeypatch)
    click(session, table, Event.CHOICE, {"i": 1})
    swap_on_table(table, game, SLEIGHT, "Vanishing Act")                                    # AFTER: move a fighter up to 3 spaces
    done(session, table)
    paused = session._paused()
    assert paused is not None and paused[2].label == "after"                                # the human is asked what the card says


@with_rig("hellboy", "houdini")
def test_the_bot_leaves_sleight_where_it_is_if_the_human_changed_their_mind(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    sleight_attack(session, table, game, cfg, monkeypatch)
    click(session, table, Event.CHOICE, {"i": 1})
    hp = game.fighters["hellboy"].hp
    msgs = done(session, table)                                                             # Sleight of Hand still at the spot
    assert said(msgs, "Sleight of Hand: te la quedas y atacas con ella") and game.fighters["hellboy"].hp == hp - 1
    assert hid(game, SLEIGHT) in [c.card_id for c in game.players[1].discard]


@with_rig("hellboy", "houdini")
def test_wrong_cards_are_refused_by_name_and_the_bot_keeps_waiting(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    sleight_attack(session, table, game, cfg, monkeypatch)
    click(session, table, Event.CHOICE, {"i": 1})
    swap_on_table(table, game, SLEIGHT, "Grand Escape")                                     # a defense
    msgs = done(session, table)
    assert said(msgs, "Grand Escape (defensa) no es una carta de ataque o versatil que Houdini pueda jugar") and session.effect_run is not None
    swap_on_table(table, game, SLEIGHT, "The Big Reveal")                                   # Houdini's card: fine
    bess_only = hid(game, "And the Beautiful Bess!")
    table.face_down = [{"id": bess_only, "guid": f"h{bess_only}"}]
    msgs = done(session, table)
    assert said(msgs, "And the Beautiful Bess! (versatil) no es una carta de ataque o versatil que Houdini pueda jugar")
    second = [c.card_id for c in game.players[1].full_set if c.title == SLEIGHT][1]
    table.face_down = [{"id": second, "guid": f"h{second}"}]
    msgs = done(session, table)
    assert said(msgs, "Sleight of Hand es otra Sleight of Hand: elige una carta distinta") and session.effect_run is not None
    assert game.fighters["hellboy"].hp == 18 and session.pending is not None


@with_rig("hellboy", "houdini")
def test_two_new_cards_or_no_card_at_all_are_refused(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    sleight_attack(session, table, game, cfg, monkeypatch)
    click(session, table, Event.CHOICE, {"i": 1})
    a, b = hid(game, "Flourish"), hid(game, "Vanishing Act")
    table.face_down = [{"id": a, "guid": f"h{a}"}, {"id": b, "guid": f"h{b}"}]
    msgs = done(session, table)
    assert said(msgs, "Hay varias cartas nuevas en tu zona de combate")
    table.face_down = []                                                                    # Sleight taken back and nothing in its place
    msgs = done(session, table)
    assert said(msgs, "Sleight of Hand ya no esta en tu zona de combate") and session.effect_run is not None


@with_rig("hellboy", "houdini")
def test_if_sleight_is_left_next_to_the_new_card_the_bot_takes_it_back_to_the_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    sleight_attack(session, table, game, cfg, monkeypatch)
    click(session, table, Event.CHOICE, {"i": 1})
    old, new = hid(game, SLEIGHT), hid(game, "Flourish")
    table.face_down = [{"id": old, "guid": f"h{old}"}, {"id": new, "guid": f"h{new}"}]
    msgs = done(session, table)
    assert [r["id"] for r in table.face_down] == [new] and old in table.human_hand
    assert said(msgs, "Houdini ataca con Flourish (3)")


@with_rig("hellboy", "houdini")
def test_a_table_that_cannot_take_sleight_back_tells_the_human_to_do_it(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    sleight_attack(session, table, game, cfg, monkeypatch)
    click(session, table, Event.CHOICE, {"i": 1})
    old, new = hid(game, SLEIGHT), hid(game, "Flourish")
    table.face_down = [{"id": old, "guid": f"h{old}"}, {"id": new, "guid": f"h{new}"}]
    table.refuse_returning = True
    msgs = done(session, table)
    assert said(msgs, "Recoge Sleight of Hand de tu zona de combate y ponla en tu mano")


@with_rig("hellboy", "houdini")
def test_resume_at_the_pause_keeps_waiting_for_the_card(rig, monkeypatch, tmp_path):
    session, table, game, fake, cfg = rig
    sleight_attack(session, table, game, cfg, monkeypatch)
    click(session, table, Event.CHOICE, {"i": 1})                                            # Yes: the cards request is on the panel
    saved = json.loads(json.dumps(session.to_dict()))
    assert saved["pending"]["flow"] is not None
    resumed = Session(game, session.client, session.ai, session.cfg)
    table.session = resumed
    resumed.restore(saved) if hasattr(resumed, "restore") else resumed.load_dict(saved)
    req = resumed.effect_run.awaiting
    assert req.kind == "cards" and req.extra["sleight"] and resumed.pending.flow.atk_card.title == SLEIGHT
    old, new = swap_on_table(table, game, SLEIGHT, "Flourish")
    hp = game.fighters["hellboy"].hp
    msgs = click(resumed, table, Event.CHOICE, {"i": 1})
    assert "Houdini ataca con Flourish (3)" in " ".join(msgs) and game.fighters["hellboy"].hp == hp - 3
