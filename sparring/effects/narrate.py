"""What a card run changed, said in the chat's language (D1): the bot announces what its interpreted cards did,
the way the legacy `applied` lines did for Hellboy and Liz.

The narration is a diff of the game around the run, not a trace of the ops: `snapshot` keeps the public state a
run may touch (hit points, positions, zone sizes, the discard piles, actions, statuses, cancellations) as JSON-safe
data in `run.flags`, so a run paused at a decision of the human and resumed from a save still describes everything
it did; `describe` reads it back when the run ends. The bot's hidden cards stay hidden: draws, cards taken from
its deck and cards put back face down are counted, never named; only what is public (the discard piles, a card
that returns from them) is named."""
from __future__ import annotations

import re

from . import table
from ..i18n import has, t, tn
from ..spaces import describe as describe_space

# the chat speaks to the human: the bot in the third person, the human in the second (tags `narr.v.*.<side>`)
STATUS_NAMES = ("cannot_gain_actions", "cannot_draw", "immune_to_effect_damage", "next_attack_bonus")
FIGHTER_STATUS_NAMES = ("cannot_leave_space", "immune_to_effect_damage")


def __getattr__(name: str):
    """`NOTHING`: the line of a card that changed nothing, in the current language."""
    if name == "NOTHING":
        return t("narr.nothing")
    raise AttributeError(name)


def _verbs(side: str) -> tuple[str, str, str, str]:
    """(draw, discard, return, possessive) for the bot (third person) or the human (second)."""
    return tuple(t(f"narr.v.{word}.{side}") for word in ("draw", "discard", "return", "poss"))


def applies(game, owner: int) -> bool:
    """Every interpreted card of the bot is narrated, Medusa's included (Ivan, 29/10)."""
    return owner == game.bot_player and game.players[owner].hero.slug in game.fx.dsl_heroes


def record(applied: list[str], line: str) -> None:
    """Adds a card's line once per card: a second moment that did nothing never repeats "sin efecto", and a moment
    that did something replaces an earlier "sin efecto" of the same card (D1 review)."""
    title = line.split(": ", 1)[0]
    idle = f"{title}: {t('narr.nothing')}"
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
            "drawn": list(game.drawn), "actions": game.actions_left, "turn": game.turn, "said": len(game.fx.said),
            "statuses": len(game.fx.statuses),
            "seen": [_seen(p) for p in game.players],
            "in_play": [game.fx.ongoing_card_id(p) for p in (0, 1)],
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
    if run.flags.get("looked_hand") and before["seen"][run.ctx.owner] != _seen(game.players[run.ctx.owner]):
        parts.append(t("narr.looks.bot" if run.ctx.owner == game.bot_player else "narr.looks.human"))
    parts = _fold_triggers(game, before, parts)
    priced = run.flags.get("bot_priced")
    if priced:
        parts = _say_bot_price(game, run, parts, priced)
    by_hand = table.lines(run)
    if by_hand:
        parts.append(t("narr.on_table", lines=", ".join(by_hand)))
    title = title or _title(game, run.ctx.card_id)
    return f"{title}: " + ("; ".join(parts) if parts else t("narr.nothing"))


def _say_bot_price(game, run, parts: list[str], priced: dict) -> list[str]:
    """The bot's answer to a price the human's card offered it, said plainly and never as "sin efecto". The wording is
    Incinerate's (a discard price that ignores the card's value); another priced optional needs its own."""
    title = _title(game, run.ctx.card_id)
    stake, cards = priced["stake"], priced["cards"]
    lethal = priced["hp"] is not None and 0 < priced["hp"] <= stake
    if not priced["can_pay"]:
        return parts + [t("narr.price.cannot_pay", cards=cards, stake=f"{stake:g}")]
    if not priced["paid"]:
        why = t("narr.price.prefers", stake=f"{stake:g}", cards=cards) if stake else t("narr.price.no_change")
        return parts + [t("narr.price.declines", cards=cards, why=why)]
    why = t("narr.price.lethal") if lethal else t("narr.price.avoids", stake=f"{stake:g}")
    bot_prefix = t("narr.bot_subject", verb="")
    discard = _verbs("bot")[1] + " "
    discarded = next((p.removeprefix(bot_prefix) for p in parts if p.startswith((discard, bot_prefix + discard))), None)
    becomes = t("narr.value_becomes", title=title, n="")
    rest = [p for p in parts if p.removeprefix(bot_prefix) != discarded and not p.startswith(becomes)]
    paid = discarded or t("narr.price.pays", cards=cards)    # `_cards` words the discard; without it the price still shows
    return [t("narr.price.ignores", paid=paid, title=title, why=why)] + rest


def _return_pattern() -> re.Pattern:
    """The line a human trigger says when a card returns to the hand: `<label>: <title> vuelve a tu mano`."""
    body = re.escape(t("narr.returns_hand", title="@@T@@")).replace("@@T@@", "(?P<title>.+)")
    return re.compile(rf"^(?P<label>[^:]+): {body}$")


def _fold_triggers(game, before: dict, parts: list[str]) -> list[str]:
    """The lines of the human's triggers that fired inside this run (`fx.said`, E2) become part of the card's own
    line (Ivan, 29/10): "descartas Fireball (Wildfire la devuelve a tu mano)"; anything else in parentheses."""
    at = before.get("said", 0)
    folded = game.fx.said[at:]
    del game.fx.said[at:]
    returns = _return_pattern()
    for _, line in folded:
        m = returns.match(line)
        if m is None:
            parts.append(f"({line})")
            continue
        title, word = m.group("title"), m.group("label").split()[0].capitalize()
        parts = [p for p in parts if p != t("narr.returns_hand", title=title)]
        discard = _verbs("human")[1] + " "
        mention = next((i for i, p in enumerate(parts) if p.startswith(discard) and title in p), None)
        if mention is None:
            parts.append(t("narr.returns_hand_by", title=title, word=word))
        else:
            parts[mention] = parts[mention].replace(title, t("narr.returned_by", title=title, word=word), 1)
    return parts


def _seen(player_state) -> list:
    return list(player_state.known.seen) + [player_state.known.turn_no]


def _title(game, card_id) -> str:
    from .select import find_card
    card = None if card_id is None else find_card(game, card_id)
    return card.title if card else t("fx.cause_default")


def _fighters(game, before: dict) -> list[str]:
    out = []
    for fid, (hp0, pos0, alive0) in before["fighters"].items():
        f = game.fighters[fid]
        if alive0 and not f.alive:
            out.append(t("narr.fighter.down", fid=fid))
        elif not alive0 and f.alive:
            out.append(t("narr.fighter.back", fid=fid, spot=describe_space(game, f.pos, (fid,)), hp=f"{f.hp:g}"))
        elif f.alive:
            if f.hp < hp0:
                out.append(t("narr.fighter.loses", fid=fid, n=f"{hp0 - f.hp:g}", hp=f"{f.hp:g}"))
            elif f.hp > hp0:
                out.append(t("narr.fighter.heals", fid=fid, n=f"{f.hp - hp0:g}", hp=f"{f.hp:g}"))
            if f.pos != pos0:
                out.append(t("narr.fighter.moves", fid=fid, spot=describe_space(game, f.pos, (fid,))))
    return out


def _cards(game, before: dict, run) -> list[str]:
    out, owner = [], run.ctx.owner
    from_deck = set(run.flags.get("deck_discards") or ())      # what the run discarded from a deck, not a hand
    for p in (owner, 1 - owner):
        st, was = game.players[p], before["players"][p]
        roba, descarta, devuelve, su = _verbs("bot" if p == game.bot_player else "human")
        if p == game.bot_player and owner != p:     # the human's card made the bot act: name it as the subject
            roba, descarta, devuelve = (t("narr.bot_subject", verb=v) for v in (roba, descarta, devuelve))
        # the owed-draws counter also falls when the table settles it (a look row put the hand back): not a draw
        draws = max(0, game.drawn[p] - before["drawn"][p])
        if draws:
            out.append(f"{roba} {draws}")
        discard_now = [c.card_id for c in st.discard]
        by_id = {c.card_id: c for c in st.full_set}
        ids = {c.card_id for c in st.hand}
        added = [i for i in discard_now if i not in was["discard"]]
        if p != game.bot_player:                    # the human's deck discard a trigger took straight back (Wildfire)
            added += [i for i in from_deck if i not in discard_now and i not in added and i in ids]
        # an ONGOING that entered play came out of the hand without touching the discard pile; the one it replaced
        # left play (it was never in the hand: not a discard from it)
        entered = game.fx.ongoing_card_id(p)
        if entered == before["in_play"][p] or entered in was["discard"]:
            entered = None
        left = before["in_play"][p] if p != game.bot_player and before["in_play"][p] in added else None
        added = [i for i in added if i != left]
        if added:
            out.append(f"{descarta} " + _join(by_id[i].title for i in added))
        if left is not None:
            out.append(t("narr.leaves_play", title=by_id[left].title))
        out += [t("narr.back_to_deck", title=by_id[i].title)
                for i in was["discard"] if i not in discard_now and by_id[i] in st.deck]
        # a card that entered the hand in plain sight: from the discard pile (Wildfire's return, a scheme recovered
        # by Ward And Prepare) or, for the bot, anything the rival now knows is there; the rest came hidden
        public = [i for i in was["discard"] if i not in discard_now and i in ids]
        if p != game.bot_player:
            public += [i for i in from_deck if i in ids and i not in public]
        if p == game.bot_player:
            was_ids = set(before["hand_ids"][p])
            public += [i for i in _seen(game.players[1 - p])[:-1]
                       if i not in before["seen"][1 - p] and i in ids - was_ids and i not in public]
            from_hand = len([i for i in added if i in was_ids])
            from_hand += int(entered is not None and entered in was_ids)
        else:                                       # the human's hand is never read: a discard the run did not
            from_hand = len([i for i in added if i not in from_deck])                   # take from a deck is theirs
            from_hand += int(entered is not None)
        out += [t("narr.returns_poss_hand", title=by_id[i].title, su=su) for i in public]
        # what the size of the hand does not explain by draws, public returns and discards went to the deck face
        # down (or, if the hand grew, came from the deck hidden: Read The Bones); no card does both
        net = len(st.hand) - was["hand"] + from_hand - draws - len(public)
        taken, to_deck = max(net, 0), max(-net, 0)
        if taken > 0:
            out.append(tn("narr.from_deck", taken, su=su))
        # the human's own return to the deck is done on the table: `en la mesa` already says it
        if to_deck > 0 and not (p != game.bot_player and any(n.get("op") == "return_to_deck" for n in table.notes(run))):
            where = (t("narr.hand_to_deck_poss", su=su) if p == game.bot_player and owner != p
                     else t("narr.hand_to_deck"))
            out.append(tn("narr.return_n", to_deck, verb=devuelve, where=where))
    return out


def _turn(game, before: dict, run) -> list[str]:
    out = []
    gained = game.actions_left - before["actions"]
    if game.turn == before["turn"] and gained > 0:          # the actions belong to whoever's turn it is
        out.append(tn("narr.gain_actions", gained, verb=t("narr.v.gain." + ("bot" if game.turn == game.bot_player else "human"))))
    if run.flags.get("end_turn") is not None:
        out.append(t("narr.end_turn"))
    return out


def _statuses(game, before: dict) -> list[str]:
    out = []
    for st in game.fx.statuses[before["statuses"]:]:
        if "fid" in st:
            tag = f"narr.fstatus.{st['name']}"
            out.append(t(tag, fid=st["fid"]) if st["name"] in FIGHTER_STATUS_NAMES else st["name"])
            continue
        side = "bot" if st["player"] == game.bot_player else "human"
        tag = f"narr.status.{st['name']}.{side}"
        out.append(t(tag, n=st.get("amount", 0)) if has(tag) else st["name"])
    return out


def _combat(before: dict, flow) -> list[str]:
    if flow is None or flow.ctx is None:
        return []
    out = []
    for side in sorted(flow.ctx.cancelled):
        if side not in before["cancelled"]:
            card = flow.atk_card if side == "atk" else flow.def_card
            out.append(t("narr.cancels", title=card.title) if card is not None else t("narr.cancels_rival"))
    for side in ("def", "atk"):
        card = flow.atk_card if side == "atk" else flow.def_card
        if card is None:
            continue
        if flow.printed_set.get(side) != before["printed"].get(side):     # "the value becomes N" / "ignore its value"
            out.append(t("narr.value_becomes", title=card.title, n=flow.printed_set[side]))
        else:
            out += [t("narr.value_delta", title=card.title, delta=f"{delta:+d}")
                    for delta, _ in flow.mods[side][before["mods"].get(side, 0):]]
    for r in flow.redirects[before["redirects"]:]:
        to = r["to"].get("name") if isinstance(r["to"], dict) else None
        out.append(t("narr.redirects_to", to=to) if to else t("narr.redirects"))
    return out


def _join(titles) -> str:
    titles = list(titles)
    return titles[0] if len(titles) == 1 else ", ".join(titles[:-1]) + t("common.and") + titles[-1]
