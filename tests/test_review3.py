"""Tercera revision: ningun estado pendiente sin salida y todo fallo de mesa se puede reintentar.

Los escenarios P1-P5 salen de los scripts de reproduccion del revisor. La mesa falsa (`Table`) modela TTS de
verdad: un descarte de 2 o mas cartas es un Deck y el mazo de 1 carta es una Card suelta."""
from conftest import t_discard_cards
import pytest

from conftest import place
from sparring.ai_medusa import Act
from sparring.session import Session, SessionError
from sparring.state import EXHAUST_DAMAGE
from sparring.tts import lua
from sparring.tts.ui import Event
from test_session import card, human_plays, ids, rig, set_bot_hand  # noqa: F401


def maneuver_plan(session, monkeypatch, boost=None):
    acts = iter([Act("maneuver", moves={"medusa": 0}, boost=boost)] if boost else [])
    monkeypatch.setattr(session.ai, "plan", lambda g: next(acts, None) or Act("maneuver", moves={"medusa": 0}))


def claws_attack(session, table, game, monkeypatch):
    """Harpy 1 ataca a Hellboy con Clutching Claws (el humano debera descartar) y queda pendiente."""
    place(game, harpy1=2, hellboy=1)
    table.positions.update({"Harpy 1": 2, "Hellboy": 1})
    set_bot_hand(table, game, "Clutching Claws", "Snipe")
    session.read_bot_hand()
    claws = card(game, 0, "Clutching Claws")
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("attack", fid="harpy1", target="hellboy", card=claws))
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert session.pending and session.pending.kind == "bot_attacks"
    game.players[1].hand[:] = [card(game, 1, "Glimpse Of Hell", 0), card(game, 1, "Glimpse Of Hell", 1)]
    table.human_count = 2
    table.face_down = []
    return claws


# ---------- N1: el descarte pendiente nunca se congela ----------
def test_n1_reconcile_failure_in_reveal_keeps_the_discard_baseline_and_the_game_finishes(rig, monkeypatch):
    session, table, game = rig
    claws_attack(session, table, game, monkeypatch)
    table.lag = 50
    msgs = session.handle(Event.REVEAL)
    assert any("no coincide" in m for m in msgs) and session.dirty
    assert session.pending is None
    assert session.pending_discard is not None and session.pending_discard["baseline"] is not None
    table.lag, table._reads = 0, 99
    table.human_discard = [card(game, 1, "Glimpse Of Hell", 1).card_id]
    table.human_count = 1
    maneuver_plan(session, monkeypatch)
    session.handle(Event.END_ACTION)
    assert session.pending_discard is None and game.turn == 1
    assert {c.card_id for c in game.players[0].discard} == set(table.bot_discard)


def test_n1_every_pending_state_has_an_exit(rig, monkeypatch):
    session, table, game = rig
    claws_attack(session, table, game, monkeypatch)
    session.handle(Event.REVEAL)
    assert session.pending_discard is not None
    msgs = session.handle(Event.CANCEL)          # el humano no puede o no quiere descartar: salida
    assert session.pending_discard is None and any("descarte" in m.lower() for m in msgs)
    maneuver_plan(session, monkeypatch)
    session.handle(Event.END_ACTION)
    assert game.turn == 1


def test_n1_hand_limit_pending_discard_has_an_exit_that_ends_the_turn(rig, monkeypatch):
    session, table, game = rig
    table.human_count = 9
    maneuver_plan(session, monkeypatch)
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert session.pending_discard["kind"] == "limit" and game.turn == 1
    session.handle(Event.CANCEL)
    assert session.pending_discard is None
    session.handle(Event.END_ACTION)
    assert session.pending_discard is None and session.pending is None


def test_n1_cancel_gives_up_after_two_failed_returns(rig, monkeypatch):
    session, table, game = rig
    dash = card(game, 0, "Dash")
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t: dash)
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    session._bot_defends(session.pending)
    table.bot_play.clear()                        # la carta ya no esta donde el bot la dejo
    first = session.handle(Event.CANCEL)
    assert session.pending is not None and any("Error de mesa" in m for m in first)
    session.handle(Event.CANCEL)
    assert session.pending is None and game.actions_left == 2


# ---------- N2: reintentos tras un fallo de asentamiento ----------
def test_n2_retry_after_settle_timeout_with_a_discard_pile_deck(rig, monkeypatch):
    session, table, game = rig
    snipe = card(game, 0, "Snipe")
    table.bot_hand.remove(snipe.card_id)
    table.bot_discard.append(snipe.card_id)
    game.players[0].discard.append(snipe)
    session.bot_discarded.add(snipe.card_id)
    session.read_bot_hand()
    boost = card(game, 0, "Dash")
    maneuver_plan(session, monkeypatch, boost=boost)
    table.lag = 50
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert any("Error de mesa" in m for m in msgs)
    table.lag, table._reads = 0, 99
    for _ in range(3):
        session._reconcile_bot()                   # reintentos: el descarte ya es un Deck de 2 cartas
    assert boost.card_id in table.bot_discard and boost.card_id in session.bot_discarded
    assert not any("Error de mesa" in m for m in session.handle(Event.END_ACTION))


def test_n2_deal_failure_after_a_good_discard_is_retryable(rig, monkeypatch):
    session, table, game = rig
    boost = card(game, 0, "Dash")
    set_bot_hand(table, game, "Snipe", "Dash")
    session.read_bot_hand()
    maneuver_plan(session, monkeypatch, boost=boost)
    real_deal = table.do_deal_cards
    table.do_deal_cards = lambda s: {"dealt": 0}
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert any("Error de mesa" in m for m in msgs)
    assert game.drawn[0] > 0 and boost.card_id in table.bot_discard
    table.do_deal_cards = real_deal
    session._reconcile_bot()
    assert game.drawn[0] == 0
    assert sorted(c.card_id for c in game.players[0].hand) == sorted(table.bot_hand)
    assert {c.card_id for c in game.players[0].discard} == set(table.bot_discard)


def test_n2_second_retry_does_not_resend_cards_already_on_the_pile(rig):
    session, table, game = rig
    dash = card(game, 0, "Dash")
    snipe = card(game, 0, "Snipe")
    for c in (snipe, dash):
        table.bot_hand.remove(c.card_id)
        table.bot_discard.append(c.card_id)
        game.players[0].discard.append(c)
    session.read_bot_hand()
    session._reconcile_bot()
    assert table.discard_calls == [] and {snipe.card_id, dash.card_id} <= session.bot_discarded


def test_n2_discard_and_read_scripts_look_inside_decks():
    s = t_discard_cards([17600], [(5.0, 1.0, 5.0)])
    assert 'o.type == "Deck"' in s and "takeObject" in s and "ContainedObjects" in s
    assert 'o.type == "Deck"' in lua.read_discard("abc")


# ---------- N3: el final del turno del bot es reintentable ----------
def test_n3_failed_reconcile_at_end_of_bot_turn_does_not_skip_or_double_end_the_human_turn(rig, monkeypatch):
    session, table, game = rig
    maneuver_plan(session, monkeypatch)
    real, boom = session._reconcile_stage, {"armed": True}

    def flaky():
        if game.turn == 1 and boom.pop("armed", False):
            raise SessionError("mesa lenta")
        return real()
    monkeypatch.setattr(session, "_reconcile_stage", flaky)
    session.dirty = False
    turn_no = game.turn_no
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)       # humano termina; el bot juega 2 maniobras y pasa
    assert game.turn == 1 and game.turn_no == turn_no + 2
    assert game.actions_left == 2, "el turno del humano debe haber empezado igualmente"
    assert any("mesa lenta" in m for m in msgs)
    session.handle(Event.MANEUVER)                # el humano puede jugar
    assert game.actions_left == 1 and game.turn_no == turn_no + 2
    assert session.dirty is False, "la deuda de mesa se salda sola en la siguiente accion"


def test_n3_retry_button_reruns_the_failed_reconcile_before_the_bot_acts_again(rig, monkeypatch):
    session, table, game = rig
    boost = card(game, 0, "Dash")
    maneuver_plan(session, monkeypatch, boost=boost)
    order, real_plan, real_rec = [], session.ai.plan, session._reconcile_stage
    monkeypatch.setattr(session.ai, "plan", lambda g: (order.append("plan"), real_plan(g))[1])
    monkeypatch.setattr(session, "_reconcile_stage", lambda: (order.append("reconcile"), real_rec())[1])
    table.lag = 50
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert any("Error de mesa" in m for m in msgs) and game.turn == 0
    table.lag, table._reads = 0, 99
    order.clear()
    session.handle(Event.END_ACTION)
    assert order[0] == "reconcile", order
    assert game.turn == 1
    assert boost.card_id in table.bot_discard and not session.dirty


def test_n3_failure_at_start_of_the_bot_turn_is_resumable_and_does_not_skip_it(rig, monkeypatch):
    session, table, game = rig
    maneuver_plan(session, monkeypatch)
    real = session.sync_positions
    state = {"fail": True}

    def flaky():
        if state["fail"] and game.turn == 0:
            state["fail"] = False
            raise TimeoutError("TTS no devolvio valor")
        real()
    monkeypatch.setattr(session, "sync_positions", flaky)
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert any("TTS no respondio" in m for m in msgs) and game.turn == 0
    session.handle(Event.END_ACTION)
    assert game.turn == 1 and game.actions_left == 2
    assert table.count("deal_cards") == 2, "el bot jugo sus dos acciones"


# ---------- N4: mazo del bot ----------
def test_n4_deck_spot_is_required(rig):
    session, table, game = rig
    session.cfg.bot_deck_spot = None
    with pytest.raises(SessionError, match="bot_deck_spot"):
        session.start()
    assert table.scripts == [] or not any(s.startswith("-- sparring:deal") for s in table.scripts)


def test_n4_deck_to_single_card_to_empty_then_exhaustion_end_to_end(rig, monkeypatch):
    session, table, game = rig
    st = game.players[0]
    keep = table.bot_deck[:2]                       # un Deck de 2 cartas; el resto, en el descarte
    rest = [c for c in st.full_set if c.card_id not in table.bot_hand and c.card_id not in keep]
    table.bot_deck = list(keep)
    table.bot_discard = [c.card_id for c in rest]
    st.discard = list(rest)
    session.bot_discarded |= {c.card_id for c in rest}
    session.read_bot_hand()
    assert len(st.deck) == 2
    maneuver_plan(session, monkeypatch)
    hp = {f.fid: f.hp for f in game.own(0)}
    game.actions_left = 0
    session.handle(Event.END_ACTION)                # 2 maniobras: Deck -> Card suelta -> vacio
    assert table.bot_deck == [] and len(st.deck) == 0 and game.drawn[0] == 0
    assert {f.fid: f.hp for f in game.own(0)} == hp, "sin dano mientras habia cartas"
    assert sorted(c.card_id for c in st.hand) == sorted(table.bot_hand)
    # siguiente turno del bot: mazo vacio -> agotamiento (2 por luchador y accion) y nada que repartir
    deals = len(table.deal_calls)
    game.actions_left = 0
    session.handle(Event.END_ACTION)
    assert len(table.deal_calls) == deals and game.drawn[0] == 0
    for f in game.own(0):
        assert f.hp <= hp[f.fid] - EXHAUST_DAMAGE or not f.alive


def test_n4_short_deal_does_not_reinflate_the_engine_deck(rig):
    session, table, game = rig
    st = game.players[0]
    table.bot_deck = []
    table.bot_discard = [c.card_id for c in st.full_set if c.card_id not in table.bot_hand]
    st.discard = [c for c in st.full_set if c.card_id in table.bot_discard]
    session.bot_discarded |= set(table.bot_discard)
    session.read_bot_hand()
    st.deck = [card(game, 0, "Gaze of Stone")]       # el motor cree que aun queda una (desfase)
    st.discard.remove(card(game, 0, "Gaze of Stone"))
    table.bot_discard.remove(card(game, 0, "Gaze of Stone").card_id)     # y la mesa no la tiene en ningun sitio
    game.draw(0)
    assert game.drawn[0] == 1
    with pytest.raises(SessionError):
        session._reconcile_bot()
    session.read_bot_hand()
    assert game.drawn[0] == 1
    assert len(st.hand) == len(table.bot_hand) + 1, "la carta debida sigue contada en la mano del motor"
    assert st.deck == [] or len(st.deck) == 0


# ---------- N7: carta ya colocada antes de pulsar Atacar ----------
def test_n7_card_already_placed_counts_as_an_attack_card(rig):
    session, table, game = rig
    place(game, hellboy=40 if 40 in game.board.spaces else 31, lobster=1, medusa=0)
    table.positions.update({"Hellboy": game.fighters["hellboy"].pos, "Lobster Johnson": 1})
    table.human_hand = ids(game, 1, "Pancakes!")
    human_plays(table, game, "Second Shot")
    session.handle(Event.ATTACKER, {"attacker": "lobster"})
    session.handle(Event.ATTACK, {"target": "medusa"})
    assert session.pending is not None


def test_n7_without_any_legal_card_it_is_refused_at_reveal(rig):
    session, table, game = rig
    place(game, hellboy=40 if 40 in game.board.spaces else 31, lobster=1, medusa=0)
    table.positions.update({"Hellboy": game.fighters["hellboy"].pos, "Lobster Johnson": 1})
    table.human_hand = ids(game, 1, "Pancakes!")
    human_plays(table, game, "On Earth As It Is In Hell")
    session.handle(Event.ATTACKER, {"attacker": "lobster"})
    session.handle(Event.ATTACK, {"target": "medusa"})      # Atacar ya no lee la mano: la legalidad se ve al Revelar
    msgs = session.handle(Event.REVEAL)
    assert any("Carta ilegal" in m for m in msgs)
    assert session.pending is not None and not session.pending.defended, "el bot no ha puesto defensa"


# ---------- N8 ----------
def test_n8_cancel_with_nothing_pending_says_so(rig):
    session, _, _ = rig
    msgs = session.handle(Event.CANCEL)
    assert any("nada que cancelar" in m.lower() for m in msgs)


def test_n8_harpy_defends_with_a_harpy_legal_card_and_the_reveal_resolves(rig):
    session, table, game = rig
    place(game, harpy1=2, hellboy=1)
    table.positions.update({"Harpy 1": 2, "Hellboy": 1})
    set_bot_hand(table, game, "Clutching Claws", "Hiss and Slither", "The Hounds of Mighty Zeus")
    session.read_bot_hand()
    session.handle(Event.ATTACKER, {"attacker": "hellboy"})
    session.handle(Event.ATTACK, {"target": "harpy1"})
    bot_card = session.pending.bot_card
    assert bot_card is None or bot_card.usable_by("Harpy")
    human_plays(table, game, "Glimpse Of Hell")
    table.human_count = 4
    msgs = session.handle(Event.REVEAL)
    assert any("Combate" in m for m in msgs) and session.pending is None


# ---------- Liz (Wildfire): las ardientes descartadas vuelven a la mano ----------
def liz_human(game):
    from sparring.heroes import load_hero
    game.players[1].hero = load_hero("liz-sherman")


def test_wildfire_forced_discard_is_accepted_when_burning_card_returned_to_hand(rig, monkeypatch):
    session, table, game = rig
    claws_attack(session, table, game, monkeypatch)
    liz_human(game)
    msgs = session.handle(Event.REVEAL)
    assert session.pending_discard is not None and any("Wildfire" in m for m in msgs)
    maneuver_plan(session, monkeypatch)
    msgs = session.handle(Event.END_ACTION)       # descarto una ardiente: volvio a la mano, el descarte no crece
    assert session.pending_discard is not None and any("otra vez" in m for m in msgs)   # primero insiste
    msgs = session.handle(Event.END_ACTION)
    assert session.pending_discard is None and not any("Aun falta" in m for m in msgs)
    assert game.turn == 1


def test_wildfire_hand_limit_discard_must_be_on_the_table(rig, monkeypatch):
    """Ivan's ruling (28/10): the hand-limit discard is the exception to Wildfire; nothing returns to the hand."""
    session, table, game = rig
    liz_human(game)
    table.human_count = 9
    maneuver_plan(session, monkeypatch)
    game.actions_left = 0
    msgs = session.handle(Event.END_ACTION)
    assert session.pending_discard["kind"] == "limit" and not any("Wildfire" in m for m in msgs)
    msgs = session.handle(Event.END_ACTION)
    assert session.pending_discard is not None and any("Aun falta" in m for m in msgs)
    table.human_count = 7                         # the two cards went to the discard for real
    session.handle(Event.END_ACTION)
    assert session.pending_discard is None


def test_without_wildfire_the_forced_discard_still_waits(rig, monkeypatch):
    session, table, game = rig
    claws_attack(session, table, game, monkeypatch)
    session.handle(Event.REVEAL)
    maneuver_plan(session, monkeypatch)
    msgs = session.handle(Event.END_ACTION)
    assert session.pending_discard is not None and any("Aun falta" in m for m in msgs)


def test_wildfire_burning_card_taken_back_from_discard_goes_to_hand_and_is_known(rig, monkeypatch):
    session, table, game = rig
    claws_attack(session, table, game, monkeypatch)
    liz_human(game)
    session.handle(Event.REVEAL)
    burning = card(game, 1, "Glimpse Of Hell", 1)    # el rig es de Hellboy: se marca como ardiente
    object.__setattr__(burning, "tags", frozenset({"burning"}))
    table.human_discard = [burning.card_id]           # la ensena en el descarte
    table.human_count = 1
    maneuver_plan(session, monkeypatch)
    session.handle(Event.END_ACTION)
    assert burning in game.players[1].discard and session.pending_discard is None
    in_deck = game.players[1].deck.count(burning)     # el rig deja copias en el mazo: solo cuenta que no crezca
    table.human_discard = []                          # y la vuelve a coger
    table.human_count = 2
    for _ in range(3):                                # la baja necesita dos botones distintos
        session.sync_human()
        session._epoch += 1
    st = game.players[1]
    assert burning in st.hand and burning not in st.discard and st.deck.count(burning) == in_deck
    assert burning.card_id in game.players[0].known.seen


def test_wildfire_burning_card_shuffled_into_deck_is_not_taken_as_returned_to_hand(rig, monkeypatch):
    """Rekindle / Searing Clarity: la ardiente sale del descarte hacia el mazo y tu mano no crece."""
    session, table, game = rig
    claws_attack(session, table, game, monkeypatch)
    liz_human(game)
    session.handle(Event.REVEAL)
    burning = card(game, 1, "Glimpse Of Hell", 1)
    object.__setattr__(burning, "tags", frozenset({"burning"}))
    table.human_discard = [burning.card_id]
    table.human_count = 1
    maneuver_plan(session, monkeypatch)
    session.handle(Event.END_ACTION)
    assert burning in game.players[1].discard
    table.human_discard = []                          # se baraja en el mazo: la mano sigue con 1
    for _ in range(3):
        session.sync_human()
        session._epoch += 1
    assert burning not in game.players[1].discard and burning.card_id not in game.players[0].known.seen


def test_choosing_the_attacker_rereads_positions_moved_outside_an_action(rig):
    """Liz se mueve 2 con Wildfire al empezar su turno: al elegir atacante el panel ya debe verla donde esta."""
    session, table, game = rig
    place(game, hellboy=14)
    table.positions.update({"Hellboy": 18})
    session.handle(Event.ATTACKER, {"attacker": "att_hellboy"})
    assert game.fighters["hellboy"].pos == 18


def test_wildfire_leftover_credit_does_not_send_a_later_shuffled_burning_card_to_hand(rig, monkeypatch):
    """La ardiente del fondo vuelve a tu mano al empezar el turno (la mano crece) y, botones despues, Rekindle baraja
    otra ardiente del descarte en el mazo: esa no va a la mano ni el bot la conoce."""
    session, table, game = rig
    claws_attack(session, table, game, monkeypatch)
    liz_human(game)
    session.handle(Event.REVEAL)
    burning = card(game, 1, "Glimpse Of Hell", 1)
    object.__setattr__(burning, "tags", frozenset({"burning"}))
    table.human_discard = [burning.card_id]
    table.human_count = 1
    maneuver_plan(session, monkeypatch)
    session.handle(Event.END_ACTION)
    assert burning in game.players[1].discard
    table.human_count = 2                             # la del fondo vuelve a la mano: credito
    session.sync_human()
    for _ in range(3):                                # botones despues, Rekindle: sale del descarte, la mano igual
        session._epoch += 1
        session.sync_human()
    table.human_discard = []
    for _ in range(3):
        session._epoch += 1
        session.sync_human()
    assert burning not in game.players[1].discard and burning.card_id not in game.players[0].known.seen
