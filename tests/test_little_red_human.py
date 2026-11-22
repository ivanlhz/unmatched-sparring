"""Little Red on the table through the panel (FakeTTS, batch mode), both seats. The human as Little Red: a wild basket (the Basket alone in the pile, or
a star card on top) is a question with three buttons (lobo / rosa / hacha) asked when a line with a symbol resolves, the engine's pile order is the
basket and the chat says what it was, What Large Hands You Have brings the top card back, Big Ears defends with an axe, save and resume in the middle
of the question. The human as the OPPONENT of the bot's Little Red: the chat says what the basket was for each card the bot plays, and the bot never
reads anything of the human's hidden hand.

The Basket itself is a loose card (CardID 17600, a one-image sheet) that lies in the discard zone from the start: no read of the discard may take it
for a card of anybody's deck. The bot's side of the same cards is in tests/test_little_red_effects.py."""
from __future__ import annotations

import json
import re

import pytest

from sparring.effects.plugins_little_red import basket
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, human_attack, human_hand, said
from test_doctor_strange_human import StrangeTable
from test_donatello_session import SPOTS
from test_e2_human_cards import labels, press, put_adjacent

BASKET_CARD = 17600                    # the loose Basket card of her bag: CardID 17600 of a one-image sheet, in no deck of hers
TRAINING = "B.P.R.D. Training"         # Hellboy's defense of value 3


class LittleRedTable(StrangeTable):
    """The fake table plus the human's `pile_card_to_hand` (the bot lifts a card of the pile into the real hand by its id)."""

    def do_pile_card_to_hand(self, s):
        i = int(re.search(r"\.CardID == (\d+)", s).group(1))
        if i not in self.human_discard:
            return {"moved": False}
        self.human_discard.remove(i)
        self.human_hand.append(i)
        self.human_count += 1
        return {"moved": True, "guid": f"h{i}"}


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=LittleRedTable, **SPOTS)
    table.human_card_spot = tuple(cfg.session_config().human_card_spot)
    table.human_deck = []
    table.hand_returns = []
    table.top_discards = []
    put_adjacent(game, table, cfg, game.hero(1).fid, game.hero(0).fid)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(*bot_hand, bot="hellboy", human="little-red-riding-hood"):
    return pytest.mark.parametrize("rig", [(bot, human, bot_hand)], indirect=True)


def no_defense(session, monkeypatch):
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)


def attack(session, table, game, title, attacker="red", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def dial(cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


def human_pile(table, game, *titles):
    """The human's discard pile, the last card on top, in the engine and on the table."""
    st = game.players[1]
    st.discard.clear()
    table.human_discard.clear()
    used = {}
    for title in titles:
        nth = used.get(title, 0)
        used[title] = nth + 1
        c = [x for x in st.full_set if x.title == title][nth]
        for zone in (st.deck, st.hand):
            if c in zone:
                zone.remove(c)
        st.discard.append(c)
        table.human_discard.append(c.card_id)


# ---------------------------------------------------------------- the human as Little Red

@with_rig(TRAINING)
def test_a_wild_basket_is_a_question_with_three_buttons_and_the_answer_decides_the_line(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Once Upon a Time", "The Wolf's Skin")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Once Upon a Time")
    assert said(msgs, "Tu cesta es comodin") and said(msgs, "1: lobo, 2: rosa, 3: hacha"), msgs
    req = session.effect_run.awaiting
    assert req.kind == "effect" and req.extra["tag"] == "basket" and req.options == [0, 1, 2]
    assert labels(session) == ["lobo", "rosa", "hacha"]
    msgs = press(session, table, 2)
    assert game.fighters["hellboy"].hp == hp - 2 - 3 and session.effect_run is None, msgs
    assert said(msgs, "cesta comodin contada como hacha"), msgs


@with_rig(TRAINING)
def test_a_known_symbol_on_top_asks_nothing_and_the_chat_says_what_the_basket_was(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Once Upon a Time", "The Wolf's Skin")
    human_pile(table, game, "Never Leave the Path", "The Wolf's Skin")            # an axe on top
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Once Upon a Time")
    assert session.effect_run is None and game.fighters["hellboy"].hp == hp - 2 - 3, msgs
    assert said(msgs, "cesta: hacha"), msgs


@with_rig(TRAINING)
def test_a_wolf_on_top_resolves_no_axe_line(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Once Upon a Time", "The Wolf's Skin")
    human_pile(table, game, "The Wolf's Skin", "Never Leave the Path")            # a wolf on top
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Once Upon a Time")
    assert game.fighters["hellboy"].hp == hp - 2 and said(msgs, "cesta: lobo"), msgs


@with_rig(TRAINING)
def test_a_star_card_on_top_is_a_question_too(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Once Upon a Time", "The Wolf's Skin")
    human_pile(table, game, "What's That In My Basket?")
    attack(session, table, game, "Once Upon a Time")
    assert session.effect_run.awaiting.extra["tag"] == "basket"
    press(session, table, 1)                                                        # a rose: no axe line
    assert session.effect_run is None and game.fighters["hellboy"].hp == game.fighters["hellboy"].max_hp - 2


@with_rig(TRAINING)
def test_the_loose_basket_card_in_the_pile_is_no_card_of_hers(rig, monkeypatch):
    """The Basket (CardID 17600) lies in her discard zone from the start: no read may adopt it, count it or warn about it."""
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Once Upon a Time", "The Wolf's Skin")
    table.human_discard.append(BASKET_CARD)
    msgs = attack(session, table, game, "Once Upon a Time")
    assert game.players[1].discard == [] and BASKET_CARD not in {c.card_id for c in game.players[1].full_set}
    assert session.effect_run.awaiting.extra["tag"] == "basket"              # the engine still sees a pile with only the Basket: wild
    assert not said(msgs, "17600") and not said(msgs, "adopt"), msgs
    press(session, table, 0)
    assert [c.title for c in game.players[1].discard] == ["Once Upon a Time"] and basket(game, 1) == "rose"


@with_rig(TRAINING)
def test_the_question_survives_a_save_and_is_answered_after_the_resume(rig, monkeypatch):
    from test_d3_table_effects import twin_session
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Once Upon a Time", "The Wolf's Skin")
    attack(session, table, game, "Once Upon a Time")
    twin = twin_session(session, cfg, json.loads(json.dumps(session.to_dict())))
    assert twin.effect_run.awaiting.extra["tag"] == "basket" and twin.effect_run.awaiting.options == [0, 1, 2]
    twin.client = session.client
    hp = game.fighters["hellboy"].hp
    click(twin, table, Event.CHOICE, {"i": 3})
    assert twin.game.fighters["hellboy"].hp == hp - 3 and twin.effect_run is None



def bot_defends_with_training(session, monkeypatch):
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: next(c for c in g.players[0].hand if c.title == TRAINING))


@with_rig(TRAINING)
def test_large_hands_with_a_rose_asks_to_return_the_top_card_and_the_bot_moves_it_back_to_the_hand(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_training(session, monkeypatch)
    human_hand(table, game, "What Large Hands You Have", "The Wolf's Skin")
    human_pile(table, game, "The Wolf's Skin", "Once Upon a Time")                  # a rose on top
    msgs = attack(session, table, game, "What Large Hands You Have")
    once = next(c.card_id for c in game.players[1].full_set if c.title == "Once Upon a Time")
    assert session.effect_run.awaiting.kind == "optional" and session.effect_run.awaiting.extra["returns_top"] == once, msgs
    msgs = press(session, table, True)
    assert once in table.human_hand and once not in table.human_discard, msgs
    assert [c.title for c in game.players[1].discard] == ["The Wolf's Skin", "What Large Hands You Have"]
    assert said(msgs, "Once Upon a Time vuelve a tu mano") and said(msgs, "cesta: rosa"), msgs


@with_rig(TRAINING)
def test_large_hands_with_a_wolf_returns_itself_or_stays_on_the_pile(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_training(session, monkeypatch)
    human_hand(table, game, "What Large Hands You Have", "The Wolf's Skin")
    human_pile(table, game, "The Wolf's Skin", "Never Leave the Path")              # a wolf: the line without a symbol
    attack(session, table, game, "What Large Hands You Have")
    assert session.effect_run.awaiting.kind == "optional"
    press(session, table, False)
    assert [c.title for c in game.players[1].discard][-1] == "What Large Hands You Have"


@with_rig(TRAINING)
def test_large_hands_with_the_basket_alone_chosen_as_a_rose_offers_nothing(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    bot_defends_with_training(session, monkeypatch)
    human_hand(table, game, "What Large Hands You Have", "The Wolf's Skin")
    attack(session, table, game, "What Large Hands You Have")
    assert session.effect_run.awaiting.extra["tag"] == "basket"
    press(session, table, 1)                                                          # a rose: nothing to bring back, and the card does not return
    assert session.effect_run is None and [c.title for c in game.players[1].discard] == ["What Large Hands You Have"]


# ---------------------------------------------------------------- What Big Ears You Have: the human defends with an attack card

def bot_attacks(session, table, game, title, fid, target, human_title=None):
    """The bot's `fid` attacks `target` with `title`; the human answers with `human_title` face down (None: no defense)."""
    from sparring.ai_medusa import Act
    card = next(c for c in game.players[0].hand if c.title == title)
    bot_turn(session, table, [Act("attack", fid=fid, target=target, card=card)])
    if human_title:
        cid = next(c.card_id for c in game.players[1].full_set if c.title == human_title and c.card_id in table.human_hand)
        table.face_down = [{"id": cid, "guid": f"h{cid}"}]
        table.human_hand.remove(cid)
        table.human_count -= 1
    else:
        table.face_down = []
    return click(session, table, Event.REVEAL)


@with_rig("Service Pistol", "Excalibur")
def test_big_ears_defends_with_its_printed_four_when_the_pile_shows_an_axe(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "What Big Ears You Have", "The Wolf's Skin")
    human_pile(table, game, "The Wolf's Skin")
    pistol = next(c for c in game.players[0].hand if c.title == "Service Pistol")
    msgs = bot_attacks(session, table, game, "Service Pistol", "hellboy", "red", "What Big Ears You Have")
    assert game.fighters["red"].hp == 14 - max(0, pistol.value - 4), msgs
    assert not said(msgs, "no puede"), msgs
    assert [c.title for c in game.players[1].discard][-1] == "What Big Ears You Have"


@with_rig("Service Pistol", "Excalibur")
def test_big_ears_with_a_wolf_on_top_is_refused_and_the_human_keeps_the_choice(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "What Big Ears You Have", "The Wolf's Skin")
    human_pile(table, game, "Never Leave the Path")
    msgs = bot_attacks(session, table, game, "Service Pistol", "hellboy", "red", "What Big Ears You Have")
    assert game.fighters["red"].hp == 14 and said(msgs, "What Big Ears You Have") and said(msgs, "no sirve para defender"), msgs


# ---------------------------------------------------------------- the bot's Little Red against the human

BOT_HAND = ("Once Upon a Time", "What Large Hands You Have", "The Wolf's Skin", "What Big Eyes You Have", "Stones in the Belly", "Never Leave the Path")
HELLBOY_HAND = ("Excalibur", "B.P.R.D. Training", "Service Pistol", "Right Hand Of Doom", "Second Shot")


def bot_red(rig, *pile):
    """The bot's Little Red next to Hellboy, her pile (the last card on top) in the engine and on the table, the human holding Hellboy's cards."""
    from test_d3_table_effects import to_bot_discard
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "red", "hellboy")
    human_hand(table, game, *HELLBOY_HAND)
    table.bot_discard.append(BASKET_CARD)                       # the Basket lies in her discard zone from the start
    to_bot_discard(session, table, game, *pile)
    return session, table, game, fake, cfg


@with_rig(*BOT_HAND, bot="little-red-riding-hood", human="hellboy")
def test_the_bots_wild_basket_is_chosen_by_the_bot_and_the_chat_says_so(rig, monkeypatch):
    session, table, game, fake, cfg = bot_red(rig)
    hp = game.fighters["hellboy"].hp
    msgs = bot_attacks(session, table, game, "Once Upon a Time", "red", "hellboy", None)
    assert session.effect_run is None and game.fighters["hellboy"].hp == hp - 2 - 3, msgs
    assert said(msgs, "cesta comodin contada como hacha"), msgs
    assert [c.title for c in game.players[0].discard] == ["Once Upon a Time"] and not said(msgs, "17600")


@with_rig(*BOT_HAND, bot="little-red-riding-hood", human="hellboy")
def test_the_bots_basket_on_top_of_the_pile_is_told_and_decides_the_line(rig):
    session, table, game, fake, cfg = bot_red(rig, "The Wolf's Skin", "Never Leave the Path")       # a wolf on top
    hp = game.fighters["hellboy"].hp
    msgs = bot_attacks(session, table, game, "Once Upon a Time", "red", "hellboy", None)
    assert game.fighters["hellboy"].hp == hp - 2 and said(msgs, "cesta: lobo"), msgs


@with_rig(*BOT_HAND, bot="little-red-riding-hood", human="hellboy")
def test_the_bots_rose_brings_back_the_top_card_of_its_own_pile_instead_of_the_card_it_played(rig):
    session, table, game, fake, cfg = bot_red(rig, "The Wolf's Skin", "Never Leave the Path", "Once Upon a Time")     # a rose on top
    msgs = bot_attacks(session, table, game, "What Large Hands You Have", "red", "hellboy", TRAINING)
    titles = [c.title for c in game.players[0].discard]
    assert titles == ["The Wolf's Skin", "Never Leave the Path", "What Large Hands You Have"], msgs        # the rose took Once Upon a Time back, not this card
    assert said(msgs, "Once Upon a Time vuelve a su mano") and said(msgs, "cesta: rosa") and "Once Upon a Time" in [c.title for c in game.players[0].hand], msgs


@with_rig(*BOT_HAND, bot="little-red-riding-hood", human="hellboy")
def test_the_bots_stones_in_the_belly_makes_the_human_discard_the_card_the_bot_names(rig):
    session, table, game, fake, cfg = bot_red(rig, "The Wolf's Skin")                 # an axe
    msgs = bot_attacks(session, table, game, "Stones in the Belly", "red", "hellboy", None)
    req = session.effect_run.awaiting if session.effect_run is not None else None
    assert req is not None and req.extra.get("ambush"), msgs
    assert said(msgs, "carta"), msgs
