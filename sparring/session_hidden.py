"""Hidden-information cards at the live table, both sides (E3).

The human's side. When a card of the human lets them look at the bot's hand (the `look_hand` op on the opponent
inside Confront Any Demon or God, Advanced Psychometry, Every Possible Angle, Remove A Painful Memory), the bot
puts its hand face up in a row at `bot_row_spot` (free table beside its combat and ongoing zones) and pings it (Ivan, 28/10). The look happens exactly when the
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
reaches the IMMEDIATELY run through `PredictionChooser`, which answers the plugin's request. A Perfect Shot the
human plays face up is public: the bot's defense knows it (Ivan, 29/10).

UNCANNY INTUITION. An attack against an Abe with an active token is played face up; the ability is read from its
trigger (`effects.events.attack_revealed`: `attacked` + `reveal attack_card` + its condition), never from a card
name. Bot attacking the human's Abe: the card is flipped when placed and named. Human attacking the bot's Abe:
`declare_attack` keeps the engine's order at Revelar (the event first, so the token is spent and the drawn card is
dealt before the defense is chosen, and the drawn card may be it), and the attack card is the one thing the bot's
defense may know (`attack_card`); the human puts it face down as always and it is turned at Revelar."""
from __future__ import annotations

from .effects.choose import ChoiceRequest
from .effects.events import attack_revealed
from .effects.model import EffectError, load_effects, walk_ops
from .effects.ops_combat import FACE_DOWN, PERFECT_SHOT, PREDICT_OP, PREDICT_VALUES
from .i18n import plural, t
from .tts import lua
from .tts.client import TTSLuaError
from .tts.lua import ChatKind

MODE_PICK = "pick"          # the row waits for the human's choice (a pending `cards` request over the bot's hand)
MODE_REVEAL = "reveal"      # the row is only to be looked at
DOMAIN = "fx"               # queue domain of the row writes: no read of the session flushes them early
PREDICT_KEY = "predict"     # key of the human's prediction request (outside any run)
_ERRORS = (TTSLuaError, OSError)


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
    if (req := manual_request(session)) is not None:
        manual_start(session, req)
        return
    show_row(session, bot_hand_request(session))


# ---------------------------------------------------------------- look at the bot's hand and make it discard (manual)
# Confront Any Demon or God and every card shaped "look at the opponent's hand and choose N cards for them to
# discard". The human does it on the table himself (Ivan, 30/10); the bot only validates the result at "Hecho".

def manual_request(session) -> ChoiceRequest | None:
    """The pending pick when it is a discard from the bot's hand (a look-and-discard card)."""
    req = bot_hand_request(session)
    return req if req is not None and req.extra.get("purpose") == "discard" else None


def manual_start(session, req: ChoiceRequest) -> None:
    session.say(t("hidden.start", cards=plural(req.max, "noun.card")), ChatKind.YOUR_TURN)


def manual_status(session) -> str:
    return t("hidden.status")


def manual_view(session) -> tuple[dict, dict]:
    """The choice slots while the human acts on the table: a single Hecho button."""
    from .session_choices import CHOICE_IDS
    states = {ident: (False, False) for ident in CHOICE_IDS}
    states[CHOICE_IDS[0]] = (True, True)
    return states, {CHOICE_IDS[0]: t("btn.done")}


def _titles(session, ids) -> str:
    from .session_choices import card_titles
    return card_titles(session.game, sorted(ids))


def manual_verdict(session) -> tuple[int | None, str | None]:
    """(CardID, None) when the table shows exactly the one allowed discard, else (None, what is wrong). Reads the
    snapshot only: the engine's hand and pile are the baseline (the bot's own writes of this step are already there)."""
    from collections import Counter
    st = session.game.players[session.bot]
    own = {c.card_id for c in st.full_set}
    expected_hand = Counter(c.card_id for c in st.hand)
    expected_pile = Counter(c.card_id for c in st.discard)
    table_hand = Counter(session._table_hand_ids())
    table_pile = Counter(r["id"] for r in session._rd_bot_discard())
    new_pile = table_pile - expected_pile
    out_of_hand = expected_hand - table_hand
    foreign = [i for i in new_pile if i not in own]
    if foreign:
        return None, t("hidden.foreign", titles=_titles(session, foreign))
    extra_in_hand = table_hand - expected_hand
    if extra_in_hand:
        return None, t("hidden.extra_in_hand", titles=_titles(session, extra_in_hand.elements()))
    n = sum(new_pile.values())
    if n > 1:
        return None, t("hidden.too_many", n=n, titles=_titles(session, new_pile.elements()))
    missing = out_of_hand - new_pile
    if missing:
        return None, t("hidden.missing", titles=_titles(session, missing.elements()))
    if n == 0:
        return None, t("hidden.nothing_yet")
    unseen = new_pile - out_of_hand
    if unseen:
        return None, t("hidden.unseen", titles=_titles(session, unseen.elements()))
    return next(iter(new_pile)), None


def manual_done(session, paused) -> None:
    """Hecho: validate; only a valid table reaches the engine. A wrong one changes nothing and says why."""
    cid, why = manual_verdict(session)
    if cid is None:
        session.say(why, ChatKind.WARNING)
        return
    st = session.game.players[session.bot]
    card = next(c for c in st.full_set if c.card_id == cid)
    guid = next((r.get("guid") for r in session._rd_bot_discard() if r["id"] == cid), None)
    # the card is already on the pile: the reconciliation must not move it. Set before the answer (the combat closes
    # inside it), taken back and not announced if the engine refuses the answer.
    had_discarded, had_flight = cid in session.bot_discarded, cid in session.fx_in_flight
    session.bot_discarded.add(cid)
    session.fx_in_flight.add(cid)
    session._answer_choice(paused, [cid])
    if manual_request(session) is not None:      # refused (rolled back): still waiting, nothing was discarded
        if not had_discarded:
            session.bot_discarded.discard(cid)
        if not had_flight:
            session.fx_in_flight.discard(cid)
        return
    session.say(t("hidden.discards", card=card.title), ChatKind.SCHEME)
    if manual_request(session) is None and card not in st.discard:   # answered, and the engine kept it (Wildfire returns a burning card): back to the hand
        session.bot_discarded.discard(cid)
        if guid:
            session._w(lua.return_card_to_hand(guid, session.cfg.bot_seat), "cards")
        session.say(t("hidden.keeps_wildfire", card=card.title), ChatKind.SCHEME)


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
        session.say(t("hidden.empty_hand" if not wanted else "hidden.not_visible"), ChatKind.WARNING)
        return
    ids = [r["id"] for r in rows]
    spots = session._look_spots(len(rows), card_row=True)
    if cfg.batch:
        session._expect_hand = (cfg.bot_seat, len(table_hand) - len(rows))
    op = session._w(lua.show_hand_row(ids, spots, session._look_rot(), cfg.bot_seat, identity=session._identity(),
                                      id_range=cfg.bot_card_ids), DOMAIN)
    session._w(lua.ping_points([cfg.bot_seat, cfg.human_seat], spots[:lua.MAX_PING_GROUPS]), "misc")
    session.look = {"ids": ids, "guids": [r["guid"] for r in rows], "spots": [[sp[0], sp[2]] for sp in spots],
                    "mode": MODE_PICK if req is not None else MODE_REVEAL,
                    "hp": {f.fid: f.hp for f in g.own(session.bot, alive_only=False)}}      # what the pick may cost
    if req is not None and isinstance(req.extra.get("purpose"), str):
        session.look["purpose"] = req.extra["purpose"]      # "discard": the pick is discarded (Wildfire may bounce it)
    session.look_fails = 0
    session.revoke_look()                        # the card itself showed the hand: no button to press
    session._post.append(lambda: session._look_shown(op))
    if req is not None:
        session.say(t("hidden.row_pick", n=len(rows)), ChatKind.YOUR_TURN)
    else:
        session.say(t("hidden.row_reveal", n=len(rows)), ChatKind.YOUR_TURN)
    for n, r in enumerate(rows, 1):
        session.say(session._card_line(n, by_id[r["id"]]), ChatKind.SCHEME)


def row_failed_text(look: dict) -> str:
    """The table took no card out of the bot's hand: what the human does instead."""
    mode = look.get("mode")
    if mode == MODE_PICK:
        return t("hidden.row_failed.pick")
    if mode == MODE_REVEAL:
        return t("hidden.row_failed.reveal")
    return t("hidden.row_failed.grant")


def look_status(session) -> str:
    mode = session.look.get("mode")
    if mode == MODE_PICK:
        return t("hidden.look_status.pick")
    if mode == MODE_REVEAL:
        return t("hidden.look_status.reveal")
    return t("hidden.look_status.grant")


def resume_prompt(session) -> str:
    mode = session.look.get("mode")
    if mode == MODE_PICK:
        return t("hidden.resume.pick")
    if mode == MODE_REVEAL:
        return t("hidden.resume.reveal")
    return t("hidden.resume.grant")


def ping(session, guid: str) -> bool:
    """A ping on a row card: answers the pending pick when the row waits for one, refuses it on a reveal. False
    when the row is E1's (the caller discards the card as before)."""
    look = session.look
    mode = look.get("mode")
    if mode == MODE_REVEAL:
        session.say(t("hidden.ping_reveal"), ChatKind.WARNING)
        return True
    if mode != MODE_PICK:
        return False
    req = bot_hand_request(session)
    card_id = look["ids"][look["guids"].index(guid)]
    if req is None or card_id not in req.options:
        session.say(t("hidden.ping_not_now"), ChatKind.WARNING)
        return True
    session._answer_choice(session._paused(), [card_id])
    return True


def close_row(session, value: list, ok: bool) -> None:
    """The human's pick was answered and the engine moved the card: the row closes to match (the chosen card to
    the bot's discard pile, to the top of its deck, or back to its hand), the rest back to the hand."""
    look = session.look
    if look is None or look.get("mode") != MODE_PICK or not ok:
        return
    from .ai_effects import bounces_back
    g, cfg, st = session.game, session.cfg, session.game.players[session.bot]
    by_id = {c.card_id: c for c in st.full_set}
    card = by_id.get(value[0]) if value else None
    dest, spot = "hand", (0.0, 0.0, 0.0)
    if card is not None and card in st.discard:
        dest, spot = "discard", session._discard_slot([c.card_id for c in st.discard].index(card.card_id))
    elif card is not None and st.deck[:1] == [card]:
        dest = "deck"
    # a card the table could not take out of the hand (a partial row) is picked by its button and still sits in
    # the bot's hand: the row returns what it holds and the discard reaches the pile through the reconciliation
    in_row = card is not None and card.card_id in look["ids"]
    guid = look["guids"][look["ids"].index(card.card_id)] if in_row and dest != "hand" else None
    session.look = None
    if cfg.batch:
        session._expect_hand = (cfg.bot_seat, len(look["ids"]) - (1 if guid else 0))
    op = session._w(lua.resolve_hand_row(look["guids"], cfg.bot_seat, identity=session._identity(),
                                         id_range=cfg.bot_card_ids, discard=guid, spot=spot,
                                         rot_y=cfg.bot_discard_rot_y,
                                         deck_guid=cfg.bot_deck_guid if guid and dest == "deck" else None), DOMAIN)
    if guid and dest == "discard":
        session.bot_discarded.add(card.card_id)   # the reconciliation of this same script must not move it again
    if guid:
        session.fx_in_flight.add(card.card_id)    # nor the projection of a human scheme's step (E2): the row moved it
    session._post.append(lambda: _row_closed(session, op, card, dest if guid else "hand", look))
    if dest == "discard":
        session.say(t("hidden.close.discard_row" if in_row else "hidden.close.discard_hand", card=card.title),
                    ChatKind.SCHEME)
    elif dest == "deck":
        session.say(t("hidden.close.deck_row" if in_row else "hidden.close.deck_hand", card=card.title), ChatKind.SCHEME)
    elif card is not None and look.get("purpose") == "discard" and bounces_back(g, session.bot, card):
        session.say(t("hidden.close.wildfire_kept", card=card.title), ChatKind.SCHEME)
    elif card is not None and (hits := _hits_taken(g, session.bot, look)):
        session.say(t("hidden.close.kept_hits", card=card.title, hits=hits), ChatKind.SCHEME)
    elif card is not None and bounces_back(g, session.bot, card):
        session.say(t("hidden.close.discard_bounce", card=card.title), ChatKind.SCHEME)
    elif card is not None:
        session.say(t("hidden.close.kept", card=card.title), ChatKind.SCHEME)
    else:
        session.say(t("hidden.close.collect"), ChatKind.NEUTRAL)


def _hits_taken(game, player: int, look: dict) -> str:
    """'Liz Sherman recibe 2 de dano' for the hit points the bot's fighters lost since the row opened (the pick's
    price when the bot kept the card), else ''."""
    lost = [(f.name, before - max(0, f.hp if f.alive else 0)) for f in game.own(player, alive_only=False)
            if (before := look.get("hp", {}).get(f.fid)) is not None]
    return t("common.and").join(t("hidden.hit", name=name, n=n) for name, n in lost if n > 0)


def _row_closed(session, op, card, dest: str, look: dict) -> bool:
    """Check at the end of the button: the table did what the engine already counted. If not, the table wins at
    the next read (the bot's discard debt is reconciled, the rest is asked by hand)."""
    try:
        res = op.result or {}
        done = res.get("discarded") == card.card_id if dest != "hand" else bool(res.get("found"))
        fail = None if done else t("hidden.fail.not_in_row")
    except _ERRORS as e:
        fail = t("hidden.fail.error", error=e)
    if fail is None and dest == "discard" and not session._settle(lambda: card.card_id in session._table_discard()):
        fail = t("hidden.fail.not_in_discard", card=card.title)
    if fail is not None:
        session.restore_row_hands(look["guids"])
        if dest == "discard":
            session.bot_discarded.discard(card.card_id)
        session._mark_dirty()
        where = "" if dest == "hand" else t(f"hidden.fail.where_{dest}", card=card.title)
        session.say(t("hidden.fail.row", fail=fail, where=where), ChatKind.WARNING)
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
    if not game.fx.interprets(player) or not _has_plugin(game, player, card, PERFECT_SHOT):
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
    session.say(t("hidden.ask_prediction", card=card.title), ChatKind.YOUR_TURN)
    session._show_choice(req)
    return True


def answer_prediction(session, p, value: list) -> None:
    v = value[0]
    p.prediction, p.predict = {"value": None if v == FACE_DOWN else v}, None
    if v == FACE_DOWN:
        session.say(t("hidden.face_down"), ChatKind.NEUTRAL)
    else:
        session.say(t("hidden.predicted", value=v), ChatKind.ATTACK)
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


# ---------------------------------------------------------------- the human's attack the bot's defense may know

def intuition_notice(session, target) -> None:
    """The human attacks the bot's Abe with an active token: the attack will be played face up."""
    if attack_revealed(session.game, target):
        session.say(t("hidden.intuition_notice", name=session._name(target)), ChatKind.ATTACK)


def declare_attack(session, p, card):
    """The engine's order at Revelar, before the bot chooses its defense: the `attacked` event once (UNCANNY
    INTUITION spends the token and draws; the draw is dealt now so the drawn card may be the defense), then the
    attack card is returned when the bot's defense may know it: the ability turned it face up, or the human played
    Perfect Shot face up (Ivan, 29/10: public information)."""
    g = session.game
    if card is None:                                     # no attack identified yet: nothing to declare
        return None
    # judged before the trigger spends the token; a declaration carried over from a cancelled attack (Ivan,
    # 29/10: the token stays spent, the draw stands, nothing fires twice) keeps the face-up it earned
    by_ability = attack_revealed(g, p.target) or bool(p.declared and p.declared.get("revealed"))
    if p.declared is None:
        drawn = g.drawn[session.bot]
        p.declared = {"counters": dict(g.fx.counters[session.bot]), "revealed": by_ability}   # the token projection diffs from here
        g.fx.emit("attacked", p.attacker, p.target, card)
        if g.drawn[session.bot] > drawn:                  # the trigger drew: the real card goes to the hand now
            session._mark_dirty()
            session._flush_table()
    if by_ability:
        session.say(t("hidden.intuition_face_up", card=card.title, value=card.value), ChatKind.ATTACK)
        return card
    if p.prediction is not None and p.prediction["value"] is not None:
        return card
    return None


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
        lines.append(t("hidden.bot_predicts", card=card.title, n=n))
    if attack_revealed(g, p.target):
        lines.append(t("hidden.bot_intuition", name=session._name(p.target), card=card.title, value=card.value))
    if not lines:
        return
    if p.bot_card_guid:
        session._w(session._flip_script(p.bot_card_guid, "bot"), "flip")
    for line in lines:
        session.say(line, ChatKind.ATTACK)
