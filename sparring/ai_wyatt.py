"""What the AI knows about Wyatt Earp's cards and SHOWDOWN (docs/heroes/wyatt-earp.md).

`ai_medusa.card_value` / `eval_defense` read the printed value and `AFTER_BONUS` is a fixed table, so what depends on the board lives here
like `ai_sinbad` and `ai_philippa`: `after_value` is added to an attack's outcome and to a defense's evaluation, `justice_value` is what
Bring 'Em To Justice defends with, `showdown_edge` is what winning an attack is worth to him before the effect is chosen. The decisions
his cards ask (`EffectAI._effect` for SHOWDOWN, `_optional` for burying the rival's top card, `_fighter` / `_space` for You Die First)
call `pick_showdown`, `bury_rival`, `die_first_fighter` and `die_first_dest` here; the search's rollouts use the cheaper `rollout_showdown`.

SHOWDOWN is chosen by what each option brings, in the evaluation's units: the draw is an average unseen card (nothing when the hand is at
its limit and no action is left to play a card), the free action is the best attack the hand can still make from where the fighters
stand (what `MedusaAI.attack_outcome` says, never less than nothing), the move is the gain in `position_value` of the best space one step
away for the fighter that attacked. A tie goes to the first printed."""
from __future__ import annotations

WYATT = "wyatt-earp"
JUSTICE = "Bring 'Em To Justice"
MARSHAL = "A Marshal And An Outlaw"
DAISY = "You're A Daisy If You Do"
HUCKLEBERRY = "I'm Your Huckleberry"
GUNFIGHT = "Gunfight At The O.K. Corral"
FAN = "Fan The Hammer"
TWO_GUNS = "I Have Two Guns, One For Each Of You"
SWEAR = "Better Swear Me In"
DRAW, ATTACK, MOVE = 0, 1, 2           # the printed order of the SHOWDOWN options (data/heroes/effects/wyatt-earp.json)
COUNTERS = ("showdown_draw", "showdown_attack", "showdown_move")

STRIP_AFTER = 0.6          # A Marshal And An Outlaw attacking: the rival discards a card of their choice (their least useful one)
BURY_AFTER = 0.15          # Better Swear Me In: the look at the rival's top card and the chance to bury it
GUNFIGHT_EDGE = 0.1        # four hits, two chosen by each side: about even, a little for whoever has the sidekick to finish
POINTLESS_DRAW = 0.05      # a card drawn into a full hand is discarded by the limit and only shortens the deck: any other effect beats it
DRAW_SHARE = 0.9           # the SHOWDOWN draw before it is chosen: an average card, a little less since the first effect is not always the draw


def is_wyatt(game, player: int) -> bool:
    return game.players[player].hero.slug == WYATT


def open_options(game, player: int) -> list[int]:
    """The SHOWDOWN effects `player` has not used this turn (every one on a turn that has no combat won yet)."""
    from .effects.select import counter_value
    return [k for k, name in enumerate(COUNTERS) if counter_value(game, player, name) == 0]


def justice_value(rival_average_boost: float) -> float:
    """Bring 'Em To Justice defends with twice the BOOST of the rival's top card, which only the average of what is left can say."""
    return 2 * rival_average_boost


def after_value(game, owner: int, card, p_win: float, foe_hp_weight: float, card_value: float, room: int | None = None,
                p_kill: float = 0.0, defending: bool = False) -> float:
    """What the AFTER of a Wyatt Earp card is worth, in the AI's units (`card_value` per card, `foe_hp_weight` per hit point of the
    opposing fighter). `room`: the cards the hand can still take (None, no limit). `p_win`: the chance the card wins its combat (when
    defending, the chance the blow is blocked). Cards of any other hero are worth 0 here."""
    fits = lambda n: n if room is None else min(n, max(0, room))
    title = card.title
    if title == DAISY:
        return card_value * fits(2)
    if title == MARSHAL:
        if defending:
            return card_value * fits(1)
        return STRIP_AFTER if game.players[1 - owner].hand else 0.0
    if title == HUCKLEBERRY:
        return p_win * foe_hp_weight if game.foes(owner) else 0.0
    if title == GUNFIGHT:
        return GUNFIGHT_EDGE * foe_hp_weight
    if title == FAN:
        return p_kill * card_value
    if title == TWO_GUNS:
        return 0.0 if defending else foe_hp_weight * min(2.0, float(_others_in_zone(game, owner)))
    if title == SWEAR:
        return BURY_AFTER
    return 0.0


def _others_in_zone(game, owner: int) -> int:
    """Opposing fighters in Doc Holliday's zone beside the one he fights (the card leaves that one out)."""
    doc = next((f for f in game.own(owner) if f.name == "Doc Holliday"), None)
    if doc is None or doc.pos is None:
        return 0
    zones = game.board.zones(doc.pos)
    return max(0, sum(1 for f in game.foes(owner) if f.pos is not None and game.board.zones(f.pos) & zones) - 1)


def showdown_edge(game, owner: int, p_win: float, card_value: float, room: int | None) -> float:
    """What winning an attack is worth before SHOWDOWN is chosen: the draw while it is still open (the best of the three is worth
    at least that), `p_win` of the time. 0 for a hero that has no SHOWDOWN or has used the three."""
    if not is_wyatt(game, owner) or not open_options(game, owner):
        return 0.0
    return p_win * DRAW_SHARE * card_value * (1 if room is None or room > 0 else 0)


def best_attack_value(ai, game, me: int, only: str | None = None) -> float:
    """The best net value of an attack the bot's hand can make now (a free action does not move anybody); never below 0. `only`: just
    attacks on that fighter (the free action of You Die First)."""
    from .ai_medusa import Model
    from . import enraged
    model, hand = Model(game, me), game.players[me].hand
    best = 0.0
    for f in game.own(me):
        for t in game.foes(me):
            if (only is not None and t.fid != only) or not game.can_declare_attack(f, t):
                continue
            for c in hand:
                if enraged.may_attack_with(game, me, c) and c.usable_by(f.name) and game.attack_card_reaches(f, t, c):
                    best = max(best, ai.attack_outcome(game, model, f, t, c)[0])
    return best


def pick_showdown(ai, game, me: int, options: list[int], attacker: str | None) -> int:
    """The SHOWDOWN effect (an index of the printed order) with the most to bring. `ai`: the player's `MedusaAI`."""
    from .ai_medusa import hand_room
    values: dict[int, float] = {}
    if DRAW in options:
        room = hand_room(game, me)
        pointless = not game.players[me].deck or (game.actions_left <= 0 and room is not None and len(game.players[me].hand) >= room)
        values[DRAW] = -POINTLESS_DRAW if pointless else ai.avg_unseen_keep(game) * DRAW_SHARE
    if ATTACK in options:
        best = best_attack_value(ai, game, me)
        values[ATTACK] = best if best > 0 else -POINTLESS_DRAW       # a free action nothing can use is lost
    if MOVE in options:
        values[MOVE] = _move_gain(ai, game, me, attacker)
    return max(options, key=lambda k: (values[k], -k))


def _move_gain(ai, game, me: int, attacker: str | None) -> float:
    from .ai_medusa import Model
    f = game.fighters.get(attacker) if attacker else None
    if f is None or not f.alive or f.pos is None or not game.fx.can_move(f):
        return 0.0
    model = Model(game, me)
    stay = ai.position_value(game, model, {f.fid: f.pos})
    best = max((ai.position_value(game, model, {f.fid: s}) for s in game.legal_moves(f, 1)), default=stay)
    return max(0.0, best - stay)


def rollout_showdown(game, me: int, options: list[int], greedy: bool) -> int:
    """The search's cheap answer: greedy takes the free action when the hand can use it, else the draw, else the move; safe takes the
    draw, then the move (it never opens another attack)."""
    from . import enraged
    hand, deck = game.players[me].hand, game.players[me].deck
    usable = any(game.can_declare_attack(f, t) and any(enraged.may_attack_with(game, me, c) and c.usable_by(f.name) and game.attack_card_reaches(f, t, c)
                                                      for c in hand)
                 for f in game.own(me) for t in game.foes(me))
    order = ([ATTACK] if usable else []) + [DRAW if deck else MOVE, MOVE, DRAW] if greedy else [DRAW if deck else MOVE, MOVE, ATTACK]
    return next((k for k in order if k in options), options[0])


def bury_rival(game, me: int, card_id: int) -> bool:
    """Better Swear Me In: the revealed top card of the rival's deck goes to the bottom when it is worth more to them than the average
    card they still hold in their deck or hand (what they already played is out of the average)."""
    from .search.adapter import card_worth
    rival = game.players[1 - me]
    card = game.cards_by_id(1 - me).get(card_id)
    left = [c for c in rival.full_set if c not in rival.gone]
    if card is None or not left:
        return False
    return card_worth(card) > sum(card_worth(c) for c in left) / len(left)


def _best_strike(ai, game, me: int, foe_fid: str, dest: int) -> float:
    """The best net value of an attack on `foe_fid` if it stood on `dest`."""
    g = game.clone()
    g.fighters[foe_fid].pos = dest
    return best_attack_value(ai, g, me, only=foe_fid)


def die_first_fighter(ai, game, me: int, cands: list) -> str:
    """You Die First: the rival the free attack hurts most once it has been pulled (or left) where the hand can strike it."""
    def reach_value(f) -> float:
        return max([_best_strike(ai, game, me, f.fid, d) for d in game.legal_moves(f, 1)] + [_best_strike(ai, game, me, f.fid, f.pos)])
    return max(cands, key=lambda f: (reach_value(f), f.hero, f.fid)).fid


def die_first_dest(ai, game, me: int, f, options: list[int], may_stay: bool) -> list[int]:
    """You Die First: the space (or staying) from which the hand strikes the fighter best."""
    stay = _best_strike(ai, game, me, f.fid, f.pos)
    scored = {d: _best_strike(ai, game, me, f.fid, d) for d in options}
    best = max(scored, key=lambda d: (scored[d], -d), default=None)
    if best is None or (may_stay and stay >= scored[best]):
        return []
    return [best]
