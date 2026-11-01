"""The game is built from HeroDef (F07 step 2) and the known rival hand (KnownHand) is discounted by itself."""
import json

import pytest

from sparring import persist, play
from sparring.heroes import HeroDataError, available_heroes, load_hero
from sparring.state import ANUNG, DETECTIVE, Game, KnownHand, RuleError
from conftest import give, place


def test_default_game_is_medusa_bot_vs_hellboy_human_with_the_same_fighters_as_before(bprd):
    g = Game.new(bprd, seed=3, controllers={})
    assert [(fid, f.owner, f.name, f.hp, f.move, f.ranged) for fid, f in g.fighters.items()] == [
        ("medusa", 0, "Medusa", 16, 3, True), ("harpy1", 0, "Harpy", 1, 3, False),
        ("harpy2", 0, "Harpy", 1, 3, False), ("harpy3", 0, "Harpy", 1, 3, False),
        ("hellboy", 1, "Hellboy", 18, 2, False), ("lobster", 1, "Lobster Johnson", 6, 2, True)]
    assert g.hero_def(0).slug == "medusa" and g.hero_def(1).slug == "hellboy"
    assert g.players[0].hero_name == "Medusa" and g.players[1].hero_name == "Hellboy"
    assert len(g.players[0].full_set) == 30 and len(g.players[1].full_set) == 30


def test_heroes_can_be_swapped_and_the_bot_can_sit_second(bprd):
    g = Game.new(bprd, seed=1, controllers={}, bot_player=1, heroes=("hellboy", "medusa"))
    assert g.hero(1).name == "Hellboy" and g.hero(0).name == "Medusa"
    assert {f.fid for f in g.own(1)} == {"hellboy", "lobster"}
    assert g.form(1) == DETECTIVE and g.form(0) is None
    assert g.start_spaces == {1: bprd.starts["1"], 0: bprd.starts["2"]}
    assert all(c.card_id >= 19700 for c in g.players[1].full_set)


def test_a_hero_without_a_card_sheet_or_the_same_hero_twice_cannot_build_a_game(bprd):
    sheetless = [s for s in available_heroes() if load_hero(s).card_base is None]   # those that do not have a sheet yet
    if sheetless:
        with pytest.raises(HeroDataError, match=f"{sheetless[0]}: deck without a CardID sheet"):
            Game.new(bprd, seed=1, controllers={}, heroes=(sheetless[0], "hellboy"))
    with pytest.raises(RuleError, match="mismo heroe"):
        Game.new(bprd, seed=1, controllers={}, heroes=("medusa", "medusa"))
    with pytest.raises(HeroDataError, match="no HeroDef for 'dracula'"):
        Game.new(bprd, seed=1, controllers={}, heroes=("medusa", "dracula"))


def test_form_counter_and_attack_bonus_come_from_the_hero_data(game):
    assert game.form(1) == DETECTIVE and game.destiny_count(1) == 0 and game.counter(1, "destiny") == 0
    game.players[1].discard = [c for c in game.players[1].full_set if c.destiny][:6]
    assert game.form(1) == ANUNG and game.destiny_count(1) == 6
    assert game.attack_bonus(game.fighters["hellboy"]) == 2
    assert game.attack_bonus(game.fighters["lobster"]) == 0      # the passive is the hero's only
    assert game.attack_bonus(game.fighters["medusa"]) == 0 and game.destiny_count(0) == 0
    game.players[1].discard.pop()
    assert game.form(1) == DETECTIVE and game.attack_bonus(game.fighters["hellboy"]) == 0


def test_anung_bonus_shows_in_the_combat_breakdown(game, ctl):
    game.players[1].discard = [c for c in game.players[1].full_set if c.destiny][:6]
    place(game, hellboy=1, medusa=2)
    card = give(game, 1, "Service Pistol")
    game.turn = 1
    res = game.attack(game.fighters["hellboy"], game.fighters["medusa"], card, None)
    assert res.atk_value == 7 and res.atk_parts == ["Service Pistol (5)", "ANUNG UN RAMA (+2)"]


def test_play_config_reads_bot_hero_and_human_hero_with_defaults(tmp_path):
    raw = json.loads(play.DEFAULT_CONFIG.read_text(encoding="utf-8"))
    cfg = play.PlayConfig(raw, play.Board.load("bprd-hq"), [])
    assert cfg.heroes == ("medusa", "hellboy")
    assert cfg.fighter_ids == ["medusa", "harpy1", "harpy2", "harpy3", "hellboy", "lobster"]
    del raw["bot_hero"], raw["human_hero"]
    assert play.PlayConfig(raw, cfg.board, []).heroes == ("medusa", "hellboy")
    raw["bot_hero"], raw["human_hero"] = "hellboy", "medusa"
    cfg2 = play.PlayConfig(raw, cfg.board, [])
    assert cfg2.fighter_ids == ["hellboy", "lobster", "medusa", "harpy1", "harpy2", "harpy3"]
    g = play.build_game(cfg2, "human", 5)
    assert g.hero(play.BOT).name == "Hellboy" and g.hero(play.HUMAN).name == "Medusa"
    assert {c.card_id for c in g.players[play.BOT].full_set} == {19700 + i for i in range(30)}


# ---------- known rival hand ----------
def test_known_hand_is_only_what_was_seen_and_forgets_one_copy_per_card_that_leaves(game):
    g = game
    ss1, ss2 = give(g, 1, "Second Shot", 0), give(g, 1, "Second Shot", 1)
    pistol = give(g, 1, "Service Pistol")
    assert g.hidden_hand(0) == ([], g.hidden_hand(0)[1], 3)     # nothing seen: the 3 cards are unknown
    g.observe_hand(0, [ss1, ss2, pistol])
    known, pool, missing = g.hidden_hand(0)
    assert [c.title for c in known] == ["Second Shot", "Second Shot", "Service Pistol"] and missing == 0
    assert pistol not in pool and ss1 not in pool and ss2 not in pool
    assert g.players[0].known.turn_no == g.turn_no
    g.discard_card(1, ss1)                                      # one copy leaves: the other still counts
    assert [c.title for c in g.hidden_hand(0)[0]] == ["Second Shot", "Service Pistol"]
    assert ss1 not in g.hidden_hand(0)[1]                       # it is already in the discard: not a candidate either
    g.discard_card(1, pistol)
    g.discard_card(1, ss2)
    assert g.players[0].known.seen == [] and g.players[0].known.turn_no is None


def test_cards_played_in_combat_leave_the_known_hand(game, ctl):
    g = game
    place(g, hellboy=1, medusa=2)
    atk = give(g, 1, "Service Pistol")
    deff = give(g, 0, "Hiss and Slither")
    g.observe_hand(0, [atk])
    g.observe_hand(1, [deff])
    g.turn = 1
    g.attack(g.fighters["hellboy"], g.fighters["medusa"], atk, deff)
    assert g.players[0].known.seen == [] and g.players[1].known.seen == []


def test_a_fresh_look_replaces_the_old_one_and_unknown_cards_are_ignored(game):
    g = game
    a = give(g, 1, "Pancakes!")
    g.observe_hand(0, [a])
    g.players[1].hand.remove(a)
    # KnownHand never reads the rival hand to check (Ivan's rule): every route that takes a card out of a hand tells it
    assert g.hidden_hand(0)[0] == [a]
    g.card_left_hand(1, a)
    assert g.hidden_hand(0)[0] == []
    assert g.players[0].known.forget(a) is False
    b = give(g, 1, "Excalibur")
    g.observe_hand(0, [b])
    assert g.players[0].known.seen == [b.card_id]
    g.observe_hand(0, [])                                        # an empty hand seen: nothing to remember
    assert g.players[0].known == KnownHand([], None)
    g.observe_hand(0, [b])
    g.players[0].known.clear()
    assert g.hidden_hand(0)[0] == []


def test_hidden_hand_drops_seen_cards_that_reached_the_discard_without_the_hook(game):
    g = game
    a, b = give(g, 1, "Excalibur"), give(g, 1, "Pancakes!")
    g.observe_hand(0, [a, b])
    g.players[1].hand.remove(a)
    g.players[1].discard.append(a)                               # moved by hand, as the table reconciliation does
    known, pool, missing = g.hidden_hand(0)
    assert known == [b] and a not in pool and missing == 0
    assert g.players[0].known.seen == [a.card_id, b.card_id]     # what was remembered is not touched: it is only filtered when queried


def test_known_hand_survives_clone_and_save_and_the_save_format_is_untouched_when_empty(game, bprd):
    g = game
    assert "known" not in persist.game_to_dict(g)["players"][0]
    a = give(g, 1, "Excalibur")
    g.observe_hand(0, [a])
    c = g.clone()
    c.discard_card(1, a)
    assert g.players[0].known.seen == [a.card_id] and c.players[0].known.seen == []
    d = persist.game_to_dict(g)
    assert d["players"][0]["known"] == {"seen": [a.card_id], "turn_no": g.turn_no} and "known" not in d["players"][1]
    fresh = Game.new(bprd, seed=0, controllers={})
    persist.apply_game(fresh, json.loads(json.dumps(d)))
    assert fresh.players[0].known == KnownHand([a.card_id], g.turn_no)
