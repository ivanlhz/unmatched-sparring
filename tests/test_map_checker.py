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
