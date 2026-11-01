import pytest

from sparring.cards import HELLBOY_BASE, MEDUSA_BASE, load_hellboy_deck, load_medusa_deck
from sparring.state import ANUNG, DETECTIVE, RuleError
from conftest import give, place


def setup(game, med=0, hb=1):
    """Medusa on `med`, Hellboy on `hb` (adjacent by default), the rest far away."""
    place(game, medusa=med, hellboy=hb, harpy1=20, harpy2=21, harpy3=22, lobster=27)
    return game.fighters["medusa"], game.fighters["hellboy"]


def fill_destiny(game, n):
    destiny = [c for c in game.players[1].full_set if c.destiny]
    game.players[1].discard = destiny[:n]


def test_data_hellboy_cards():
    deck = load_hellboy_deck()
    assert len(deck) == 30
    by = {c.title: c for c in deck}
    assert by["Excalibur"].value == 6 and by["Excalibur"].boost == 3 and by["Excalibur"].destiny
    assert all(c.fighter == "Lobster Johnson" for c in deck if c.title in ("Second Shot", "Posthumous Power"))
    assert by["Pancakes!"].is_scheme and by["Pancakes!"].value is None
    assert by["On Earth As It Is In Hell"].type == "defense"
    assert sum(c.destiny for c in deck) == 11
    assert deck[5].card_id == HELLBOY_BASE + 5
    assert len(load_medusa_deck()) == 30 and load_medusa_deck()[0].card_id == MEDUSA_BASE


def test_card_restriction(game):
    med, hb = setup(game)
    hounds = give(game, 0, "The Hounds of Mighty Zeus")
    ss = give(game, 0, "Second Shot")
    with pytest.raises(RuleError):
        game.attack(med, hb, hounds)  # Harpy card played by Medusa
    place(game, harpy1=2)
    harpy = game.fighters["harpy1"]
    with pytest.raises(RuleError):
        game.attack(harpy, hb, ss)  # Medusa card played by a Harpy
    place(game, harpy1=0, medusa=2)
    game.attack(harpy, hb, hounds, def_card=None)


def test_defense_restriction(game):
    med, hb = setup(game)
    ss = give(game, 0, "Second Shot")
    lobster_card = give(game, 1, "Second Shot")
    with pytest.raises(RuleError):
        game.attack(med, hb, ss, def_card=lobster_card)  # neither defense nor versatile


def test_defender_card_must_match_fighter(game):
    med, hb = setup(game)
    hiss = give(game, 0, "Hiss and Slither")
    hb_atk = give(game, 1, "Service Pistol")
    place(game, harpy1=2, hellboy=4, medusa=3)
    game.turn = 1
    game.begin_turn()
    with pytest.raises(RuleError):
        game.attack(hb, game.fighters["harpy1"], hb_atk, def_card=hiss)  # Hiss is Medusa's only


def test_damage_and_winner(game):
    med, hb = setup(game)
    ss = give(game, 0, "Second Shot")
    d = give(game, 1, "Planned Recklessness")
    r = game.attack(med, hb, ss, def_card=d)
    assert r.damage == 0 and not r.attacker_won and hb.hp == 18
    game.begin_turn()
    ss2 = give(game, 0, "Second Shot", 1)
    r = game.attack(med, hb, ss2, def_card=None)
    assert r.damage == 3 and r.attacker_won and hb.hp == 15


def test_second_shot_boost(game, ctl):
    med, hb = setup(game)
    ss = give(game, 0, "Second Shot")
    gaze = give(game, 0, "Gaze of Stone")
    ctl[0].boost = gaze
    ons = give(game, 1, "Glimpse Of Hell")  # 2, versatile, with no effect that cancels
    r = game.attack(med, hb, ss, def_card=ons)
    assert r.atk_value == 7 and r.damage == 5 and gaze in game.players[0].discard and r.boost_card is gaze


def test_second_shot_boost_not_offered_if_cancelled(game, ctl):
    med, hb = setup(game)
    ss = give(game, 0, "Second Shot")
    gaze = give(game, 0, "Gaze of Stone")
    ctl[0].boost = gaze
    d = give(game, 1, "Planned Recklessness")  # detective: cancels effects
    r = game.attack(med, hb, ss, def_card=d)
    assert "atk" in r.cancelled and r.atk_value == 3 and gaze in game.players[0].hand


def test_gaze_of_stone(game):
    med, hb = setup(game)
    gaze = give(game, 0, "Gaze of Stone")
    game.attack(med, hb, gaze, def_card=None)
    assert hb.hp == 18 - 2 - 8
    game.begin_turn()
    gaze2 = give(game, 0, "Gaze of Stone", 1)
    d = give(game, 1, "Glimpse Of Hell")  # 2 against 2: the attacker loses
    r = game.attack(med, hb, gaze2, def_card=d)
    assert not r.attacker_won and hb.hp == 8


def test_feint_cancels_rival_effects(game):
    med, hb = setup(game)
    feint = give(game, 0, "Feint")
    hb_atk = give(game, 1, "Right Hand Of Doom")
    game.turn = 1
    game.begin_turn()
    r = game.attack(hb, med, hb_atk, def_card=feint)
    assert r.human_effects == [] and r.cancelled == {"atk"}
    game.turn = 0
    game.begin_turn()
    feint2 = give(game, 0, "Feint", 1)
    d = give(game, 1, "Confront Any Demon or God")
    r = game.attack(med, hb, feint2, def_card=d)
    assert r.human_effects == [] and r.cancelled == {"def"}


def test_defender_resolves_first_in_same_window(game):
    med, hb = setup(game)
    feint = give(game, 0, "Feint")
    pr = give(game, 1, "Planned Recklessness")
    r = game.attack(med, hb, feint, def_card=pr)
    # the defender resolves first: Planned Recklessness (detective) cancels Feint and Feint then cancels nothing
    assert r.cancelled == {"atk"}
    assert any("Planned Recklessness" in e for e in r.human_effects)      # E2: the human's card, narrated to them
    assert any(s["name"] == "immune_to_effect_damage" and s["fid"] == "hellboy" for s in game.fx.statuses)


def test_planned_recklessness_blocks_effect_damage(game):
    med, hb = setup(game)
    fill_destiny(game, 6)
    assert game.form(1) == ANUNG
    gaze = give(game, 0, "Gaze of Stone")
    pr = give(game, 1, "Planned Recklessness")  # ANUNG: does not cancel, but protects from effect damage
    r = game.attack(med, hb, gaze, def_card=pr)
    assert r.cancelled == set() and r.damage == 0 and hb.hp == 18


def test_regroup_snipe_draws(game):
    med, hb = setup(game)
    reg = give(game, 0, "Regroup")
    n = len(game.players[0].hand)
    game.attack(med, hb, reg, def_card=None)  # wins: draws 2
    assert len(game.players[0].hand) == n - 1 + 2
    game.begin_turn()
    sn = give(game, 0, "Snipe")
    d = give(game, 1, "Glimpse Of Hell")
    n = len(game.players[0].hand)
    game.attack(med, hb, sn, def_card=d)  # Snipe always draws 1
    assert len(game.players[0].hand) == n - 1 + 1
    game.begin_turn()
    reg2 = give(game, 0, "Regroup", 1)
    d3 = give(game, 1, "Glimpse Of Hell", 1)
    n = len(game.players[0].hand)
    game.attack(med, hb, reg2, def_card=d3)  # loses: draws 1
    assert len(game.players[0].hand) == n - 1 + 1


def test_dash_moves_after_combat(game, ctl):
    med, hb = setup(game)
    dash = give(game, 0, "Dash")
    target = min(game.legal_moves(med, 3) - {1})
    ctl[0].moves["medusa"] = target
    game.attack(med, hb, dash, def_card=None)
    assert med.pos == target


def test_hounds_moves_every_harpy(game, ctl):
    med, hb = setup(game)
    place(game, harpy1=2, harpy2=21)
    hounds = give(game, 0, "The Hounds of Mighty Zeus")
    h1, h2 = game.fighters["harpy1"], game.fighters["harpy2"]
    place(game, hellboy=4)
    d1 = min(game.legal_moves(h1, 3) - {0})
    d2 = min(game.legal_moves(h2, 3))
    ctl[0].moves = {"harpy1": d1, "harpy2": d2}
    game.attack(h1, hb, hounds, def_card=None)
    assert (h1.pos, h2.pos) == (d1, d2)


def test_clutching_claws_makes_opponent_discard(game, ctl):
    med, hb = setup(game)
    place(game, harpy1=2, hellboy=4)
    c = give(game, 0, "Clutching Claws")
    keep = give(game, 1, "Glimpse Of Hell")
    spare = give(game, 1, "Excalibur")
    ctl[1].discards = [spare]
    game.attack(game.fighters["harpy1"], hb, c, def_card=None)
    assert spare in game.players[1].discard and keep in game.players[1].hand


def test_hiss_and_slither_defense_makes_opponent_discard(game, ctl):
    med, hb = setup(game)
    hiss = give(game, 0, "Hiss and Slither")
    atk = give(game, 1, "Service Pistol")
    spare = give(game, 1, "Excalibur")
    ctl[1].discards = [spare]
    game.turn = 1
    game.begin_turn()
    r = game.attack(hb, med, atk, def_card=hiss)
    assert spare in game.players[1].discard and r.damage == 1


def test_momentary_glance(game):
    med, hb = setup(game)
    g = give(game, 0, "A Momentary Glance")
    far = game.fighters["lobster"]
    place(game, lobster=10)
    assert not game.board.share_zone(0, 10)
    with pytest.raises(RuleError):
        game.play_scheme(0, med, g, target=far)
    place(game, hellboy=4)
    game.play_scheme(0, med, g, target=hb)
    assert hb.hp == 16 and game.actions_left == 1 and g in game.players[0].discard


def test_winged_frenzy(game, ctl):
    med, hb = setup(game)
    place(game, hellboy=2)
    wf = give(game, 0, "Winged Frenzy")
    h2 = game.fighters["harpy2"]
    h2.alive, h2.pos, h2.hp = False, None, 0
    ctl[0].moves = {"medusa": 4}  # 0 -> 2 (Hellboy) -> 4 passing through the rival
    ctl[0].placement = 3
    game.play_scheme(0, med, wf)
    assert med.pos == 4
    assert h2.alive and h2.pos == 3 and h2.hp == 1


def test_forms_and_anung_bonus(game):
    med, hb = setup(game)
    fill_destiny(game, 5)
    assert game.form(1) == DETECTIVE
    fill_destiny(game, 6)
    assert game.form(1) == ANUNG
    game.turn = 1
    game.begin_turn()
    atk = give(game, 1, "Service Pistol")
    r = game.attack(hb, med, atk, def_card=None)
    assert r.atk_value == 7 and med.hp == 9


def test_on_earth_value_is_destiny_count(game):
    med, hb = setup(game)
    fill_destiny(game, 4)
    oe = give(game, 1, "On Earth As It Is In Hell")
    ss = give(game, 0, "Second Shot")
    r = game.attack(med, hb, ss, def_card=oe)
    assert r.def_value == 4 and r.damage == 0


def test_defeated_sidekick_removed_and_hero_ends_game(game):
    med, hb = setup(game)
    place(game, lobster=2)
    lob = game.fighters["lobster"]
    lob.hp = 1
    ss = give(game, 0, "Second Shot")
    game.attack(med, lob, ss, def_card=None)
    assert not lob.alive and lob.pos is None and game.winner is None
    hb.hp = 2
    game.begin_turn()
    ss2 = give(game, 0, "Second Shot", 1)
    game.attack(med, hb, ss2, def_card=None)
    assert game.winner == 0


def test_every_medusa_card_title_is_covered():
    titles = {c.title for c in load_medusa_deck()}
    assert titles == {"Second Shot", "Gaze of Stone", "Regroup", "Dash", "Snipe", "Feint",
                      "The Hounds of Mighty Zeus", "Clutching Claws", "Hiss and Slither",
                      "A Momentary Glance", "Winged Frenzy"}
