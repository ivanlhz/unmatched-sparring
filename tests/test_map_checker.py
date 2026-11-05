"""tools/map_checker.py: the logic behind the local map checker (edit, validate, confirm, the guards of the server).
The browser page itself is not tested."""
from __future__ import annotations

import http.client
import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import map_checker as mc  # noqa: E402

from sparring.board import Board, catalog  # noqa: E402

ZONES = ["red", "blue", "green"]


def ring(n=4):
    return {"key": "t", "name": "T", "imageKey": "A" * 40, "playable": False, "verified": False, "problems": ["x"],
            "starts": {"1": 0, "2": 2},
            "spaces": [{"id": i, "local": [float(i), 0.0], "zones": ["red"], "adj": sorted({(i + 1) % n, (i - 1) % n})}
                       for i in range(n)]}


@pytest.fixture
def maps(tmp_path):
    d = tmp_path / "maps"
    d.mkdir()
    (d / "t.json").write_text(json.dumps(ring()), encoding="utf-8")
    (d / "catalog.json").write_text(json.dumps([
        {"key": "t", "name": "T", "imageKey": "A" * 40, "status": "unavailable", "why": ["x"]},
        {"key": "navy-pier", "name": "Navy Pier", "imageKey": "B" * 40, "status": "excluded", "reason": "tokens"}]), encoding="utf-8")
    return d


# ---------- editing ----------
def test_an_edit_replaces_the_edges_zones_and_starts_and_leaves_the_original_alone():
    data = ring()
    out = mc.apply_edit(data, {"edges": [[0, 1], [1, 2], [2, 3], [0, 2]], "zones": {"1": ["blue", "green"]}, "starts": {"1": 1, "2": 3}})
    assert out["spaces"][0]["adj"] == [1, 2] and out["spaces"][2]["adj"] == [0, 1, 3]
    assert out["spaces"][3]["adj"] == [2] and out["spaces"][1]["zones"] == ["blue", "green"] and out["starts"] == {"1": 1, "2": 3}
    assert data == ring()


@pytest.mark.parametrize("edit", [{"edges": [[0, 9]]}, {"edges": [[1, 1]]}, {"zones": {"9": ["red"]}}, {"zones": {"0": "red"}},
                                  {"starts": {"1": 9}}, {"starts": {"7": 0}}, {"starts": {"5": 0}}])
def test_a_bad_edit_is_rejected(edit):
    with pytest.raises(ValueError):
        mc.apply_edit(ring(), edit)


# ---------- the structural checks ----------
def test_a_sound_map_has_no_problems_and_a_dead_end_is_left_to_the_person():
    assert mc.validate(ring(), {"spacesCount": 4, "zonesCount": 1}, ZONES) == []
    chain = mc.apply_edit(ring(), {"edges": [[0, 1], [1, 2], [2, 3]]})
    assert mc.validate(chain, None, ZONES) == []


@pytest.mark.parametrize("make, text", [
    (lambda d: mc.apply_edit(d, {"edges": [[0, 1], [2, 3]]}), "not connected"),
    (lambda d: mc.apply_edit(d, {"zones": {"2": []}}), "without a zone: [2]"),
    (lambda d: mc.apply_edit(d, {"zones": {"2": ["pink"]}}), "not know"),
    (lambda d: mc.apply_edit(d, {"starts": {"1": 0}}), "start 2 is not set"),
    (lambda d: mc.apply_edit(d, {"starts": {"1": 1, "2": 1}}), "same space"),
])
def test_each_structural_check_reports(make, text):
    assert any(text in p for p in mc.validate(make(ring()), None, ZONES))


def test_the_published_counts_are_checked():
    problems = mc.validate(ring(), {"spacesCount": 5, "zonesCount": 3}, ZONES)
    assert any("4 spaces, the map has 5" in p for p in problems) and any("1 zone colours used, the map has 3" in p for p in problems)


def test_an_edge_that_is_not_symmetric_is_reported():
    data = ring()
    data["spaces"][0]["adj"] = [1, 2, 3]
    data["spaces"][2]["adj"] = [1, 3]
    assert any("not symmetric" in p for p in mc.validate(data, None, ZONES))


# ---------- confirming ----------
def test_confirm_writes_a_verified_playable_map_and_marks_it_supported(maps):
    ok, problems = mc.confirm(maps, "t", {"zones": {"1": ["blue"]}}, {"spacesCount": 4, "zonesCount": 2}, ZONES)
    assert ok and problems == []
    written = json.loads((maps / "t.json").read_text(encoding="utf-8"))
    assert written["verified"] is True and written["playable"] is True and "problems" not in written
    assert written["spaces"][1]["zones"] == ["blue"]
    entry = json.loads((maps / "catalog.json").read_text(encoding="utf-8"))[0]
    assert entry["status"] == "supported" and "why" not in entry
    assert not list(maps.glob("*.tmp"))


def test_confirm_writes_nothing_while_a_check_fails(maps):
    before = (maps / "t.json").read_text(encoding="utf-8"), (maps / "catalog.json").read_text(encoding="utf-8")
    ok, problems = mc.confirm(maps, "t", {"edges": [[0, 1], [2, 3]]}, None, ZONES)
    assert not ok and any("not connected" in p for p in problems)
    assert (maps / "t.json").read_text(encoding="utf-8") == before[0]
    assert (maps / "catalog.json").read_text(encoding="utf-8") == before[1]


def test_an_excluded_or_unknown_map_cannot_be_confirmed(maps):
    assert mc.confirm(maps, "navy-pier", {}, None, ZONES)[0] is False
    (maps / "ghost.json").write_text(json.dumps(ring()), encoding="utf-8")
    assert mc.confirm(maps, "ghost", {}, None, ZONES)[0] is False
    with pytest.raises(ValueError):
        mc.confirm(maps, "../x", {}, None, ZONES)


def test_the_list_hides_the_excluded_maps_and_the_view_places_the_spaces(maps):
    assert [m["key"] for m in mc.list_maps(maps)] == ["t"]
    view = mc.map_view(maps, "t")
    assert view["spaces"][0]["fx"] == 0.5 and view["spaces"][0]["fy"] == 0.5
    assert view["spaces"][1]["fx"] == pytest.approx(0.5 - 1 / 16.75)


def test_the_published_counts_are_matched_by_map_key(tmp_path):
    p = tmp_path / "maps.json"
    p.write_text(json.dumps([{"name": "B.P.R.D. HQ", "spacesCount": 32, "zonesCount": 9},
                             {"name": "Thrilla In Manilla", "spacesCount": 30, "zonesCount": 7}]), encoding="utf-8")
    assert mc.load_expected(p) == {"bprd-hq": {"spacesCount": 32, "zonesCount": 9},
                                   "thrilla-in-manila": {"spacesCount": 30, "zonesCount": 7}}
    assert mc.load_expected(None) == {}


def test_every_zone_name_the_checker_offers_is_one_the_bot_can_say():
    assert "red" in mc.known_zones() and "teal" in mc.known_zones()


def test_the_supported_data_in_the_repo_passes_the_checks_that_confirm_would_run():
    for entry in catalog():
        if entry.status == "supported":
            data = json.loads((ROOT / "data" / "maps" / f"{entry.key}.json").read_text(encoding="utf-8"))
            assert mc.validate(data, None, mc.known_zones()) == [], entry.key
            assert Board.load(entry.key)


# ---------- the server guards ----------
@pytest.fixture
def server(maps, tmp_path):
    images = tmp_path / "images"
    images.mkdir()
    (images / ("A" * 40 + ".img")).write_bytes(b"\x89PNG\r\n\x1a\nxx")
    mc.Handler.maps_dir, mc.Handler.images_dir, mc.Handler.expected, mc.Handler.zones = maps, images, {}, ZONES
    srv = ThreadingHTTPServer(("127.0.0.1", 0), mc.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", maps
    srv.shutdown()
    srv.server_close()


def call(url, body=None, headers=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read(), r.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers


def test_the_server_serves_the_map_and_the_image_from_the_images_folder(server):
    base, _ = server
    status, body, _ = call(base + "/api/map/t")
    assert status == 200 and json.loads(body)["spaces"][0]["id"] == 0
    status, body, headers = call(base + "/image/t")
    assert status == 200 and headers["Content-Type"] == "image/png"
    assert call(base + "/image/..%2Fcatalog")[0] == 404


def test_the_server_refuses_a_foreign_host_origin_or_a_form_post(server):
    base, maps = server
    assert call(base + "/api/maps", headers={"Host": "evil.test"})[0] == 403
    assert call(base + "/api/confirm/t", {}, {"Content-Type": "application/json", "Origin": "http://evil.test"})[0] == 403
    assert call(base + "/api/confirm/t", {}, {"Content-Type": "text/plain"})[0] == 403
    assert json.loads((maps / "catalog.json").read_text(encoding="utf-8"))[0]["status"] == "unavailable"


def test_the_server_confirms_through_the_same_logic(server):
    base, maps = server
    status, body, _ = call(base + "/api/confirm/t", {"zones": {"1": ["blue"]}}, {"Content-Type": "application/json"})
    assert status == 200 and json.loads(body)["written"] is True
    assert json.loads((maps / "t.json").read_text(encoding="utf-8"))["verified"] is True
    status, body, _ = call(base + "/api/check/t", {"edges": [[0, 1]]}, {"Content-Type": "application/json"})
    assert any("not connected" in p for p in json.loads(body)["problems"])


def test_the_checker_refuses_an_images_folder_inside_the_repo():
    assert mc.main(["--images", str(ROOT / "assets")]) == 2


def test_a_map_that_is_already_confirmed_is_refused_unless_reconfirming_is_allowed(maps):
    assert mc.confirm(maps, "t", {}, None, ZONES)[0] is True
    ok, problems = mc.confirm(maps, "t", {"zones": {"1": ["blue"]}}, None, ZONES)
    assert not ok and "already confirmed" in problems[0]
    assert json.loads((maps / "t.json").read_text(encoding="utf-8"))["spaces"][1]["zones"] == ["red"]
    assert mc.confirm(maps, "t", {"zones": {"1": ["blue"]}}, None, ZONES, allow_reconfirm=True)[0] is True


def raw_post(base, path, headers, body=b""):
    conn = http.client.HTTPConnection(base.split("//")[1], timeout=5)
    conn.putrequest("POST", path, skip_host=True)
    for k, v in headers.items():
        conn.putheader(k, v)
    conn.endheaders(body)
    resp = conn.getresponse()
    return resp.status, resp.read()


def test_the_server_checks_who_is_asking_before_it_reads_the_body(server):
    base, _ = server
    # claims 100 bytes and sends none: a server that read first would hang until the timeout
    status, _ = raw_post(base, "/api/confirm/t", {"Host": "evil.test", "Content-Type": "application/json", "Content-Length": "100"})
    assert status == 403


@pytest.mark.parametrize("length", ["-5", "abc", "999999999"])
def test_a_missing_negative_or_huge_content_length_is_a_400(server, length):
    base, _ = server
    headers = {"Host": base.split("//")[1], "Content-Type": "application/json", "Content-Length": length}
    assert raw_post(base, "/api/confirm/t", headers)[0] == 400
    assert raw_post(base, "/api/confirm/t", {k: v for k, v in headers.items() if k != "Content-Length"})[0] == 400


@pytest.mark.parametrize("body", [b"[1,2]", b'"x"', b"null", b"{not json"])
def test_a_body_that_is_not_a_json_object_is_a_400_not_a_traceback(server, body):
    base, maps = server
    headers = {"Host": base.split("//")[1], "Content-Type": "application/json", "Content-Length": str(len(body))}
    assert raw_post(base, "/api/check/t", headers, body)[0] == 400
    assert raw_post(base, "/api/confirm/t", headers, body)[0] == 400
    assert json.loads((maps / "catalog.json").read_text(encoding="utf-8"))[0]["status"] == "unavailable"


def test_the_server_refuses_to_reconfirm_unless_started_with_the_flag(server):
    base, maps = server
    post = {"Content-Type": "application/json"}
    assert json.loads(call(base + "/api/confirm/t", {}, post)[1])["written"] is True
    again = json.loads(call(base + "/api/confirm/t", {"zones": {"1": ["blue"]}}, post)[1])
    assert again["written"] is False and "already confirmed" in again["problems"][0]
    assert json.loads(call(base + "/api/maps")[1])["reconfirm"] is False


# ---------- secret passages ----------
def test_passages_make_a_split_board_connected():
    split = mc.apply_edit(ring(), {"edges": [[0, 1], [2, 3]]})
    assert any("not connected" in p for p in mc.validate(split))
    bridged = mc.apply_edit(split, {"passages": [[1, 2]]})
    assert bridged["passages"] == [[1, 2]] and mc.validate(bridged) == []


def test_bad_passages_are_rejected_or_dropped():
    with pytest.raises(ValueError):
        mc.apply_edit(ring(), {"passages": [[0, 9]]})
    assert "passages" not in mc.apply_edit(mc.apply_edit(ring(), {"passages": [[0, 2]]}), {"passages": [[1], []]})
    assert any("two passage groups" in p for p in mc.validate({**ring(), "passages": [[0, 1], [1, 2]]}))


def test_confirm_round_trips_passages_into_a_board(maps):
    ok, problems = mc.confirm(maps, "t", {"edges": [[0, 1], [2, 3]], "passages": [[1, 2]]}, None, ZONES)
    assert ok, problems
    written = json.loads((maps / "t.json").read_text(encoding="utf-8"))
    assert written["passages"] == [[1, 2]] and mc.map_view(maps, "t")["passages"] == [[1, 2]]
    board = Board.load(maps / "t.json")
    assert not board.adjacent(1, 2) and board.distance(0, 3) == 3


def test_an_edit_without_passages_keeps_the_ones_on_file(maps):
    data = ring()
    data["passages"] = [[0, 2]]
    (maps / "t.json").write_text(json.dumps(data), encoding="utf-8")
    assert mc.confirm(maps, "t", {}, None, ZONES)[0]
    assert json.loads((maps / "t.json").read_text(encoding="utf-8"))["passages"] == [[0, 2]]


# ---------- directional bonuses ----------
def test_confirm_round_trips_bonuses_into_a_board(maps):
    ok, problems = mc.confirm(maps, "t", {"bonuses": [{"from": 1, "to": 0, "value": 1}]}, None, ZONES)
    assert ok, problems
    assert json.loads((maps / "t.json").read_text(encoding="utf-8"))["bonuses"] == [{"from": 1, "to": 0, "value": 1}]
    board = Board.load(maps / "t.json")
    assert board.attack_bonus(1, 0) == 1 and board.attack_bonus(0, 1) == 0


def test_a_bonus_between_spaces_that_are_not_adjacent_fails_the_check():
    data = mc.apply_edit(ring(), {"bonuses": [{"from": 0, "to": 2, "value": 1}]})
    assert any("not adjacent" in p for p in mc.validate(data))
    assert mc.validate(mc.apply_edit(ring(), {"bonuses": [{"from": 0, "to": 1, "value": 1}]})) == []


def test_bad_or_empty_bonus_edits():
    with pytest.raises(ValueError):
        mc.apply_edit(ring(), {"bonuses": [{"from": 0, "to": 9}]})
    kept = mc.apply_edit(ring(), {"bonuses": [{"from": 0, "to": 1}]})
    assert kept["bonuses"][0]["value"] == 1
    assert "bonuses" not in mc.apply_edit(kept, {"bonuses": []})
    assert mc.apply_edit(kept, {})["bonuses"] == kept["bonuses"]


# ---------- one-way edges ----------
def test_confirm_round_trips_one_way_into_a_board(maps):
    ok, problems = mc.confirm(maps, "t", {"one_way": [[0, 1]]}, None, ZONES)
    assert ok, problems
    assert json.loads((maps / "t.json").read_text(encoding="utf-8"))["one_way"] == [[0, 1]]
    board = Board.load(maps / "t.json")
    assert board.adjacent(1, 0) and 0 not in board.moves[1] and 1 in board.moves[0]


def test_one_way_edits_are_validated():
    with pytest.raises(ValueError):
        mc.apply_edit(ring(), {"one_way": [[0, 9]]})
    assert any("not adjacent" in p for p in mc.validate(mc.apply_edit(ring(), {"one_way": [[0, 2]]})))
    both = mc.apply_edit(ring(), {"one_way": [[0, 1], [1, 0]]})
    assert any("both directions" in p for p in mc.validate(both))
    kept = mc.apply_edit(ring(), {"one_way": [[0, 1]]})
    assert mc.apply_edit(kept, {})["one_way"] == [[0, 1]] and "one_way" not in mc.apply_edit(kept, {"one_way": []})


def test_the_check_warns_about_a_space_that_cannot_be_left():
    path = {"edges": [[0, 1], [1, 2], [2, 3]]}                         # 0-1-2-3 in a row
    assert mc.validate(mc.apply_edit(ring(), path)) == []
    trapped = mc.apply_edit(ring(), {**path, "one_way": [[2, 3]]})      # 3 can be reached but never left
    assert any("cannot be reached by movement" in p and "[3]" in p for p in mc.validate(trapped))


def test_the_check_warns_about_a_space_that_cannot_be_reached():
    cut = mc.apply_edit(ring(), {"edges": [[0, 1], [1, 2], [2, 3]], "one_way": [[3, 2]]})     # 2 -> 3 is closed
    assert any("not connected" in p for p in mc.validate(cut))


# ---------- review: strict bonus and one-way entries ----------
@pytest.mark.parametrize("bad", [
    [{"from": 0, "to": 1, "value": 0}], [{"from": 0, "to": 1, "value": -1}], [{"from": 0, "to": 1, "value": "2"}],
    [{"from": 0, "to": 1, "value": 1.7}], [{"from": 0, "to": 1, "value": 4}], [{"from": 0, "to": 1, "value": True}],
    [{"from": "0", "to": 1, "value": 1}], [{"from": 0, "to": 1, "value": 1}, {"from": 1, "to": 0, "value": 1}]])
def test_bonuses_must_be_small_positive_integers_one_way_round(bad):
    with pytest.raises(ValueError):
        mc.apply_edit(ring(), {"bonuses": bad})


def test_the_largest_bonus_is_accepted():
    assert mc.apply_edit(ring(), {"bonuses": [{"from": 0, "to": 1, "value": mc.MAX_BONUS}]})["bonuses"][0]["value"] == 3


@pytest.mark.parametrize("bad", [[["01"]], [[0]], [[0, 1, 2]], [["0", "1"]], [[0, 1.0]], [[True, 1]], ["01"], [[0, None]]])
def test_one_way_entries_must_be_pairs_of_integers(bad):
    with pytest.raises((ValueError, TypeError)):
        mc.apply_edit(ring(), {"one_way": bad})


# ---------- hazard edges ----------
def test_confirm_round_trips_hazards_into_a_board(maps):
    ok, problems = mc.confirm(maps, "t", {"hazards": [{"edge": [2, 1], "damage": 2}, {"edge": [0, 1]}]}, None, ZONES)
    assert ok, problems
    saved = json.loads((maps / "t.json").read_text(encoding="utf-8"))["hazards"]
    assert saved == [{"edge": [0, 1], "damage": 1}, {"edge": [1, 2], "damage": 2}]
    assert Board.load(maps / "t.json").hazards == {(0, 1): 1, (1, 2): 2}


@pytest.mark.parametrize("hazard", [{"edge": [0, 9], "damage": 1}, {"edge": [1, 1], "damage": 1}, {"edge": [0, 1], "damage": 0},
                                    {"edge": [0, 1], "damage": mc.MAX_HAZARD + 1}, {"edge": [0, 1], "damage": 1.5},
                                    {"edge": [0], "damage": 1}, {"damage": 1}, "0-1"])
def test_bad_hazards_are_rejected(hazard):
    with pytest.raises(ValueError):
        mc.apply_edit(ring(), {"hazards": [hazard]})


def test_a_repeated_hazard_edge_is_rejected_in_either_order():
    with pytest.raises(ValueError):
        mc.apply_edit(ring(), {"hazards": [{"edge": [0, 1], "damage": 1}, {"edge": [1, 0], "damage": 2}]})


def test_the_check_flags_a_hazard_on_spaces_that_are_not_adjacent():
    assert any("hazard 0-2" in p and "not adjacent" in p for p in mc.validate(mc.apply_edit(ring(), {"hazards": [{"edge": [0, 2], "damage": 1}]})))
    assert not any("hazard" in p for p in mc.validate(mc.apply_edit(ring(), {"hazards": [{"edge": [0, 1], "damage": 1}]})))


def test_hazards_are_kept_when_not_in_the_edit_and_cleared_by_an_empty_list():
    kept = mc.apply_edit(ring(), {"hazards": [{"edge": [0, 1], "damage": 2}]})
    assert mc.apply_edit(kept, {})["hazards"] == kept["hazards"] and "hazards" not in mc.apply_edit(kept, {"hazards": []})


def test_a_confirmed_map_gets_its_one_way_edges_through_the_server_when_reconfirming_is_allowed(server):
    base, maps = server
    post = {"Content-Type": "application/json"}
    assert json.loads(call(base + "/api/confirm/t", {}, post)[1])["written"] is True
    mc.Handler.allow_reconfirm = True
    try:
        assert json.loads(call(base + "/api/maps")[1])["reconfirm"] is True
        edit = {"one_way": [[0, 1]]}
        assert json.loads(call(base + "/api/check/t", edit, post)[1])["problems"] == []
        assert json.loads(call(base + "/api/confirm/t", edit, post)[1])["written"] is True
        assert json.loads(call(base + "/api/map/t")[1])["one_way"] == [[0, 1]]            # reopened: still there
        assert json.loads(call(base + "/api/confirm/t", {"one_way": [[1, 0]]}, post)[1])["written"] is True
        assert json.loads((maps / "t.json").read_text(encoding="utf-8"))["one_way"] == [[1, 0]]
    finally:
        mc.Handler.allow_reconfirm = False


def test_a_one_way_edge_marked_in_both_directions_is_reported_once():
    both = mc.apply_edit(ring(), {"one_way": [[0, 1], [1, 0]]})
    assert [p for p in mc.validate(both) if "both directions" in p] == ["edge 0-1 is one-way in both directions, so nobody can cross it"]
