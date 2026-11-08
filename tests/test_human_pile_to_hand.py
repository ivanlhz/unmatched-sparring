"""A card the ENGINE picked out of the human's discard pile goes to their hand by the bot (Golden Bat's Insight of the Ancients).

FakeTTS sessions, bot Hellboy against a human Golden Bat who defends with Insight and wins. The bot takes the random card off the
human's pile by GUID, CardID and deck image into the White seat's hand and says so; a card the table does not hold, a refused
move or a table error leave the old instruction. A card the HUMAN picks (Ward And Prepare, tests/test_e2_human_cards.py) is still theirs to move.
"""
from __future__ import annotations

import re

import pytest

from sparring.ai_medusa import Act
from sparring.tts.ui import Event
from test_d3_table_effects import FxTable, build, bot_turn, card_ids, human_hand, said
from test_e2_human_cards import put_adjacent
from test_batch import click


class HandTable(FxTable):
    """Adds the human's side of `pile_card_to_hand`: the card leaves the human pile and enters the real hand."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.refused: set[int] = set()            # CardIDs the table will not move
        self.pile_moves: list[str] = []
        self.fail_with_error = False

    def do_pile_card_to_hand(self, s):
        guid = re.search(r'getObjectFromGUID\("(\w+)"\)', s).group(1)
        self.pile_moves.append(s)
        if self.fail_with_error:
            return {"__error__": "no se pudo mover"}
        i = int(guid[1:])
        if i in self.refused or i not in self.human_discard:
            return {"moved": False}
        self.human_discard.remove(i)
        self.human_hand.append(i)
        self.human_count += 1
        return {"moved": True, "guid": guid}


@pytest.fixture
def rig(tmp_path):
    session, table, game, fake, cfg, client = build(
        tmp_path, "hellboy", "golden-bat", ("Horseshoes And Hand Grenades", "Service Pistol"), table_cls=HandTable)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def insight_wins(rig, pile_titles=("A Punch to Shake the Earth",), before_reveal=lambda table, pile: None):
    """The bot attacks with a 2; the human defends with Insight and wins. Returns (messages, ids on the pile)."""
    session, table, game, fake, cfg = rig
    human = game.hero(1).fid
    put_adjacent(game, table, cfg, "hellboy", human)
    human_hand(table, game, "Insight of the Ancients", "Skirmish")
    pile = card_ids(game, 1, *pile_titles)
    table.human_discard = list(pile)
    attack = next(c for c in game.players[0].hand if c.title == "Horseshoes And Hand Grenades")      # 2 against Insight's 3
    insight = card_ids(game, 1, "Insight of the Ancients")[0]
    bot_turn(session, table, [Act("attack", fid="hellboy", target=human, card=attack)])
    table.face_down = [{"id": insight, "guid": f"h{insight}"}]
    table.human_hand.remove(insight)
    table.human_count -= 1
    before_reveal(table, pile)
    return click(session, table, Event.REVEAL), pile


PUNCH_LINE = "He puesto A Punch to Shake the Earth de tu descarte en tu mano."
INSTRUCTION = "Recoge A Punch to Shake the Earth de tu descarte a tu mano (efectos del combate)"


def engine_zones(game, title):
    st = game.players[1]
    card = next(c for c in st.full_set if c.title == title)
    return [name for name in ("hand", "discard", "deck") if card in getattr(st, name)]


def test_insight_moves_the_random_card_from_the_pile_to_the_hand_and_says_so(rig):
    session, table, game, fake, cfg = rig
    msgs, (punch,) = insight_wins(rig)
    assert said(msgs, "Tu carta: Insight of the Ancients: A Punch to Shake the Earth vuelve a tu mano")
    assert said(msgs, PUNCH_LINE) and not said(msgs, "Recoge"), msgs
    assert punch not in table.human_discard and punch in table.human_hand
    assert engine_zones(game, "A Punch to Shake the Earth") == ["hand"]
    (script,) = table.pile_moves
    assert f'getObjectFromGUID("g{punch}")' in script and f"CardID == {punch}" in script, "by GUID and CardID"
    assert "IDENT" in script and "cardOurs" in script, "and by the deck image of the human"
    assert f'Player["{cfg.session_config().human_seat}"]' in script, "into the human's own seat"


def test_the_next_table_read_expects_the_card_in_the_hand_and_off_the_pile(rig):
    session, table, game, fake, cfg = rig
    msgs, (punch,) = insight_wins(rig)
    insight = card_ids(game, 1, "Insight of the Ancients")[0]
    table.human_discard.append(insight)                         # the human puts the played card on the pile
    hand_before = len(game.players[1].hand)
    msgs = click(session, table, Event.END_ACTION)
    st = game.players[1]
    assert not any(w in m for m in msgs for w in ("Aun no veo", "Recoge", "Pon ", "mano")), msgs
    assert [c.card_id for c in st.discard if c.title == "A Punch to Shake the Earth"] == []
    assert engine_zones(game, "A Punch to Shake the Earth") == ["hand"] and len(st.hand) == hand_before
    assert table.human_count == len(st.hand), "the table's hand count and the engine's agree"
    assert insight in [c.card_id for c in st.discard]
    again = click(session, table, Event.MANEUVER)               # and a second read finds nothing new to say
    assert not any("A Punch" in m for m in again), again


@pytest.mark.parametrize("why", ("not_on_pile", "refused", "error"))
def test_a_failed_move_falls_back_to_the_old_instruction(rig, why):
    session, table, game, fake, cfg = rig
    punch = card_ids(game, 1, "A Punch to Shake the Earth")[0]
    if why == "refused":
        table.refused.add(punch)
    elif why == "error":
        table.fail_with_error = True
    gone = (lambda t, pile: t.human_discard.clear()) if why == "not_on_pile" else (lambda t, pile: None)   # the engine's pile has it, the table's does not
    msgs, _ = insight_wins(rig, before_reveal=gone)
    assert said(msgs, INSTRUCTION), msgs
    assert not said(msgs, PUNCH_LINE)
    assert punch not in table.human_hand
    if why != "not_on_pile":
        assert len(table.pile_moves) == 1
