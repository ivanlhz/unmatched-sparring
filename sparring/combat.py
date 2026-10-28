"""Combate y esquemas. Efectos de Medusa implementados; los de Hellboy los resuelve el humano
(se devuelven en `human_effects`), salvo Planned Recklessness y el valor de On Earth As It Is In Hell,
que alteran el calculo del combate."""
from __future__ import annotations

from dataclasses import dataclass, field

from .cards import MEDUSA_BASE, Card
from .state import ANUNG, Fighter, Game, RuleError

GAZE_DAMAGE = 8
GLANCE_DAMAGE = 2
FRENZY_STEPS = 3
DASH_STEPS = 3
HOUNDS_STEPS = 3

SECOND_SHOT = "Second Shot"
FEINT = "Feint"
PLANNED = "Planned Recklessness"
ON_EARTH = "On Earth As It Is In Hell"


def is_medusa_card(card: Card) -> bool:
    return MEDUSA_BASE <= card.card_id < MEDUSA_BASE + 100


@dataclass
class CombatResult:
    attacker: str
    target: str
    atk_card: Card
    def_card: Card | None
    atk_value: int
    def_value: int
    damage: int
    attacker_won: bool
    cancelled: set[str] = field(default_factory=set)
    boost_card: Card | None = None
    human_effects: list[str] = field(default_factory=list)
    atk_parts: list[str] = field(default_factory=list)      # de donde sale el total del atacante (para anunciarlo)
    def_parts: list[str] = field(default_factory=list)
    applied: list[str] = field(default_factory=list)        # efectos de despues del combate que el motor ya aplico


@dataclass
class CombatCtx:
    attacker: Fighter
    target: Fighter
    atk_card: Card
    def_card: Card | None
    atk_value: int
    def_value: int
    cancelled: set[str]


def _side_cards(ctx: CombatCtx):
    """(lado, luchador, carta, rival) en orden de resolucion: primero el defensor."""
    out = []
    if ctx.def_card is not None:
        out.append(("def", ctx.target, ctx.def_card, ctx.attacker))
    out.append(("atk", ctx.attacker, ctx.atk_card, ctx.target))
    return out


def resolve_combat(game: Game, att: Fighter, tgt: Fighter, atk_card: Card, def_card: Card | None,
                   values: tuple[int, int] = (0, 0), boost: Card | None = None) -> CombatResult:
    """`boost`: carta de impulso que el humano ha puesto en su descarte para el BOOST de su ataque (Second Shot); el
    bot la lee de la mesa en el paso "Continuar" y entra aqui, tras el DURING del defensor."""
    if def_card is not None:
        game.check_defense_card(tgt, def_card)
        if def_card not in game.players[tgt.owner].hand:
            raise RuleError(f"{def_card.title} no esta en la mano de {tgt.fid}")
    pa, pd = att.owner, tgt.owner
    game.take_from_hand(pa, atk_card)
    if def_card is not None:
        game.take_from_hand(pd, def_card)
    played = [(pa, atk_card)] + ([(pd, def_card)] if def_card else [])

    bonus_parts = game.attack_bonus_parts(att)   # pasivas del heroe (Hellboy en ANUNG UN RAMA: +2)
    bonus = sum(n for n, _ in bonus_parts)
    atk_value = (atk_card.value or 0) + values[0] + bonus
    def_value = (def_card.value or 0) if def_card else 0
    def_value += values[1]
    ctx = CombatCtx(att, tgt, atk_card, def_card, atk_value, def_value, set())
    result = CombatResult(att.fid, tgt.fid, atk_card, def_card, atk_value, def_value, 0, False)
    result.atk_parts = [f"{atk_card.title} ({atk_card.value or 0})"]
    result.atk_parts += [f"{label} (+{n})" for n, label in bonus_parts if n]
    if values[0]:
        result.atk_parts.append(f"valor extra ({values[0]:+d})")

    # IMMEDIATELY: primero el defensor; lo cancelado no llega a resolver
    for side, fighter, card, _ in _side_cards(ctx):
        if side in ctx.cancelled:
            continue
        other = "atk" if side == "def" else "def"
        if is_medusa_card(card) and card.title == FEINT:
            ctx.cancelled.add(other)
        elif not is_medusa_card(card) and card.title == PLANNED:
            game.effect_shield[fighter.owner] = game.turn_no
            if game.form(fighter.owner) != ANUNG:
                ctx.cancelled.add(other)

    # DURING
    if def_card is not None and "def" not in ctx.cancelled and not is_medusa_card(def_card) and def_card.title == ON_EARTH:
        ctx.def_value = game.destiny_count(pd) + values[1]
    elif def_card is not None and "def" in ctx.cancelled and def_card.title == ON_EARTH and not is_medusa_card(def_card):
        ctx.def_value = values[1]
    if def_card is not None:
        result.def_parts = [f"{def_card.title} ({ctx.def_value - values[1]})"]
        if "def" in ctx.cancelled:
            result.def_parts[0] += " cancelada"
    if values[1]:
        result.def_parts.append(f"valor extra ({values[1]:+d})")
    if "atk" not in ctx.cancelled and is_medusa_card(atk_card) and atk_card.title == SECOND_SHOT:
        boost = game.controllers[pa].choose_combat_boost(game, ctx)
        if boost is not None:
            game.discard_card(pa, boost)
            ctx.atk_value += boost.boost
            result.boost_card = boost
            result.atk_parts.append(f"potencia con {boost.title} (+{boost.boost})")

    if boost is not None and "atk" not in ctx.cancelled and can_boost(atk_card):
        game.discard_card(pa, boost)
        ctx.atk_value += boost.boost
        result.boost_card = boost
        result.atk_parts.append(f"potencia con {boost.title} (+{boost.boost})")

    damage = max(0, ctx.atk_value - ctx.def_value)
    game.damage(tgt, damage, "combat")
    won = damage >= 1
    result.atk_value, result.def_value, result.damage, result.attacker_won = ctx.atk_value, ctx.def_value, damage, won
    result.cancelled = set(ctx.cancelled)

    # AFTER COMBAT: primero el defensor
    if game.winner is None:
        for side, fighter, card, rival in _side_cards(ctx):
            if side in ctx.cancelled:
                continue
            i_won = won == (side == "atk")
            if is_medusa_card(card):
                _medusa_after(game, fighter, rival, card, i_won)
            elif not (_hellboy_after(game, fighter, card, i_won, result) or _liz_after(game, card, result)):
                after = after_text(card)
                if after:
                    result.human_effects.append(f"{card.title}: {after}")
                elif card.title == PLANNED:
                    result.applied.append(f"{card.title}: aplicado ({card.text})")
                elif card.text.strip() and not can_boost(card):   # el BOOST de Second Shot ya se resolvio en el DURING
                    result.human_effects.append(f"{card.title}: {card.text}")
                # una carta sin texto (Excalibur, Service Pistol) no tiene efecto que resolver
    for owner, card in played:
        game.players[owner].discard.append(card)
    return result


def can_boost(card: Card) -> bool:
    """Una carta del humano con un BOOST de su propio ataque en el DURING COMBAT: de la mano (Second Shot) o del
    fondo del mazo (Flame Lash)."""
    return not is_medusa_card(card) and ("boost this attack" in card.text.lower() or deck_boost(card))


def deck_boost(card: Card) -> bool:
    """Flame Lash: el BOOST es la carta del fondo del mazo, no una de la mano."""
    text = card.text.lower()
    return "bottom card of your deck" in text and "boost value to this card" in text


def after_text(card: Card) -> str:
    """Solo la parte AFTER COMBAT del texto de la carta (lo de IMMEDIATELY y DURING ya lo resuelve el calculo)."""
    head, sep, tail = card.text.partition("AFTER COMBAT:")
    return tail.strip() if sep else ""


def _liz_after(game: Game, card: Card, result: CombatResult) -> bool:
    """Flame Lash: AFTER COMBAT gana 1 accion (siempre es la carta del atacante, en su turno)."""
    if card.title == "Flame Lash":
        game.grant_actions(1)
        result.applied.append(f"{card.title}: ganas 1 accion")
        return True
    return False


def _hellboy_after(game: Game, me: Fighter, card: Card, i_won: bool, result: CombatResult) -> bool:
    """Efectos de despues del combate de Hellboy que no necesitan ninguna decision ni informacion oculta del
    humano: se aplican aqui. Los demas (robar, mover, elegir) siguen siendo del humano. True si se aplico."""
    if card.title == "Horseshoes And Hand Grenades" and me.alive:
        hit = [f for f in game.zone_mates(me)]
        for f in hit:
            game.damage(f, 1)
        names = ", ".join(f.fid for f in hit) or "nadie"
        result.applied.append(f"{card.title}: 1 de dano a cada otro luchador de la zona ({names})")
        return True
    if card.title == ON_EARTH:
        if not i_won:
            hb = game.hero_named("Hellboy")
            before = hb.hp
            game.heal(hb, 2)
            result.applied.append(f"{card.title}: Hellboy recupera {hb.hp - before:g} PV (perdio el combate)")
        else:
            result.applied.append(f"{card.title}: no recupera (no perdio el combate)")
        return True
    return False


def _medusa_after(game: Game, me: Fighter, foe: Fighter, card: Card, i_won: bool) -> None:
    ctrl = game.controllers[me.owner]
    t = card.title
    if t == "Gaze of Stone" and i_won:
        game.damage(foe, GAZE_DAMAGE)
    elif t == "Regroup":
        game.draw(me.owner, 2 if i_won else 1)
    elif t == "Dash" and me.alive:
        _optional_move(game, ctrl, me, DASH_STEPS)
    elif t == "Snipe":
        game.draw(me.owner, 1)
    elif t == "The Hounds of Mighty Zeus":
        for h in game.own(me.owner):
            if h.name == "Harpy":
                _optional_move(game, ctrl, h, HOUNDS_STEPS)
    elif t in ("Clutching Claws", "Hiss and Slither"):
        game.force_discard(foe.owner, 1, t)


def _optional_move(game: Game, ctrl, fighter: Fighter, steps: int, through: bool = False) -> None:
    dest = ctrl.choose_move(game, fighter, steps, through)
    if dest is not None:
        game.move_fighter(fighter, dest, steps, through)


def check_scheme(game: Game, fighter: Fighter, card: Card, target: Fighter | None = None) -> None:
    if is_medusa_card(card) and card.title == "A Momentary Glance":
        if target is None or not target.alive or not game.board.share_zone(fighter.pos, target.pos):
            raise RuleError("A Momentary Glance necesita un luchador en la zona de Medusa")


def resolve_scheme(game: Game, player: int, fighter: Fighter, card: Card, target: Fighter | None = None) -> list[str]:
    if not is_medusa_card(card):
        return [f"{card.title}: {card.text}"]
    ctrl = game.controllers[player]
    if card.title == "A Momentary Glance":
        game.damage(target, GLANCE_DAMAGE)
    elif card.title == "Winged Frenzy":
        for f in sorted(game.own(player), key=lambda x: x.fid):
            _optional_move(game, ctrl, f, FRENZY_STEPS, through=True)
        dead = [f for f in game.own(player, alive_only=False) if f.name == "Harpy" and not f.alive]
        medusa = game.hero(player)
        if dead:
            taken = {f.pos for f in game.fighters.values() if f.alive}
            options = sorted(s for s in game.board.spaces if s not in taken and game.board.share_zone(medusa.pos, s))
            spot = ctrl.choose_placement(game, dead[0], options)
            if spot is not None:
                dead[0].alive, dead[0].hp, dead[0].pos = True, 1, spot
    return []
