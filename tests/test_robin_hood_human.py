"""Robin Hood on the table through the panel (FakeTTS, batch mode), both seats. The human's Robin: the move his ability gives after each
attack (said in the chat, made by hand, read back from the table, refused when it breaks the rules, an Outlaw as the attacker, resumed from a
save while it is open), the cards he draws, Defenders of Sherwood putting a defeated Outlaw back by hand, Steal From the Rich asking the bot,
Ambush making the bot discard. The bot's Robin against the human: its move written on the table, its Outlaw coming back, Steal From the Rich
asking the human, Ambush asking the human to lay the card the bot names. The bot's side of the same cards is in
tests/test_robin_hood_effects.py.

The Outlaws are four Custom_Token objects called Outlaw (a token real TTS may report as "Tile"): nothing that reads or moves a piece looks at the type."""
from __future__ import annotations

import json

import pytest

from sparring.ai_medusa import Act, MedusaAI
from sparring.session import Session
from sparring.state import Game
from sparring.tts.ui import Event
from test_batch import click
from test_d3_table_effects import bot_turn, build, card_ids, human_attack, human_hand, said
from test_doctor_strange_human import StrangeTable
from test_donatello_session import SPOTS
from test_e2_human_cards import press, put_adjacent

TRAINING = "B.P.R.D. Training"        # Hellboy's defense of value 3
HELLBOY_HAND = ("Excalibur", TRAINING, "Service Pistol", "Right Hand Of Doom")        # the bot Hellboy's
ROBIN_HAND = ("A Hunter's Eye", "Piercing Shot", "Highway Robbery", "Snark", "Disarming Shot")      # the human Robin's


@pytest.fixture
def rig(request, tmp_path):
    bot, human, hand = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human, hand, table_cls=StrangeTable, **SPOTS)
    table.human_card_spot = tuple(cfg.session_config().human_card_spot)
    table.human_deck = []
    table.hand_returns = []
    table.top_discards = []
    put_adjacent(game, table, cfg, game.hero(1).fid, game.hero(0).fid)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def with_rig(*bot_hand, bot="hellboy", human="robin-hood"):
    return pytest.mark.parametrize("rig", [(bot, human, bot_hand)], indirect=True)


def reload(session, table):
    """The session as a save brings it back: a fresh Session loaded from the saved dict, then resumed against the same table."""
    saved = json.loads(json.dumps(session.to_dict()))
    other = Session(Game.new(session.game.board, seed=3, controllers={}, bot_player=session.bot,
                             heroes=tuple(p.hero.slug for p in session.game.players)), session.client, MedusaAI(0), session.cfg)
    other.game_id = session.game_id
    other.load_dict(saved)
    other.snap = None
    other.resume()
    return other


def no_defense(session, monkeypatch):
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: None)


def defends_with(session, game, title, monkeypatch):
    card = next(c for c in game.players[0].hand if c.title == title)
    monkeypatch.setattr(session.ai, "choose_defense", lambda g, a, t, attack_card=None: card)


def attack(session, table, game, title, attacker="robin", target="hellboy"):
    human_attack(session, table, game, attacker, target, title)
    return click(session, table, Event.REVEAL)


def dial(cfg, table, fid):
    return table.dials[cfg.session_config().dials[fid]]["value"]


def free_within(game, fid, steps=2):
    """Empty spaces at most `steps` away from `fid`, the nearest first."""
    me = game.fighters[fid]
    taken = {f.pos for f in game.fighters.values() if f.alive}
    return sorted((s for s in game.board.spaces if s not in taken and 0 < game.board.distance(me.pos, s) <= steps),
                  key=lambda s: (game.board.distance(me.pos, s), s))


def free_in_zone(game, fid):
    """Empty spaces of `fid`'s zone."""
    taken = {f.pos for f in game.fighters.values() if f.alive}
    pos = game.fighters[fid].pos
    return [s for s in sorted(game.board.spaces) if s not in taken and game.board.share_zone(pos, s)]


def walk(session, table, cfg, fid, space):
    """The human puts the miniature of `fid` on `space` by hand and presses End action: the bot reads the table."""
    table.positions[cfg.nicknames[fid]] = space
    return click(session, table, Event.END_ACTION)


def awaiting(session):
    return session.effect_run.awaiting if session.effect_run is not None else session._paused()[2].awaiting


def lay_on_pile(table, game, title):
    """The human discards the named card of their hand onto their discard pile by hand (what the bot's Ambush waits for)."""
    by_id = {c.card_id: c for c in game.players[1].full_set}
    i = next(i for i in table.human_hand if by_id[i].title == title)
    table.human_hand.remove(i)
    table.human_discard.append(i)
    table.human_count -= 1
    return i


def defeat_outlaws(game, table, cfg, *fids):
    for fid in fids:
        game.defeat(game.fighters[fid])
        table.positions.pop(cfg.nicknames[fid], None)


# ================================================================ the human plays Robin Hood

@with_rig(*HELLBOY_HAND)
def test_after_the_attack_the_chat_says_which_fighter_may_move_and_how_far(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    msgs = attack(session, table, game, "A Hunter's Eye")
    assert said(msgs, "puede moverse") and said(msgs, "hasta 2 casillas"), msgs
    assert game.hand_moves == {"robin": {"steps": 2, "up_to": True, "through": False}}
    assert session.effect_run is None                                   # nothing waits for a button: the move is made on the table


@with_rig(*HELLBOY_HAND)
def test_the_miniature_the_human_moves_by_hand_is_read_back_and_the_engine_follows(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    attack(session, table, game, "A Hunter's Eye")
    dest = free_within(game, "robin")[-1]
    walk(session, table, cfg, "robin", dest)
    assert game.fighters["robin"].pos == dest and game.hand_moves == {}
    assert game.fighters["hellboy"].hp == game.fighters["hellboy"].max_hp - 5


@with_rig(*HELLBOY_HAND)
def test_a_human_who_does_not_move_keeps_the_miniature_where_it_is(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    attack(session, table, game, "A Hunter's Eye")
    spot = game.fighters["robin"].pos
    msgs = click(session, table, Event.END_ACTION)
    assert game.fighters["robin"].pos == spot and game.hand_moves == {} and not said(msgs, "casillas"), msgs


@with_rig(*HELLBOY_HAND)
def test_a_walk_of_three_spaces_is_refused_and_nothing_changes_until_it_is_put_right(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    attack(session, table, game, "A Hunter's Eye")
    spot = game.fighters["robin"].pos
    far = next(s for s in sorted(free_within(game, "robin", 3), reverse=True) if game.board.distance(spot, s) == 3)
    msgs = walk(session, table, cfg, "robin", far)
    assert game.fighters["robin"].pos == spot and "robin" in game.hand_moves, msgs
    assert said(msgs, "casillas"), msgs
    near = free_within(game, "robin")[0]
    walk(session, table, cfg, "robin", near)
    assert game.fighters["robin"].pos == near and game.hand_moves == {}


@with_rig(*HELLBOY_HAND)
def test_an_outlaw_that_attacks_is_the_one_the_chat_tells_to_move(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    put_adjacent(game, table, cfg, "outlaw2", "hellboy")
    robin_spot = game.fighters["robin"].pos
    msgs = attack(session, table, game, "Highway Robbery", attacker="outlaw2")
    assert list(game.hand_moves) == ["outlaw2"] and said(msgs, "outlaw2"), msgs
    dest = free_within(game, "outlaw2")[-1]
    walk(session, table, cfg, "outlaw2", dest)
    assert game.fighters["outlaw2"].pos == dest and game.fighters["robin"].pos == robin_spot


@with_rig(*HELLBOY_HAND)
def test_the_open_walk_survives_a_save_and_the_resumed_session_reads_the_same_table(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    attack(session, table, game, "A Hunter's Eye")
    other = reload(session, table)
    assert other.game.hand_moves == {"robin": {"steps": 2, "up_to": True, "through": False}}
    dest = free_within(other.game, "robin")[-1]
    walk(other, table, cfg, "robin", dest)
    assert other.game.fighters["robin"].pos == dest and other.game.hand_moves == {}


@with_rig(*HELLBOY_HAND)
def test_the_resumed_session_still_refuses_a_walk_that_breaks_the_rule(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    attack(session, table, game, "A Hunter's Eye")
    spot = game.fighters["robin"].pos
    other = reload(session, table)
    far = next(s for s in sorted(free_within(other.game, "robin", 4), reverse=True) if other.game.board.distance(spot, s) > 2)
    msgs = walk(other, table, cfg, "robin", far)
    assert other.game.fighters["robin"].pos == spot and "robin" in other.game.hand_moves and said(msgs, "casillas"), msgs


# ---------------------------------------------------------------- the human's cards

@with_rig(*HELLBOY_HAND)
def test_piercing_shot_gets_two_cards_dealt_after_the_combat(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    dealt = len(table.human_deals)
    msgs = attack(session, table, game, "Piercing Shot")
    assert table.human_deals[dealt:] == [2] and said(msgs, "Te he dado 2 cartas"), msgs


@with_rig(*HELLBOY_HAND)
def test_disarming_shot_deals_as_many_cards_as_the_damage_the_blow_did(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    dealt, hp = len(table.human_deals), game.fighters["hellboy"].hp
    attack(session, table, game, "Disarming Shot")
    assert game.fighters["hellboy"].hp == hp - 1 and table.human_deals[dealt:] == [1]


@with_rig(*HELLBOY_HAND)
def test_disarming_shot_counts_the_overkill_against_a_sidekick(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    put_adjacent(game, table, cfg, "lobster", "robin")
    game.fighters["lobster"].hp = 1
    dealt = len(table.human_deals)
    attack(session, table, game, "Disarming Shot", target="lobster")
    assert not game.fighters["lobster"].alive and table.human_deals[dealt:] == [4]


@with_rig(*HELLBOY_HAND)
def test_highway_robbery_played_by_an_outlaw_ignores_the_bots_defense_value(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    defends_with(session, game, TRAINING, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    put_adjacent(game, table, cfg, "outlaw1", "hellboy")
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Highway Robbery", attacker="outlaw1")
    assert game.fighters["hellboy"].hp == hp - 2, msgs


@with_rig(*HELLBOY_HAND)
def test_robin_hood_himself_cannot_play_highway_robbery_at_the_table(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, *ROBIN_HAND)
    hp = game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Highway Robbery", attacker="robin")
    assert said(msgs, "Carta ilegal: Highway Robbery es de Outlaw") and game.fighters["hellboy"].hp == hp, msgs
    assert session.pending is not None and session.pending.kind == "human_attacks"          # the combat did not happen: change the card and Reveal again


@with_rig("Excalibur", "Service Pistol")
def test_ambush_makes_the_bot_discard_a_random_card_and_adds_its_boost(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    human_hand(table, game, "Ambush", "Snark")
    before, hp = len(game.players[0].hand), game.fighters["hellboy"].hp
    msgs = attack(session, table, game, "Ambush")
    gone = game.players[0].discard[-1]
    assert len(game.players[0].hand) == before - 1 and gone.card_id in table.bot_discard, msgs
    assert game.fighters["hellboy"].hp == hp - (2 + gone.boost), msgs


@with_rig()
def test_ambush_against_a_bot_with_an_empty_hand_is_a_plain_two(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    no_defense(session, monkeypatch)
    game.players[0].hand.clear()
    table.bot_hand = []
    session.read_bot_hand()
    human_hand(table, game, "Ambush", "Snark")
    hp = game.fighters["hellboy"].hp
    attack(session, table, game, "Ambush")
    assert game.fighters["hellboy"].hp == hp - 2


# ---------------------------------------------------------------- Defenders of Sherwood (the human defends)

def bot_attacks_robin(session, table, game, human_title, bot_title="Service Pistol"):
    """The bot's Hellboy attacks Robin Hood; the human answers with `human_title` face down; the reveal resolves it."""
    card = next(c for c in game.players[0].hand if c.title == bot_title)
    bot_turn(session, table, [Act("attack", fid="hellboy", target="robin", card=card)])
    cid = card_ids(game, 1, human_title)[0]
    table.face_down = [{"id": cid, "guid": f"h{cid}"}]
    table.human_hand.remove(cid)
    table.human_count -= 1
    return click(session, table, Event.REVEAL)


@with_rig(*HELLBOY_HAND)
def test_defenders_of_sherwood_returns_an_outlaw_without_asking_which_and_the_human_places_it_by_hand(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "robin")
    defeat_outlaws(game, table, cfg, "outlaw1", "outlaw3")
    human_hand(table, game, "Defenders of Sherwood", "Snark", "Feint")
    msgs = bot_attacks_robin(session, table, game, "Defenders of Sherwood")
    assert session.effect_run is None and said(msgs, "Te he dado 1 carta"), msgs         # the four tokens are the same: no question
    assert game.placing == {"outlaw1"} and said(msgs, "la zona de tu heroe"), msgs
    spot = free_in_zone(game, "robin")[0]
    walk(session, table, cfg, "outlaw1", spot)
    assert game.fighters["outlaw1"].alive and game.fighters["outlaw1"].pos == spot and not game.fighters["outlaw3"].alive
    assert game.placing == set() and game.fighters["outlaw1"].hp == 1


@with_rig(*HELLBOY_HAND)
def test_the_human_who_lays_the_token_of_another_fallen_outlaw_is_followed(rig):
    """The four tokens look alike: the engine returns outlaw1, the human lays outlaw3's. The fids trade tokens and the Outlaw stands where it was laid."""
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "robin")
    defeat_outlaws(game, table, cfg, "outlaw1", "outlaw3")
    human_hand(table, game, "Defenders of Sherwood", "Snark", "Feint")
    bot_attacks_robin(session, table, game, "Defenders of Sherwood")
    token1, token3 = session.cfg.pieces["outlaw1"], session.cfg.pieces["outlaw3"]
    spot = free_in_zone(game, "robin")[0]
    msgs = walk(session, table, cfg, "outlaw3", spot)
    o1, o3 = game.fighters["outlaw1"], game.fighters["outlaw3"]
    assert o1.alive and o1.pos == spot and not o3.alive and game.placing == set(), msgs
    assert session.cfg.pieces["outlaw1"] == token3 and session.cfg.pieces["outlaw3"] == token1
    assert not said(msgs, "No encuentro"), msgs
    again = click(session, table, Event.END_ACTION)
    assert not said(again, "No encuentro") and o1.pos == spot, again


@with_rig(*HELLBOY_HAND)
def test_the_outlaw_still_to_place_survives_a_save_and_another_token_is_still_followed(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "robin")
    defeat_outlaws(game, table, cfg, "outlaw2", "outlaw4")
    human_hand(table, game, "Defenders of Sherwood", "Snark", "Feint")
    bot_attacks_robin(session, table, game, "Defenders of Sherwood")
    assert game.placing == {"outlaw2"}
    other = reload(session, table)
    assert other.game.placing == {"outlaw2"}
    spot = free_in_zone(other.game, "robin")[0]
    msgs = walk(other, table, cfg, "outlaw4", spot)
    assert other.game.fighters["outlaw2"].alive and other.game.fighters["outlaw2"].pos == spot and other.game.placing == set(), msgs
    assert not said(msgs, "No encuentro"), msgs


@with_rig(*HELLBOY_HAND)
def test_defenders_of_sherwood_with_no_defeated_outlaw_only_deals_the_card(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "robin")
    human_hand(table, game, "Defenders of Sherwood", "Snark", "Feint")
    msgs = bot_attacks_robin(session, table, game, "Defenders of Sherwood")
    assert session.effect_run is None and game.placing == set() and said(msgs, "Te he dado 1 carta"), msgs


# ---------------------------------------------------------------- Steal From the Rich (the human plays it, the bot is the rival)

def human_scheme(session, table, game, title):
    click(session, table, Event.SCHEME)
    cid = card_ids(game, 1, title)[0]
    table.human_discard.append(cid)
    table.human_count -= 1
    return click(session, table, Event.END_ACTION)


@with_rig(*HELLBOY_HAND)
def test_steal_from_the_rich_the_bot_that_keeps_its_hand_gives_the_human_a_second_card(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    monkeypatch.setattr("sparring.ai_robin.steal_pays", lambda game, req: False)
    human_hand(table, game, "Steal From the Rich", "Snark")
    dealt, hand = len(table.human_deals), len(game.players[0].hand)
    msgs = human_scheme(session, table, game, "Steal From the Rich")
    assert sum(table.human_deals[dealt:]) == 2 and len(game.players[0].hand) == hand, msgs


@with_rig(*HELLBOY_HAND)
def test_steal_from_the_rich_the_bot_that_discards_a_card_leaves_the_human_one_draw(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    monkeypatch.setattr("sparring.ai_robin.steal_pays", lambda game, req: True)
    human_hand(table, game, "Steal From the Rich", "Snark")
    dealt, hand = len(table.human_deals), len(game.players[0].hand)
    msgs = human_scheme(session, table, game, "Steal From the Rich")
    assert sum(table.human_deals[dealt:]) == 1 and len(game.players[0].hand) == hand - 1 and len(table.bot_discard) == 1, msgs


# ================================================================ the bot plays Robin Hood against the human

MANEUVER_DRAWS = 1          # the two maneuvers the harness has the bot make after its plan draw this many cards in all (measured)
BOT_ROBIN = ("A Hunter's Eye", "Snark", "Piercing Shot", "Highway Robbery", "Disarming Shot")


def bot_attacks(session, table, game, title, human_cards=(TRAINING, "Excalibur"), fid="robin", target="hellboy"):
    human_hand(table, game, *human_cards)
    card = next(c for c in game.players[0].hand if c.title == title)
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
    first = bot_turn(session, table, [Act("attack", fid=fid, target=target, card=card)])
    return [*first, *click(session, table, Event.REVEAL)]


@with_rig(*BOT_ROBIN, bot="robin-hood", human="hellboy")
def test_the_bots_robin_moves_after_its_attack_and_the_miniature_follows_on_the_table(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "robin", "hellboy")
    spot = game.fighters["robin"].pos
    bot_attacks(session, table, game, "Snark")
    robin = game.fighters["robin"]
    assert robin.pos != spot and game.board.distance(spot, robin.pos) <= 2
    assert table.positions[cfg.nicknames["robin"]] == robin.pos


@with_rig(*BOT_ROBIN, bot="robin-hood", human="hellboy")
def test_the_bots_outlaw_that_attacks_is_the_one_that_moves(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "outlaw1", "hellboy")
    robin_spot, spot = game.fighters["robin"].pos, game.fighters["outlaw1"].pos
    bot_attacks(session, table, game, "Highway Robbery", fid="outlaw1")
    assert game.fighters["robin"].pos == robin_spot and game.board.distance(spot, game.fighters["outlaw1"].pos) <= 2
    assert table.positions[cfg.nicknames["outlaw1"]] == game.fighters["outlaw1"].pos


@with_rig(*BOT_ROBIN, bot="robin-hood", human="hellboy")
def test_the_bots_piercing_shot_draws_two_for_the_bot(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "robin", "hellboy")
    hand = len(game.players[0].hand)
    msgs = bot_attacks(session, table, game, "Piercing Shot")
    assert len(game.players[0].hand) == hand - 1 + 2 and said(msgs, "roba 2"), msgs


@with_rig("Defenders of Sherwood", "Snark", "Feint", bot="robin-hood", human="hellboy")
def test_the_bots_defenders_of_sherwood_brings_an_outlaw_back_and_places_it_on_the_table(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "robin")
    defeat_outlaws(game, table, cfg, "outlaw2")
    defends_with(session, game, "Defenders of Sherwood", monkeypatch)
    human_hand(table, game, "Service Pistol", "Excalibur")
    hand = len(game.players[0].hand)
    msgs = attack(session, table, game, "Service Pistol", attacker="hellboy", target="robin")
    outlaw = game.fighters["outlaw2"]
    assert outlaw.alive and outlaw.hp == 1 and game.board.share_zone(outlaw.pos, game.fighters["robin"].pos), msgs
    assert table.positions[cfg.nicknames["outlaw2"]] == outlaw.pos
    assert len(game.players[0].hand) == hand - 1 + 1, msgs                       # the card played, the card drawn


@with_rig("Defenders of Sherwood", "Snark", "Feint", bot="robin-hood", human="hellboy")
def test_the_bots_defenders_of_sherwood_with_no_free_space_in_the_zone_only_draws(rig, monkeypatch):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "hellboy", "robin")
    defeat_outlaws(game, table, cfg, "outlaw2")
    defends_with(session, game, "Defenders of Sherwood", monkeypatch)
    human_hand(table, game, "Service Pistol", "Excalibur")
    zone = free_in_zone(game, "robin")
    mates = [f for f in game.fighters.values() if f.alive and f.fid not in ("robin", "hellboy")]
    if len(zone) > len(mates):
        pytest.skip("the zone has more free spaces than fighters to fill them")
    for f, s in zip(mates, zone):
        f.pos = s
        table.positions[cfg.nicknames[f.fid]] = s
    attack(session, table, game, "Service Pistol", attacker="hellboy", target="robin")
    assert not game.fighters["outlaw2"].alive and cfg.nicknames["outlaw2"] not in table.positions


@with_rig("Steal From the Rich", "Snark", bot="robin-hood", human="hellboy")
def test_the_bots_steal_from_the_rich_asks_the_human_and_a_no_gives_the_bot_a_second_card(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Excalibur", TRAINING, "Service Pistol")
    card = next(c for c in game.players[0].hand if c.title == "Steal From the Rich")
    hand = len(game.players[0].hand)
    msgs = bot_turn(session, table, [Act("scheme", fid="robin", card=card)])
    req = awaiting(session)
    assert req.kind == "optional" and req.player == 1 and req.card_owner == 0, msgs
    assert said(msgs, "Descartas 1 carta para que Robin Hood no robe otra?") and said(msgs, "1: Descarto 1 carta, 2: No") and not said(msgs, "Usas el efecto") and not said(msgs, "Carta: Draw 1 card"), msgs
    press(session, table, False)
    assert session.effect_run is None and session.pending_discard is None
    assert len(game.players[0].hand) == hand - 1 + 2 + MANEUVER_DRAWS


@with_rig("Steal From the Rich", "Snark", bot="robin-hood", human="hellboy")
def test_the_bots_steal_from_the_rich_the_human_who_discards_lays_the_card_on_their_pile_and_the_bot_draws_one(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Excalibur", TRAINING, "Service Pistol")
    card = next(c for c in game.players[0].hand if c.title == "Steal From the Rich")
    hand = len(game.players[0].hand)
    bot_turn(session, table, [Act("scheme", fid="robin", card=card)])
    press(session, table, True)
    assert session.pending_discard == {"n": 1, "baseline": 0, "kind": "cards", "hand": True}        # the discard is the human's, by hand
    lay_on_pile(table, game, "Service Pistol")
    click(session, table, Event.END_ACTION)
    assert session.pending_discard is None and any(c.title == "Service Pistol" for c in game.players[1].discard)
    assert len(game.players[0].hand) == hand - 1 + 1 + MANEUVER_DRAWS


@with_rig("Steal From the Rich", "Snark", bot="robin-hood", human="hellboy")
def test_the_human_choice_in_the_bots_steal_from_the_rich_survives_a_save(rig):
    session, table, game, fake, cfg = rig
    human_hand(table, game, "Excalibur", TRAINING)
    card = next(c for c in game.players[0].hand if c.title == "Steal From the Rich")
    bot_turn(session, table, [Act("scheme", fid="robin", card=card)])
    other = reload(session, table)
    assert other.effect_run.awaiting.kind == "optional" and other.effect_run.awaiting.player == 1
    press(other, table, False)
    assert other.effect_run is None


@with_rig("Ambush", "Snark", bot="robin-hood", human="hellboy")
def test_the_bots_ambush_names_a_position_and_reads_the_card_the_human_lays_on_their_pile(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "robin", "hellboy")
    msgs = bot_attacks_ambush(session, table, game)
    assert said(msgs, "al azar: la carta"), msgs
    req = awaiting(session)
    assert req.kind == "cards" and req.extra["pile_mode"] == "reveal" and req.extra["ambush"] and (req.min, req.max) == (1, 1)
    hp = game.fighters["hellboy"].hp
    lay_on_pile(table, game, "Excalibur")                                  # BOOST 3
    click(session, table, Event.CHOICE, {"i": 1})                          # Done
    assert session.pending is None and game.fighters["hellboy"].hp == hp - (2 + 3)
    assert any(c.title == "Excalibur" for c in game.players[1].discard)


@with_rig("Ambush", "Snark", bot="robin-hood", human="hellboy")
def test_the_bots_ambush_waits_while_the_pile_shows_no_new_card_and_survives_a_save(rig):
    session, table, game, fake, cfg = rig
    put_adjacent(game, table, cfg, "robin", "hellboy")
    bot_attacks_ambush(session, table, game)
    msgs = click(session, table, Event.CHOICE, {"i": 1})                   # Done with nothing laid down
    assert awaiting(session).kind == "cards" and said(msgs, "no veo"), msgs
    other = reload(session, table)
    assert awaiting(other).kind == "cards" and awaiting(other).extra["ambush"]


def bot_attacks_ambush(session, table, game):
    human_hand(table, game, TRAINING, "Excalibur", "Service Pistol")
    card = next(c for c in game.players[0].hand if c.title == "Ambush")
    session.ai.choose_defense = lambda g, a, t, attack_card=None: None
    first = bot_turn(session, table, [Act("attack", fid="robin", target="hellboy", card=card)])
    return [*first, *click(session, table, Event.REVEAL)]
