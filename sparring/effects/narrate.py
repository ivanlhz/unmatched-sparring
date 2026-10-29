"""What a card run changed, said in Spanish for the chat (D1): the bot announces what its interpreted cards did,
the way the legacy `applied` lines did for Hellboy and Liz.

The narration is a diff of the game around the run, not a trace of the ops: `snapshot` keeps the public state a
run may touch (hit points, positions, zone sizes, the discard piles, actions, statuses, cancellations) as JSON-safe
data in `run.flags`, so a run paused at a decision of the human and resumed from a save still describes everything
it did; `describe` reads it back when the run ends. The bot's hidden cards stay hidden: draws, cards taken from
its deck and cards put back face down are counted, never named; only what is public (the discard piles, a card
that returns from them) is named."""
from __future__ import annotations

from . import table

# the chat speaks to the human: the bot in the third person, the human in the second
VERBS = {"bot": ("roba", "descarta", "devuelve", "su"), "human": ("robas", "descartas", "devuelves", "tu")}
NOTHING = "sin efecto"
PLAYER_STATUS = {"cannot_gain_actions": "no {gana} acciones este turno", "cannot_draw": "no {roba} cartas este turno",
                 "immune_to_effect_damage": "{sus} luchadores no reciben dano de efectos este turno",
                 "next_attack_bonus": "+{n} a {su} proximo ataque"}
FIGHTER_STATUS = {"cannot_leave_space": "{fid} no puede dejar su espacio este turno",
                  "immune_to_effect_damage": "{fid} no recibe dano de efectos este turno"}


def applies(game, owner: int) -> bool:
    """Every interpreted card of the bot is narrated, Medusa's included (Ivan, 29/10)."""
    return owner == game.bot_player and game.players[owner].hero.slug in game.fx.dsl_heroes


def record(applied: list[str], line: str) -> None:
    """Adds a card's line once per card: a second moment that did nothing never repeats "sin efecto", and a moment
    that did something replaces an earlier "sin efecto" of the same card (D1 review)."""
    title = line.split(": ", 1)[0]
    idle = f"{title}: {NOTHING}"
    if line == idle:
        if not any(a.startswith(title + ": ") for a in applied):
            applied.append(line)
        return
    if idle in applied:
        applied.remove(idle)
    applied.append(line)


def snapshot(game, flow=None) -> dict:
    return {"fighters": {fid: [f.hp, f.pos, f.alive] for fid, f in game.fighters.items()},
            "players": [{"hand": len(p.hand), "deck": len(p.deck), "discard": [c.card_id for c in p.discard]}
                        for p in game.players],
            "hand_ids": [[c.card_id for c in game.players[p].hand] if p == game.bot_player else []
                         for p in (0, 1)],
            "drawn": list(game.drawn), "actions": game.actions_left, "turn": game.turn,
            "statuses": len(game.fx.statuses),
            "seen": [_seen(p) for p in game.players],
            "cancelled": [] if flow is None or flow.ctx is None else sorted(flow.ctx.cancelled),
            "redirects": 0 if flow is None else len(flow.redirects),
            "mods": {} if flow is None else {side: len(mods) for side, mods in flow.mods.items()},
            "printed": {} if flow is None else dict(flow.printed_set)}


def describe(game, before: dict, run, flow=None, title: str | None = None) -> str:
    """One line: `<card>: <what changed>; ...` or `<card>: sin efecto`. A run of the human's card (E2, table mode)
    ends with what they do on the table themselves (`en la mesa: ...`). `title`: for a run without a card (an
    ability trigger)."""
    parts = _fighters(game, before) + _cards(game, before, run) + _turn(game, before, run)
    parts += _statuses(game, before) + _combat(before, flow)
    if before["seen"][run.ctx.owner] != _seen(game.players[run.ctx.owner]):
        parts.append("mira tu mano" if run.ctx.owner == game.bot_player else "miras la mano del bot")
    by_hand = table.lines(run)
    if by_hand:
        parts.append("en la mesa: " + ", ".join(by_hand))
    title = title or _title(game, run.ctx.card_id)
    return f"{title}: " + ("; ".join(parts) if parts else NOTHING)


def _seen(player_state) -> list:
    return list(player_state.known.seen) + [player_state.known.turn_no]


def _title(game, card_id) -> str:
    from .select import find_card
    card = None if card_id is None else find_card(game, card_id)
    return card.title if card else "efecto"


def _fighters(game, before: dict) -> list[str]:
    out = []
    for fid, (hp0, pos0, alive0) in before["fighters"].items():
        f = game.fighters[fid]
        if alive0 and not f.alive:
            out.append(f"{fid} abatido")
        elif not alive0 and f.alive:
            out.append(f"{fid} vuelve al tablero en {f.pos} con {f.hp:g} PV")
        elif f.alive:
            if f.hp < hp0:
                out.append(f"{fid} -{hp0 - f.hp:g} PV ({f.hp:g})")
            elif f.hp > hp0:
                out.append(f"{fid} recupera {f.hp - hp0:g} PV ({f.hp:g})")
            if f.pos != pos0:
                out.append(f"{fid} se mueve a {f.pos}")
    return out


def _cards(game, before: dict, run) -> list[str]:
    out, owner = [], run.ctx.owner
    from_deck = set(run.flags.get("deck_discards") or ())      # what the run discarded from a deck, not a hand
    for p in (owner, 1 - owner):
        st, was = game.players[p], before["players"][p]
        roba, descarta, devuelve, su = VERBS["bot" if p == game.bot_player else "human"]
        draws = game.drawn[p] - before["drawn"][p]
        if draws:
            out.append(f"{roba} {draws}")
        discard_now = [c.card_id for c in st.discard]
        by_id = {c.card_id: c for c in st.full_set}
        ids = {c.card_id for c in st.hand}
        added = [i for i in discard_now if i not in was["discard"]]
        if added:
            out.append(f"{descarta} " + _join(by_id[i].title for i in added))
        out += [f"{by_id[i].title} vuelve al mazo" for i in was["discard"] if i not in discard_now and by_id[i] in st.deck]
        # a card that entered the hand in plain sight: from the discard pile (Wildfire's return, a scheme recovered
        # by Ward And Prepare) or, for the bot, anything the rival now knows is there; the rest came hidden
        public = [i for i in was["discard"] if i not in discard_now and i in ids]
        if p == game.bot_player:
            was_ids = set(before["hand_ids"][p])
            public += [i for i in _seen(game.players[1 - p])[:-1]
                       if i not in before["seen"][1 - p] and i in ids - was_ids and i not in public]
            from_hand = len([i for i in added if i in was_ids])
        else:                                       # the human's hand is never read: a discard the run did not
            from_hand = len([i for i in added if i not in from_deck])                   # take from a deck is theirs
        out += [f"{by_id[i].title} vuelve a {su} mano" for i in public]
        # what the size of the hand does not explain by draws, public returns and discards went to the deck face
        # down (or, if the hand grew, came from the deck hidden: Read The Bones); no card does both
        net = len(st.hand) - was["hand"] + from_hand - draws - len(public)
        taken, to_deck = max(net, 0), max(-net, 0)
        if taken > 0:
            out.append(f"{taken} carta{'s' if taken > 1 else ''} del mazo a {su} mano")
        if to_deck > 0:
            out.append(f"{devuelve} {to_deck} carta{'s' if to_deck > 1 else ''} de la mano al mazo")
    return out


def _turn(game, before: dict, run) -> list[str]:
    out = []
    gained = game.actions_left - before["actions"]
    if game.turn == before["turn"] and gained > 0:          # the actions belong to whoever's turn it is
        verb = "gana" if game.turn == game.bot_player else "ganas"
        out.append(f"{verb} {gained} accion{'es' if gained > 1 else ''}")
    if run.flags.get("end_turn") is not None:
        out.append("termina el turno")
    return out


def _statuses(game, before: dict) -> list[str]:
    out = []
    for st in game.fx.statuses[before["statuses"]:]:
        if "fid" in st:
            out.append(FIGHTER_STATUS.get(st["name"], st["name"]).format(fid=st["fid"]))
            continue
        bot = st["player"] == game.bot_player
        words = {"gana": "gana" if bot else "ganas", "roba": "roba" if bot else "robas", "su": "su" if bot else "tu",
                 "sus": "sus" if bot else "tus", "n": st.get("amount", 0)}
        out.append(PLAYER_STATUS.get(st["name"], st["name"]).format(**words))
    return out


def _combat(before: dict, flow) -> list[str]:
    if flow is None or flow.ctx is None:
        return []
    out = []
    for side in sorted(flow.ctx.cancelled):
        if side not in before["cancelled"]:
            card = flow.atk_card if side == "atk" else flow.def_card
            out.append(f"cancela los efectos de {card.title}" if card is not None else "cancela los efectos del rival")
    for side in ("def", "atk"):
        card = flow.atk_card if side == "atk" else flow.def_card
        if card is None:
            continue
        if flow.printed_set.get(side) != before["printed"].get(side):     # "the value becomes N" / "ignore its value"
            out.append(f"el valor de {card.title} pasa a {flow.printed_set[side]}")
        else:
            out += [f"valor de {card.title} {delta:+d}" for delta, _ in flow.mods[side][before["mods"].get(side, 0):]]
    for r in flow.redirects[before["redirects"]:]:
        to = r["to"].get("name") if isinstance(r["to"], dict) else None
        out.append(f"desvia su dano de combate a {to}" if to else "desvia su dano de combate")
    return out


def _join(titles) -> str:
    titles = list(titles)
    return titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + " y " + titles[-1]
