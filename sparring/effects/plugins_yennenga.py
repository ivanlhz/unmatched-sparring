"""Yennenga's plugins (docs/heroes/yennenga.md): `yennenga:surprise_volley` and the ability `yennenga:assign_damage`.

Both need her Archers, the two 2-life sidekicks of the HeroDef (name "Archer"): the first brings a defeated one back as the
attacker of the running combat, the second lets her owner hand them damage meant for her (see `assign_options`)."""
from __future__ import annotations

from .model import EffectError, load_effects
from .ops_core import OPS, plugin
from .select import defeated, space_options

ARCHER = "Archer"
ASSIGN = "yennenga:assign_damage"
RUN_KEY = "damage:def"                       # the flow's run that asks the assignment of the combat damage
VOLLEY_WHERE = {"zone_of": "opposing"}       # "a space in the opposing fighter's zone"


def defeated_archers(game, owner: int) -> list:
    """The owner's Archers that fell, in fighter id order."""
    return sorted((f for f in game.own(owner, alive_only=False) if f.name == ARCHER and not f.alive and defeated(game, f)),
                  key=lambda f: f.fid)


@plugin("yennenga:surprise_volley")
def _surprise_volley(run, game, spec):
    """Surprise Volley, IMMEDIATELY: "You may return a defeated Archer to a space in the opposing fighter's zone. If you do, that
    Archer is now the attacker. If not, gain 1 action." With a defeated Archer and a free space there the owner is asked; the Archer
    returns with its full life and takes the place of the attacker in this combat (what Smoke And Mirrors does for its swap)."""
    owner, flow = run.ctx.owner, getattr(run, "flow", None)
    back = defeated_archers(game, owner)
    if flow is not None and back and space_options(game, run, VOLLEY_WHERE) \
            and run.ask(game, "optional", owner, [True, False], 1, 1, "return a defeated Archer?")[0]:
        archer = back[0]
        run.bind("fighters", "returned", [archer.fid])
        OPS["revive"](run, game, {"op": "revive", "target": {"role": "$returned", "state": "defeated"}, "where": VOLLEY_WHERE, "hp": archer.max_hp, "chooser": "owner"})
        old = flow.att
        if archer.alive and flow.replace_combatant(old, archer):
            run.ctx.this_fid = archer.fid
            run.ctx.attacker_fid = archer.fid
        return
    OPS["gain_action"](run, game, {"op": "gain_action", "amount": 1})


# ---------------------------------------------------------------- the ability: damage handed to the Archers

def assigns_damage(game, fighter) -> bool:
    """`fighter` is a living hero whose effects file declares the passive `yennenga:assign_damage`."""
    if not fighter.hero or not fighter.alive or fighter.pos is None:
        return False
    slug = game.players[fighter.owner].hero.slug
    return slug in game.fx.dsl_heroes and any(p.get("kind") == "plugin" and p.get("plugin") == ASSIGN
                                             for p in load_effects(slug).passives)


def archers_in_zone(game, hero) -> list:
    """The Archers of the hero's owner that stand in a zone she shares, in fighter id order."""
    return sorted((f for f in game.zone_mates(hero) if f.owner == hero.owner and f.name == ARCHER), key=lambda f: f.fid)


def ask_shares(run, game, hero, damage: int, source: str, reserved: dict | None = None) -> dict[str, int]:
    """What each Archer takes of `damage` meant for `hero` (fighter id -> points, only the ones above 0). Her owner is asked once
    per Archer in her zone, in fighter id order: from 0 to the least of the damage still to place and the Archer's life.
    `reserved` (fighter id -> damage): what the same effect is about to do to an Archer itself, which its share must leave room for.
    Decisions are asked before anything is applied, so a paused run changes nothing."""
    owner, left, shares = hero.owner, int(damage), {}
    archers = archers_in_zone(game, hero)
    for i, archer in enumerate(archers):
        room = min(left, int(archer.hp - (reserved or {}).get(archer.fid, 0)))
        if room <= 0:
            continue
        got = run.ask(game, "amount", owner, list(range(room + 1)), 1, 1, f"damage to {archer.name}", assign=archer.fid,
                      fighter=hero.fid, left=left, damage=int(damage), source=source,
                      later=[a.fid for a in archers[i + 1:]])[0]
        if got:
            shares[archer.fid] = got
            left -= got
    return shares


def effect_shares(run, game, fighter, n, reserved: dict | None = None) -> list[tuple]:
    """(fighter, damage) pairs for `n` effect damage (already modified) aimed at `fighter`: the Archers' shares first, then what is left for the hero."""
    if not assigns_damage(game, fighter) or n < 1:
        return [(fighter, n)]
    shares = ask_shares(run, game, fighter, int(n), "effect", reserved)
    rest = n - sum(shares.values())
    return [(game.fighters[fid], k) for fid, k in shares.items()] + ([(fighter, rest)] if rest > 0 else [])


@plugin(ASSIGN)
def _assign_damage(run, game, spec):
    """The combat damage of the running flow (`combat_wait`): asks the shares and leaves them in `run.flags["assigned"]`."""
    args = spec.get("args")
    if not args:
        raise EffectError(f"{ASSIGN} is a passive of the hero: the damage code reads it, no card runs it")
    run.flags["assigned"] = ask_shares(run, game, game.fighters[args["fighter"]], args["amount"], "combat")


def combat_wait(flow, victim, damage):
    """Before the combat damage lands on `victim`: when it is Yennenga with Archers in her zone, her owner decides how much of it
    they take. Returns the Await of a paused decision (the human at the panel), else None; the answer waits in `flow.runs`."""
    game = flow.game
    if damage < 1 or not assigns_damage(game, victim) or not archers_in_zone(game, victim):
        return None
    if RUN_KEY not in flow.runs:
        from .ops_combat import default_choosers
        from .run import Ctx, EffectRun
        ops = [{"op": "plugin", "id": ASSIGN, "args": {"fighter": victim.fid, "amount": int(damage)}}]
        run = EffectRun(ops, Ctx(owner=victim.owner, this_fid=victim.fid, moment="damage", attacker_fid=flow.att.fid,
                                 defender_fid=flow.tgt.fid), label="damage")
        run.flow = flow
        flow.runs[RUN_KEY] = run
        if flow.choosers is None:
            flow.choosers = default_choosers(game)
    flow.await_key = f"{RUN_KEY}:assign_damage"
    return flow.runs[RUN_KEY].run(game, flow.choosers)


def combat_shares(flow, victim, damage) -> list[tuple]:
    """(fighter, damage) pairs for the combat damage that lands on `victim`: the Archers' shares the run decided (asked from their life and
    the damage left, and nothing happens between the question and the damage), then what is left for her."""
    run = flow.runs.get(RUN_KEY)
    assigned = {} if run is None else run.flags.get("assigned") or {}
    shares = [(flow.game.fighters[fid], k) for fid, k in assigned.items()]
    return shares + ([(victim, damage - sum(assigned.values()))] if damage > sum(assigned.values()) else [])
