"""George Washington's ESPIONAGE at the live table (docs/heroes/george-washington.md).

"When you attack, you may use a ruse token, placing it next to the card. Before your opponent chooses whether or not to defend, they may
discard 1 random card to remove the ruse token." The engine does it in the `attacked` event (effects file: the triggers `espionage` and
`espionage_remove`); this module is the session's side of the two seats.

The human is Washington. The attack card lies face down, so the question "a ruse token on this attack?" is asked at Reveal, before the
bot chooses its defense, with the panel buttons (the same slot Perfect Shot's prediction uses: `Pending.predict`, answered by
`answer_prediction`, which calls Reveal again). The answer is kept in `Pending.prediction["ruse"]` and given to the `attacked` event through
`RuseChooser`; the bot, the opponent, decides whether to discard a random card with its own AI before it defends, and the chat says what
it did. The token goes next to the card by the human's hand: the chat says when.

The bot is Washington. Its attack card is placed face down; the `attacked` event is raised then (`bot_attack_placed`): the bot decides
whether to put a token on it, a copy of the stack of Ruse tokens is laid on the table (the engine counter `ruse`, translated like Abe's
tokens), and the human is asked, on the panel, whether to discard 1 random card to remove it: a parked decision like any other trigger of the
bot's that asks the human something. The discard is the one of the random-discard route (the bot says the position, counted from the left)."""
from __future__ import annotations

from .ai_washington import is_washington, ruse_on, tokens
from .effects.choose import ChoiceRequest
from .i18n import plural, t
from .tts.lua import ChatKind

KEY = "ruse"                   # key of the human's request (outside any run); the prediction slot tells it from Perfect Shot's
USE = "use"                    # the `washington` extra of the plugin's request that asks the attacker


def human_washington(session) -> bool:
    return is_washington(session.game, session.human)


def bot_washington(session) -> bool:
    return is_washington(session.game, session.bot)


def _carries_ruse(card) -> bool:
    return card is not None and "ruse" in card.tags


# ---------------------------------------------------------------- the human attacks as Washington

def ruse_request(session, p, card) -> ChoiceRequest | None:
    """The yes/no the human sees at Reveal: a token on an attack card that carries a ruse effect, while the supply has one and none lies
    on a card yet. None when there is nothing to ask (another hero, a card without a ruse, no token, an attack already declared)."""
    g = session.game
    if not human_washington(session) or not g.fx.interprets(session.human) or p.declared is not None:
        return None
    if not _carries_ruse(card) or tokens(g, session.human) < 1 or ruse_on(g, session.human):
        return None
    return ChoiceRequest("optional", session.human, [True, False], 1, 1, None, KEY, "use a ruse token on this attack?",
                         {"washington": USE, "ruse_card": card.card_id}, session.human)


def is_ruse_request(raw: dict | None) -> bool:
    return isinstance(raw, dict) and raw.get("key") == KEY


def answered(session, p, value: list) -> None:
    """The human pressed Yes or No: the decision is kept for the `attacked` event Reveal raises next."""
    use = bool(value[0])
    p.predict = None
    p.prediction = {"value": None, "ruse": use}
    session.say(t("espionage.you_use" if use else "espionage.you_keep"), ChatKind.ATTACK)


class RuseChooser:
    """Answers Washington's question to the human with what they pressed at Reveal; everything else goes to the usual chooser."""

    def __init__(self, inner, use: bool):
        self.inner, self.use = inner, use

    def choose(self, game, req):
        if req.extra.get("washington") == USE:
            return [self.use]
        return self.inner.choose(game, req)


def emit_attacked(session, p, card) -> None:
    """Raises the human's attack's `attacked` event. With Washington on the human's side the ruse answer is given and the chat tells what
    happened (the token went on, the bot took it off by discarding a card); the bot's discard reaches the table in the same step.
    Without him it is the bare event."""
    g = session.game
    if not human_washington(session) or not _carries_ruse(card):
        g.fx.emit("attacked", p.attacker, p.target, card)
        return
    use = bool((p.prediction or {}).get("ruse", False))
    bot_hand = len(g.players[session.bot].hand)
    left, choosers = tokens(g, session.human), g.fx.choosers
    g.fx.choosers = {**(choosers or session._choosers()), session.human: RuseChooser((choosers or session._choosers())[session.human], use)}
    try:
        g.fx.emit("attacked", p.attacker, p.target, card)
    finally:
        g.fx.choosers = choosers
    if not use:
        return
    name = session._name(g.hero(session.human))
    if ruse_on(g, session.human):
        session.say(t("espionage.placed", name=name, card=card.title, left=tokens(g, session.human)), ChatKind.ATTACK)
    else:
        session.say(t("espionage.removed_by_bot", name=name, left=tokens(g, session.human)), ChatKind.ATTACK)
    if len(g.players[session.bot].hand) < bot_hand:          # the random card the bot gave up
        session._mark_dirty()
        session._flush_table()


# ---------------------------------------------------------------- the bot attacks as Washington

def bot_attack_placed(session, p) -> None:
    """The bot's attack card is on the table face down. Raises the `attacked` event if nothing did yet (the bot decides the token there),
    lays the token copy, says what the bot did and, when the trigger asked the human something, shows the question."""
    g = session.game
    if not bot_washington(session) or not _carries_ruse(p.bot_card):
        return
    from . import session_bot_effects as bot_effects
    before = bot_effects.snapshot(session)
    if p.declared is None:
        p.declared = {"counters": dict(g.fx.counters[session.bot]), "revealed": False}
        g.fx.emit("attacked", p.attacker, p.target, p.bot_card)
    else:                                              # another trigger raised the event already (Abe's UNCANNY INTUITION)
        before["counters"] = dict(p.declared["counters"])
    if ruse_on(g, session.bot):
        session.say(t("espionage.bot_places", name=session._name(g.hero(session.bot)),
                      left=tokens(g, session.bot)), ChatKind.ATTACK)
    fin = session._project_effects(before)
    session._flush_table()
    fin()
    p.declared["counters"] = dict(g.fx.counters[session.bot])      # the diff of the end of the combat starts from the token on the card
    if (paused := session._paused()) is not None:
        session._show_choice(paused[2].awaiting)


def tokens_line(session) -> str:
    """'3 ruse tokens' for the chat."""
    return plural(tokens(session.game, session.human), "noun.token")
