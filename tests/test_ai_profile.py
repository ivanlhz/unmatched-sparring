"""Fighter AI profile (sparring/ai_profile.py): computed when a hero is imported, weighed by the bot against the state."""
import copy
import dataclasses
import json

import pytest

from conftest import Scripted
from sparring.ai_medusa import MedusaAI, Model, fighter_profile, kill_value, protect_factor, stake
from sparring.ai_profile import compute_ai_profile
from sparring.heroes import HEROES_DIR, load_hero, parse_hero
from sparring.state import Game
from test_ai_hellboy_bot import BABA, hellboy_vs_baba

JACKALOPE_TRAP = {"op": "damage", "target": {"side": "enemy", "kind": "hero"}, "amount": 2}


def bigfoot_like():
    """A hero whose sidekick owns a scheme (x3) that deals 2 damage to an enemy hero."""
    def card(i, title, fighter, kind, value):
        return {"idx": i, "title": title, "fighter": fighter, "type": kind, "value": value, "boost": 1, "text": "", "tags": []}
    cards = [card(i, "Punch", "Bigfoot", "attack", 3) for i in range(27)]
    cards += [card(27 + i, "Jackalope Trap", "Jackalope", "scheme", None) for i in range(3)]
    hero = {"slug": "bigfoot-like", "name": "Bigfoot", "fid": "bigfoot", "hp": 15, "move": 2, "attack": "melee",
            "sidekicks": [{"fid": "jackalope", "name": "Jackalope", "count": 1, "hp": 1, "move": 3, "attack": "melee"}],
            "deck": {"card_base": 100, "cards": cards}}
    effects = {"cards": [{"title": "Jackalope Trap", "copies": 3, "effects": {"scheme": [JACKALOPE_TRAP]}}]}
    return hero, effects


def test_import_gives_the_jackalope_the_value_of_its_exclusive_scheme():
    hero, effects = bigfoot_like()
    prof = compute_ai_profile(hero, effects)["jackalope"]
    [trap] = prof["exclusive"]
    assert trap["title"] == "Jackalope Trap" and trap["copies"] == 3
    assert trap["impact"] == pytest.approx(0.3 + 2.0)      # a dead card plus 2 damage to an enemy hero
    assert prof["role"] == "keep_away"                     # 1 hit point, melee
    assert compute_ai_profile(hero, effects, {"jackalope": "striker"})["jackalope"]["role"] == "striker"
    assert compute_ai_profile(hero, None)["jackalope"]["exclusive"][0]["impact"] == pytest.approx(0.3)
    with pytest.raises(ValueError):
        compute_ai_profile(hero, effects, {"jackalope": "tank"})


def test_a_prized_sidekick_is_hunted_while_its_copies_remain_and_less_once_they_are_discarded(bprd):
    g = hellboy_vs_baba(bprd, ["Service Pistol"])
    koschei = g.fighters["koschei"]
    koschei.alive, koschei.pos, koschei.hp = True, 21, 3
    baba = g.players[1].hero
    prof = copy.deepcopy(baba.ai_profile)
    prof["koschei"]["exclusive"], prof["koschei"]["requires_alive"] = [], []
    g.players[1].hero = dataclasses.replace(baba, ai_profile=prof)
    plain = kill_value(g, koschei)
    prof = copy.deepcopy(prof)
    prof["koschei"]["exclusive"] = [{"title": "Read The Bones", "type": "scheme", "copies": 3, "impact": 2.3}]
    g.players[1].hero = dataclasses.replace(baba, ai_profile=prof)
    full = kill_value(g, koschei)
    assert full > plain
    assert stake(g, koschei, prof["koschei"]) == pytest.approx(3 * 2.3)
    discard = g.players[1].discard
    for c in [c for c in g.players[1].full_set if c.title == "Read The Bones"]:
        discard.append(c)
    assert kill_value(g, koschei) < full
    assert stake(g, koschei, prof["koschei"]) == 0
    # the same blow is worth more against it than against the same piece once its cards are gone
    ai, hb = MedusaAI(0), g.fighters["hellboy"]
    hand = g.players[0].hand
    discard.clear()
    prized = ai.attack_eval(g, Model(g, 0), hb, koschei, hand[0])[0]
    discard.extend(c for c in g.players[1].full_set if c.title == "Read The Bones")
    spent = ai.attack_eval(g, Model(g, 0), hb, koschei, hand[0])[0]
    assert prized > spent


def test_the_last_piece_of_a_group_carries_the_whole_stake():
    g = Game.new(__import__("sparring.board", fromlist=["Board"]).Board.load("bprd-hq"), 1,
                 {0: Scripted(), 1: Scripted()}, bot_player=1, heroes=("medusa", "abe-sapien"))
    harpies = [f for f in g.own(1) if f.name == "Harpy"]
    prof = fighter_profile(g, harpies[0])
    three = stake(g, harpies[0], prof)
    for h in harpies[1:]:
        h.alive = False
    assert stake(g, harpies[0], prof) == pytest.approx(three * 9)


def test_koschei_is_worth_fateful_bargains():
    prof = load_hero("baba-yaga").fighter_profile("Koschei")
    sources = {r["source"]: r for r in prof["requires_alive"]}
    assert sources["ability:fateful_bargains"]["impact"] > 0 and sources["ability:fateful_bargains"]["kind"] == "ability"
    assert "Bound In Blood" in sources and sources["Bound In Blood"]["copies"] == 2
    assert [e["title"] for e in prof["exclusive"]] == ["Death's Release"]


def test_lobster_steps_into_range_to_shoot_when_the_rival_cannot_punish(bprd):
    g = hellboy_vs_baba(bprd, ["Service Pistol", "B.P.R.D. Training"], hellboy=5, lobster=6)
    g.players[1].hand.clear()
    lobster = g.fighters["lobster"]
    assert not bprd.can_reach_target(lobster.pos, BABA, True)
    act = MedusaAI(0).plan(g)
    assert act.kind == "maneuver"
    assert bprd.can_reach_target(act.moves["lobster"], BABA, True)


def test_roles_of_the_current_heroes():
    assert load_hero("hellboy").fighter_profile("Lobster Johnson")["role"] == "striker"
    assert load_hero("medusa").fighter_profile("Harpy")["role"] == "keep_away"
    assert load_hero("abe-sapien").fighter_profile("B.P.R.D. Agent")["role"] == "striker"
    assert load_hero("baba-yaga").fighter_profile("Koschei")["role"] == "striker"


def test_the_harpies_keep_their_kiting_score(bprd):
    g = Game.new(bprd, 2, {0: Scripted(), 1: Scripted()}, bot_player=0, heroes=("medusa", "hellboy"))
    ai, harpy = MedusaAI(0), next(f for f in g.own(0) if f.name == "Harpy")
    foes = g.foes(0)
    for dest in sorted(bprd.spaces):
        near = min(bprd.distance(dest, e.pos) for e in foes)
        assert ai.harpy_score(g, harpy, dest) == -0.25 * near + (0.6 if near == 1 else 0.0)


def test_generated_profiles_are_part_of_the_versioned_herodef():
    for slug in ("medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"):
        raw = json.loads((HEROES_DIR / f"{slug}.json").read_text(encoding="utf-8"))
        assert set(raw["ai_profile"]) == {f.fid.rstrip("123") for f in load_hero(slug).fighters()}
        parse_hero(raw)
