"""Pandora's Box at the table (docs/heroes/pandora.md): what the chat says of the Miseries.

The engine reports each reveal, a look (HOPE) and the stop as intents (`pandora_reveal`, `pandora_look`, `pandora_stop`, from
`effects/plugins_pandora.py`). The bot's Box is virtual (the engine draws the Miseries), so the chat names each one and what it does; the
pieces and dials it moves (a Kakodaemon in her zone, the damage) follow the usual projection. The human's Box is the real deck on the table:
they reveal the cards and the panel asks which one came up, so the chat adds nothing: the line of the trigger already says the damage ("Pandora -3 PV")."""
from __future__ import annotations

from .effects import plugins_pandora as box
from .i18n import t
from .session_translators import BOT, HUMAN, Ctx, register
from .tts.lua import ChatKind


def _mode(session, intent: dict) -> str:
    return BOT if intent["owner"] == session.bot else HUMAN


def _nothing(session, intent: dict, ctx: Ctx) -> list:
    return []


def _hero(session, intent: dict) -> str:
    return session._name(session.game.hero(intent["owner"]))


@register("pandora_reveal", mode=_mode, human=_nothing)
def _reveal_bot(session, intent: dict, ctx: Ctx) -> list:
    misery = t("pandora.misery." + box.NAMES[intent["idx"]].lower())
    session.say(t("tr.pandora.reveal", hero=_hero(session, intent), misery=misery, feathers=intent["feathers"]), ChatKind.ABILITY)
    return []


@register("pandora_look", mode=_mode, human=_nothing)
def _look_bot(session, intent: dict, ctx: Ctx) -> list:
    session.say(t("tr.pandora.hope_bot", hero=_hero(session, intent)), ChatKind.ABILITY)
    return []


@register("pandora_stop", mode=_mode, human=_nothing)
def _stop_bot(session, intent: dict, ctx: Ctx) -> list:
    if intent["damage"]:
        session.say(t("tr.pandora.stop_damage", hero=_hero(session, intent), feathers=intent["feathers"], damage=intent["damage"]),
                    ChatKind.ABILITY)
    else:
        session.say(t("tr.pandora.stop", hero=_hero(session, intent)), ChatKind.ABILITY)
    return []
