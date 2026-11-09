"""Yennefer & Triss' plugins (docs/effects-dsl.md, section 39): `<fid>:mill` (Merigold's Hailstorm) and `<fid>:lodge`
(Lodge of sorceresses). Both variants of the hero (the hero is Yennefer or Triss, the other is the sidekick) share the code;
the plugin id carries the fid of the variant's hero, as the validator demands, so each handler is registered under both.

Mill: "they discard the top N cards of their deck" by the card owner's opponent's choice. The engine's player has a known deck;
the human's is on the table: they press the one button the panel shows and the session's bot moves the real top cards to their
pile (`session_blind`), exactly as for She-Hulk's Lady Justice (`plugins_strange.discard_top`).

Lodge: both players reveal a card of their hand at once and draw its printed BOOST value; whoever drew the most (both on a tie) deals
that much damage to their own hero. Every decision is asked before anything moves (an op that pauses runs again), the bot's pick uses
only its own hand and the human names theirs on the panel, so neither sees the other's choice before making it."""
from __future__ import annotations

from . import table
from .ops_core import OPS, plugin
from .ops_info import _remember_in_hand
from .plugins_strange import discard_top, _unplayed

FIDS = ("yennefer", "triss")


def _both(name: str):
    def deco(fn):
        for fid in FIDS:
            plugin(f"{fid}:{name}")(fn)
        return fn
    return deco


@_both("mill")
def _mill(run, game, spec):
    """Discards the top `args.amount` cards of the OPPONENT's deck (the one who chose this option); an empty deck discards nothing."""
    rival = 1 - run.ctx.owner
    n = min(int(spec["args"]["amount"]), len(game.players[rival].deck))
    if n <= 0:
        return
    if table.physical(game, rival):
        run.ask(game, "amount", rival, [n], 1, 1, "discard the top cards", top_discard=True, confirm=True, rival_deck=True)
    discard_top(run, game, rival, n, rival_deck=True)


def _revealed(run, game, player: int):
    """The card `player` reveals from their hand, or None with an empty hand."""
    st = game.players[player]
    if table.physical(game, player):
        first: dict[str, int] = {}
        for i in sorted(_unplayed(st)):
            first.setdefault(game.card_of(i, player).title, i)       # one button per title: the value is all that matters
        options = sorted(first.values())
        if not st.hand or not options:
            return None
        got = run.ask(game, "cards", player, options, 1, 1, "reveal a card", zone="hand", purpose="lodge", of=player,
                      table_reveal=True)
    else:
        if not st.hand:
            return None
        got = run.ask(game, "cards", player, [c.card_id for c in st.hand], 1, 1, "reveal a card", zone="hand",
                      purpose="lodge", of=player)
    return game.card_of(got[0], player)


@_both("lodge")
def _lodge(run, game, spec):
    owner = run.ctx.owner
    order = (owner, 1 - owner)
    shown = {p: _revealed(run, game, p) for p in order}               # every decision first: nothing has moved yet
    drawn = {p: (0 if c is None else c.boost) for p, c in shown.items()}
    done = run.flags.setdefault("lodge_done", {}).setdefault(run._op_key, [])      # steps already applied: a damage that pauses reruns this
    if "shown" not in done:
        done.append("shown")
        for p, card in shown.items():
            if card is None:
                continue
            if table.physical(game, p):
                _remember_in_hand(game, p, card)                      # the bot now knows this card is in their hand
            else:
                table.intent(game, op="reveal_show", player=p, cards=[card.card_id])
            run.flags.setdefault("lodge", {})[str(p)] = [card.title, card.boost]
    for p in order:
        if drawn[p] and f"draw{p}" not in done:
            done.append(f"draw{p}")
            OPS["draw"](run, game, {"op": "draw", "player": "owner" if p == owner else "opponent", "amount": drawn[p]})
            if game.winner is not None:
                return
    most = max(drawn.values())
    for p in order:
        if most > 0 and drawn[p] == most and f"hit{p}" not in done:
            done.append(f"hit{p}")
            OPS["damage"](run, game, {"op": "damage", "amount": most,
                                      "target": {"side": "own" if p == owner else "enemy", "kind": "hero"}})
            if game.winner is not None:
                return
