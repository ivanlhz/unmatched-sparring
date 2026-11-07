"""The future of Ninjutsu, "look at the top card of ANY deck" (Ivan, 7/11): the engine side.

Whoever plays it chooses the deck: their own or the rival's. The table player's real deck is read through
`Game.deck_reader` (its engine copy is virtual); the bot's deck is the engine's own order, so the human is shown its real
top card. The bot decides with `EffectAI` and only knows a card it looked at while that card is legitimately known."""
import pytest

from conftest import Scripted, card
from sparring.ai_effects import EffectAI
from sparring.ai_medusa import MedusaAI
from sparring.effects.choose import ChoiceRequest, PanelChooser, ScriptedChooser, SyntheticChooser
from sparring.effects.run import Ctx, EffectRun
from sparring.state import Game

OWN, RIVAL = 0, 1
LEAVE, BOTTOM = 0, 1


class Human(Scripted):
    human = True            # the table player: `effects.table.physical` is true for their seat


def make(bprd, bot_human=False):
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Human() if bot_human else Scripted()},
                 bot_player=0, heroes=("donatello", "hellboy"))
    g.turn, g.turn_no = 0, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    g.fx.intents = []
    return g


def donatello_run(g, choosers):
    ctx = Ctx(owner=0, this_fid="metalhead", card_id=card(g, 0, "The future of Ninjutsu").card_id)
    run = EffectRun.for_card("donatello", "The future of Ninjutsu", "scheme", ctx)
    run.run(g, choosers)
    return run


def top(g, player):
    return g.players[player].deck[0]


# ---------------------------------------------------------------- the bot plays it, the rival deck is the engine's

def test_the_bot_looks_at_the_rivals_deck_and_puts_a_strong_top_card_at_the_bottom(bprd):
    g = make(bprd)
    seen = top(g, 1)
    chooser = ScriptedChooser([[RIVAL], [BOTTOM]])
    run = donatello_run(g, {0: chooser, 1: Scripted()})
    assert run.awaiting is None and not run.frames
    assert g.players[1].deck[-1] is seen and g.players[1].deck[0] is not seen
    assert [r.extra.get("future") for r in chooser.requests] == ["deck", "peek"]
    assert chooser.requests[1].extra["top"] == seen.card_id and chooser.requests[1].extra["deck_of"] == 1
    assert g.players[0].known.top_of_deck == [], "put at the bottom: the next top card is unknown"
    assert g.drawn[0] == 1 and g.actions_left == 3


def test_left_on_top_the_bot_knows_that_card_until_the_rival_draws_it(bprd):
    g = make(bprd)
    seen = top(g, 1)
    donatello_run(g, {0: ScriptedChooser([[RIVAL], [LEAVE]]), 1: Scripted()})
    assert g.players[1].deck[0] is seen
    assert g.players[0].known.top_of_deck == [seen.card_id]
    assert g.players[0].known.top(g.players[1]) == [seen]
    g.draw(1, 1)
    assert g.players[0].known.top_of_deck == [] and seen in g.players[1].hand
    assert seen.card_id in g.players[0].known.seen, "it was the known top card, now seen in their hand"


def test_the_deck_question_never_shows_the_rivals_top_card(bprd):
    g = make(bprd)
    own_top = g.players[0].deck[0].card_id
    chooser = ScriptedChooser([[OWN], [LEAVE]])
    donatello_run(g, {0: chooser, 1: Scripted()})
    deck_request = chooser.requests[0]
    assert deck_request.extra["future"] == "deck" and deck_request.options == [OWN, RIVAL]
    assert "top" not in deck_request.extra and "rival_top" not in deck_request.extra
    assert deck_request.extra["own_top"] == own_top


def test_the_own_deck_keeps_the_old_flow(bprd):
    g = make(bprd)
    weak = min(g.players[0].deck, key=lambda c: (c.value or 0) + c.boost)
    g.players[0].deck.remove(weak)
    g.players[0].deck.insert(0, weak)
    chooser = ScriptedChooser([[OWN], [True]])
    donatello_run(g, {0: chooser, 1: Scripted()})
    assert chooser.requests[1].kind == "optional" and chooser.requests[1].extra["bury"] == [weak.card_id]
    assert g.players[0].deck[-1] is weak


def test_an_empty_rival_deck_is_not_offered(bprd):
    g = make(bprd)
    g.players[1].deck.clear()
    chooser = ScriptedChooser([[True]])
    donatello_run(g, {0: chooser, 1: Scripted()})
    assert [r.kind for r in chooser.requests] == ["optional"]


# ---------------------------------------------------------------- the bot plays it, the rival deck is the human's real one

def test_the_bot_reads_the_humans_real_top_card_and_moves_it_to_the_bottom_on_the_table(bprd):
    g = make(bprd, bot_human=True)
    real = card(g, 1, "Service Pistol")
    g.deck_reader = lambda player: real.card_id if player == 1 else None
    virtual = list(g.players[1].deck)
    chooser = ScriptedChooser([[RIVAL], [BOTTOM]])
    donatello_run(g, {0: chooser, 1: Scripted()})
    assert chooser.requests[1].extra["top"] == real.card_id
    assert g.players[1].deck == virtual, "the engine never invents an order for their deck"
    assert g.fx.intents == [{"op": "future_look", "player": 1, "card": real.card_id, "position": "bottom"}]
    assert g.players[0].known.top_of_deck == []


def test_left_on_top_the_bot_remembers_the_humans_top_card_and_says_so_to_the_table(bprd):
    g = make(bprd, bot_human=True)
    real = card(g, 1, "Service Pistol")
    g.deck_reader = lambda player: real.card_id
    donatello_run(g, {0: ScriptedChooser([[RIVAL], [LEAVE]]), 1: Scripted()})
    assert g.fx.intents == [{"op": "future_look", "player": 1, "card": real.card_id, "position": "top"}]
    assert g.players[0].known.top(g.players[1]) == [real]


def test_without_a_deck_reader_the_humans_deck_is_not_offered(bprd):
    g = make(bprd, bot_human=True)
    chooser = ScriptedChooser([[True]])
    donatello_run(g, {0: chooser, 1: Scripted()})
    assert [r.kind for r in chooser.requests] == ["optional"], "a clone or a simulation has no table to read"


def test_a_failed_read_falls_back_to_the_own_deck(bprd):
    g = make(bprd, bot_human=True)
    g.deck_reader = lambda player: None
    chooser = ScriptedChooser([[RIVAL], [True]])
    donatello_run(g, {0: chooser, 1: Scripted()})
    assert [r.kind for r in chooser.requests] == ["effect", "optional"]
    assert g.fx.intents == []


def test_a_card_that_is_not_the_humans_is_a_failed_read(bprd):
    g = make(bprd, bot_human=True)
    g.deck_reader = lambda player: 999999
    chooser = ScriptedChooser([[RIVAL], [True]])
    donatello_run(g, {0: chooser, 1: Scripted()})
    assert [r.kind for r in chooser.requests] == ["effect", "optional"]


def test_a_clone_never_carries_the_deck_reader(bprd):
    g = make(bprd, bot_human=True)
    g.deck_reader = lambda player: 1
    assert g.clone().deck_reader is None


# ---------------------------------------------------------------- the human plays it, the bot's deck is the engine's

def human_run(g, choosers):
    ctx = Ctx(owner=1, this_fid="metalhead", card_id=card(g, 1, "The future of Ninjutsu").card_id)
    run = EffectRun.for_card("donatello", "The future of Ninjutsu", "scheme", ctx)
    run.run(g, choosers)
    return run


def human_game(bprd):
    g = Game.new(bprd, seed=3, controllers={0: Scripted(), 1: Human()}, bot_player=0, heroes=("hellboy", "donatello"))
    g.turn, g.turn_no = 1, 2
    g.begin_turn()
    for p in g.players:
        p.hand.clear()
    g.fx.intents = []
    return g


def test_the_human_chooses_the_deck_with_two_labelled_buttons(bprd):
    g = human_game(bprd)
    run = human_run(g, {0: Scripted(), 1: PanelChooser()})
    req = run.awaiting
    assert req.kind == "effect" and req.options == [OWN, RIVAL] and req.player == 1 and req.extra["future"] == "deck"
    assert len(req.extra["labels"]) == 2 and "own_top" not in req.extra, "the engine does not know their real top card"


def test_the_human_looking_at_the_bots_deck_is_shown_its_engine_top_card_and_pauses(bprd):
    g = human_game(bprd)
    seen = top(g, 0)
    run = human_run(g, {0: Scripted(), 1: PanelChooser()})
    run.resume([RIVAL])
    run.run(g, {0: Scripted(), 1: PanelChooser()})
    req = run.awaiting
    assert req.kind == "effect" and req.extra["future"] == "peek" and req.extra["top"] == seen.card_id
    assert req.extra["deck_of"] == 0 and req.options == [LEAVE, BOTTOM] and len(req.extra["labels"]) == 2
    assert g.drawn[1] == 0, "the draw waits for the answer"


def test_putting_the_bots_top_card_at_the_bottom_changes_its_engine_deck_and_the_run_goes_on(bprd):
    g = human_game(bprd)
    seen = top(g, 0)
    choosers = {0: Scripted(), 1: PanelChooser()}
    run = human_run(g, choosers)
    run.resume([RIVAL]); run.run(g, choosers)
    run.resume([BOTTOM]); run.run(g, choosers)
    assert run.awaiting is None and not run.frames
    assert g.players[0].deck[-1] is seen and g.players[0].deck[0] is not seen
    assert g.drawn[1] == 1 and g.actions_left == 3
    assert g.players[1].known.top_of_deck == [], "the human saw it and it went to the bottom"


def test_leaving_the_bots_top_card_keeps_its_engine_deck(bprd):
    g = human_game(bprd)
    seen = top(g, 0)
    choosers = {0: Scripted(), 1: PanelChooser()}
    run = human_run(g, choosers)
    run.resume([RIVAL]); run.run(g, choosers)
    run.resume([LEAVE]); run.run(g, choosers)
    assert g.players[0].deck[0] is seen
    assert g.players[1].known.top_of_deck == [seen.card_id]


def test_the_human_choosing_their_own_deck_keeps_the_current_flow(bprd):
    g = human_game(bprd)
    choosers = {0: Scripted(), 1: PanelChooser()}
    run = human_run(g, choosers)
    run.resume([OWN]); run.run(g, choosers)
    assert run.awaiting.kind == "optional"
    run.resume([False]); run.run(g, choosers)
    assert not run.frames and g.drawn[1] == 1
    assert g.fx.intents == []


def test_the_pause_survives_a_save(bprd):
    g = human_game(bprd)
    choosers = {0: Scripted(), 1: PanelChooser()}
    run = human_run(g, choosers)
    run.resume([RIVAL]); run.run(g, choosers)
    again = EffectRun.from_dict(run.to_dict())
    assert again.awaiting.to_dict() == run.awaiting.to_dict() and again.awaiting.extra["future"] == "peek"
    again.resume([BOTTOM]); again.run(g, choosers)
    assert not again.frames and g.players[0].deck[-1].card_id == run.awaiting.extra["top"]


# ---------------------------------------------------------------- the bot's judgement

def deck_request(g, own_top):
    return ChoiceRequest("effect", 0, [OWN, RIVAL], 1, 1, 0, "scheme/0:0", "which deck",
                         {"future": "deck", "labels": ["a", "b"], "own_top": own_top}, 0)


def peek_request(g, card_id):
    return ChoiceRequest("effect", 0, [LEAVE, BOTTOM], 1, 1, 0, "scheme/0:1", "keep or bottom",
                         {"future": "peek", "labels": ["a", "b"], "top": card_id, "deck_of": 1}, 0)


def test_the_bot_buries_a_weak_own_top_card_and_otherwise_looks_at_the_rivals_deck(bprd):
    g = make(bprd)
    ai = EffectAI(0, MedusaAI(0))
    weak = min(g.players[0].deck, key=lambda c: (c.value or 0) + c.boost)
    assert ai.choose_effect(g, deck_request(g, weak.card_id)) == [OWN]
    strong = card(g, 0, "Electro grenade")
    assert ai.choose_effect(g, deck_request(g, strong.card_id)) == [RIVAL]
    assert ai.choose_effect(g, deck_request(g, None)) == [RIVAL], "no own top card: nothing to improve there"


def test_the_bot_puts_a_strong_card_of_the_human_at_the_bottom_and_leaves_a_weak_one(bprd):
    g = make(bprd)
    ai = EffectAI(0, MedusaAI(0))
    from sparring.search.adapter import card_worth
    ranked = sorted(g.players[1].full_set, key=card_worth)
    assert ai.choose_effect(g, peek_request(g, ranked[-1].card_id)) == [BOTTOM]
    assert ai.choose_effect(g, peek_request(g, ranked[0].card_id)) == [LEAVE]


def test_the_judgement_ignores_what_the_human_already_played(bprd):
    g = make(bprd)
    ai = EffectAI(0, MedusaAI(0))
    from sparring.search.adapter import card_worth
    ranked = sorted(g.players[1].full_set, key=card_worth)
    g.players[1].discard.extend(ranked[len(ranked) // 2:])       # the strong half is already gone: what is left is weak
    mid = ranked[len(ranked) // 2 - 1]
    assert ai.choose_effect(g, peek_request(g, mid.card_id)) == [BOTTOM], "better than anything that is left"


@pytest.mark.parametrize("policy", ["first", "random", "greedy", "safe"])
def test_a_simulation_answers_both_questions(bprd, policy):
    g = make(bprd)
    for req in (deck_request(g, None), peek_request(g, top(g, 1).card_id)):
        answer = SyntheticChooser(policy=policy).choose(g, req)
        assert req.validate(answer)
