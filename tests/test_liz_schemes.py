"""Bot-Liz's schemes (reported live 30/10: Searing Clarity played with nothing to shuffle, Fight Or Flight played
without moving Liz, an English "maneuver" in the chat, a Wildfire return said twice, a shuffle announced before the play
that caused it). The position is the saved game's: Liz at 3, Baba Yaga at 15, Koschei at 16, the discard pile holding
only schemes. No TTS and no sockets for the engine tests; the chat tests use the FakeTTS table."""
import pytest

from sparring.ai_medusa import Act, MedusaAI, Model
from sparring.board import Board
from sparring.hellboy_script import ScriptedHellboy
from sparring.state import Game
from test_d3_table_effects import build as d3_build, to_bot_discard

BOT, HUMAN = 0, 1


def saved_position(hand: list[str], discard: list[str], liz_at: int = 3) -> tuple[Game, MedusaAI]:
    ai = MedusaAI(BOT)
    game = Game.new(Board.load("bprd-hq"), 1, {BOT: ai, HUMAN: ScriptedHellboy(HUMAN, 0)}, bot_player=BOT,
                    heroes=("liz-sherman", "baba-yaga"))
    me = game.players[BOT]
    used: set[int] = set()

    def take(titles):
        out = []
        for t in titles:
            c = next(c for c in me.full_set if c.title == t and c.card_id not in used)
            used.add(c.card_id)
            out.append(c)
        return out
    me.hand[:] = take(hand)
    me.discard[:] = take(discard)
    me.deck[:] = [c for c in me.full_set if c.card_id not in used]
    for fid, pos in (("liz", liz_at), ("baba", 15), ("koschei", 16)):
        game.fighters[fid].pos = pos
    game.turn, game.actions_left = BOT, 2
    return game, ai


SAVED_HAND = ["Evade", "Feint", "Feint", "Evade", "Pyrotechnics", "Pyrotechnics"]
ONLY_SCHEMES = ["Fight Or Flight", "Searing Clarity", "Fight Or Flight", "Fight Or Flight", "Searing Clarity"]


def test_searing_clarity_with_only_schemes_in_the_discard_is_not_played():
    game, ai = saved_position(SAVED_HAND + ["Searing Clarity"], ONLY_SCHEMES)
    plan = ai.plan(game)
    assert not (plan.kind == "scheme" and plan.card.title == "Searing Clarity")
    acts = ai.candidates(game, Model(game, BOT))
    empty = [a for a in acts if a.kind == "scheme"]
    assert all(a.value < 0 for a in empty), "an empty shuffle is worth less than nothing: only its own action comes back"
    assert max(a.value for a in acts if a.kind == "maneuver") > max((a.value for a in empty), default=-9)


def test_searing_clarity_still_shuffles_a_non_scheme_card_and_never_a_scheme():
    game, ai = saved_position(SAVED_HAND[:-1] + ["Searing Clarity"], ONLY_SCHEMES + ["Pyrotechnics"])
    me = game.players[BOT]
    sc = next(c for c in me.hand if c.title == "Searing Clarity")
    act = next(a for a in ai.candidates(game, Model(game, BOT)) if a.kind == "scheme")
    assert act.value > 0, "with a card to shuffle the scheme keeps its worth (the card, plus the action it gives back)"
    discard_schemes = [c for c in me.discard if c.is_scheme]
    game.play_scheme(BOT, game.hero(BOT), sc)
    assert [c.title for c in me.discard if not c.is_scheme] == []
    assert all(c in me.discard for c in discard_schemes) and sc in me.discard
    assert sum(c.title == "Pyrotechnics" for c in me.deck) == 5 - 2 + 1 or any(c.title == "Pyrotechnics" for c in me.deck)
    assert game.actions_left == 2, "the scheme costs its action and gives it back"


def test_fight_or_flight_moves_liz_into_reach_when_the_hand_can_attack():
    """In the save she played it three times and never left space 3 (out of reach of both rivals)."""
    game, ai = saved_position(SAVED_HAND + ["Fight Or Flight"], ONLY_SCHEMES[:1])
    liz = game.hero(BOT)
    foes = game.foes(BOT)
    assert not any(game.can_attack(liz, e) for e in foes)
    fof = next(c for c in game.players[BOT].hand if c.title == "Fight Or Flight")
    ai.execute(game, Act("scheme", 0, "liz", "", fof))
    assert liz.pos != 3
    assert any(game.can_attack(liz, e) for e in foes)
    assert game.actions_left == 1, "an action is left to use the position"


def test_fight_or_flight_move_is_untouched_without_an_attack_card():
    game, ai = saved_position(["Evade", "Evade", "Fight Or Flight"], ONLY_SCHEMES[:1])
    assert not ai.reach_dests(game, game.hero(BOT), {3, 1, 14})


def test_a_second_fight_or_flight_is_not_stacked_for_nothing():
    game, ai = saved_position(SAVED_HAND + ["Fight Or Flight", "Fight Or Flight"], [])
    first = next(c for c in game.players[BOT].hand if c.title == "Fight Or Flight")
    game.play_scheme(BOT, game.hero(BOT), first)
    game.actions_left = 2
    assert game.fx.ongoing_card_id(BOT) == first.card_id
    ranked = ai.candidates(game, Model(game, BOT))
    second = [a for a in ranked if a.kind == "scheme"]
    best_other = max(a.total for a in ranked if a.kind != "scheme")
    assert all(a.total < best_other for a in second), "the second copy only replaces the ONGOING in play"


# ---------------------------------------------------------------------- the chat
def liz_turn(tmp_path, monkeypatch, plans, hand, discard=()):
    session, table, game, fake, cfg, client = d3_build(tmp_path, "liz-sherman", "hellboy", hand)
    if discard:
        to_bot_discard(session, table, game, *discard)
    sequence = iter(plans(game))
    monkeypatch.setattr(session.ai, "plan", lambda g: next(sequence))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    game.turn, game.actions_left, session.bot_stage = BOT, 2, None
    session.messages = []
    return session, table, game, client


def test_the_chat_says_maniobra_and_an_empty_scheme_says_so_before_anything_else(tmp_path, monkeypatch):
    def plans(game):
        sc = [c for c in game.players[BOT].hand if c.title == "Searing Clarity"]
        pos = game.hero(BOT).pos
        return [Act("scheme", 0, "liz", "", sc[0]), Act("scheme", 0, "liz", "", sc[1]),
                Act("maneuver", moves={"liz": pos}), Act("maneuver", moves={"liz": pos})]
    session, table, game, client = liz_turn(tmp_path, monkeypatch, plans,
                                            ["Searing Clarity", "Searing Clarity", "Evade", "Feint"], ["Pyrotechnics"])
    session._bot_continue()
    lines = list(session.messages)
    client.close()
    assert not any("maneuver" in m or "El bot hace" in m for m in lines)
    played = [i for i, m in enumerate(lines) if m.startswith("El bot juega Searing Clarity")]
    shuffle = [i for i, m in enumerate(lines) if m.startswith("El bot baraja")]
    assert len(played) == 2 and len(shuffle) == 1
    assert played[0] < shuffle[0] < played[1], "the play is said first, then the shuffle it causes"
    assert lines[played[1]] == "El bot juega Searing Clarity: sin efecto, solo recupera la accion."
    maneuvers = [m for m in lines if m.startswith("El bot maniobra")]
    assert maneuvers == ["El bot maniobra y roba, sin mover a nadie."] * 2


def test_a_wildfire_return_is_said_once(tmp_path, monkeypatch):
    from test_liz_wildfire_scene import liz_session, said, start_bot_turn
    session, table, game, fake, cfg, card_back, client = liz_session(tmp_path, monkeypatch, burning=True)
    start_bot_turn(session, game)
    lines = list(session.messages)
    client.close()
    assert sum("vuelve a la mano" in t for t in lines) == 1
    assert not any(t.startswith("El bot recupera") for t in lines)
    assert any("(fuego)" in t for t in lines), "the parenthesis reaches the table"


def test_no_chat_line_loses_a_character_on_the_way_to_the_table(tmp_path, monkeypatch):
    """Every line the bot says goes through the broadcast filter whole: parentheses and commas included."""
    from sparring.tts import lua

    def plans(game):
        pos = game.hero(BOT).pos
        return [Act("maneuver", moves={"liz": pos}), Act("maneuver", moves={"liz": pos})]
    session, table, game, client = liz_turn(tmp_path, monkeypatch, plans, ["Evade", "Feint"])
    session._bot_continue()
    client.close()
    for line in session.messages:
        assert "".join(lua.ascii_text(line)) .replace(" ", "") == _ascii(line).replace(" ", ""), line


def _ascii(text: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
