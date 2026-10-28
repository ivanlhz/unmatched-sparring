"""Deteccion de los heroes en la mesa (solo lectura) y opciones --bot-hero / --human-hero."""
import json
import os
from pathlib import Path

import pytest

from fake_tts import FakeTTS
from sparring import persist, play
from sparring.hero_detect import HeroDetectionError, TableReading, detect_heroes, hero_slugs
from sparring.play import ConfigError, load_config, main, resolve_heroes
from sparring.tts import lua
from sparring.tts.hero_table import load_hero_table
from test_play import free_port
from test_session import rig  # noqa: F401

REAL_CONFIG = Path(__file__).resolve().parent.parent / "config" / "partida.json"
SLUGS = hero_slugs()
BOT_SPOT, HUMAN_SPOT = (7.28, 13.93), (-4.6, 13.67)


def pile(slug, x, z, n=30, kind="Deck"):
    counts = [n if s == slug else 0 for s in SLUGS]
    return {"type": kind, "guid": f"p{slug[:3]}{int(x)}", "x": x, "z": z, "counts": counts}


def reading(*piles, pieces=()):
    return TableReading(list(piles), {g: (0.0, 0.0) for g in pieces}, SLUGS)


def at_bot(slug, **kw):
    return pile(slug, 7.0, 14.0, **kw)


def at_human(slug, **kw):
    return pile(slug, -5.0, 13.5, **kw)


def detect(r, fixed=(None, None)):
    return detect_heroes(r, BOT_SPOT, HUMAN_SPOT, fixed)


# ---------- la decision ----------
def test_medusa_and_liz_are_told_apart_and_assigned_by_the_nearest_deck_spot():
    assert detect(reading(at_bot("medusa"), at_human("liz-sherman"))) == ("medusa", "liz-sherman")
    assert detect(reading(at_bot("liz-sherman"), at_human("medusa"))) == ("liz-sherman", "medusa")


def test_discard_and_hand_cards_follow_their_side_and_a_stray_card_does_not_confuse():
    r = reading(at_bot("medusa", n=12), pile("medusa", 15.0, -14.0, n=8, kind="Card"),
                at_human("hellboy", n=14), pile("hellboy", -30.0, -9.0, n=3, kind="Card"),
                pile("medusa", -12.0, 0.0, n=1, kind="Card"))
    assert detect(r) == ("medusa", "hellboy")


def test_a_fixed_side_is_used_as_is_and_the_other_is_still_detected():
    r = reading(at_bot("medusa"), at_human("abe-sapien"), pile("hellboy", -5.0, 13.0))
    with pytest.raises(HeroDetectionError):
        detect(r)
    assert detect(r, (None, "hellboy")) == ("medusa", "hellboy")           # el fijado no cuenta como candidato del otro
    assert detect(reading(at_bot("medusa")), (None, "liz-sherman")) == ("medusa", "liz-sherman")   # el fijado no esta en la mesa
    assert detect(reading(at_bot("medusa"), at_human("abe-sapien")), ("baba-yaga", None)) == ("baba-yaga", "abe-sapien")


@pytest.mark.parametrize("r, text", [
    (reading(), "no veo ningun mazo"),
    (reading(at_bot("medusa")), "humano"),
    (reading(at_bot("medusa"), pile("hellboy", 6.0, 12.0), at_human("liz-sherman")), "2 heroes candidatos"),
    (reading(at_bot("medusa"), at_human("medusa")), "el mismo heroe en los dos"),
])
def test_ambiguity_is_an_error_that_lists_what_was_seen_and_how_to_force_it(r, text):
    with pytest.raises(HeroDetectionError, match=text) as e:
        detect(r)
    assert "--bot-hero" in str(e.value) and "--human-hero" in str(e.value)


def test_miniatures_alone_are_reported_but_never_decide():
    guid = next(iter(load_hero_table("hellboy").fighters.values())).pieces[0]
    with pytest.raises(HeroDetectionError, match="solo 1 miniatura"):
        detect(reading(at_bot("medusa"), pieces=[guid]))


def test_same_hero_fixed_on_both_sides_is_an_error():
    with pytest.raises(HeroDetectionError, match="mismo heroe"):
        detect(reading(at_bot("medusa"), at_human("liz-sherman")), ("medusa", "medusa"))


# ---------- el script de Lua ----------
def test_the_lua_counts_cards_per_hero_range_and_ignores_what_is_inside_bags():
    lupa = pytest.importorskip("lupa")
    from lupa import lua54
    from test_review10 import STUB, conv
    rt = lua54.LuaRuntime()
    rt.execute(STUB)
    rt.globals().JSON = rt.table_from({"encode": lambda v: json.dumps(conv(v))})
    medusa, liz = load_hero_table("medusa"), load_hero_table("liz-sherman")
    guid = medusa.fighters["medusa"].pieces[0]
    rt.execute(f"""
local cards = {{}}
for i = 0, 29 do table.insert(cards, {{cid = {medusa.card_ids[0]} + i, guid = 'm' .. i, owner = 'medusa'}}) end
mkobj({{guid = 'dm', type = 'Deck', cards = cards, pos = {{x = 7, y = 1, z = 14}}}})
mkobj({{guid = 'cl', type = 'Card', cid = {liz.card_ids[0] + 3}, owner = 'liz', pos = {{x = -5, y = 1, z = 13}}}})
mkobj({{guid = 'other', type = 'Card', cid = 5, owner = 'x'}})
mkobj({{guid = 'bag', type = 'Bag', cards = {{}}}})
mkobj({{guid = '{guid}', type = 'Figurine', pos = {{x = 1, y = 1, z = 2}}}})
""")
    rt.execute(lua.request(lua.table_heroes([medusa.card_ids, liz.card_ids], [guid, "ffffff"]), 1))
    reply = conv(rt.globals().SENT[1])
    res = json.loads(reply["value"])
    by_guid = {p["guid"]: p for p in res["piles"]}
    assert set(by_guid) == {"dm", "cl"} and by_guid["dm"]["counts"] == [30, 0] and by_guid["cl"]["counts"] == [0, 1]
    assert set(res["pieces"]) == {guid}


def test_the_lua_script_is_read_only_and_validates_its_input():
    assert "table_heroes" in play.READ_ONLY_TAGS
    for bad in ([], [("a", 2)]):
        with pytest.raises(TypeError):
            lua.table_heroes(bad, [])
    with pytest.raises(ValueError):
        lua.table_heroes([(1, 2)], ['x"'])


# ---------- prioridades al cargar y al resolver ----------
class Reader:
    """Cliente falso: responde a `table_heroes` con una mesa fija y apunta cada script."""

    def __init__(self, *piles, fail=False):
        self.piles, self.fail, self.seen = piles, fail, []

    def call_lua(self, script, *a, **k):
        self.seen.append(script.split("\n")[0])
        if self.fail:
            raise TimeoutError("sin respuesta")
        return {"piles": list(self.piles), "pieces": {}}


def cfg_with(tmp_path, **over):
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    raw.update(over)
    path = tmp_path / "c.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    return path


MEDUSA_LIZ = (at_bot("medusa"), at_human("liz-sherman"))


def test_auto_and_a_missing_key_both_mean_detect_and_the_line_is_printed(tmp_path):
    lines = []
    cfg = resolve_heroes(Reader(*MEDUSA_LIZ), load_config(REAL_CONFIG), echo=lines.append)
    assert cfg.heroes == ("medusa", "liz-sherman") and cfg.raw["human_deck_guid"] == load_hero_table("liz-sherman").deck_guid
    assert lines == ["Heroes detectados: bot Medusa, humano Liz Sherman (por los mazos en la mesa)"]
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    del raw["bot_hero"], raw["human_hero"]
    path = tmp_path / "nokeys.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    assert resolve_heroes(Reader(*MEDUSA_LIZ), load_config(path), echo=lambda _: None).heroes == ("medusa", "liz-sherman")


def test_startup_option_beats_detection_and_config_and_a_config_value_beats_detection(tmp_path):
    reader = Reader(at_bot("medusa"), at_human("hellboy"))
    lines = []
    cfg = resolve_heroes(reader, load_config(cfg_with(tmp_path, bot_hero="baba-yaga"), bot_hero="abe-sapien"),
                         echo=lines.append)
    assert cfg.heroes == ("abe-sapien", "hellboy") and "bot: opcion de arranque; humano: mazos en la mesa" in lines[0]
    cfg = resolve_heroes(reader, load_config(cfg_with(tmp_path, bot_hero="baba-yaga", human_hero="liz-sherman")),
                         echo=lines.append)
    assert cfg.heroes == ("baba-yaga", "liz-sherman") and reader.seen == ["-- sparring:table_heroes"]   # no leyo la 2a vez
    assert "(por configuracion)" in lines[1]


def test_when_both_sides_are_fixed_the_table_is_not_even_read(tmp_path):
    reader = Reader()
    cfg = resolve_heroes(reader, load_config(REAL_CONFIG, "liz-sherman", "baba-yaga"), echo=lambda _: None)
    assert cfg.heroes == ("liz-sherman", "baba-yaga") and reader.seen == []


def test_an_unreadable_table_falls_back_to_medusa_vs_hellboy_with_a_warning():
    lines = []
    cfg = resolve_heroes(Reader(fail=True), load_config(REAL_CONFIG, human_hero="liz-sherman"), echo=lines.append)
    assert cfg.heroes == ("medusa", "liz-sherman")
    assert any("no pude detectar los heroes" in w and "sin respuesta" in w for w in cfg.warnings)


def test_a_clear_read_that_is_ambiguous_does_not_fall_back():
    with pytest.raises(HeroDetectionError):
        resolve_heroes(Reader(at_bot("medusa")), load_config(REAL_CONFIG), echo=lambda _: None)


def test_resume_takes_the_heroes_from_the_save_unless_an_option_says_otherwise():
    reader = Reader(*MEDUSA_LIZ)
    cfg = resolve_heroes(reader, load_config(REAL_CONFIG, bot_hero="hellboy"), ("baba-yaga", "abe-sapien"),
                         echo=lambda _: None)
    assert cfg.heroes == ("hellboy", "abe-sapien") and reader.seen == []


def test_the_real_config_asks_for_detection_and_the_unknown_slug_is_a_config_error():
    raw = json.loads(REAL_CONFIG.read_text(encoding="utf-8"))
    assert raw["bot_hero"] == raw["human_hero"] == "auto"
    assert "--bot-hero" in " ".join(raw["_notes"])
    with pytest.raises(ConfigError):
        resolve_heroes(Reader(), load_config(REAL_CONFIG, "nadie", "hellboy"), echo=lambda _: None)


# ---------- de punta a punta con FakeTTS ----------
@pytest.fixture
def wire():
    state = {"piles": list(MEDUSA_LIZ), "scripts": []}

    def answer(msg):
        tag = msg["script"].split("\n")[0]
        state["scripts"].append(tag)
        if tag == "-- sparring:table_heroes":
            return {"piles": state["piles"], "pieces": {}}
        return {}
    fake = FakeTTS(return_value=answer)
    listen = free_port()
    fake.reply_port = listen
    yield state, fake, ["--send-port", str(fake.port), "--listen-port", str(listen)]
    fake.close()


def test_read_only_detects_with_a_single_read_only_message_and_prints_the_line(wire, capsys, monkeypatch):
    state, fake, ports = wire
    seen = []
    monkeypatch.setattr(play, "read_only_report", lambda client, cfg: seen.append(cfg.heroes) or ["informe"])
    assert main(["--config", str(REAL_CONFIG), "--read-only", *ports]) == 0
    assert seen == [("medusa", "liz-sherman")]
    assert "Heroes detectados: bot Medusa, humano Liz Sherman" in capsys.readouterr().out
    assert state["scripts"] == ["-- sparring:table_heroes"] and {m["messageID"] for m in fake.received} == {3}


def test_main_refuses_with_exit_2_when_the_table_is_ambiguous_and_never_plays(wire, capsys):
    state, fake, ports = wire
    state["piles"] = [at_bot("medusa")]
    assert main(["--config", str(REAL_CONFIG), "--read-only", *ports]) == 2
    err = capsys.readouterr().err
    assert "No puedo saber el heroe del humano" in err and "--human-hero" in err
    assert state["scripts"] == ["-- sparring:table_heroes"]


def test_main_option_forces_the_hero_and_skips_the_ambiguity(wire, capsys, monkeypatch):
    state, fake, ports = wire
    state["piles"] = [at_bot("medusa")]
    seen = []
    monkeypatch.setattr(play, "read_only_report", lambda client, cfg: seen.append(cfg.heroes) or [])
    assert main(["--config", str(REAL_CONFIG), "--read-only", "--human-hero", "abe-sapien", *ports]) == 0
    assert seen == [("medusa", "abe-sapien")]


def test_resume_respects_the_heroes_stored_in_the_save(wire, tmp_path, monkeypatch):
    state, fake, ports = wire
    save = tmp_path / "s.json"
    persist.save_atomic(save, {"heroes": ["baba-yaga", "abe-sapien"]})
    seen = []

    def stop(cfg, *a, **k):
        seen.append(cfg.heroes)
        raise KeyboardInterrupt
    monkeypatch.setattr(play, "play", stop)
    main(["--config", str(REAL_CONFIG), "--state", str(save), "--resume", *ports])
    assert seen == [("baba-yaga", "abe-sapien")] and state["scripts"] == []


def test_the_save_records_the_heroes_of_the_game(rig):
    session, table, game = rig
    assert session.to_dict()["heroes"] == ["medusa", "hellboy"]


# ---------- robustez: cartas sueltas, mayorias y empates ----------
def test_a_single_stray_card_of_a_third_hero_near_the_bot_spot_does_not_confuse():
    r = reading(at_bot("medusa"), pile("hellboy", 6.5, 13.0, n=1, kind="Card"), at_human("liz-sherman"))
    assert detect(r) == ("medusa", "liz-sherman")


def test_two_plus_two_loose_cards_of_two_other_heroes_are_not_candidates():
    r = reading(at_bot("medusa"), at_human("liz-sherman"),
                pile("hellboy", 6.5, 13.0, n=2, kind="Card"), pile("abe-sapien", 6.0, 14.0, n=2, kind="Card"))
    assert detect(r) == ("medusa", "liz-sherman")


def test_a_four_card_pile_alone_is_not_a_candidate():
    with pytest.raises(HeroDetectionError, match="no veo ningun mazo"):
        detect(reading(at_bot("medusa"), at_human("hellboy", n=4)))


def test_several_candidates_pick_the_clear_majority_only():
    assert detect(reading(at_bot("medusa"), pile("hellboy", 6.0, 12.0, n=6), at_human("liz-sherman"))) == ("medusa", "liz-sherman")
    with pytest.raises(HeroDetectionError, match="2 heroes candidatos"):   # 30 contra 20 no es claro
        detect(reading(at_bot("medusa"), pile("hellboy", 6.0, 12.0, n=20), at_human("liz-sherman")))
    with pytest.raises(HeroDetectionError, match="2 heroes candidatos"):   # 5 contra 5
        detect(reading(pile("medusa", 7.0, 14.0, n=5), pile("hellboy", 6.0, 12.0, n=5), at_human("liz-sherman")))


def test_a_tie_between_sides_is_ambiguous_not_given_to_the_human():
    r = reading(pile("medusa", 7.0, 14.0, n=10), pile("medusa", -5.0, 13.5, n=10))
    with pytest.raises(HeroDetectionError):
        detect(r)
    r = reading(pile("medusa", 7.0, 14.0, n=3), pile("medusa", -5.0, 13.5, n=3), at_bot("hellboy"))
    assert detect(r, (None, "liz-sherman")) == ("hellboy", "liz-sherman")   # 3 y 3 no cuentan


@pytest.mark.parametrize("bot", ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"])
@pytest.mark.parametrize("human", ["medusa", "hellboy", "abe-sapien", "baba-yaga", "liz-sherman"])
def test_every_pair_of_heroes_is_detected_in_either_seat(bot, human):
    if bot == human:
        pytest.skip("el mismo heroe en los dos bandos es un error")
    stray = pile("liz-sherman" if "liz-sherman" not in (bot, human) else "hellboy", 6.5, 13.0, n=1, kind="Card")
    assert detect(reading(at_bot(bot), at_human(human), stray)) == (bot, human)
