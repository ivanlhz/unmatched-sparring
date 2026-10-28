"""Combat flow as a serializable state machine (sparring/combat_flow.py). See docs/combat-flow.md."""
import json

import pytest

from sparring.combat_flow import Phase, PendingChoice

NO_DECK = lambda card_id: False  # noqa: E731


# ---------- types ----------
def test_pending_choice_roundtrip():
    choice = PendingChoice("boost", player=1, card_id=19709, deck=True,
                           extra={"guid": "abc123", "baseline": [3, 4], "hand": 5, "stuck": True})
    raw = json.loads(json.dumps(choice.to_dict()))
    assert raw == {"kind": "boost", "player": 1, "card": 19709, "deck": True,
                   "guid": "abc123", "baseline": [3, 4], "hand": 5, "stuck": True}
    assert PendingChoice.from_dict(raw, default_player=1, deck_of=NO_DECK) == choice


def test_pending_choice_translates_legacy_boost_wait():
    old = {"card": 19709, "guid": None, "baseline": [7], "hand": None, "stuck": False}   # old save: no kind/player/deck
    choice = PendingChoice.from_dict(old, default_player=1, deck_of=lambda card_id: card_id == 19709)
    assert (choice.kind, choice.player, choice.card_id, choice.deck) == ("boost", 1, 19709, True)
    assert choice.extra == {"guid": None, "baseline": [7], "hand": None, "stuck": False}
    flat = choice.to_dict()
    assert flat["card"] == 19709 and flat["baseline"] == [7] and flat["stuck"] is False and flat["deck"] is True


@pytest.mark.parametrize("raw", [
    {"card": "x"},
    {"card": True},
    {"baseline": []},
    {"kind": "teleport", "player": 1, "card": 1, "deck": False},
    {"kind": "boost", "player": "1", "card": 1, "deck": False},
    [],
    None,
])
def test_pending_choice_rejects_invalid(raw):
    with pytest.raises(KeyError):
        PendingChoice.from_dict(raw, default_player=1, deck_of=NO_DECK)


def test_phase_order():
    assert [p.value for p in Phase] == ["declared", "cards_set", "revealed", "immediately", "during", "damage",
                                        "after", "done"]
    assert Phase("during") is Phase.DURING
