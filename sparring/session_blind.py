"""BLIND BOOST of the human on the real table (Doctor Strange, Ivan 7/11).

The human DECLARES the count on the panel (an `amount` request with `blind_count`: 0 / 1 for Bolts of Balthakk, 0 / 1 / 2 for
Seven Suns of Cinnibus) before any card is taken. Their deck is physical and hidden from the engine, so once they have
answered the BOT moves that many cards from the top of their deck to their discard pile, face up (`lua.deck_top_to_discard`),
reads which cards they were and hands their CardIDs to the plugin (`run.flags["blind_cards"]`, saved with the run), which adds
their BOOST values. If the table cannot do it, the plugin falls back to a `cards` request (`pile_mode: blind`) that asks them to
lay the top cards by hand (`session_rage`), so the game never stalls."""
from __future__ import annotations

from .effects.choose import ChoiceRequest
from .i18n import t
from .session_choices import request_card
from .tts import lua
from .tts.lua import ChatKind


def is_count(req: ChoiceRequest | None) -> bool:
    return req is not None and req.kind == "amount" and bool(req.extra.get("blind_count") or req.extra.get("top_discard"))


def declared(session, run, value: list) -> None:
    """The human answered the count: move the cards before the engine goes on. A refused table says so in the chat and leaves
    the plugin to ask for the cards by hand."""
    req = run.awaiting
    count = int(value[0]) if value else 0
    card = request_card(session.game, req)
    name = card.title if card is not None else t("pile.this_card")
    if req.extra.get("ability"):                                # Daredevil's special ability, not the card's own BLIND BOOST
        name = t("blind.ability_name")
    if count == 0:
        session.say(t("blind.none", card=name), ChatKind.YOUR_TURN)
        return
    moved, why = _move(session, min(count, len(session.game.players[session.human].deck)))
    if moved is None:
        session.say(t("blind.auto_failed", card=name, why=why), ChatKind.WARNING)
        return
    by_id = {c.card_id: c for c in session.game.players[session.human].full_set}
    if req.extra.get("top_discard"):                            # Take A Knee: the heal is told by the effect's own line
        session.say(t("knee.auto", card=name, title=by_id[moved[0]].title), ChatKind.YOUR_TURN)
    else:
        session.say(t("blind.auto", card=name, n=len(moved), titles=", ".join(by_id[i].title for i in moved),
                      bonus=f"+{sum(by_id[i].boost for i in moved)}"), ChatKind.YOUR_TURN)
    run.flags.setdefault("blind_cards", {})[req.key.rsplit(":", 1)[0]] = moved


def _move(session, n: int) -> tuple[list[int] | None, str]:
    """(CardIDs in the order they left the deck, "") or (None, why) when the table did not move exactly `n` cards of the human's."""
    from .session import SessionError             # the session imports this module: resolved at call time
    from .session_translators import ERRORS
    cfg = session.cfg
    if not cfg.human_deck_guid or not cfg.human_discard_zone:
        return None, t("blind.why_config")
    try:
        script = lua.deck_top_to_discard(cfg.human_deck_guid, n, cfg.human_discard_zone, cfg.human_card_ids,
                                         identity=session._identity("human"), **session._deck_kw("human"))
        res = session._w(script, "cards").result
    except ERRORS + (SessionError,) as e:
        return None, str(e)
    res = res if isinstance(res, dict) else {}
    own = {c.card_id for c in session.game.players[session.human].full_set}
    moved = [i for i in res.get("moved") or [] if isinstance(i, int) and i in own]
    if res.get("deck") is not True or res.get("zone") is not True or len(moved) != n:
        return None, t("blind.why_table")
    return moved, ""
