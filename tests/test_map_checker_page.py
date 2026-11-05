"""The checker page's own script (clicks, modes, drawing), run under node with a stub DOM. Skipped without node."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import map_checker as mc  # noqa: E402

NODE = shutil.which("node")
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")

DRIVER = r"""
const vm = require("vm"), fs = require("fs");
const input = JSON.parse(fs.readFileSync(0, "utf8"));
const els = {};
const mk = () => ({innerHTML: "", textContent: "", style: {}, children: [], className: "", src: "",
  classList: {add() {}}, append(c) { this.children.push(c) }, querySelectorAll() { return [] }});
const ctx = {document: {getElementById: id => els[id] || (els[id] = mk()), createElement: mk},
  addEventListener: (t, f) => { ctx.listener = f },
  fetch: async (url, opts) => ({json: async () => {
    ctx.posts.push({url, body: opts && opts.body ? JSON.parse(opts.body) : null});
    if (url === "/api/maps") return {maps: [{key: "t", name: "T", status: input.status}], zones: ["red"], reconfirm: input.reconfirm};
    if (url.startsWith("/api/map/")) return input.map;
    return {problems: [], written: true};
  }}), posts: [], console};
ctx.clickSpace = id => { const c = els.wrap.children; c[c.length - ctx.M_COUNT + id].onclick() };
ctx.M_COUNT = input.map.spaces.length;
vm.createContext(ctx);
const run = code => vm.runInContext(code, ctx);
(async () => {
  run(input.script);
  await run("init()"); await run("open('t')");
  const out = [];
  for (const step of input.steps) {
    const r = run(step);
    if (r && r.then) await r;
    out.push(run("JSON.stringify({OW, HZ, BON, edges:[...edges], RO, svg:$('lines').innerHTML, panel:$('panel').innerHTML})"));
  }
  console.log(JSON.stringify({states: out.map(JSON.parse), posts: ctx.posts}));
})();
"""


def page_script() -> str:
    return re.search(r"<script>(.*)</script>", mc.PAGE, re.S).group(1).replace("__MAX_HAZARD__", str(mc.MAX_HAZARD))


def square(one_way=None, hazards=None):
    data = {"key": "t", "name": "T", "starts": {"1": 0, "2": 2},
            "spaces": [{"id": i, "local": [float(i), float(i % 2)], "zones": ["red"], "adj": sorted({(i + 1) % 4, (i - 1) % 4}),
                        "fx": 0.2 + 0.2 * i, "fy": 0.3 + 0.1 * (i % 2)} for i in range(4)]}
    if one_way:
        data["one_way"] = one_way
    if hazards:
        data["hazards"] = hazards
    return data


def drive(steps, status="unverified", reconfirm=False, **map_extra):
    payload = {"script": page_script(), "steps": steps, "status": status, "reconfirm": reconfirm, "map": square(**map_extra)}
    done = subprocess.run([NODE, "-e", DRIVER], input=json.dumps(payload), capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout)


def test_the_page_script_is_valid_and_its_modes_exist():
    assert "Hazard mode (key H)" in mc.PAGE and "One-way mode (key O)" in mc.PAGE
    out = drive([])
    assert out["posts"][0]["url"] == "/api/maps"


def test_two_clicks_on_an_edge_cycle_a_to_b_then_b_to_a_then_two_way():
    clicks = "setOmode(true);clickOneWay(0);clickOneWay(1)"
    out = drive([clicks, "clickOneWay(0);clickOneWay(1)", "clickOneWay(0);clickOneWay(1)"])
    assert [s["OW"] for s in out["states"]] == [[[0, 1]], [[1, 0]], []]


def test_a_one_way_edge_is_drawn_as_a_red_arrow_with_a_head():
    out = drive(["setOmode(true);clickOneWay(0);clickOneWay(1)"])
    svg = out["states"][0]["svg"]
    assert 'stroke="#f33"' in svg and "<polygon" in svg
    assert "<polygon" not in drive(["setOmode(true)"])["states"][0]["svg"]


def test_one_way_needs_an_existing_edge():
    out = drive(["setOmode(true);clickOneWay(0);clickOneWay(2)"])
    assert out["states"][0]["OW"] == [] and "not adjacent" in out["states"][0]["panel"]


def test_removing_an_edge_drops_the_marks_that_lived_on_it():
    out = drive(["pmode=false;sel=0;document.getElementById('x');" "sel=0", "(()=>{sel=0;const k=ek(0,1);edges.has(k)?dropEdge(k):0;draw()})()"],
                one_way=[[0, 1]], hazards=[{"edge": [0, 1], "damage": 2}])
    last = out["states"][-1]
    assert last["OW"] == [] and last["HZ"] == [] and "0-1" not in last["edges"]


def test_hazard_clicks_cycle_the_damage_and_are_drawn():
    click = "clickHazard(1);clickHazard(2)"
    out = drive(["setHmode(true);" + click, click, click, click])
    assert [[h["damage"] for h in s["HZ"]] for s in out["states"]] == [[1], [2], [3], []]
    assert "stroke-dasharray" in out["states"][0]["svg"] and "-1" in out["states"][0]["svg"]


def test_hazard_needs_an_existing_edge_and_either_click_order_finds_it():
    out = drive(["setHmode(true);clickHazard(0);clickHazard(2)", "clickHazard(2);clickHazard(1);clickHazard(1);clickHazard(2)"])
    assert out["states"][0]["HZ"] == [] and "not adjacent" in out["states"][0]["panel"]
    assert [h["damage"] for h in out["states"][1]["HZ"]] == [2]


def test_check_and_confirm_send_one_way_and_hazards():
    out = drive(["setOmode(true);clickOneWay(0);clickOneWay(1);setHmode(true);clickHazard(2);clickHazard(3)", "check()", "confirmMap()"])
    checks = [p for p in out["posts"] if p["url"].startswith("/api/check/") or p["url"].startswith("/api/confirm/")]
    assert [p["url"] for p in checks] == ["/api/check/t", "/api/confirm/t"]
    for p in checks:
        assert p["body"]["one_way"] == [[0, 1]] and p["body"]["hazards"] == [{"edge": [2, 3], "damage": 1}]


def test_a_confirmed_map_is_read_only_unless_the_checker_allows_reconfirming():
    steps = ["setOmode(true)", "clickSpace(0)", "clickSpace(1)"]
    locked = drive(steps, status="supported")
    assert locked["states"][-1]["RO"] is True and locked["states"][-1]["OW"] == []
    open_ = drive(steps, status="supported", reconfirm=True)
    assert open_["states"][-1]["RO"] is False and open_["states"][-1]["OW"] == [[0, 1]]


def test_clicking_two_spaces_in_one_way_mode_goes_through_the_real_click_handlers():
    out = drive(["setOmode(true)", "clickSpace(1)", "clickSpace(2)", "clickSpace(1)", "clickSpace(2)"])
    assert [s["OW"] for s in out["states"]][-3:] == [[[1, 2]], [[1, 2]], [[2, 1]]]
