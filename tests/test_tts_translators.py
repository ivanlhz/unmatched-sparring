"""The TTS translators (phase 1: `draw`, `discard`, `move`): the registry of `sparring/session_translators.py`, one
function per op with a variant where the bot moves the objects and one where the human does.

The rigs are the usual FakeTTS sessions (batch, ephemeral ports): nothing here touches the real TTS ports. The Crown
Of Flame / draw / move flows keep their own files; this one pins the dispatch, each variant and the new flow of a
human ONGOING scheme that leaves play (the bot pings it, says why, waits and moves it to the human's discard)."""
from __future__ import annotations

import dataclasses

from sparring import session_bot_effects as bot_effects
from sparring import session_translators as translators
from sparring.effects import ongoing
from sparring.session_translators import BOT, HUMAN, TRANSLATORS, Ctx, Translator, translate
from test_d3_table_effects import card_ids, said
from test_e2_human_cards import HELLBOY_VS_ABE, LIZ_VS_HELLBOY, ONGOING_SPOTS, rig, with_rig  # noqa: F401

CROWN = "And Upon His Brow Is Set A Crown Of Flame"
FOF = "Fight Or Flight"


def tags(table) -> list[str]:
    """The writes of the rig in the order they reached TTS."""
    names = (s.split("\n", 1)[0].removeprefix("-- sparring:") for s in table.scripts)
    return [t for t in names if t != "snapshot"]


def settle(session) -> None:
    session._flush()


# ---------------------------------------------------------------- the registry

@with_rig(*HELLBOY_VS_ABE)
def test_the_registry_holds_the_translated_ops_with_both_variants(rig):
    assert set(TRANSLATORS) == {"draw", "discard", "move", "place", "swap", "revive", "summon", "return_to_deck",
                                "put_in_hand", "search_deck", "counter", "form", "ongoing", "tuck", "remove", "stack_top", "reveal_deck",
                                "shuffle_deck", "hand_to_deck_all", "future_look"}
    for t in TRANSLATORS.values():
        assert callable(t.bot) and callable(t.human) and t.bot is not t.human and callable(t.mode)


@with_rig(*HELLBOY_VS_ABE)
def test_an_op_without_translator_keeps_the_diff_path(rig):
    session, table, game, fake, cfg = rig
    assert translate(session, {"op": "damage", "fid": "hellboy"}, Ctx()) is None
    assert tags(table) == []


@with_rig(*HELLBOY_VS_ABE)
def test_what_is_not_about_the_human_s_table_is_left_to_its_own_projection(rig):
    session, table, game, fake, cfg = rig
    bot = session.bot
    assert translate(session, {"op": "draw", "player": bot, "n": 1}, Ctx()) is None
    assert translate(session, {"op": "discard", "player": bot, "zone": "in_play", "card": 1}, Ctx()) is None
    assert translate(session, {"op": "move", "fid": "abe", "owner": bot}, Ctx()) is None
    assert tags(table) == [] and not session.messages


@with_rig(*HELLBOY_VS_ABE)
def test_translate_hands_the_intent_and_the_context_to_the_variant_its_mode_picks(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    seen = []
    spy = Translator(mode=lambda s, i: HUMAN if i["pick"] == "h" else BOT,
                     bot=lambda s, i, c: seen.append(("bot", i, c)) or ["b"],
                     human=lambda s, i, c: seen.append(("human", i, c)) or ["h"])
    monkeypatch.setitem(TRANSLATORS, "draw", spy)
    ctx = Ctx("x")
    assert translate(session, {"op": "draw", "pick": "h"}, ctx) == ["h"]
    assert translate(session, {"op": "draw", "pick": "b"}, ctx) == ["b"]
    assert [(v, i["pick"], c) for v, i, c in seen] == [("human", "h", ctx), ("bot", "b", ctx)]


# ---------------------------------------------------------------- draw

@with_rig(*HELLBOY_VS_ABE)
def test_the_owed_draws_of_the_human_go_through_the_draw_translator(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    seen = []
    monkeypatch.setitem(TRANSLATORS, "draw", Translator(mode=lambda s, i: BOT, bot=lambda s, i, c: seen.append((i, c)) or [],
                                                        human=lambda s, i, c: []))
    game.drawn[session.human] += 3
    session._deal_owed_draws("Pancakes!")
    session._deal_owed_draws("Pancakes!")                         # already counted: nothing owed twice
    assert [(i["n"], i["cause"], c.cause) for i, c in seen] == [(3, "Pancakes!", "Pancakes!")]


@with_rig(*HELLBOY_VS_ABE)
def test_draw_bot_variant_deals_from_the_human_deck_to_their_seat(rig):
    session, table, game, fake, cfg = rig
    assert translators._draw_mode(session, {"player": session.human}) == BOT
    translate(session, {"op": "draw", "player": session.human, "n": 2, "cause": "efecto de X"}, Ctx("efecto de X"))
    session._commit()
    assert table.human_deals == [2] and said(session.messages, "Te he dado 2 cartas (efecto de X)")


@with_rig(*HELLBOY_VS_ABE)
def test_draw_human_variant_says_to_draw_by_hand_when_there_is_no_deck(rig):
    session, table, game, fake, cfg = rig
    session.cfg = dataclasses.replace(session.cfg, human_deck_guid=None)
    assert translators._draw_mode(session, {"player": session.human}) == HUMAN
    translate(session, {"op": "draw", "player": session.human, "n": 2, "cause": "efecto de X"}, Ctx("efecto de X"))
    session._commit()
    assert table.human_deals == [] and said(session.messages, "Robas 2 cartas (efecto de X): hazlo en la mesa")


# ---------------------------------------------------------------- discard: the human's hand

@with_rig(*HELLBOY_VS_ABE)
def test_discard_human_variant_owes_a_count_the_human_chooses(rig):
    session, table, game, fake, cfg = rig
    base = len(game.players[session.human].discard)
    intent = {"op": "discard", "player": session.human, "zone": "hand", "n": 2, "reason": "Algo"}
    assert translators._discard_mode(session, intent) == HUMAN
    translate(session, intent, Ctx())
    assert session.pending_discard == {"n": 2, "baseline": base, "kind": "cards", "hand": True}
    assert said(session.messages, "Descarta 2 carta(s) (Algo) y pulsa Fin de accion") and tags(table) == []


@with_rig(*HELLBOY_VS_ABE)
def test_the_forced_discard_of_the_engine_reaches_the_translator(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    seen = []
    monkeypatch.setitem(TRANSLATORS, "discard", Translator(mode=lambda s, i: HUMAN, bot=lambda s, i, c: [],
                                                           human=lambda s, i, c: seen.append(i) or []))
    session._owe_discard(1, "Algo")
    assert seen == [{"op": "discard", "player": session.human, "zone": "hand", "n": 1, "reason": "Algo", "all": False}]


@with_rig(*HELLBOY_VS_ABE)
def test_discard_bot_variant_for_crown_moves_the_hand_and_asks_only_for_what_is_left(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    intent = {"op": "discard", "player": session.human, "zone": "hand", "n": 3, "reason": CROWN, "all": True}
    assert translators._discard_mode(session, intent) == BOT
    calls = []
    monkeypatch.setattr(session, "_discard_human_hand", lambda n, reason: calls.append((n, reason)) or 1)
    translate(session, intent, Ctx())
    assert calls == [(3, CROWN)] and session.pending_discard["n"] == 1
    assert said(session.messages, f"Descarta 1 carta(s) ({CROWN})")
    session.pending_discard, session.messages[:] = None, []
    monkeypatch.setattr(session, "_discard_human_hand", lambda n, reason: 0)
    translate(session, intent, Ctx())
    assert session.pending_discard is None and not session.messages


@with_rig(*HELLBOY_VS_ABE)
def test_discard_of_named_cards_is_owed_to_the_human_until_the_pile_shows_them(rig):
    session, table, game, fake, cfg = rig
    ids = card_ids(game, session.human, "Excalibur", "Service Pistol")
    intent = {"op": "discard", "player": session.human, "zone": "hand", "cards": ids}
    translate(session, intent, Ctx("efecto del bot"))
    assert session.pending_discard["cards"] == ids
    assert said(session.messages, "Pon Excalibur y Service Pistol de tu mano en tu descarte (efecto del bot) y pulsa Fin de accion")


# ---------------------------------------------------------------- discard: the human's ONGOING leaves play

def put_in_play(game, title=FOF, player=1):
    card = next(c for c in game.players[player].full_set if c.title == title)
    for zone in (game.players[player].hand, game.players[player].deck, game.players[player].discard):
        if card in zone:
            zone.remove(card)
    ongoing.enter_play(game, player, card)
    return card.card_id


def leaves_play(session, table, game, cause="caduca"):
    """The step: the scheme leaves play (the op's intent) and the projection of the step reaches the table."""
    before = bot_effects.snapshot(session)
    ongoing.leave_play(game, session.human)
    fin = session._project_effects(before, cause=cause)
    settle(session)
    fin()
    settle(session)


def zone_with(table, card_id):
    table.human_ongoing.append(card_id)
    return card_id


@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_an_ongoing_that_leaves_play_is_pinged_explained_and_moved_to_the_discard_by_the_bot(rig):
    session, table, game, fake, cfg = rig
    fof = zone_with(table, put_in_play(game))
    session.cfg.ongoing_hold = 1.5
    leaves_play(session, table, game)
    order = [t for t in tags(table) if t in ("ping_objects", "broadcast", "hold", "card_to_discard")]
    assert order[0] == "ping_objects" and order.index("hold") < order.index("card_to_discard"), order
    assert table.pings == [[[f"g{fof}"]]] and table.holds == [1.5] and table.card_moves == [fof]
    assert fof in table.human_discard and fof not in table.human_ongoing
    assert said(session.messages, f"{FOF} deja de estar en juego (caduca): mira el ping, la llevo yo a tu descarte")
    assert session.pending_discard is None and not said(session.messages, "pasala de tu zona ONGOING")
    assert fof in [c.card_id for c in game.players[1].discard] and game.fx.ongoing_card_id(1) is None
    assert any(m.shown for m in session.messages if "mira el ping" in m), "it is on screen before the pause"


@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_without_a_hold_the_bot_does_not_pause_between_ping_and_move(rig):
    session, table, game, fake, cfg = rig
    fof = zone_with(table, put_in_play(game))
    leaves_play(session, table, game)
    assert not getattr(table, "holds", []) and table.card_moves == [fof] and fof in table.human_discard


@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_a_card_that_is_not_on_the_ongoing_zone_falls_back_to_the_manual_flow_without_pinging(rig):
    session, table, game, fake, cfg = rig
    fof = put_in_play(game)                                       # the table shows nothing on the zone
    leaves_play(session, table, game)
    assert "ping_objects" not in tags(table) and "card_to_discard" not in tags(table)
    assert session.pending_discard["cards"] == [fof]
    assert said(session.messages, f"{FOF} deja de estar en juego (caduca): pasala de tu zona ONGOING a tu descarte")


@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_a_count_mismatch_on_the_zone_falls_back_to_the_manual_flow(rig):
    session, table, game, fake, cfg = rig
    fof = put_in_play(game)
    table.human_ongoing += [fof, fof]                             # two copies read: not exactly one
    leaves_play(session, table, game)
    assert "card_to_discard" not in tags(table) and session.pending_discard["cards"] == [fof]


@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_a_table_that_refuses_the_move_falls_back_to_the_manual_flow_once(rig):
    session, table, game, fake, cfg = rig
    fof = zone_with(table, put_in_play(game))
    table.card_to_discard_fails = True
    leaves_play(session, table, game)
    assert table.card_moves == [fof] and fof in table.human_ongoing
    assert session.pending_discard["cards"] == [fof]
    assert len([m for m in session.messages if "pasala de tu zona ONGOING" in m]) == 1


@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_a_table_error_reading_the_zone_falls_back_to_the_manual_flow(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    fof = zone_with(table, put_in_play(game))
    monkeypatch.setattr(session, "_rd_ongoing", lambda side: (_ for _ in ()).throw(OSError("sin mesa")))
    leaves_play(session, table, game)
    assert "ping_objects" not in tags(table) and session.pending_discard["cards"] == [fof]


@with_rig(*LIZ_VS_HELLBOY, human_ongoing_spot=None, bot_ongoing_spot=None)
def test_without_an_ongoing_spot_the_card_already_sits_on_the_pile(rig):
    session, table, game, fake, cfg = rig
    put_in_play(game)
    assert translators._discard_mode(session, {"player": session.human, "zone": "in_play"}) == HUMAN
    leaves_play(session, table, game)
    assert said(session.messages, f"{FOF} deja de estar en juego (caduca): queda en tu descarte")
    assert session.pending_discard is None and "card_to_discard" not in tags(table)


@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_the_ops_report_the_ongoing_that_left_play_and_a_clone_listens_to_nothing(rig):
    session, table, game, fake, cfg = rig
    fof = put_in_play(game)
    assert game.clone().fx.intents is None
    game.fx.intents.clear()
    ongoing.leave_play(game, 1)
    assert game.fx.intents == [{"op": "discard", "zone": "in_play", "player": 1, "card": fof}]
    assert bot_effects._drain_intents(session) == [{"op": "discard", "zone": "in_play", "player": 1, "card": fof}]
    assert game.fx.intents == []


# ---------------------------------------------------------------- move

def free_space_near(game, fid):
    taken = {f.pos for f in game.fighters.values() if f.alive}
    pos = game.fighters[fid].pos
    return next(s for s in sorted(game.board.adj[pos]) if s not in taken)


def bot_moves_the_human(session, table, game, cfg, intent=True):
    """A bot effect moves Hellboy (the human's) to a free adjacent space; returns (fid, destination)."""
    before = bot_effects.snapshot(session)
    dest = free_space_near(game, "hellboy")
    game.fighters["hellboy"].pos = dest
    if intent:
        game.fx.intents.append({"op": "move", "fid": "hellboy", "owner": session.human})
    fin = session._project_effects(before)
    settle(session)
    fin()
    return dest


@with_rig(*HELLBOY_VS_ABE)
def test_move_bot_variant_moves_the_human_miniature_and_says_so(rig):
    session, table, game, fake, cfg = rig
    dest = bot_moves_the_human(session, table, game, cfg)
    assert table.moves == [(cfg.nicknames["hellboy"], dest)]
    assert said(session.messages, "se mueve a ") and said(session.messages, "lo he movido yo (efecto del bot)")


@with_rig(*HELLBOY_VS_ABE)
def test_a_move_the_diff_finds_without_an_intent_gets_the_same_writes(rig):
    session, table, game, fake, cfg = rig
    dest = bot_moves_the_human(session, table, game, cfg, intent=False)
    assert table.moves == [(cfg.nicknames["hellboy"], dest)]
    assert said(session.messages, "lo he movido yo (efecto del bot)")


@with_rig(*HELLBOY_VS_ABE)
def test_move_human_variant_is_the_fallback_when_the_table_refuses(rig):
    session, table, game, fake, cfg = rig
    table.move_fails.add(session._guids("hellboy")[0])
    bot_moves_the_human(session, table, game, cfg)
    assert table.moves == []
    assert said(session.messages, "por un efecto del bot: no he podido mover su miniatura, muevela tu")
    assert not said(session.messages, "lo he movido yo")


@with_rig(*HELLBOY_VS_ABE)
def test_a_piece_that_did_not_end_elsewhere_is_not_moved(rig):
    session, table, game, fake, cfg = rig
    before = bot_effects.snapshot(session)
    ctx = Ctx("c", before)
    intent = {"op": "move", "fid": "hellboy", "owner": session.human}
    assert translate(session, intent, ctx) == [] and tags(table) == []


@with_rig(*HELLBOY_VS_ABE)
def test_the_move_op_reports_the_human_pieces_it_moved(rig):
    session, table, game, fake, cfg = rig
    from sparring.effects.choose import ControllerChooser
    from sparring.effects.run import Ctx as RunCtx, EffectRun
    game.fx.intents.clear()
    start = {f.fid: f.pos for f in game.own(session.human)}
    spec = [{"op": "move", "target": {"side": "enemy"}, "amount": 2, "up_to": True}]
    EffectRun(spec, RunCtx(owner=session.bot, this_fid="abe")).run(game, ControllerChooser())
    moved = {fid for fid, pos in start.items() if game.fighters[fid].pos != pos}
    assert moved, "the bot's controller moved at least one of the human's pieces"
    assert {i["fid"] for i in game.fx.intents} == moved
    assert all(i == {"op": "move", "fid": i["fid"], "owner": session.human} for i in game.fx.intents)


@with_rig(*LIZ_VS_HELLBOY, **ONGOING_SPOTS)
def test_a_scheme_that_expires_at_the_bot_s_turn_is_moved_by_the_bot_and_nothing_is_owed(rig):
    """The whole button flow of tests/test_e2_human_cards.py (Fight Or Flight expires), now without the manual step."""
    from sparring.ai_medusa import Act
    from sparring.tts.ui import Event
    from test_batch import click
    from test_d3_table_effects import human_hand
    session, table, game, fake, cfg = rig
    human_hand(table, game, FOF, "Evade", "Fireball")
    fof = card_ids(game, 1, FOF)[0]
    click(session, table, Event.SCHEME)
    table.human_ongoing.append(fof)
    table.human_count -= 1
    click(session, table, Event.END_ACTION)
    assert game.fx.ongoing_card_id(1) == fof
    table.human_count += 1
    click(session, table, Event.MANEUVER)
    table.positions[cfg.nicknames["liz"]] = game.fighters["liz"].pos
    session.ai.plan = lambda g: Act("maneuver", moves={})
    session.ai.pick_ability_target = lambda g: None
    msgs = click(session, table, Event.END_ACTION)
    assert game.fx.ongoing_card_id(1) is None and table.card_moves == [fof]
    assert said(msgs, f"{FOF} deja de estar en juego (caduca): mira el ping") and not said(msgs, "pasala de tu zona ONGOING")
    assert session.pending_discard is None and fof in table.human_discard and table.human_ongoing == []
    msgs = click(session, table, Event.END_ACTION)
    assert fof in [c.card_id for c in game.players[1].discard] and not said(msgs, "Aun no veo en tu descarte")


def test_the_card_to_discard_script_takes_one_loose_card_by_guid_and_never_one_in_a_hand():
    from conftest import TEST_IDENT
    from sparring.tts import lua
    script = lua.card_to_discard("g12", "906a7a", (1000, 1029), identity=TEST_IDENT)
    assert script.startswith("-- sparring:card_to_discard") and lua.is_sendable(script)
    assert 'getObjectFromGUID("g12")' in script and 'getObjectFromGUID("906a7a")' in script
    assert "card.held_by_color" in script and "not ours(card)" in script and "Vector(0, turn, 0)" in script
    assert "getHandObjects" not in script and "setPositionSmooth" not in script
