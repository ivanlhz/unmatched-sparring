"""TTS translators, phases 2 and 3 (`sparring/session_translators.py`, docs/effects-dsl.md section 21).

Phase 2: every op that touches the real table reports an intent (`effects.table.intent`) and has a translator with a
bot and a human variant; the before/after diff of `session_bot_effects.project` only confirms what the ops reported and
translates, with an inferred intent, what they did not. Phase 3: the per-title patches of the session (Crown Of Flame,
Fight Or Flight, "Pancakes!") read the card's data instead. The flows that use them all keep their own files; this one
pins the intents the ops report, the dispatch, and the two bugs fixed with it (`fx.intents` left full when `project`
returns early, `_attack_announced` surviving the turn)."""
from __future__ import annotations

import dataclasses

from sparring import session_bot_effects as bot_effects
from sparring import session_translators as translators
from sparring.ai_medusa import Act
from sparring.effects import ongoing
from sparring.effects.choose import ControllerChooser
from sparring.effects.run import Ctx as RunCtx, EffectRun
from sparring.session_translators import BOT, HUMAN, Ctx, translate
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import card_ids, said
from test_e2_human_cards import HELLBOY_VS_ABE, LIZ_VS_HELLBOY, ONGOING_SPOTS, rig, with_rig  # noqa: F401

FOF = "Fight Or Flight"
CROWN = "And Upon His Brow Is Set A Crown Of Flame"


def run_ops(game, owner: int, ops: list[dict], this_fid: str = "abe") -> list[dict]:
    """Runs `ops` for `owner`'s controller and returns the intents they reported."""
    game.fx.intents.clear()
    EffectRun(ops, RunCtx(owner=owner, this_fid=this_fid)).run(game, ControllerChooser())
    return list(game.fx.intents)


def to_bot_discard(game, n: int) -> list[int]:
    st = game.players[0]
    cards = [c for c in st.full_set if not c.is_scheme][:n]
    for c in cards:
        for zone in (st.hand, st.deck):
            if c in zone:
                zone.remove(c)
    st.discard[:] = cards
    return [c.card_id for c in cards]


# ---------------------------------------------------------------- the ops report what they do to the table

@with_rig(*HELLBOY_VS_ABE)
def test_return_to_deck_reports_the_zone_the_cards_left_and_the_position_in_deck_order(rig):
    session, table, game, fake, cfg = rig
    ids = to_bot_discard(game, 2)
    spec = [{"op": "return_to_deck", "cards": {"zone": "discard", "player": "owner", "pick": "all"}, "position": "bottom"}]
    intents = run_ops(game, session.bot, spec)
    assert intents == [{"op": "return_to_deck", "player": session.bot, "zone": "discard", "cards": ids, "position": "bottom"}]
    assert [c.card_id for c in game.players[session.bot].deck][-2:] == ids, "the intent lists them in the order the deck holds"


@with_rig(*HELLBOY_VS_ABE)
def test_put_in_hand_reports_each_card_taken_out_of_a_pile(rig):
    session, table, game, fake, cfg = rig
    ids = to_bot_discard(game, 2)
    intents = run_ops(game, session.bot, [{"op": "put_in_hand", "cards": {"zone": "discard", "player": "owner", "pick": "all"}}])
    assert [(i["op"], i["player"], i["zone"], i["cards"]) for i in intents] == [("put_in_hand", 0, "discard", [i]) for i in ids]


@with_rig(*HELLBOY_VS_ABE)
def test_search_deck_reports_the_cards_the_bot_took(rig):
    session, table, game, fake, cfg = rig
    intents = run_ops(game, session.bot, [{"op": "search_deck", "player": "owner", "look": 3, "take": {"amount": 1},
                                           "rest": "bottom_random"}])
    assert len(intents) == 1 and intents[0]["op"] == "search_deck" and intents[0]["player"] == session.bot
    assert len(intents[0]["cards"]) == 1 and intents[0]["cards"][0] in [c.card_id for c in game.players[0].hand]


@with_rig(*HELLBOY_VS_ABE)
def test_place_swap_and_revive_report_the_pieces_they_put_elsewhere(rig):
    session, table, game, fake, cfg = rig
    hellboy_at = game.fighters["hellboy"].pos
    intents = run_ops(game, session.bot, [{"op": "swap", "target": "hero", "with": {"side": "enemy", "kind": "hero"}}])
    assert intents == [{"op": "swap", "fid": "abe", "owner": session.bot}, {"op": "swap", "fid": "hellboy", "owner": session.human}]
    assert game.fighters["abe"].pos == hellboy_at
    free = next(s for s in sorted(game.board.spaces) if all(f.pos != s for f in game.fighters.values()))
    intents = run_ops(game, session.bot, [{"op": "place", "target": {"side": "enemy", "kind": "hero"},
                                           "where": {"any": True}, "chooser": "owner"}])
    assert intents in ([{"op": "place", "fid": "hellboy", "owner": session.human}], []), "only a piece that ended elsewhere"
    assert free is not None
    game.fighters["hellboy"].alive = False
    intents = run_ops(game, session.bot, [{"op": "revive", "target": {"side": "enemy", "state": "defeated"},
                                           "where": {"any": True}, "hp": 3, "chooser": "owner"}])
    assert intents == [{"op": "revive", "fid": "hellboy", "owner": session.human}]


@with_rig(*HELLBOY_VS_ABE)
def test_counter_reports_only_a_value_that_changed(rig):
    session, table, game, fake, cfg = rig
    spec = {"op": "counter", "name": "intuition", "delta": 1}
    assert run_ops(game, session.bot, [spec]) == [{"op": "counter", "player": session.bot, "name": "intuition"}]
    assert run_ops(game, session.bot, [{"op": "counter", "name": "intuition", "set": 1}]) == []


@with_rig(*HELLBOY_VS_ABE)
def test_a_scheme_entering_play_reports_the_ongoing(rig):
    session, table, game, fake, cfg = rig
    card = next(c for c in game.players[0].full_set if c.title == "Counterhex Shield")
    game.fx.intents.clear()
    ongoing.enter_play(game, 0, card)
    assert game.fx.intents == [{"op": "ongoing", "player": 0, "card": card.card_id}]
    assert game.clone().fx.intents is None


# ---------------------------------------------------------------- the diff confirms the intents and fills in the rest

def test_groups_keep_the_ops_position_cut_to_what_the_diff_confirms_and_infer_the_rest():
    reported = [{"op": "return_to_deck", "player": 0, "zone": "discard", "cards": [3, 1, 99], "position": "bottom"},
                {"op": "move", "fid": "abe", "owner": 0}]
    out = bot_effects._groups(reported, "return_to_deck", 0, "discard", [1, 2, 3], keep_order=True)
    assert out == [{"op": "return_to_deck", "player": 0, "zone": "discard", "cards": [3, 1], "position": "bottom"},
                   {"op": "return_to_deck", "player": 0, "zone": "discard", "cards": [2], "position": None}]
    assert bot_effects._groups([], "put_in_hand", 0, "discard", [1, 2]) == [
        {"op": "put_in_hand", "player": 0, "zone": "discard", "cards": [1, 2], "position": None}]
    assert bot_effects._groups(reported, "return_to_deck", 1, "discard", [1]) == [
        {"op": "return_to_deck", "player": 1, "zone": "discard", "cards": [1], "position": None}]


@with_rig(*HELLBOY_VS_ABE)
def test_project_drains_the_intents_even_when_there_is_nothing_to_project(rig):
    session, table, game, fake, cfg = rig
    game.fx.intents.append({"op": "move", "fid": "hellboy", "owner": session.human})
    assert bot_effects.project(session, None)() is None
    assert game.fx.intents == []


@with_rig(*HELLBOY_VS_ABE)
def test_a_place_the_ops_reported_is_moved_by_the_bot_like_a_move(rig):
    session, table, game, fake, cfg = rig
    before = bot_effects.snapshot(session)
    dest = next(s for s in sorted(game.board.adj[game.fighters["hellboy"].pos])
                if all(f.pos != s for f in game.fighters.values() if f.alive))
    game.fighters["hellboy"].pos = dest
    game.fx.intents.append({"op": "place", "fid": "hellboy", "owner": session.human})
    fin = session._project_effects(before)
    session._flush()
    fin()
    assert table.moves == [(cfg.nicknames["hellboy"], dest)] and said(session.messages, "lo he movido yo (efecto del bot)")


# ---------------------------------------------------------------- dispatch

@with_rig(*HELLBOY_VS_ABE)
def test_every_phase_two_op_picks_its_variant_by_who_owns_the_cards(rig):
    session, table, game, fake, cfg = rig
    bot, human = session.bot, session.human
    assert translators._return_mode(session, {"player": bot, "zone": "hand"}) == BOT
    assert translators._return_mode(session, {"player": human, "zone": "hand"}) == HUMAN, "their hand is theirs"
    assert translators._return_mode(session, {"player": human, "zone": "discard"}) == BOT
    session.cfg = dataclasses.replace(session.cfg, human_deck_guid=None)
    assert translators._return_mode(session, {"player": human, "zone": "discard"}) == HUMAN
    assert translators._put_mode(session, {"player": bot, "zone": "discard"}) == BOT
    assert translators._put_mode(session, {"player": human, "zone": "discard"}) == HUMAN
    assert translators._put_mode(session, {"player": bot, "zone": "deck"}) is None
    assert translators._search_mode(session, {"player": bot}) == BOT
    assert translators._search_mode(session, {"player": human}) is None
    assert translators._counter_mode(session, {"player": human, "name": "intuition"}) is None
    assert translators._counter_mode(session, {"player": bot, "name": "intuition"}) == BOT
    assert translators._counter_mode(session, {"player": bot, "name": "nothing"}) is None, "a counter with no token"
    assert translators._ongoing_mode(session, {"player": human}) == HUMAN
    session.cfg = dataclasses.replace(session.cfg, bot_ongoing_spot=None)
    assert translators._ongoing_mode(session, {"player": bot}) == HUMAN, "no bot_ongoing_spot"


@with_rig(*HELLBOY_VS_ABE, **ONGOING_SPOTS)
def test_the_bot_ongoing_is_written_on_its_spot_and_the_human_one_is_said(rig):
    session, table, game, fake, cfg = rig
    assert translators._ongoing_mode(session, {"player": session.bot}) == BOT
    card = next(c for c in game.players[0].full_set if c.title == "Counterhex Shield")
    ongoing.enter_play(game, 0, card)
    translate(session, {"op": "ongoing", "player": session.bot, "card": card.card_id}, Ctx())
    session._flush()
    assert said(session.messages, "El bot deja Counterhex Shield en juego: la pone boca arriba en su zona ONGOING")
    mine = next(c for c in game.players[1].full_set if c.title == "Pancakes!")
    translate(session, {"op": "ongoing", "player": session.human, "card": mine.card_id, "replaces": None}, Ctx())
    assert said(session.messages, "Pancakes! queda en juego: dejala en tu zona ONGOING")


@with_rig(*HELLBOY_VS_ABE)
def test_the_human_variant_of_a_discard_to_deck_names_the_cards_when_there_is_no_deck_to_write(rig):
    session, table, game, fake, cfg = rig
    session.cfg = dataclasses.replace(session.cfg, human_deck_guid=None)
    ids = card_ids(game, session.human, "Excalibur", "Service Pistol")
    translate(session, {"op": "return_to_deck", "player": session.human, "zone": "discard", "cards": ids,
                        "position": "bottom"}, Ctx("efecto del bot"))
    assert said(session.messages, "Pon Excalibur y Service Pistol de tu descarte en el fondo de tu mazo (efecto del bot)")
    assert "card_to_deck_bottom" not in "".join(table.scripts)


@with_rig(*HELLBOY_VS_ABE)
def test_the_human_hand_cards_put_in_their_deck_are_named_for_their_position(rig):
    session, table, game, fake, cfg = rig
    ids = card_ids(game, session.human, "Excalibur")
    for position, text in (("top", "en la parte superior de tu mazo"), ("bottom", "en el fondo de tu mazo"),
                           ("shuffle", "en tu mazo y baraja")):
        session.messages[:] = []
        translate(session, {"op": "return_to_deck", "player": session.human, "zone": "hand", "cards": ids,
                            "position": position}, Ctx("efecto del bot"))
        assert said(session.messages, f"Pon Excalibur de tu mano {text} (efecto del bot)")


# ---------------------------------------------------------------- the two bugs

@with_rig(*LIZ_VS_HELLBOY)
def test_an_identical_attack_is_announced_again_once_the_turn_has_changed(rig):
    session, table, game, fake, cfg = rig
    session._attack_announced = ("liz", "hellboy", 7)       # a failed placement left it behind
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    game.actions_left = 0
    click(session, table, Event.END_ACTION)
    assert game.turn == session.human and session._attack_announced is None


# ---------------------------------------------------------------- phase 3: the data decides, not the title

def test_the_traits_of_the_three_patched_cards_come_from_their_data():
    assert ongoing.scheme_traits("hellboy", CROWN) == {"bonus": 0, "draw": 2, "discards_hand": True, "choose": 0, "heal": 0}
    assert ongoing.scheme_traits("hellboy", "Pancakes!") == {"bonus": 0, "draw": 0, "discards_hand": False, "choose": 2, "heal": 2}
    assert ongoing.scheme_traits("liz-sherman", FOF) == {"bonus": 1, "draw": 1, "discards_hand": False, "choose": 0, "heal": 0}
    assert ongoing.scheme_traits("hellboy", "Not a card") == {}
    assert ongoing.scheme_traits("liz-sherman", "Searing Clarity")["discards_hand"] is False


@with_rig(*HELLBOY_VS_ABE)
def test_a_whole_hand_discard_is_flagged_for_the_translator_only_while_it_is_owed(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    seen = []
    monkeypatch.setattr(translators, "translate", lambda s, intent, ctx: seen.append(dict(intent)))
    spec = lambda pick: [{"op": "discard", "cards": {"zone": "hand", "player": "owner", "pick": pick, "amount": 1}}]
    EffectRun(spec("all"), RunCtx(owner=session.human, this_fid="hellboy")).run(game, ControllerChooser())
    EffectRun(spec("chosen"), RunCtx(owner=session.human, this_fid="hellboy")).run(game, ControllerChooser())
    assert [i["all"] for i in seen] == [True, False] and game.fx.whole_hand is False


@with_rig(*HELLBOY_VS_ABE)
def test_the_translator_moves_a_whole_hand_whatever_the_card_is_called(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    intent = {"op": "discard", "player": session.human, "zone": "hand", "n": 3, "reason": "Otra carta", "all": True}
    assert translators._discard_mode(session, intent) == BOT
    assert translators._discard_mode(session, {**intent, "all": False}) == HUMAN
