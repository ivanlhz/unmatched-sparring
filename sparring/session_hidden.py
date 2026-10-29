"""Hidden-information cards at the live table, both sides (E3).

The human's side. When a card of the human lets them look at the bot's hand (the `look_hand` op on the opponent
inside Confront Any Demon or God, Advanced Psychometry, Every Possible Angle, Remove A Painful Memory), the bot
puts its hand face up in a row at `look_spot` and pings it (Ivan, 28/10). The look happens exactly when the
interpreter runs the op, so its conditions (Confront only when lost, Psychometry only when adjacent) are the
engine's, not the panel's: `Game.hand_reader` is the one hook (`note_look`), and the row goes out at the end of
the same button (`after_step`). If the card then asks the human to pick one of those cards (the PanelChooser
pause of a `cards` request over the bot's hand), the human answers by pinging the card (Tab) or by pressing its
button (the bot's cards can be named on the panel); the row closes with the chosen card where the engine put it
(the discard pile, the top of the bot's deck, or back in the hand when the bot kept it) and the rest back in the
hand. A look without a pick (Advanced Psychometry) is a reveal: the row shows until Fin de accion or Cancelar
returns it. E1's grant-a-button route stays for a hero outside the interpreter.

Perfect Shot. The prediction belongs to the moment the card is played, before the defense. The human is asked at
Revelar, before the bot chooses its defense (`PredictionWait`, saved in `Pending.predict`); the bot decides with
`ai_effects.predict_value` when it places the card, plays it face up and announces it. Either way the value
reaches the IMMEDIATELY run through `PredictionChooser`, which answers the plugin's request.

UNCANNY INTUITION. An attack against an Abe with an active token is played face up; the ability is read from its
trigger (`attacked` + `reveal attack_card` + its condition), never from a card name. Bot attacking the human's
Abe: the card is flipped when placed and named. Human attacking the bot's Abe: the attack card is the one thing
the bot's defense may know (`attack_card`); the human puts it face down as always and it is turned at Revelar."""
from __future__ import annotations

from .effects.choose import ChoiceRequest
from .effects.model import EffectError, load_effects, walk_ops
from .effects.ops_combat import FACE_DOWN, PERFECT_SHOT, PREDICT_OP, PREDICT_VALUES
from .effects.run import Ctx, EffectRun
from .effects.select import condition
from .tts import lua
from .tts.client import TTSLuaError
from .tts.lua import ChatKind

MODE_PICK = "pick"          # the row waits for the human's choice (a pending `cards` request over the bot's hand)
MODE_REVEAL = "reveal"      # the row is only to be looked at
DOMAIN = "fx"               # queue domain of the row writes: no read of the session flushes them early
PREDICT_KEY = "predict"     # key of the human's prediction request (outside any run)
_ERRORS = (TTSLuaError, OSError)


def interpreted(game, player: int) -> bool:
    """`player`'s hero runs on the effects interpreter (its cards resolve in the engine, the panel asks)."""
    heroes = game.fx.dsl_heroes
    return bool(heroes) and game.players[player].hero.slug in heroes


# ---------------------------------------------------------------- the human looks at the bot's hand

def note_look(session, player: int) -> None:
    """`Game.hand_reader` was asked for `player`'s hand: for the bot's it is the human looking at it (a card of the
    human says so), and the row goes out when the button ends."""
    if player == session.bot:
        session.reveal_bot_hand = True


def bot_hand_request(session) -> ChoiceRequest | None:
    """The pending decision of the human, when it is a pick among the bot's hand cards."""
    run = session.effect_run
    req = None if run is None else run.awaiting
    if req is None or req.kind != "cards" or req.player != session.human:
        return None
    if req.extra.get("zone") != "hand" or req.extra.get("of") != session.bot:
        return None
    return req


def after_step(session) -> None:
    """End of a button: a look the human's card took this step puts the bot's hand on the table."""
    if not session.reveal_bot_hand:
        return
    session.reveal_bot_hand = False
    if session.look is not None or session.game.winner is not None:
        return
    show_row(session, bot_hand_request(session))


def show_row(session, req: ChoiceRequest | None) -> None:
    """The bot's hand face up in the row, pinged. With `req` the row waits for the human's pick (ping or button);
    without it the row is a reveal."""
    g, cfg = session.game, session.cfg
    st = g.players[session.bot]
    by_id = {c.card_id: c for c in st.full_set}
    hand_ids = [c.card_id for c in st.hand]
    if req is not None and sorted(req.options) != sorted(hand_ids):
        # the bot drew in this very step (Evade, Exploit) and the request was built with a placeholder for the card
        # the table had not dealt yet; the hand was re-identified since, and the op reruns on it once answered
        req.options = hand_ids
    wanted = set(hand_ids)
    table_hand = session._table_hand_ids()
    rows = [r for r in session._rd_bot_hand() if r["id"] in wanted and r["id"] in by_id][:lua.MAX_LOOK_CARDS]
    if not rows:
        session.say("Miras la mano del bot: no tiene cartas en la mano." if not wanted else
                    "Miras la mano del bot, pero no veo sus cartas en la mesa: pidele que las muestre.", ChatKind.WARNING)
        return
    ids = [r["id"] for r in rows]
    spots = session._look_spots(len(rows))
    if cfg.batch:
        session._expect_hand = (cfg.bot_seat, len(table_hand) - len(rows))
    op = session._w(lua.show_hand_row(ids, spots, session._look_rot(), cfg.bot_seat, identity=session._identity(),
                                      id_range=cfg.bot_card_ids), DOMAIN)
    session._w(lua.ping_points([cfg.bot_seat, cfg.human_seat], spots[:lua.MAX_PING_GROUPS]), "misc")
    session.look = {"ids": ids, "guids": [r["guid"] for r in rows], "spots": [[sp[0], sp[2]] for sp in spots],
                    "mode": MODE_PICK if req is not None else MODE_REVEAL}
    session.look_fails = 0
    session.revoke_look()                        # the card itself showed the hand: no button to press
    session._post.append(lambda: session._look_shown(op))
    if req is not None:
        session.say(f"El bot pone su mano boca arriba ({len(rows)} cartas) y hace ping: elige una con ping (Tab) "
                    "sobre la carta o con su boton del panel.", ChatKind.YOUR_TURN)
    else:
        session.say(f"El bot pone su mano boca arriba ({len(rows)} cartas) y hace ping: solo miras. Pulsa Fin de "
                    "accion o Cancelar y la recoge.", ChatKind.YOUR_TURN)
    for n, r in enumerate(rows, 1):
        session.say(session._card_line(n, by_id[r["id"]]), ChatKind.SCHEME)


def look_status(session) -> str:
    mode = session.look.get("mode")
    if mode == MODE_PICK:
        return "Mano del bot a la vista: Tab sobre la carta que eliges, o su boton"
    if mode == MODE_REVEAL:
        return "Mano del bot a la vista: Fin de accion o Cancelar la recoge"
    return "Mano del bot a la vista: Tab sobre la carta a descartar o Cancelar"


def resume_prompt(session) -> str:
    mode = session.look.get("mode")
    if mode == MODE_PICK:
        return "La mano del bot sigue a la vista: elige una carta con ping (Tab) o con su boton del panel."
    if mode == MODE_REVEAL:
        return "La mano del bot sigue a la vista (solo mirar): pulsa Fin de accion o Cancelar y la recoge."
    return "La mano del bot sigue a la vista: haz ping (Tab) sobre la carta a descartar o pulsa Cancelar."


def ping(session, guid: str) -> bool:
    """A ping on a row card: answers the pending pick when the row waits for one, refuses it on a reveal. False
    when the row is E1's (the caller discards the card as before)."""
    look = session.look
    mode = look.get("mode")
    if mode == MODE_REVEAL:
        session.say("Esta vez solo miras: pulsa Fin de accion o Cancelar y el bot recoge su mano.", ChatKind.WARNING)
        return True
    if mode != MODE_PICK:
        return False
    req = bot_hand_request(session)
    card_id = look["ids"][look["guids"].index(guid)]
    if req is None or card_id not in req.options:
        session.say("Esa carta no se puede elegir ahora.", ChatKind.WARNING)
        return True
    session._answer_choice(session._paused(), [card_id])
    return True


def close_row(session, value: list, ok: bool) -> None:
    """The human's pick was answered and the engine moved the card: the row closes to match (the chosen card to
    the bot's discard pile, to the top of its deck, or back to its hand), the rest back to the hand."""
    look = session.look
    if look is None or look.get("mode") != MODE_PICK or not ok:
        return
    g, cfg, st = session.game, session.cfg, session.game.players[session.bot]
    by_id = {c.card_id: c for c in st.full_set}
    card = by_id.get(value[0]) if value else None
    dest, guid, spot = "hand", None, (0.0, 0.0, 0.0)
    if card is not None and card in st.discard:
        dest, spot = "discard", session._discard_slot([c.card_id for c in st.discard].index(card.card_id))
    elif card is not None and st.deck[:1] == [card]:
        dest = "deck"
    if dest != "hand":
        guid = look["guids"][look["ids"].index(card.card_id)]
    session.look = None
    if cfg.batch:
        session._expect_hand = (cfg.bot_seat, len(look["ids"]) - (1 if guid else 0))
    op = session._w(lua.resolve_hand_row(look["guids"], cfg.bot_seat, identity=session._identity(),
                                         id_range=cfg.bot_card_ids, discard=guid, spot=spot,
                                         rot_y=cfg.bot_discard_rot_y,
                                         deck_guid=cfg.bot_deck_guid if dest == "deck" else None), DOMAIN)
    if dest == "discard":
        session.bot_discarded.add(card.card_id)   # the reconciliation of this same script must not move it again
    session._post.append(lambda: _row_closed(session, op, card, dest, look))
    if dest == "discard":
        session.say(f"El bot descarta {card.title} y devuelve el resto de su mano.", ChatKind.SCHEME)
    elif dest == "deck":
        session.say(f"{card.title} va a la parte superior del mazo del bot; el resto vuelve a su mano.", ChatKind.SCHEME)
    elif card is not None:
        session.say(f"El bot se queda {card.title} y recoge su mano.", ChatKind.SCHEME)
    else:
        session.say("El bot recoge su mano.", ChatKind.NEUTRAL)


def _row_closed(session, op, card, dest: str, look: dict) -> bool:
    """Check at the end of the button: the table did what the engine already counted. If not, the table wins at
    the next read (the bot's discard debt is reconciled, the rest is asked by hand)."""
    try:
        res = op.result or {}
        done = res.get("discarded") == card.card_id if dest != "hand" else bool(res.get("found"))
        fail = None if done else "esa carta no estaba en la fila de la mesa"
    except _ERRORS as e:
        fail = f"error: {e}"
    if fail is None and dest == "discard" and not session._settle(lambda: card.card_id in session._table_discard()):
        fail = f"{card.title} aun no se ve en el descarte del bot"
    if fail is not None:
        if dest == "discard":
            session.bot_discarded.discard(card.card_id)
        session._mark_dirty()
        where = {"discard": f" y pon {card.title} en su descarte", "deck": f" y pon {card.title} en la parte superior de su mazo",
                 "hand": ""}[dest]
        session.say(f"La mesa no cerro la fila del bot ({fail}): recoge sus cartas a su mano{where}; pulsa Fin de "
                    "accion para sincronizar.", ChatKind.WARNING)
        return False
    session.read_bot_hand()
    return True


# ---------------------------------------------------------------- Perfect Shot: the prediction

def _has_plugin(game, player: int, card, plugin_id: str, moment: str = "immediately") -> bool:
    try:
        ops = load_effects(game.players[player].hero.slug).moment_ops(card.title, moment)
    except EffectError:
        return False
    return any(o["op"] == "plugin" and o.get("id") == plugin_id for o in walk_ops(ops))


def prediction_request(game, player: int, card) -> ChoiceRequest | None:
    """The human's prediction buttons for a Perfect Shot: the same options the plugin asks for."""
    if not interpreted(game, player) or not _has_plugin(game, player, card, PERFECT_SHOT):
        return None
    return ChoiceRequest("effect", player, [*PREDICT_VALUES, FACE_DOWN], 1, 1, card.card_id, PREDICT_KEY,
                         "predict the printed value of the opponent's card, or play face down",
                         {"op": PREDICT_OP, "face_down": FACE_DOWN})


class PredictionWait:
    """What `Session._paused` hands the panel while the human predicts at Revelar (no EffectRun behind it)."""

    def __init__(self, request: ChoiceRequest):
        self.awaiting = request


def prediction_wait(p) -> PredictionWait | None:
    return None if p is None or p.predict is None else PredictionWait(ChoiceRequest.from_dict(p.predict))


def ask_prediction(session, p, card) -> bool:
    """At Revelar, before the bot's defense: True when the human still has to predict (the buttons are up)."""
    if p.prediction is not None:
        return False
    req = prediction_request(session.game, session.human, card)
    if req is None:
        return False
    p.predict = req.to_dict()
    session.say(f"{card.title}: predice el valor impreso de la carta del bot (la juegas boca arriba) o juegala boca "
                "abajo, con los botones del panel. El bot elige su defensa despues.", ChatKind.YOUR_TURN)
    session._show_choice(req)
    return True


def answer_prediction(session, p, value: list) -> None:
    v = value[0]
    p.prediction, p.predict = {"value": None if v == FACE_DOWN else v}, None
    if v == FACE_DOWN:
        session.say("Juegas la carta boca abajo: sin prediccion.", ChatKind.NEUTRAL)
    else:
        session.say(f"Predices que la carta del bot tiene valor impreso {v}: tu carta se juega boca arriba.", ChatKind.ATTACK)
    session._reveal({})


class PredictionChooser:
    """Answers the Perfect Shot plugin with the value decided when the card was played; everything else goes to
    the owner's usual chooser."""

    def __init__(self, inner, value: int | None):
        self.inner, self.value = inner, value

    def choose(self, game, req: ChoiceRequest):
        if req.extra.get("op") == PREDICT_OP:
            return [FACE_DOWN if self.value is None else self.value]
        return self.inner.choose(game, req)


def flow_choosers(session, p) -> dict:
    choosers = session._choosers()
    if p.prediction is not None:
        owner = session.human if p.kind == "human_attacks" else session.bot
        choosers[owner] = PredictionChooser(choosers[owner], p.prediction["value"])
    return choosers


# ---------------------------------------------------------------- UNCANNY INTUITION: the attack played face up

def attack_revealed(game, target) -> bool:
    """`target`'s hero has an ability that, attacked now, turns the attack card face up (an `attacked` trigger with
    a `reveal` of `attack_card` whose condition holds: an active Intuition token)."""
    owner = target.owner
    if not interpreted(game, owner) or target is not game.hero(owner):
        return False
    try:
        triggers = load_effects(game.players[owner].hero.slug).triggers
    except EffectError:
        return False
    run = EffectRun([], Ctx(owner=owner, this_fid=target.fid))
    for t in triggers:
        when = t.get("when") or {}
        if when.get("event") != "attacked" or when.get("target", "hero") != "hero":
            continue
        if not any(o["op"] == "reveal" and o.get("cards") == "attack_card" for o in walk_ops(t.get("ops") or [])):
            continue
        cond = t.get("condition")
        if cond is None or condition(game, run, cond):
            return True
    return False


def intuition_notice(session, target) -> None:
    """The human attacks the bot's Abe with an active token: the attack will be played face up."""
    if attack_revealed(session.game, target):
        session.say(f"UNCANNY INTUITION: {session._name(target)} tiene una ficha activa: la gasta, roba 1 carta y tu "
                    "ataque se juega boca arriba. Pon tu carta boca abajo como siempre y pulsa Revelar: la giro y "
                    "el bot elige su defensa viendola.", ChatKind.ATTACK)


def revealed_attack(session, p, card):
    """The human's attack card the bot's defense may know, or None."""
    return card if p.kind == "human_attacks" and attack_revealed(session.game, p.target) else None


# ---------------------------------------------------------------- the bot's attack played face up

def bot_attack_placed(session, p) -> None:
    """The bot's attack card is on the table face down. Perfect Shot (the bot predicts and announces) or the
    human Abe's UNCANNY INTUITION turn it face up in the same step."""
    from .ai_effects import predict_value
    g, card = session.game, p.bot_card
    lines = []
    if _has_plugin(g, session.bot, card, PERFECT_SHOT):
        n = predict_value(g, session.bot)
        p.prediction = {"value": n}
        lines.append(f"El bot juega {card.title} boca arriba y predice que el valor impreso de tu carta es {n}.")
    if attack_revealed(g, p.target):
        lines.append(f"UNCANNY INTUITION: {session._name(p.target)} tiene una ficha activa: gastas una, robas 1 carta "
                     f"(hazlo en la mesa) y el ataque del bot se juega boca arriba: {card.title} (valor {card.value}).")
    if not lines:
        return
    if p.bot_card_guid:
        session._w(session._flip_script(p.bot_card_guid, "bot"), "flip")
    for line in lines:
        session.say(line, ChatKind.ATTACK)
