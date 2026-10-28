"""F07 paso 10: la conexion con TTS ya no esta atada a Medusa (bot) y Hellboy (humano).

Cualquier par de heroes de la caja Hellboy mas Medusa, en cualquiera de los dos lados, monta su configuracion desde
`data/tts/<slug>.json`: piezas, diales, mazos, rangos de CardID, botones de atacante y panel con la vida de todos los
luchadores. Medusa vs Hellboy sigue dando EXACTAMENTE los mismos valores y scripts que antes (ademas de los dorados)."""
import json
import re
from pathlib import Path

import pytest

from fake_tts import FakeTTS
from conftest import place
from sparring import play
from sparring.ai_medusa import Act, MedusaAI
from sparring.heroes import available_heroes, load_hero
from sparring.play import ConfigError, load_config
from sparring.session import Session
from sparring.state import Game
from sparring.tts import lua, ui
from sparring.tts.client import TTSClient
from sparring.tts.hero_table import TTS_DIR
from sparring.tts.ui import Event
from test_batch import click
from test_play import cfg_file, live  # noqa: F401
from test_session import Table, human_plays

REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "partida.json"
TABLE_OVERRIDES = {"bot_seat": "Blue", "human_seat": "Red", "bot_card_spot": [0.0, 1.0, 5.0],
                   "human_card_spot": [0.0, -5.0], "bot_discard_spot": [5.0, 1.0, 5.0], "bot_discard_zone": "BOTZ",
                   "human_discard_zone": "HUMZ", "bot_deck_spot": [0.0, 3.0], "bot_discard_bounds": None,
                   "setup": False, "bot_pause": 0.0}
PAIRS = [("medusa", "hellboy"), ("medusa", "liz-sherman"), ("hellboy", "abe-sapien"), ("baba-yaga", "medusa"),
         ("abe-sapien", "baba-yaga"), ("liz-sherman", "hellboy")]
OLD_NICKNAMES = {"medusa": "Medusa", "harpy1": "Harpy 1", "harpy2": "Harpy 2", "harpy3": "Harpy 3", "hellboy": "Hellboy",
                 "lobster": "Lobster Johnson"}
OLD_PIECES = {"medusa": "04b2c9", "harpy1": "328e52", "harpy2": "33c5ec", "harpy3": "01eb1f",
              "hellboy": ["f9789a", "e6f06e"], "lobster": "e33604"}
OLD_DIALS = {"medusa": "bcd809", "hellboy": "046660", "lobster": "18c384"}


def config_for(tmp_path, bot_hero=None, human_hero=None, **over) -> play.PlayConfig:
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    raw.update(TABLE_OVERRIDES)
    if bot_hero:
        raw["bot_hero"] = bot_hero
    if human_hero:
        raw["human_hero"] = human_hero
    raw.update(over)
    path = tmp_path / "cfg.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return load_config(path)


# ---------- Medusa vs Hellboy no cambia ----------
def test_the_real_config_yields_exactly_the_old_medusa_vs_hellboy_values():
    cfg = load_config(REAL_CONFIG)
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    assert not {"pieces", "dials", "nicknames", "bot_deck_guid", "human_deck_guid", "destiny_dial"} & set(raw)
    assert cfg.todos == []
    assert cfg.raw["pieces"] == OLD_PIECES and cfg.raw["dials"] == OLD_DIALS and cfg.raw["nicknames"] == OLD_NICKNAMES
    assert (cfg.raw["bot_deck_guid"], cfg.raw["human_deck_guid"], cfg.raw["destiny_dial"]) == ("d42056", "00dc9a", "e17c66")
    scfg = cfg.session_config()
    assert scfg.bot_card_ids == lua.BOT_CARD_IDS == (17600, 17629) and scfg.human_card_ids == lua.HUMAN_CARD_IDS
    assert scfg.human_card_ids == (19700, 19729) and scfg.start_spaces == {}
    assert (scfg.bot_label, scfg.human_label) == ("MEDUSA", "HELLBOY")
    assert cfg.attacker_ids == ui.DEFAULT_ATTACKERS == ("hellboy", "lobster")


def test_the_default_panel_script_is_the_one_of_medusa_vs_hellboy():
    targets = ["medusa", "harpy1", "harpy2", "harpy3"]
    assert lua.create_panel(targets) == lua.create_panel(targets, attacker_ids=("hellboy", "lobster"))


def test_an_old_config_that_spells_everything_out_still_works(tmp_path):
    cfg = config_for(tmp_path, pieces=OLD_PIECES, dials=OLD_DIALS, nicknames=OLD_NICKNAMES, bot_deck_guid="d42056",
                     human_deck_guid="00dc9a", destiny_dial="e17c66")
    assert cfg.raw["pieces"] == OLD_PIECES and cfg.session_config().destiny_dial == "e17c66"


def test_the_config_by_hand_wins_over_the_hero_data_but_only_for_this_pair(tmp_path):
    cfg = config_for(tmp_path, "medusa", "liz-sherman", pieces={"medusa": "aaaaaa", "hellboy": "bbbbbb"},
                     start_spaces={"bot": 30, "human": 3, "hellboy": 9})
    assert cfg.raw["pieces"]["medusa"] == "aaaaaa" and "hellboy" not in cfg.raw["pieces"]
    assert cfg.raw["pieces"]["liz"] == "874d20"
    assert cfg.session_config().start_spaces == {"medusa": 30, "liz": 3}
    assert len(cfg.warnings) == 1 and "'hellboy'" in cfg.warnings[0]


def test_a_hero_without_tts_data_or_the_same_hero_twice_is_a_clear_config_error(tmp_path):
    with pytest.raises(ConfigError, match="no hay datos de TTS|HeroDef"):
        config_for(tmp_path, "medusa", "nadie")
    with pytest.raises(ConfigError, match="los dos bandos"):
        config_for(tmp_path, "medusa", "medusa")


def test_every_hero_of_the_box_has_its_tts_data():
    boxed = {"medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"}
    assert boxed <= set(available_heroes())
    assert all((TTS_DIR / f"{slug}.json").exists() for slug in boxed)


# ---------- el panel sale de los luchadores de cada bando ----------
@pytest.mark.parametrize("bot, human", PAIRS)
def test_the_panel_attacker_buttons_come_from_the_humans_fighters(tmp_path, bot, human):
    cfg = config_for(tmp_path, bot, human)
    human_fighters = load_hero(human).fighters()
    bot_fighters = load_hero(bot).fighters()
    assert cfg.attacker_ids == tuple(f.fid for f in human_fighters)
    targets = [f.fid for f in bot_fighters]
    script = lua.create_panel(targets, cfg.panel_position, cfg.panel_rotation, cfg.panel_scale, cfg.nicknames,
                              attacker_ids=cfg.attacker_ids)
    for f in human_fighters:
        assert f'id="att_{f.fid}"' in script and f"Ataca {cfg.nicknames[f.fid]}</Button>" in script
    for f in bot_fighters:
        assert f'id="{f.fid}"' in script and f"Atacar a {cfg.nicknames[f.fid]}</Button>" in script
    for f in [*human_fighters, *bot_fighters]:       # la vida de TODOS los luchadores, los dos bandos
        assert all(f'id="{p}_{f.fid}"' in script for p in ("hpm", "hpp", "rm"))
    others = [a for a in ("hellboy", "lobster") if a not in cfg.attacker_ids]
    assert all(f'id="att_{a}"' not in script for a in others)


# ---------- una sesion con cualquier par ----------
def build(tmp_path, bot, human):
    cfg = config_for(tmp_path, bot, human)
    scfg = cfg.session_config()
    table = Table(cfg.nicknames, {fid: g for fid, g in scfg.pieces.items()}, bot_cards=scfg.bot_card_ids[0])
    # una pieza que cambia de GUID responde por cualquiera de los dos
    table.guid_name = {g: cfg.nicknames[fid] for fid, v in scfg.pieces.items() for g in play.piece_guids(v)}
    fake = FakeTTS(return_value=table)
    client = TTSClient(send_port=fake.port, listen_port=0)
    fake.reply_port = client.start_listening().port
    scfg.settle_wait, scfg.settle_tries = 0.0, 4
    game = Game.new(cfg.board, seed=3, controllers={}, bot_player=0, heroes=cfg.heroes)
    session = Session(game, client, MedusaAI(0), scfg)
    game.turn, game.turn_no = 1, 2
    game.begin_turn()
    bot_fids, human_fids = [f.fid for f in game.own(0)], [f.fid for f in game.own(1)]
    spaces = sorted(game.board.spaces)
    place(game, **{bot_fids[0]: spaces[0], human_fids[0]: spaces[1]})
    for i, fid in enumerate(bot_fids[1:]):
        place(game, **{fid: spaces[20 + i]})
    for i, fid in enumerate(human_fids[1:]):
        place(game, **{fid: spaces[-1 - i]})
    table.positions = {cfg.nicknames[f]: g.pos for f, g in game.fighters.items()}
    for fid, g in scfg.dials.items():
        table.dials[g] = {"found": True, "name": g, "value": game.fighters[fid].hp, "max": game.fighters[fid].hp}
        session.dials_written[g] = game.fighters[fid].hp
    if scfg.destiny_dial:
        table.dials[scfg.destiny_dial] = {"found": True, "name": "destinos", "value": 0, "max": 11}
    hand = game.players[0].full_set[:5]
    table.bot_hand = [c.card_id for c in hand]
    table.bot_deck = [c.card_id for c in game.players[0].full_set if c.card_id not in table.bot_hand]
    session.read_bot_hand()
    session.snap = None
    return session, table, game, fake, cfg, client


@pytest.fixture
def pair(tmp_path, request):
    bot, human = request.param
    session, table, game, fake, cfg, client = build(tmp_path, bot, human)
    yield session, table, game, fake, cfg
    client.close()
    fake.close()


def human_attack_card(game):
    hero = game.hero(1)
    return next(c for c in game.players[1].full_set if c.can_attack and c.usable_by(hero.name) and c.value is not None)


@pytest.mark.parametrize("pair", PAIRS, ids=[f"{b}-vs-{h}" for b, h in PAIRS], indirect=True)
def test_a_game_with_any_pair_starts_and_the_buttons_cost_what_they_cost_before(pair, monkeypatch):
    session, table, game, fake, cfg = pair
    bot_hero, human_hero = game.hero(0), game.hero(1)
    ranges = [tuple(json.loads((TTS_DIR / f"{slug}.json").read_text("utf-8"))["deck"]["card_ids"]) for slug in cfg.heroes]
    assert [session.cfg.bot_card_ids, session.cfg.human_card_ids] == ranges
    spent = {}

    def run(label, fn):
        n = fake.lua_messages
        fn()
        spent[label] = fake.lua_messages - n
    run("maniobra", lambda: click(session, table, Event.MANEUVER))
    run("fin de accion", lambda: click(session, table, Event.END_ACTION))
    click(session, table, Event.ATTACKER, {"attacker": f"att_{human_hero.fid}"})
    run("atacar", lambda: click(session, table, Event.ATTACK, {"target": bot_hero.fid}))
    table.face_down = [{"id": human_attack_card(game).card_id, "guid": "hcard"}]
    run("revelar", lambda: click(session, table, Event.REVEAL))
    monkeypatch.setattr(session.ai, "plan", lambda g: Act("maneuver", moves={bot_hero.fid: 0}))
    monkeypatch.setattr(session.ai, "pick_ability_target", lambda g: None)
    run("turno del bot", lambda: click(session, table, Event.END_ACTION))
    budget = {"maniobra": 1, "fin de accion": 1, "atacar": 1, "revelar": 3, "turno del bot": 3}   # test_message_counts
    assert spent.keys() == budget.keys() and all(0 < spent[k] <= budget[k] for k in budget), spent


@pytest.mark.parametrize("pair", PAIRS, ids=[f"{b}-vs-{h}" for b, h in PAIRS], indirect=True)
def test_the_panel_of_a_live_session_enables_one_attacker_button_per_fighter_of_the_human(pair):
    session, table, game, fake, cfg = pair
    status, states = session.panel_view()
    humans = [f.fid for f in game.own(1)]
    assert {i for i in states if i.startswith("att_")} == {f"att_{fid}" for fid in humans}
    assert all(states[f"att_{fid}"] == (True, True) for fid in humans)
    assert set(session._panel_ids()) >= {f"{p}_{f}" for f in game.fighters for p in ("hpm", "hpp", "rm")}


@pytest.mark.parametrize("pair", PAIRS, ids=[f"{b}-vs-{h}" for b, h in PAIRS], indirect=True)
def test_a_full_bot_turn_with_the_real_ai_does_not_break_with_any_hero(pair):
    session, table, game, fake, cfg = pair
    click(session, table, Event.MANEUVER)
    click(session, table, Event.END_ACTION)
    click(session, table, Event.MANEUVER)
    msgs = click(session, table, Event.END_ACTION)             # pasa al bot, que juega con la IA de siempre
    lo, hi = session.cfg.bot_card_ids
    assert game.winner is None and not any("Accion ilegal" in m for m in msgs)
    if session.pending is not None:                       # ataca con una carta de SU mazo...
        assert session.pending.kind == "bot_attacks" and lo <= session.pending.bot_card.card_id <= hi
        assert session.pending.bot_card_guid in {f"g{i}" for i in table.bot_play}
    else:                                                 # ...o maniobra y pasa el turno
        assert game.turn == 1 and table.moves


def test_a_bot_whose_ability_is_not_coded_announces_its_text_and_still_plays(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "hellboy", "abe-sapien")
    try:
        session._announce_bot_hero()
        said = [str(m) for m in session.messages]
        assert any("Hellboy" in m and "no esta codificada" in m for m in said)
        assert session._bot_ability_coded() is False
    finally:
        client.close()
        fake.close()


def test_medusa_as_bot_keeps_her_coded_ability_and_says_nothing_extra(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "medusa", "liz-sherman")
    try:
        session._announce_bot_hero()
        assert session.messages == [] and session._bot_ability_coded() is True
    finally:
        client.close()
        fake.close()


def test_the_setup_texts_name_the_humans_own_pieces(tmp_path):
    for human, text in (("hellboy", "Lobster Johnson"), ("abe-sapien", "Victor, Carla y Kate"), ("liz-sherman", "")):
        session, table, game, fake, cfg, client = build(tmp_path, "medusa" if human != "medusa" else "hellboy", human)
        try:
            assert session._sidekick_names() == text
        finally:
            client.close()
            fake.close()


# ---------- el mazo y las piezas cuando el heroe esta aun en su bolsa ----------
def test_the_deck_identity_falls_back_to_the_hero_data_when_the_deck_is_not_on_the_table(tmp_path):
    session, table, game, fake, cfg, client = build(tmp_path, "medusa", "liz-sherman")
    try:
        table.do_deck_identities = lambda s: [{"found": False, "pairs": []} for _ in range(2)]
        session._deck_ident.clear()
        for side in ("bot", "human"):
            pairs = session._identity(side)
            assert pairs == session.cfg.deck_identity[side] and "steamusercontent" in pairs[0][0]
        assert session._identity("human") != session._identity("bot")
    finally:
        client.close()
        fake.close()

# ---------- desempaquetar: nunca duplica nada (se ejecuta el Lua real con lupa sobre una mesa minima) ----------
WORLD = r"""
WORLD = {}
local function vec(x, y, z) return {x = x, y = y, z = z} end
Vector = function(x, y, z) return vec(x, y, z) end
function add(o)
  o.pos = o.pos or vec(0, 1, 0)
  o.getPosition = function() return o.pos end
  o.getData = function()
    if o.type == "Card" then return {CardID = o.cid} end
    local co = {}
    for _, c in ipairs(o.cards or {}) do table.insert(co, {CardID = c}) end
    return {ContainedObjects = co}
  end
  o.getObjects = function()
    local out = {}
    for _, g in ipairs(o.contents or {}) do table.insert(out, {guid = g}) end
    return out
  end
  o.shuffle = function() o.shuffled = true end
  o.takeObject = function(p)
    for i, g in ipairs(o.contents) do
      if g == p.guid then
        table.remove(o.contents, i)
        local n = add({guid = g, type = "Thing", pos = p.position})
        if p.callback_function then p.callback_function(n) end
        return n
      end
    end
  end
  table.insert(WORLD, o)
  return o
end
getObjects = function() return WORLD end
getObjectFromGUID = function(g) for _, o in ipairs(WORLD) do if o.guid == g then return o end end return nil end
function count(g) local n = 0 for _, o in ipairs(WORLD) do if o.guid == g then n = n + 1 end end return n end
"""


@pytest.fixture
def world():
    pytest.importorskip("lupa")
    from lupa import lua54
    rt = lua54.LuaRuntime()
    rt.execute(WORLD)

    def conv(x):
        if lua54.lua_type(x) == "table":
            keys = list(x.keys())
            if not keys:
                return []
            if all(isinstance(k, int) for k in keys):
                return [conv(x[k]) for k in sorted(keys)]
            return {str(k): conv(x[k]) for k in keys}
        return x
    rt.globals().JSON = rt.table_from({"encode": lambda v: json.dumps(conv(v))})

    class W:
        def add(self, guid, type_="Thing", **kw):
            spec = {"guid": guid, "type": type_}
            for k, v in kw.items():
                spec[k] = rt.table_from(v) if isinstance(v, (list, dict)) else v
            return rt.eval("add")(rt.table_from(spec))

        def count(self, guid):
            return rt.eval("count")(guid)

        def run(self, plan):
            return json.loads(rt.execute(lua.unpack_from_bags(plan).split("\n", 1)[1]))
    return W()


def hero_plan(tmp_path, bot="medusa", human="hellboy"):
    return play.unpack_plan(config_for(tmp_path, bot, human))


def everything_on_the_table(w, plan, skip=()):
    """El primer GUID de cada objeto del plan en la mesa, menos los de `skip`."""
    for _, guids, *_ in plan:
        if guids[0] not in skip:
            w.add(guids[0])


def test_a_piece_in_its_other_state_is_not_missing_and_nothing_is_duplicated(world, tmp_path):
    """(a) Hellboy en ANUNG UN RAMA: f9789a ya es e6f06e. La bolsa interior aun guarda f9789a."""
    plan = hero_plan(tmp_path)
    everything_on_the_table(world, plan, skip={"f9789a"})
    world.add("e6f06e")
    world.add("c592d8", "Bag", contents=["f9789a"])
    res = world.run(plan)
    assert res["taken"] == [] and res["missing"] == []
    assert world.count("f9789a") == 0 and world.count("e6f06e") == 1


def test_a_deck_that_became_a_card_is_found_by_site_and_range_and_not_taken_again(world, tmp_path):
    """(b) el mazo del humano perdio su GUID (queda una Card en su sitio): no se saca otro de la bolsa."""
    cfg = config_for(tmp_path)
    x, z = cfg.raw["human_deck_spot"]
    plan = play.unpack_plan(cfg)
    everything_on_the_table(world, plan, skip={"00dc9a"})
    world.add("zzzzzz", "Card", cid=19705, pos={"x": x, "y": 1.0, "z": z})
    world.add("c592d8", "Bag", contents=["00dc9a"])
    res = world.run(plan)
    assert res["taken"] == [] and res["missing"] == [] and world.count("00dc9a") == 0


def test_a_card_of_another_game_at_the_deck_site_does_not_count_as_the_deck(world, tmp_path):
    cfg = config_for(tmp_path)
    x, z = cfg.raw["human_deck_spot"]
    plan = play.unpack_plan(cfg)
    everything_on_the_table(world, plan, skip={"00dc9a"})
    world.add("yyyyyy", "Card", cid=555, pos={"x": x, "y": 1.0, "z": z})
    world.add("c592d8", "Bag", contents=["00dc9a"])
    assert world.run(plan)["taken"] == ["00dc9a"] and world.count("00dc9a") == 1


def test_with_the_inner_bag_loose_on_the_table_pieces_already_out_are_not_taken_twice(world, tmp_path):
    """(c) la bolsa interior suelta en la mesa aun lista piezas que ya estan fuera."""
    plan = hero_plan(tmp_path)
    everything_on_the_table(world, plan)
    world.add("c592d8", "Bag", contents=["046660", "18c384", "e33604", "1644a3", "e17c66"])
    world.add("e5a45c", "Bag", contents=["bcd809", "04b2c9", "328e52"])
    res = world.run(plan)
    assert res["taken"] == [] and res["missing"] == []
    assert all(world.count(guids[0]) == 1 for _, guids, *_ in plan if guids[0] not in ("c592d8", "e5a45c"))


def test_a_guid_repeated_in_another_bag_of_the_mod_is_never_taken(world, tmp_path):
    """(e) 18c384 es el dial de Lobster y tambien "The Jackalope" de Bigfoot; bcd809 un objeto de Loki."""
    plan = hero_plan(tmp_path)
    everything_on_the_table(world, plan, skip={"18c384", "bcd809", "4fdf31"})
    world.add("aaaaaa", "Bag", contents=["18c384", "bcd809", "4fdf31"])         # bolsa de otro personaje
    res = world.run(plan)
    assert res["taken"] == [] and set(res["missing"]) == {"18c384", "bcd809"}
    assert world.count("18c384") == world.count("bcd809") == 0
    world.add("c592d8", "Infinite", contents=["18c384"])                        # una infinita con ese GUID tampoco
    assert world.run(plan)["taken"] == []


def test_the_hero_inner_bag_gives_what_is_missing_once_and_a_second_run_takes_nothing(world, tmp_path):
    plan = hero_plan(tmp_path, "medusa", "liz-sherman")
    pieces = [g[0] for _, g, bag, *_ in plan if bag == "77449a"]
    everything_on_the_table(world, plan, skip=set(pieces))
    world.add("77449a", "Bag", contents=list(pieces))
    first = world.run(plan)
    assert sorted(first["taken"]) == sorted(pieces) and first["missing"] == []
    assert all(world.count(g) == 1 for g in pieces)
    second = world.run(plan)
    assert second["taken"] == [] and all(world.count(g) == 1 for g in pieces)


def test_the_inner_bag_not_on_the_table_means_a_warning_and_no_action(tmp_path):
    cfg = config_for(tmp_path, "medusa", "liz-sherman")
    lines, calls = [], []

    class Client:
        def call_lua(self, script):
            calls.append(script.split("\n")[0])
            return {"present": [], "taken": [], "missing": ["874d20"]}
    play.prepare_heroes(Client(), cfg, lines.append)
    assert calls == ["-- sparring:unpack_from_bags"]
    assert any("874d20" in line and "colocalos a mano" in line for line in lines)
    assert not any("saca la bolsa" in line for line in lines)


def test_unpack_is_opt_in_and_never_runs_when_resuming(live, cfg_file, monkeypatch, tmp_path):
    table, fake, ports = live
    seen = []
    monkeypatch.setattr(play, "prepare_heroes", lambda *a, **k: seen.append(1))

    def interrupted(*a, **k):
        raise KeyboardInterrupt
    monkeypatch.setattr(play, "run_loop", interrupted)
    state = ["--state", str(tmp_path / "s.json")]
    play.main(["--config", str(cfg_file()), *ports, *state])
    assert seen == []                                              # por defecto no
    play.main(["--config", str(cfg_file()), *ports, *state, "--unpack"])
    assert seen == [1]
    play.main(["--config", str(cfg_file(unpack=True)), *ports, *state])
    assert seen == [1, 1]
    play.main(["--config", str(cfg_file(unpack=True)), *ports, *state, "--unpack", "--resume"])
    assert seen == [1, 1]                                          # nunca con --resume


def test_the_real_config_has_no_unpack_keys_and_the_default_spots_clear_the_hand_zones():
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    assert not {"unpack", "bot_unpack_spot", "human_unpack_spot", "unpack_step"} & set(raw)
    hands = [(-30.1, 7.0, 10, 4), (30.1, 6.9, 9.9, 3.9)]               # Purple 9bdc19 y Yellow aed1b8
    for side, (x, y, z) in play.UNPACK_SPOTS.items():
        for n in range(8):
            zz = z + n * play.UNPACK_STEP[2]
            for cx, cz, w, d in hands:
                assert not (abs(x - cx) < w / 2 + 1 and abs(zz - cz) < d / 2 + 1), (side, n)


def test_unpack_script_takes_only_from_the_given_bag_by_exact_guid():
    script = lua.unpack_from_bags([("piece", ("874d20",), "77449a", (1.0, 2.0, 3.0), None),
                                   ("deck", ("b603cb",), "77449a", (4.0, 2.0, 5.0), (19900, 19929))])
    assert script.startswith("-- sparring:unpack_from_bags") and 'bag.type == "Bag"' in script
    assert "takeObject" in script and "UI." not in script and "Global" not in script
    for bad in ([("piece", ('x"); os.exit() --',), "77449a", (0.0, 0.0, 0.0), None)],
                [("bag", ("874d20",), "77449a", (0.0, 0.0, 0.0), None)],
                [("piece", ("874d20",), "bad guid", (0.0, 0.0, 0.0), None)], []):
        with pytest.raises(ValueError):
            lua.unpack_from_bags(bad)
