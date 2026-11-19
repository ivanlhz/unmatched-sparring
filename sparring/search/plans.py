"""Compare the tree's action with a line that puts immediate pressure on the rival hero.

Both continuations see the same sampled deal and play through the rival's reply. The first
action is fixed before sampling. The follow-up uses only cards available after that action.
"""
from __future__ import annotations

import random
import time

from ..ai_medusa import MedusaAI
from .adapter import EngineState, by_title, sidekick_plan

PLAN_SAMPLES = 16
GAIN_SIGMAS = 1.65       # one-sided 95% on the paired gain over the tree's line


def best_blow(state, allowed=None):
    game = state.game
    p = game.turn
    scorer = MedusaAI(p)
    best, value = None, float("-inf")
    for attack in state._attack_moves(p):
        fighter, target = (game.fighters[fid] for fid in attack[1:])
        for title in state._attack_titles(p, fighter, target):
            if allowed is not None and title not in allowed:
                continue
            card = by_title(game.players[p].hand, title)
            strength = scorer.card_value(game, fighter, target, card) + game.attack_bonus(fighter, target)
            score = min(target.hp, strength) + float(target.hero)
            if score > value:
                best, value = (attack, ("attack_card", fighter.fid, title)), score
    return best, value


def pressure_action(root, seed, deadline):
    """A legal attack, or an approach opening one with a card already held."""
    state = root.clone()
    state.determinize(root.observer, random.Random(seed))
    blow, _ = best_blow(state)
    if blow:
        return blow
    if state.game.paid_actions < 2:
        return None
    p = state.game.turn
    moves = [m for m in state.legal_moves() if m[0] == "maneuver"]
    for move in moves:  # the unboosted Maneuver comes first
        hand = list(state.game.players[p].hand)
        if move[1] is not None:
            hand.remove(by_title(hand, move[1]))
        titles = {c.title for c in hand if c.can_attack}
        if not titles:
            continue
        moved = state.clone()
        moved.apply(move)
        if moved.phase != "maneuver_place":
            continue
        best, rank = None, None
        for placement in moved.legal_moves():
            if deadline is not None and time.perf_counter() >= deadline:
                return None
            after = moved.clone()
            after.apply(placement)
            if after.is_terminal() or after.game.turn != p or after.phase != "action":
                continue
            blow, strength = best_blow(after, titles)
            if blow:
                key = (strength, -after.threat(p, urgent=True)[0])
                if rank is None or key > rank:
                    best, rank = (move, placement), key
        if best:
            return best
    return None


def apply_line(state, line):
    state.apply(line[0])
    # A unique attack card or placement may already have been resolved by the engine.
    if len(line) > 1 and state.phase == {"place": "maneuver_place", "attack_card": "attack_card"}[line[1][0]]:
        state.apply(line[1])


def withdraw_action(state):
    """Best unboosted cover after landing a hit, with the opponent about to take its turn."""
    move = ("maneuver", None)
    g, p = state.game, state.game.turn
    if not g.players[p].deck or move not in state.legal_moves():
        return None
    moved = state.clone()
    moved.apply(move)
    if moved.phase != "maneuver_place":
        return (move,)
    best, value = None, float("-inf")
    for place in moved.legal_moves():
        _, d, policy = place
        preview = moved.clone()
        board = preview.game
        hero = board.hero(p)
        positions = sidekick_plan(board, p, preview._extra(), policy, hero_dest=d)
        hero.pos = d
        for fid, dest in positions:
            board.fighters[fid].pos = dest
        damage, lethal = preview.threat(p, urgent=True)
        score = -damage - lethal
        if score > value:
            best, value = (move, place), score
    return best


def continuation(sample, line, rng, turns, withdraw=False):
    start = sample.game.turn_no
    apply_line(sample, line)
    for _ in range(32):  # extra actions are legal; bound schemes that keep granting actions
        if sample.is_terminal() or sample.game.turn_no >= start + turns:
            break
        if sample.pending is None and sample.phase == "action":
            if withdraw and sample.game.turn_no == start:
                withdraw = False
                walk = withdraw_action(sample)
                if walk:
                    apply_line(sample, walk)
                    continue
            blow, _ = best_blow(sample)
            if blow:
                apply_line(sample, blow)
                continue
            if sample.game.turn_no == start and sample.game.actions_left > 0:
                walk = withdraw_action(sample)     # no blow this turn: the follow-up is the same unboosted walk to cover for every line, not a random move
                if walk:
                    apply_line(sample, walk)
                    continue
            if rng.random() < 0.4:
                schemes = [m for m in sample.legal_moves() if m[0] == "scheme"]
                if schemes:
                    sample.apply(rng.choice(schemes))
                    continue
        if sample.pending is not None:
            # A defender sees the attacker, never the committed face-down card.
            defenses = sample._defend_moves()[1:]
            if defenses and rng.random() < 0.8:
                hand = sample.game.players[sample.player_to_move()].hand
                sample.apply(max(defenses, key=lambda m: by_title(hand, m[1]).value))
                continue
        sample.apply(sample.rollout_move(rng))
    return sample.evaluate(sample.observer)


def tree_preference(tree_values, chosen, line):
    """How much the tree's root statistics prefer its own first action over the first action of `line` (0 when either is unvisited or they coincide)."""
    if not tree_values:
        return 0.0
    own, other = tree_values.get(tuple(chosen[0])), tree_values.get(tuple(line[0]))
    if own is None or other is None:
        return 0.0
    return max(0.0, own - other)


def compare_plans(root: EngineState, chosen, config, deadline, tree_values=None):
    if chosen[0][0] not in ("maneuver", "attack", "scheme"):
        return chosen, None
    if deadline is not None and time.perf_counter() >= deadline:
        return chosen, None
    pressure = pressure_action(root, config.seed, deadline)
    if not pressure:
        return chosen, None
    lines = {"tree": chosen}
    if list(pressure) != chosen:
        lines["pressure"] = pressure
    if pressure[0][0] == "attack" and root.game.paid_actions >= 2:
        lines["hit_and_withdraw"] = pressure
    if len(lines) == 1:
        return chosen, None
    values = {name: [] for name in lines}
    rng = random.Random(config.seed)
    # If the bot is trailing with the shorter deck, delay is expensive. Include one
    # more exchange to see the cards and life the extra maneuvers will cost.
    g, me = root.game, root.observer
    trailing = g.hero(me).hp < g.hero(1 - me).hp
    short_deck = len(g.players[me].deck) < len(g.players[1 - me].deck)
    turns = 4 if trailing and short_deck else 2
    samples = 0
    for _ in range(PLAN_SAMPLES):
        if deadline is not None and time.perf_counter() >= deadline:
            break
        world = root.clone()
        world.determinize(root.observer, rng)
        seed = rng.getrandbits(64)
        for name, line in lines.items():
            trial = world.clone()
            # Game.clone shares its RNG. Give both alternatives the same independent
            # stream for shuffles and random card effects as well as for the policy.
            trial.game.rng = random.Random(seed)
            values[name].append(continuation(trial, line, random.Random(seed), turns, withdraw=name == "hit_and_withdraw"))
        samples += 1
    if not samples:
        return chosen, None
    scores = {name: sum(v) / samples for name, v in values.items()}
    # The samples are paired (same deal, same stream), so an alternative replaces the tree's action only when its mean gain
    # clears its own standard error: at 16 samples a fixed 0.01 margin picks noise (+0.05 for a plan that skipped the scheme drawing the only defence card).
    # The gain must also outweigh how much the tree itself preferred its action over the plan's first one: on 18/11 T15 the tree
    # rated Child of the Elder Blood 0.042 above the attack and the plans' +0.040 swapped it anyway (Cloak cancelled the attack).
    # On T9 the tree had the two within 0.003 and the swap gave the best blow of the game.
    selected = "tree"
    gains_report = {}
    for name in lines:
        if name == "tree" or samples < 4:
            continue
        gains = [a - b for a, b in zip(values[name], values["tree"])]
        mean = sum(gains) / samples
        error = (sum((x - mean) ** 2 for x in gains) / (samples - 1) / samples) ** 0.5
        preference = tree_preference(tree_values, chosen, lines[name])
        gains_report[name] = {"gain": round(mean, 4), "error": round(error, 4), "tree_preference": round(preference, 4)}
        if mean > preference + max(0.01, GAIN_SIGMAS * error) and (selected == "tree" or scores[name] > scores[selected]):
            selected = name
    return list(lines[selected]), {
        **scores, "samples": samples, "turns": turns, "gains": gains_report,
        "tree_line": chosen, "pressure_line": pressure, "selected": selected,
    }
