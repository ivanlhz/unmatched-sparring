"""tools/import_map.py: the extraction of a map from a TTS save and its image, on synthetic maps drawn with OpenCV.

The real maps are checked by eye on docs/maps-check; these tests pin the pieces: pixel geometry, which snap points
are spaces, the connectors between circles (and what must NOT count as one), the zones, the checks that mark a map
as not playable, the exclusions read off the save, and the data file the tool writes."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")
pytest.importorskip("scipy")
pytest.importorskip("PIL")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import import_map as im  # noqa: E402

from sparring.board import Board  # noqa: E402

R = 72
INK = (0, 0, 0)
FILLS = {"a": (200, 120, 60), "b": (60, 170, 90), "c": (70, 70, 210)}


def blank(w=1600, h=900):
    return np.full((h, w, 3), (225, 225, 225), np.uint8)


def circle(img, x, y, fill, split=None):
    cv2.circle(img, (x, y), R, FILLS[fill], -1)
    if split:
        cv2.rectangle(img, (x - R, y), (x + R, y + R), FILLS[split], -1)
        cv2.circle(img, (x, y), R, INK, 6)
        cv2.circle(img, (x, y), R + 4, (225, 225, 225), 3)
    cv2.circle(img, (x, y), R, INK, 6)


def line(img, a, b, width=8):
    cv2.line(img, a, b, INK, width)


def three_in_a_row():
    img = blank()
    pts = [(300, 400), (700, 400), (1100, 400)]
    for x, y in pts:
        circle(img, x, y, "a")
    return img, np.array(pts, float)


# ---------- the save ----------
def test_slug_and_image_key():
    assert im.slugify("Hell's Kitchen") == "hells-kitchen" and im.slugify("McMinnville, OR") == "mcminnville-or"
    key = "0123456789ABCDEF0123456789ABCDEF01234567"
    assert im.image_key(f"https://x.test/ugc/1/{key.lower()}/") == key
    with pytest.raises(ValueError):
        im.image_key("https://x.test/board.png")


def snap(x, z):
    return {"Position": {"x": x, "y": 0, "z": z}}


def save_with(*objects):
    return {"SaveName": "test", "ObjectStates": list(objects)}


def map_bag(name, x, z, snaps=((1, 2),), key="A" * 40):
    return {"Name": "Custom_Model_Infinite_Bag", "Nickname": name, "Transform": {"posX": x, "posZ": z},
            "ContainedObjects": [{"Name": "Custom_Board", "CustomImage": {"ImageURL": f"https://x.test/ugc/1/{key}/"},
                                  "AttachedSnapPoints": [snap(*s) for s in snaps]}]}


def side_bag(name, x, z):
    return {"Name": "Infinite_Bag", "Nickname": name, "Transform": {"posX": x, "posZ": z}}


def test_read_save_maps_takes_the_board_inside_each_map_bag():
    save = save_with(map_bag("Naglfar", 0, 0, snaps=((1, 2), (3, 4))),
                     {"Name": "Custom_Model_Infinite_Bag", "Nickname": "Hellboy", "ContainedObjects": [{"Name": "Custom_Model_Bag"}]})
    [m] = im.read_save_maps(save)
    assert (m.name, m.key, m.snaps) == ("Naglfar", "naglfar", [(1, 2), (3, 4)])


def test_exclusions_are_read_off_the_bags_beside_the_maps():
    save = save_with(map_bag("Navy Pier", 0, 0), map_bag("Heorot", 10, 70), map_bag("Soho", 30, 70), map_bag("Venice", 50, 0),
                     side_bag("Navy Pier Battlefield Items", 2, 0),
                     side_bag("Doors", 12, 70),             # next to Heorot
                     side_bag("Doors", 0, 109),             # the generic one, far from every map
                     side_bag("Phone Booth", 0, 109))
    maps = im.read_save_maps(save)
    assert im.exclusions(save, maps) == {"navy-pier": "tokens", "heorot": "doors"}


# ---------- geometry ----------
def test_a_snap_point_lands_where_the_image_was_stretched_over_the_square_board():
    px = im.snap_pixels([(6.971, -4.067), (0.0, 0.0)], (1052, 1600))
    assert px[0] == pytest.approx((134.2, 270.6), abs=0.5)         # space 3 of B.P.R.D. HQ, measured on its image
    assert px[1] == pytest.approx((800, 526))


def test_only_snaps_with_a_circle_around_them_are_spaces():
    img, pts = three_in_a_row()
    centers, ring = im.refine_centers(img, np.vstack([pts, [(700, 750)]]) + 3, R)       # 3 px off, and one on bare floor
    assert ring[:3].min() > 0.9 and ring[3] < im.RING_MIN
    assert np.abs(centers[:3] - pts).max() <= 3       # within the thickness of the outline


# ---------- connectors ----------
def test_a_connector_joins_two_circles_and_a_chord_through_a_third_does_not():
    img, pts = three_in_a_row()
    line(img, (372, 400), (628, 400))
    line(img, (772, 400), (1028, 400))
    assert im.find_adjacency(img, pts, R) == {(0, 1), (1, 2)}          # 0-2 would cross circle 1 and has no line


def test_a_curved_connector_counts_but_a_wide_wall_between_two_circles_does_not():
    img = blank()
    pts = [(300, 300), (900, 300), (300, 700), (900, 700)]
    for x, y in pts:
        circle(img, x, y, "a")
    cv2.ellipse(img, (600, 300), (300 - 72, 170), 0, 0, 180, INK, 8)           # arc bulging down: 0-1
    cv2.rectangle(img, (372, 680), (828, 720), INK, -1)                        # a wall between 2 and 3: 40 px, not a pen stroke
    for a, b in ((0, 2), (1, 3)):
        line(img, (pts[a][0], pts[a][1] + 72), (pts[b][0], pts[b][1] - 72))
    adj = im.find_adjacency(img, np.array(pts, float), R)
    assert (0, 1) in adj and (0, 2) in adj and (1, 3) in adj and (2, 3) not in adj


def test_two_branches_that_merge_make_the_stem_adjacent_to_both_but_not_the_branches():
    img = blank()
    pts = [(300, 200), (700, 200), (500, 700)]
    for x, y in pts:
        circle(img, x, y, "a")
    line(img, (330, 266), (500, 520), 9)
    line(img, (670, 266), (500, 520), 9)
    line(img, (500, 520), (500, 628), 9)
    assert im.find_adjacency(img, np.array(pts, float), R) == {(0, 2), (1, 2)}


def test_the_orange_icon_on_a_connector_does_not_cut_it():
    img, pts = three_in_a_row()
    line(img, (372, 400), (628, 400))
    cv2.circle(img, (500, 400), 22, tuple(int(v) for v in im.ICON_ORANGE), -1)
    assert (0, 1) in im.find_adjacency(img, pts, R)


# ---------- zones ----------
def test_a_circle_split_in_two_has_two_zones_and_a_plain_one_has_one():
    img = blank()
    circle(img, 300, 400, "a", split="b")
    circle(img, 700, 400, "a")
    centers = [(300, 400), (700, 400)]
    lab = im.weighted_lab(img)
    raw = [im.space_colors(lab, img, c, R, np.zeros(3)) for c in centers]
    palette, members = im.build_palette([im.settle(c, 12) for c in raw], 12)
    assert len(palette) == 2 and len(members[0]) == 2 and len(members[1]) == 1
    assert set(members[1]) < set(members[0])


def test_the_darker_strokes_of_a_pattern_are_not_another_zone():
    img = blank()
    circle(img, 300, 400, "a")
    for k in range(-60, 61, 20):
        cv2.line(img, (300 + k, 340), (300 + k, 460), (170, 100, 50), 3)           # same hue, a bit darker
    lab = im.weighted_lab(img)
    colors = im.settle(im.space_colors(lab, img, (300, 400), R, np.zeros(3)), 12)
    assert len(colors) == 1


def test_palette_colours_get_distinct_names_the_catalogs_know():
    palette = [im._lab_of_rgb(c) for c in ((200, 70, 70), (205, 75, 72), (84, 130, 188), (96, 168, 100))]
    palette = [palette[0], palette[2], palette[3]]
    names = im.name_palette(palette)
    assert len(set(names)) == 3 and names[0] in ("red", "brick") and names[1] == "blue"
    catalog = json.loads((ROOT / "data" / "i18n" / "en.json").read_text(encoding="utf-8"))
    assert all(f"spaces.color.{n}" in catalog for n in im.COLOR_NAMES)


# ---------- start markers ----------
def test_the_numerals_are_told_apart_by_their_templates():
    templates = im.load_digit_templates()
    assert set(templates) == set("1234")
    for digit, variants in templates.items():
        scores = im.digit_scores(variants[0], templates)
        assert scores[digit] == 1.0 and scores[digit] - max(v for d, v in scores.items() if d != digit) >= 0.25


def test_a_diamond_on_a_rim_is_read_and_a_plain_rim_is_not():
    img, pts = three_in_a_row()
    x, y = int(pts[0][0] - R), int(pts[0][1])
    cv2.fillPoly(img, [np.array([(x - 12, y), (x, y - 12), (x + 12, y), (x, y + 12)])], INK)
    glyph = im.load_digit_templates()["1"][0]
    ys, xs = np.nonzero(glyph)
    for gy, gx in zip(ys, xs):
        img[y - 5 + round(gy * 0.62), x - 2 + round(gx * 0.2)] = (200, 200, 200)       # a thin light "1" in the diamond
    found = im.find_start_markers(img, pts, R, np.zeros(3))
    assert [i for i, _ in found] == [0]
    assert im.find_starts(blank(), pts, R, np.zeros(3)) == {}


# ---------- the checks ----------
def extracted(n=4, edges=None, zones=None, starts=None, palette=2):
    centers = np.array([(100.0 * i, 50.0) for i in range(n)])
    return im.Extracted("t", "T", "A" * 40, blank(), list(range(n)), [(float(i), 0.0) for i in range(n)], centers,
                        edges if edges is not None else {tuple(sorted((i, (i + 1) % n))) for i in range(n)},
                        zones or [["red"] for _ in range(n)], {f"c{i}": (0, 0, 0) for i in range(palette)},
                        starts if starts is not None else {"1": 0, "2": n - 1}, 0)


def test_a_clean_map_has_no_problems():
    assert im.check_map(extracted(), {"spacesCount": 4, "zonesCount": 2}) == []


@pytest.mark.parametrize("make, expected, text", [
    (lambda: extracted(), {"spacesCount": 5}, "4 spaces found, the map has 5"),
    (lambda: extracted(edges={(0, 1)}), None, "not connected"),
    (lambda: extracted(edges={(0, 1), (1, 2), (0, 2)}), None, "without a neighbour: [3]"),
    (lambda: extracted(edges={(0, 1), (1, 2), (2, 3), (1, 3)}), None, "single neighbour"),
    (lambda: extracted(zones=[["red"], [], ["red"], ["red"]]), None, "without a zone: [1]"),
    (lambda: extracted(palette=3), {"zonesCount": 2}, "3 zone colours found, the map has 2"),
    (lambda: extracted(starts={"1": 0}), None, "start marker 2 not found"),
    (lambda: extracted(starts={"1": 1, "2": 1}), None, "same space"),
])
def test_each_failed_check_is_reported(make, expected, text):
    problems = im.check_map(make(), expected)
    assert any(text in p for p in problems), problems


def test_a_map_with_problems_is_written_as_not_playable(tmp_path):
    bad = extracted(edges={(0, 1)})
    bad.problems = im.check_map(bad, None)
    data = im.map_data(bad, "test")
    assert data["playable"] is False and data["problems"]
    good = im.map_data(extracted(), "test")
    assert good["playable"] is True and good["verified"] is False and "problems" not in good


def test_the_data_file_loads_as_a_board(tmp_path):
    data = im.map_data(extracted(), "test")
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    board = Board.load(path)
    assert sorted(board.spaces) == [0, 1, 2, 3] and board.adjacent(1, 2) and board.adjacent(0, 3) and not board.adjacent(0, 2)
    assert board.starts == {"1": 0, "2": 3} and board.zones(0) == frozenset({"red"})


def test_the_picture_for_the_eye_is_written(tmp_path):
    m = extracted()
    m.img = blank(400, 200)
    out = tmp_path / "check" / "t.png"
    im.render_check(m, out, width=400)
    assert out.stat().st_size > 0 and cv2.imread(str(out)) is not None


def test_images_are_only_fetched_over_https_and_once(tmp_path):
    with pytest.raises(ValueError, match="https"):
        im.fetch_image("http://x.test/a", tmp_path / "a.img")
    cached = tmp_path / "b.img"
    cached.write_bytes(b"x")
    assert im.fetch_image("https://never-called.test/b", cached) == cached




def test_overwrite_keeps_a_map_a_person_confirmed_unless_forced(tmp_path, monkeypatch):
    save = save_with(map_bag("Yukon", 0, 0))
    save_path = tmp_path / "save.json"
    save_path.write_text(json.dumps(save), encoding="utf-8")
    out = tmp_path / "maps"
    out.mkdir()
    confirmed = {"key": "yukon", "name": "Yukon", "imageKey": "A" * 40, "verified": True, "playable": True, "starts": {"1": 0},
                 "spaces": [{"id": 0, "local": [1.0, 2.0], "zones": ["red"], "adj": []}]}
    (out / "yukon.json").write_text(json.dumps(confirmed), encoding="utf-8")
    calls = []

    def fake_extract(sm, img, expected=None, passages=None):
        calls.append(sm.key)
        return extracted()
    monkeypatch.setattr(im, "fetch_image", lambda url, dest: dest)
    monkeypatch.setattr(im, "load_work_image", lambda path: blank(400, 200))
    monkeypatch.setattr(im, "extract_map", fake_extract)
    monkeypatch.setattr(im, "render_check", lambda *a, **k: None)
    argv = ["--save", str(save_path), "--images", str(tmp_path / "img"), "--out", str(out), "--check-dir", str(tmp_path / "c"),
            "--overwrite"]
    assert im.main(argv) == 0
    assert calls == [] and json.loads((out / "yukon.json").read_text(encoding="utf-8")) == confirmed
    assert im.main(argv + ["--force-unverify"]) == 0
    assert calls == ["yukon"] and json.loads((out / "yukon.json").read_text(encoding="utf-8"))["verified"] is False


# ---------- secret passages ----------
def test_passages_count_as_movement_links_in_the_checks():
    two_islands = {(0, 1), (2, 3)}
    assert any("not connected" in p for p in im.check_map(extracted(edges=two_islands), None))
    bridged = extracted(edges=two_islands)
    bridged.passages = [[0, 2]]
    assert not any("not connected" in p for p in im.check_map(bridged, None))


def test_a_dead_end_with_a_passage_is_not_a_missing_connector():
    m = extracted(edges={(0, 1), (1, 2), (2, 3), (1, 3)})            # space 0 has a single neighbour
    assert any("single neighbour" in p for p in im.check_map(m, None))
    m.passages = [[0, 3]]
    assert not any("single neighbour" in p for p in im.check_map(m, None))


def test_passages_are_written_and_loaded_without_becoming_adjacency(tmp_path):
    m = extracted(edges={(0, 1), (2, 3)})
    m.passages = [[0, 2]]
    data = im.map_data(m, "test")
    assert data["passages"] == [[0, 2]]
    assert "passages" not in im.map_data(extracted(), "test")
    path = tmp_path / "t.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    board = Board.load(path)
    assert not board.adjacent(0, 2) and board.distance(0, 2) == 1
    assert im.extracted_from_data(data, blank(400, 200)).passages == [[0, 2]]


def test_overwriting_an_unverified_map_keeps_its_passages(tmp_path, monkeypatch):
    save_path = tmp_path / "save.json"
    save_path.write_text(json.dumps(save_with(map_bag("Yukon", 0, 0))), encoding="utf-8")
    out = tmp_path / "maps"
    out.mkdir()
    old = {"key": "yukon", "name": "Yukon", "imageKey": "A" * 40, "verified": False, "playable": False, "starts": {"1": 0},
           "passages": [[0, 2]], "spaces": [{"id": 0, "local": [1.0, 2.0], "zones": ["red"], "adj": []}]}
    (out / "yukon.json").write_text(json.dumps(old), encoding="utf-8")
    seen = []

    def fake_extract(sm, img, expected=None, passages=None):
        seen.append(passages)
        m = extracted(edges={(0, 1), (2, 3)})
        m.passages = [list(g) for g in passages or []]
        return m
    monkeypatch.setattr(im, "fetch_image", lambda url, dest: dest)
    monkeypatch.setattr(im, "load_work_image", lambda path: blank(400, 200))
    monkeypatch.setattr(im, "extract_map", fake_extract)
    monkeypatch.setattr(im, "render_check", lambda *a, **k: None)
    assert im.main(["--save", str(save_path), "--images", str(tmp_path / "img"), "--out", str(out),
                    "--check-dir", str(tmp_path / "c"), "--overwrite"]) == 0
    assert seen == [[[0, 2]]]
    assert json.loads((out / "yukon.json").read_text(encoding="utf-8"))["passages"] == [[0, 2]]
