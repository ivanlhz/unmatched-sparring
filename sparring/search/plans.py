"""Compare the tree's action with pressure lines that can attack this turn.

All continuations see the same sampled deal and play through the rival's reply. The first
action is fixed before sampling. The follow-up uses only cards available after that action.
"""
from __future__ import annotations

import random
import time

from ..ai_medusa import MedusaAI, boost_effect_value
from .adapter import EngineState, by_title, sidekick_plan

PLAN_SAMPLES = 16
MAX_APPROACHES = 3
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


def pressure_actions(root, seed, deadline):
    """A legal attack, or a short list of distinct ways to maneuver and attack."""
    state = root.clone()
    state.determinize(root.observer, random.Random(seed))
    blow, _ = best_blow(state)
    if blow:
        return [blow]
    if state.game.paid_actions < 2:
        return []
    p = state.game.turn
    hand = state.game.players[p].hand
    moves = [m for m in state.legal_moves() if m[0] == "maneuver"]
    candidates = []
    seen, free_ends = set(), set()
    for move in moves:
        if deadline is not None and time.perf_counter() >= deadline:
            break
        boost = by_title(hand, move[1]) if move[1] is not None else None
        boost_effect = boost_effect_value(state.game, p, boost) if boost else 0
        titles = {c.title for c in hand if c != boost and c.can_attack}
        if not titles:
            continue
        moved = state.clone()
        moved.game.rng = random.Random(seed)
        moved.apply(move)
        if moved.phase != "maneuver_place":
            continue
        hero = moved.game.hero(p)
        # Include routes that the end-of-turn positioning filter may have dropped.
        placements = set(moved.legal_moves())
        for dest in moved._hero_options(hero) & moved._striking_spots(p):
            placements.update(("place", dest, policy) for policy in moved._policies(p))
        for placement in sorted(placements):
            if deadline is not None and time.perf_counter() >= deadline:
                break
            _, dest, policy = placement
            side = sidekick_plan(moved.game, p, moved._extra(), policy, hero_dest=dest)
            key = (move, dest, side)
            if key in seen:
                continue
            seen.add(key)
            after = moved.clone()
            after.game.rng = random.Random(seed)
            after.apply(placement)
            if after.is_terminal() or after.game.turn != p or after.phase != "action":
                continue
            blow, strength = best_blow(after, titles)
            if not blow:
                continue
            position = (dest, side)
            end = (position, tuple(sorted(after.game.counters(p).items())))
            if boost is None:
                free_ends.add(end)
            elif end in free_ends and boost_effect == 0:
                continue
            # Rank the position after paying for the attack, without credit for the unknown draw.
            remaining = after.game.players[p].hand
            attack_card = by_title(remaining, blow[1][2])
            remaining[:] = [card for card in remaining if card in hand and card != attack_card]
            damage, lethal = after.threat(p, urgent=True)
            candidates.append(((strength - 0.5 * int(boost is not None) - 2 * damage - 4 * lethal,
                                -lethal, -damage), (move, placement), position))
    return _shortlist_approaches(candidates)


def _shortlist_approaches(candidates):
    ranked = sorted(candidates, key=lambda candidate: candidate[0], reverse=True)
    if not ranked:
        return []
    # Keep the best free route and the best boosted route, favoring a different position
    # for the latter. Fill any remaining slot with a different arrangement of fighters.
    free = next((entry for entry in ranked if entry[1][0][1] is None), None)
    boosted = [entry for entry in ranked if entry[1][0][1] is not None]
    first_boosted = next((entry for entry in boosted if free is None or entry[2] != free[2]),
                         boosted[0] if boosted else None)
    kept = [entry for entry in (free, first_boosted) if entry is not None]
    positions = {entry[2] for entry in kept}
    for entry in ranked:
        if len(kept) >= MAX_APPROACHES:
            break
        if entry[2] not in positions:
            kept.append(entry)
            positions.add(entry[2])
    kept.sort(key=lambda entry: entry[0], reverse=True)
    return [line for _, line, _ in kept]


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
        if move := sample.lethal_reply():
            sample.apply(move)
            continue
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
    approaches = pressure_actions(root, config.seed, deadline)
    if not approaches:
        return chosen, None
    pressure = approaches[0]
    lines = {"tree": chosen}
    for i, approach in enumerate(approaches, 1):
        if list(approach) != chosen:
            lines["pressure" if i == 1 else f"pressure_{i}"] = approach
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
        **({"pressure_lines": {name: line for name, line in lines.items() if name.startswith("pressure")}}
           if len(approaches) > 1 else {}),
    }
