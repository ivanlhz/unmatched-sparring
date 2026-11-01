"""The bot really uses the Harpy cards and moves and attacks with all three Harpies."""
from collections import Counter

from sparring.ai_medusa import MedusaAI
from sparring.cards import load_medusa_deck
from sparring.sim import play
from sparring.state import Game

HARPY_TITLES = {c.title for c in load_medusa_deck() if c.fighter == "Harpy"}


def test_there_are_five_harpy_only_cards():
    assert sum(c.fighter == "Harpy" for c in load_medusa_deck()) == 5


def _instrumented_games(monkeypatch, seeds):
    log = Counter()
    real_attack, real_maneuver = Game.attack, Game.maneuver

    def attack(self, attacker, target, card, def_card="ask", values=(0, 0)):
        res = real_attack(self, attacker, target, card, def_card, values)
        for fighter, c in ((attacker, res.atk_card), (target, res.def_card)):
            if c is not None and c.fighter == "Harpy":
                assert fighter.name == "Harpy", f"{c.title} played by {fighter.fid}"
                log[("harpy_card", "attack" if fighter is attacker else "defense")] += 1
        if attacker.owner == 0:
            log[("attacker", attacker.fid)] += 1
            if card.fighter == "Harpy":
                log[("harpy_attack", attacker.fid)] += 1
        return res

    def maneuver(self, player, moves, boost_card=None):
        before = {f.fid: f.pos for f in self.own(player)}
        real_maneuver(self, player, moves, boost_card)
        if player == 0:
            for f in self.own(player):
                if f.pos != before[f.fid]:
                    log[("moved", f.fid)] += 1

    monkeypatch.setattr(Game, "attack", attack)
    monkeypatch.setattr(Game, "maneuver", maneuver)
    for seed in seeds:
        play(seed, medusa=MedusaAI(0))
    return log


def test_bot_plays_harpy_cards_only_with_harpies_and_uses_all_three_harpies(monkeypatch):
    log = _instrumented_games(monkeypatch, range(12))
    assert log[("harpy_card", "attack")] > 0, "the bot never attacks with Harpy cards"
    for h in ("harpy1", "harpy2", "harpy3"):
        assert log[("moved", h)] > 0, f"{h} never moves in maneuvers"
        assert log[("attacker", h)] > 0, f"{h} never attacks"
    assert log[("attacker", "medusa")] > 0


def test_harpies_defend_only_with_cards_a_harpy_may_play(monkeypatch):
    """When a Harpy is attacked, the bot's defense is a legal card for a Harpy (never one exclusive to Medusa)."""
    log = Counter()
    real = MedusaAI.choose_defense

    def choose_defense(self, game, attacker, target):
        card = real(self, game, attacker, target)
        if target.name == "Harpy":
            log["harpy_targeted"] += 1
            if card is not None:
                assert card.usable_by("Harpy"), f"{card.title} cannot be played by a Harpy"
                assert card.can_defend
                log["harpy_defended"] += 1
                if card.fighter == "Harpy":
                    log["harpy_card_defense"] += 1
        return card

    monkeypatch.setattr(MedusaAI, "choose_defense", choose_defense)
    for seed in range(12):
        play(seed, medusa=MedusaAI(0))
    assert log["harpy_targeted"] > 0 and log["harpy_defended"] > 0
