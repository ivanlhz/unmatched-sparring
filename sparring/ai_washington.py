"""What the AI knows about George Washington's cards and ESPIONAGE (docs/heroes/george-washington.md).

`ai_medusa.card_value` and the rival models read the printed value and the effects table, so the cards whose figures move need these:
Make A Stand is a 5 when its fighter has not moved this turn, Network Of Spies is worth 2 plus the friends in Washington's zone,
Circumvent ignores the defense when a ruse token goes on it, and the AFTER of the others (Agent 711's 7 damage, Sabotage's two
discards, the heal and the action of Allies Everywhere, the token Misinformation gives back, the Spy Recruit To The Ring brings back).

Two decisions are the bot's own, both made by `EffectAI` when the interpreter asks (`ai_effects._optional`):
  use_ruse     the bot attacks with a card that carries a ruse effect: a token goes on it when what the effect is worth, once the
               opponent may take it off by discarding a card (`P_REMOVE`, an assumption), beats what a token is worth to keep (the
               fewer left, the dearer). Agent 711 against the hero, Circumvent against a good defense and Sabotage nearly always pay;
               Allies Everywhere only when Washington has hit points to heal.
  remove_ruse  a ruse token lies on the human's attack and the bot may discard a random card of its hand to take it off. It does not
               know the card: it weighs the ruse cards of Washington's deck that are not yet in his public discard pile (the
               cards that could carry a ruse) against what a card of its hand is worth, and never gives up the last card.
The ai_medusa units are passed in (`W_HERO`, `CARD_VALUE`...) so this module imports nothing from it at load time."""
from __future__ import annotations

MAKE_A_STAND = "Make A Stand"
NETWORK = "Network Of Spies"
CIRCUMVENT = "Circumvent"
AGENT = "Agent 711"
SABOTAGE = "Sabotage"
ALLIES = "Allies Everywhere"
MISINFORMATION = "Misinformation"
LEAD_ASTRAY = "Lead Astray"
RECRUIT = "Recruit To The Ring"

RUSE_MAX = 4                # the supply Washington starts with (the effects file's counter `ruse_tokens`)
P_REMOVE = 0.3              # assumed chance the opponent discards a card to remove a token: the bot cannot know
PRICE_FIRST = 0.3           # what keeping a token is worth with the whole supply left; each token already spent adds PRICE_STEP
PRICE_STEP = 0.15
DAMAGE = 7                  # Agent 711
STAND_VALUE = 5             # Make A Stand standing still
MOVE_AFTER = 0.3            # Lead Astray's move
TOKEN_BACK = 0.5            # a token Misinformation gives back, in hit points of the rival it would otherwise be worth
SPY_BACK = 0.9              # a Spy Recruit To The Ring returns, in the units of a Harpy (`ai_medusa.HARPY_VALUE`)
P_WIN_THREAT = 0.5          # chance the unseen ruse attack wins the combat, for the bot deciding whether to remove the token
AVG_BLOW = 2.5              # the combat damage a won attack is assumed to deal before Agent 711's 7 lands
REMOVE_MARGIN = 0.2         # the threat must beat the price of a card by this much to give a card up


def is_washington(game, player: int) -> bool:
    return game.players[player].hero.slug == "george-washington"


def tokens(game, player: int) -> int:
    """Ruse tokens in `player`'s supply (the full supply for a hero that has none: it is only asked of Washington)."""
    return game.fx.counter_value(player, "ruse_tokens", RUSE_MAX)


def ruse_on(game, player: int) -> bool:
    return bool(game.fx.counter_value(player, "ruse", 0))


def can_ruse(game, player: int, card) -> bool:
    """A token could go on `card` now: its owner is Washington, the card carries a ruse effect, a token is left and none is on yet."""
    return is_washington(game, player) and "ruse" in card.tags and tokens(game, player) > 0 and not ruse_on(game, player)


def own_value(game, fighter, card) -> float | None:
    """The value `card` will have for `fighter` when its DURING is known now, or None when it is the printed one."""
    if not is_washington(game, fighter.owner):
        return None
    if card.title == MAKE_A_STAND:
        start = game.fx.turn_start_pos.get(fighter.fid)
        return float(STAND_VALUE) if start is not None and fighter.pos == start else None
    if card.title == NETWORK:
        hero = game.hero(fighter.owner)
        if not hero.alive or hero.pos is None:
            return None
        return float((card.value or 0) + sum(1 for o in game.zone_mates(hero) if o.owner == fighter.owner and o is not fighter))
    return None


def circumvents(game, fighter, card) -> bool:
    """The attack makes the defender's card count for nothing: Circumvent with a ruse token the bot will put on it."""
    return card.title == CIRCUMVENT and can_ruse(game, fighter.owner, card)


def price(game, player: int) -> float:
    """What a ruse token is worth to keep: dearer as the supply runs out."""
    return PRICE_FIRST + PRICE_STEP * (RUSE_MAX - tokens(game, player))


def effect_worth(game, owner: int, card, p_win: float, foe_hp_weight: float, card_value: float, hero_hp_weight: float,
                 foe_hp: float, action_value: float) -> float:
    """The ruse part of `card` as the bot prices it, if the token stays on (Circumvent's is `circumvents`, not counted here)."""
    title = card.title
    if title == AGENT:
        return foe_hp_weight * min(float(DAMAGE), foe_hp) * p_win
    if title == SABOTAGE:
        return card_value * min(2, len(game.players[1 - owner].hand)) * p_win
    if title == ALLIES:
        hero = game.hero(owner)
        return hero_hp_weight * min(3.0, hero.max_hp - hero.hp) if hero.alive else 0.0
    return 0.0


def after_value(game, owner: int, card, p_win: float, foe_hp_weight: float, card_value: float, hero_hp_weight: float,
                foe_hp: float, action_value: float, spy_value: float) -> float:
    """What the AFTER of a Washington card is worth, in the AI's units. The ruse effects count in proportion to the chance the token
    stays on the card (`1 - P_REMOVE`), and only while a token can go on."""
    title = card.title
    if title not in (AGENT, SABOTAGE, ALLIES, MISINFORMATION, LEAD_ASTRAY, RECRUIT) or not is_washington(game, owner):
        return 0.0
    if title == LEAD_ASTRAY:
        return MOVE_AFTER
    if title == MISINFORMATION:
        return foe_hp_weight * TOKEN_BACK * p_win if tokens(game, owner) < RUSE_MAX else 0.0
    if title == RECRUIT:
        back = any(not f.alive for f in game.own(owner, alive_only=False) if not f.hero and f.name == "Spy")
        return spy_value * SPY_BACK * (0.5 + 0.5 * p_win) if back else 0.0
    ruse = (1.0 - P_REMOVE) if can_ruse(game, owner, card) else 0.0
    worth = effect_worth(game, owner, card, p_win, foe_hp_weight, card_value, hero_hp_weight, foe_hp, action_value) * ruse
    return worth + (action_value if title == ALLIES else 0.0)


# ---------------------------------------------------------------- the two decisions of the bot

def use_ruse(ai, game, req) -> bool:
    """Put a ruse token on the attack the bot is declaring (`req.extra`: attack_card, attacker, target)."""
    from . import ai_medusa as m
    me = req.player
    card = game.cards_by_id(me).get(req.extra["attack_card"])
    f, t = game.fighters.get(req.extra["attacker"]), game.fighters.get(req.extra["target"])
    if card is None or f is None or t is None or not can_ruse(game, me, card):
        return False
    medusa, model = ai.medusa(me), m.Model(game, me)
    p_win = medusa.p_win_of(game, model, f, t, card)
    hero = game.hero(me)
    if card.title == CIRCUMVENT:
        defense = sum(p * (dv or 0) for p, dv in model.defense_dist(t))
        worth = m.weight(t) * min(defense, t.hp)
    else:
        worth = effect_worth(game, me, card, p_win, m.weight(t), m.CARD_VALUE, m.W_MEDUSA_HP, t.hp, m.ACTION_VALUE)
        if card.title == AGENT and t.hp <= DAMAGE:
            worth += (m.HERO_KILL if t.hero else 0.0) * p_win          # the 7 finishes the hero
    total = (1.0 - P_REMOVE) * worth + P_REMOVE * m.CARD_VALUE * 2.5   # a card the opponent discards to remove it is a card lost
    return total > price(game, me)


def remove_ruse(ai, game, req) -> bool:
    """Discard a random card to take the ruse token off the human's attack: the card is unknown, so the bot weighs every ruse card
    of Washington's deck that is not in his public discard pile against what a card of its own hand is worth."""
    from . import ai_medusa as m
    me, rival = req.player, 1 - req.player
    hand = game.players[me].hand
    t = game.fighters.get(req.extra["target"])
    if len(hand) < 2 or t is None:
        return False
    st = game.players[rival]
    pool = [c for c in st.full_set if "ruse" in c.tags and c not in st.gone]
    if not pool:
        return False
    best_defense = max((c.value or 0 for c in hand if c.can_defend), default=0)
    threat = 0.0
    for c in pool:
        if c.title == AGENT and t.hero:
            threat += P_WIN_THREAT * (ai.hp_change(t, t.hp - AVG_BLOW, me, game) - ai.hp_change(t, t.hp - AVG_BLOW - DAMAGE, me, game))
        elif c.title == CIRCUMVENT:
            threat += P_WIN_THREAT * (m.W_MEDUSA_HP * min(best_defense, t.hp) if t.hero else m.HARPY_VALUE * 0.5)
        elif c.title == SABOTAGE:
            threat += P_WIN_THREAT * 2 * m.keep_value(min(hand, key=lambda x: m.keep_value(x, hand)), hand)
        elif c.title == ALLIES:
            threat += 0.2
    threat /= len(pool)
    cost = sum(m.keep_value(c, hand) for c in hand) / len(hand)
    return threat > cost + REMOVE_MARGIN
