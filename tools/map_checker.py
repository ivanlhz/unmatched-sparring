r"""Local map checker: a person looks at a map, fixes what is wrong and confirms it, and only then the bot plays it.

    .venv\Scripts\python tools\map_checker.py --images C:\path\to\map-images --expected ..\unmatched-memory\data\maps.json

then open http://127.0.0.1:8765 (localhost only). `--images` is the folder `tools\import_map.py` downloaded the map
pictures into (`<imageKey>.img`); it must stay outside the repo, the art is not ours. The page lists every map except
the ones that need tokens or doors; for one map it shows the picture with the spaces numbered, the edges, the zones and
the starts. Click a space, then another: that toggles the edge between them. With a space selected you can tick its
zones and make it start 1 / 2 / 3 / 4. Check re-runs the structural checks; Confirm re-runs them and, if they pass,
writes data/maps/<key>.json with "playable": true, "verified": true and marks the map supported in the catalog.

Only the standard library; the pure logic (edit, validate, confirm) is what the tests cover, not the page."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
MAPS_DIR = ROOT / "data" / "maps"
I18N_EN = ROOT / "data" / "i18n" / "en.json"
BOARD_UNITS = 16.75                   # same constant as tools/import_map.py: the picture is stretched over a square board
MAX_BODY = 1_000_000
EXPECTED_ALIASES = {"thrilla-in-manilla": "thrilla-in-manila"}


# ---------------------------------------------------------------- pure logic

def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("'", "")).strip("-")


def load_expected(path: Path | None) -> dict[str, dict]:
    """Published {spacesCount, zonesCount} by map key (unmatched-memory's maps.json); optional."""
    if path is None or not path.exists():
        return {}
    out = {}
    for entry in json.loads(path.read_text(encoding="utf-8")):
        key = _slug(entry["name"]).replace("b-p-r-d-hq", "bprd-hq")
        key = EXPECTED_ALIASES.get(key, key)
        out[key] = {"spacesCount": entry["spacesCount"], "zonesCount": entry["zonesCount"]}
    return out


def known_zones(i18n_path: Path = I18N_EN) -> list[str]:
    """Zone colour names the bot can say (spaces.color.* in the catalog)."""
    catalog = json.loads(i18n_path.read_text(encoding="utf-8"))
    return sorted(k.split(".", 2)[2] for k in catalog if k.startswith("spaces.color."))


def edges_of(data: dict) -> set[tuple[int, int]]:
    return {(min(s["id"], n), max(s["id"], n)) for s in data["spaces"] for n in s["adj"]}


def apply_edit(data: dict, edit: dict) -> dict:
    """A copy of `data` with the person's changes: `edges` (the full list of [a, b]), `zones` ({id: [names]}) and
    `passages` (the full list of secret-passage groups), `bonuses` (the full list of {from, to, value}: high ground on
    the stairs) and `starts` ({"1": id, ...}). Anything missing from `edit` is left as it was. Raises ValueError on a bad id."""
    ids = {s["id"] for s in data["spaces"]}
    out = json.loads(json.dumps(data))
    if "edges" in edit:
        edges = set()
        for pair in edit["edges"]:
            a, b = (int(v) for v in pair)
            if a not in ids or b not in ids or a == b:
                raise ValueError(f"bad edge {pair}")
            edges.add((min(a, b), max(a, b)))
        for s in out["spaces"]:
            s["adj"] = sorted(b if a == s["id"] else a for a, b in edges if s["id"] in (a, b))
    for sid, names in (edit.get("zones") or {}).items():
        space = next((s for s in out["spaces"] if s["id"] == int(sid)), None)
        if space is None or not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            raise ValueError(f"bad zones for space {sid}")
        space["zones"] = sorted(set(names))
    if "passages" in edit:
        groups = []
        for group in edit["passages"]:
            members = sorted({int(v) for v in group})
            if any(v not in ids for v in members):
                raise ValueError(f"bad passage {group}")
            if len(members) >= 2:
                groups.append(members)
        if groups:
            out["passages"] = groups
        else:
            out.pop("passages", None)
    if "bonuses" in edit:
        bonuses = {}
        for b in edit["bonuses"]:
            a, c, value = int(b["from"]), int(b["to"]), int(b.get("value", 1))
            if a not in ids or c not in ids or a == c or value == 0:
                raise ValueError(f"bad bonus {b}")
            bonuses[(a, c)] = value
        if bonuses:
            out["bonuses"] = [{"from": a, "to": c, "value": v} for (a, c), v in sorted(bonuses.items())]
        else:
            out.pop("bonuses", None)
    if "starts" in edit:
        starts = {}
        for digit, sid in edit["starts"].items():
            if digit not in ("1", "2", "3", "4") or int(sid) not in ids:
                raise ValueError(f"bad start {digit}: {sid}")
            starts[digit] = int(sid)
        out["starts"] = dict(sorted(starts.items()))
    return out


def validate(data: dict, expected: dict | None = None, zone_names: list[str] | None = None) -> list[str]:
    """The structural checks a confirmed map must pass (empty list: it passes). A space with a single neighbour is not
    an error here: the person looking at the picture decides."""
    problems = []
    spaces = data["spaces"]
    ids = [s["id"] for s in spaces]
    if len(set(ids)) != len(ids):
        problems.append("duplicate space ids")
        return problems
    adj = {s["id"]: set(s["adj"]) for s in spaces}
    for a, neighbours in adj.items():
        for b in neighbours:
            if b not in adj:
                problems.append(f"space {a} is joined to {b}, which does not exist")
            elif a not in adj[b]:
                problems.append(f"edge {a}-{b} is not symmetric")
            elif a == b:
                problems.append(f"space {a} is joined to itself")
    if expected and expected.get("spacesCount") not in (None, len(spaces)):
        problems.append(f"{len(spaces)} spaces, the map has {expected['spacesCount']}")
    passages = data.get("passages") or []
    moves = {a: set(n) for a, n in adj.items()}
    seen_in_groups: set[int] = set()
    for group in passages:
        if len(group) < 2 or any(v not in adj for v in group):
            problems.append(f"bad passage group {group}")
        elif seen_in_groups & set(group):
            problems.append(f"a space is in two passage groups: {group}")
        else:
            seen_in_groups.update(group)
            for a in group:
                moves[a].update(set(group) - {a})
    for b in data.get("bonuses") or []:
        if b["to"] not in adj.get(b["from"], ()):
            problems.append(f"bonus {b['from']}->{b['to']}: the spaces are not adjacent")
    if ids and all(b in adj for n in adj.values() for b in n):
        seen, queue = {ids[0]}, deque([ids[0]])
        while queue:
            for n in moves[queue.popleft()]:
                if n not in seen:
                    seen.add(n)
                    queue.append(n)
        if len(seen) != len(ids):
            problems.append(f"the board (with its passages) is not connected ({len(seen)} of {len(ids)} spaces reachable from space {ids[0]})")
    bare = [s["id"] for s in spaces if not s["zones"]]
    if bare:
        problems.append(f"spaces without a zone: {bare}")
    used = {z for s in spaces for z in s["zones"]}
    if zone_names is not None and used - set(zone_names):
        problems.append(f"zone names the bot does not know: {sorted(used - set(zone_names))}")
    if expected and expected.get("zonesCount") not in (None, len(used)):
        problems.append(f"{len(used)} zone colours used, the map has {expected['zonesCount']}")
    starts = data.get("starts") or {}
    for digit in ("1", "2"):
        if digit not in starts:
            problems.append(f"start {digit} is not set")
    if any(v not in adj for v in starts.values()):
        problems.append("a start is on a space that does not exist")
    if len(set(starts.values())) != len(starts):
        problems.append("two starts on the same space")
    return problems


def _write_json(path: Path, data) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    os.replace(tmp, path)


def confirm(maps_dir: Path, key: str, edit: dict, expected: dict | None = None,
            zone_names: list[str] | None = None, allow_reconfirm: bool = False) -> tuple[bool, list[str]]:
    """Applies the person's edit to data/maps/<key>.json and, if the checks pass, writes it as verified and playable
    and marks the map supported in catalog.json. Returns (written, problems); nothing is written when problems remain."""
    path = maps_dir / f"{_safe_key(key)}.json"
    catalog_path = maps_dir / "catalog.json"
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    entry = next((e for e in catalog if e["key"] == key), None)
    if entry is None or entry["status"] == "excluded" or not path.exists():
        return False, [f"{key} cannot be confirmed (not in the catalog, or it needs tokens or doors)"]
    if entry["status"] == "supported" and not allow_reconfirm:
        return False, [f"{key} is already confirmed; start the checker with --allow-reconfirm to change it"]
    edited = apply_edit(json.loads(path.read_text(encoding="utf-8")), edit)
    problems = validate(edited, expected, zone_names)
    if problems:
        return False, problems
    edited["playable"], edited["verified"] = True, True
    edited.pop("problems", None)
    entry["status"] = "supported"
    entry.pop("why", None)
    _write_json(path, edited)
    _write_json(catalog_path, catalog)
    return True, []


def _safe_key(key: str) -> str:
    if not re.fullmatch(r"[a-z0-9-]{1,40}", key):
        raise ValueError(f"bad map key {key!r}")
    return key


def list_maps(maps_dir: Path) -> list[dict]:
    catalog = json.loads((maps_dir / "catalog.json").read_text(encoding="utf-8"))
    return [{"key": e["key"], "name": e["name"], "status": e["status"], "why": e.get("why", [])}
            for e in catalog if e["status"] != "excluded"]


def map_view(maps_dir: Path, key: str) -> dict:
    """What the page needs: the data plus where each space is on the picture (fractions of its width and height)."""
    data = json.loads((maps_dir / f"{_safe_key(key)}.json").read_text(encoding="utf-8"))
    for s in data["spaces"]:
        s["fx"] = 0.5 - s["local"][0] / BOARD_UNITS
        s["fy"] = 0.5 + s["local"][1] / BOARD_UNITS
    return data


def image_path(images_dir: Path, maps_dir: Path, key: str) -> Path | None:
    data = json.loads((maps_dir / f"{_safe_key(key)}.json").read_text(encoding="utf-8"))
    path = images_dir / f"{data['imageKey']}.img"
    return path if path.is_file() else None


def image_type(head: bytes) -> str:
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return "application/octet-stream"


# ---------------------------------------------------------------- the page

PAGE = r"""<!doctype html><meta charset="utf-8"><title>Map checker</title>
<style>
body{font:14px system-ui,sans-serif;margin:0;display:flex;height:100vh}
#side{width:330px;padding:10px;overflow:auto;background:#1e1e24;color:#eee;box-sizing:border-box}
#side a{display:block;color:#9cf;cursor:pointer;padding:2px 0} #side .unverified{color:#fc6} #side .supported{color:#7d7} #side .unavailable{color:#f88}
#stage{flex:1;overflow:auto;background:#111}
#wrap{position:relative;display:inline-block;margin:10px}
#wrap img{display:block;width:1500px;max-width:none}
#lines{position:absolute;inset:0;width:100%;height:100%}
.sp{position:absolute;transform:translate(-50%,-50%);min-width:26px;text-align:center;background:#000c;color:#fff;border:2px solid #fff;
border-radius:14px;font-weight:bold;cursor:pointer;padding:1px 3px;font-size:13px}
.sp small{display:block;font-weight:normal;font-size:10px;color:#ffd}
.sp.sel{border-color:#f0f;background:#406c}.sp.start{border-color:#f33}
.bonus-from{border-color:#6f6;background:#262c}
.sp.pass{border-color:#f90;border-style:dashed;background:#530c}.sp.pass.cur{border-color:#0ff;background:#056c}
button.on{background:#f90;font-weight:bold}
button{margin:2px;padding:4px 8px} #problems{color:#f99;white-space:pre-wrap} #ok{color:#7d7}
label{display:inline-block;width:110px}
</style>
<div id=side><b>Maps</b><div id=list></div><hr><div id=panel></div></div>
<div id=stage><div id=wrap><img id=img><svg id=lines viewBox="0 0 1000 1000" preserveAspectRatio="none"></svg></div></div>
<script>
let M=null,key=null,edges=new Set(),sel=null,PASS=[],cur=0,pmode=false,BON=[],bmode=false,bsel=null,ZN=[],RECONFIRM=false,RO=false,ST={};
const $=id=>document.getElementById(id), ek=(a,b)=>Math.min(a,b)+"-"+Math.max(a,b);
async function api(p,body){const r=await fetch(p,body?{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(body)}:{});return r.json()}
async function init(){const d=await api("/api/maps");ZN=d.zones;RECONFIRM=d.reconfirm;ST={};for(const m of d.maps)ST[m.key]=m.status;$("list").innerHTML="";
 for(const m of d.maps){const a=document.createElement("a");a.className=m.status;a.textContent=m.name+" ["+m.status+"]";a.onclick=()=>open(m.key);$("list").append(a)}}
async function open(k){key=k;RO=ST[k]==="supported"&&!RECONFIRM;M=await api("/api/map/"+k);edges=new Set();for(const s of M.spaces)for(const n of s.adj)edges.add(ek(s.id,n));
 PASS=(M.passages||[]).map(g=>[...g]);cur=0;pmode=false;BON=(M.bonuses||[]).map(b=>({...b}));bmode=false;bsel=null;sel=null;$("img").src="/image/"+k;draw();panel("")}
function body(){const zones={};for(const s of M.spaces)zones[s.id]=s.zones;return{bonuses:BON,passages:PASS.filter(g=>g.length>1),edges:[...edges].map(e=>e.split("-").map(Number)),zones,starts:M.starts}}
function draw(){const w=$("wrap");w.querySelectorAll(".sp").forEach(e=>e.remove());let svg="";
 for(const e of edges){const[a,b]=e.split("-").map(Number),A=M.spaces[a],B=M.spaces[b];
  svg+=`<line x1="${A.fx*1000}" y1="${A.fy*1000}" x2="${B.fx*1000}" y2="${B.fy*1000}" stroke="#ff0" stroke-width="3" vector-effect="non-scaling-stroke"/>`}
 BON.forEach(b=>{const A=M.spaces[b.from],B=M.spaces[b.to],mx=(A.fx+B.fx)*500,my=(A.fy+B.fy)*500,ax=B.fx*1000-A.fx*1000,ay=B.fy*1000-A.fy*1000,L=Math.hypot(ax,ay)||1,ux=ax/L*14,uy=ay/L*14;
  svg+=`<line x1="${A.fx*1000}" y1="${A.fy*1000}" x2="${B.fx*1000}" y2="${B.fy*1000}" stroke="#6f6" stroke-width="3" vector-effect="non-scaling-stroke"/>`
   +`<polygon points="${mx+ux},${my+uy} ${mx-uy*0.6-ux*0.6},${my+ux*0.6-uy*0.6} ${mx+uy*0.6-ux*0.6},${my-ux*0.6-uy*0.6}" fill="#6f6"/>`
   +`<text x="${mx}" y="${my-10}" fill="#6f6" font-size="16" font-weight="bold" text-anchor="middle">+${b.value}</text>`});
 PASS.forEach((g,i)=>{for(let j=1;j<g.length;j++){const A=M.spaces[g[j-1]],B=M.spaces[g[j]];
  svg+=`<line x1="${A.fx*1000}" y1="${A.fy*1000}" x2="${B.fx*1000}" y2="${B.fy*1000}" stroke="${i===cur?"#0ff":"#f90"}" stroke-width="3" stroke-dasharray="8 6" vector-effect="non-scaling-stroke"/>`}});
 $("lines").innerHTML=svg;
 for(const s of M.spaces){const d=document.createElement("div");d.className="sp"+(sel===s.id?" sel":"");
  const st=Object.entries(M.starts).filter(([k,v])=>v===s.id).map(([k])=>"S"+k).join(" ");if(st)d.classList.add("start");
  d.style.left=s.fx*100+"%";d.style.top=s.fy*100+"%";if(bsel===s.id)d.classList.add("bonus-from");const gi=PASS.findIndex(g=>g.includes(s.id));if(gi>=0){d.classList.add("pass");if(gi===cur)d.classList.add("cur")}
  d.innerHTML=(gi>=0?"&#128274;":"")+s.id+(st?" "+st:"")+"<small>"+s.zones.join("/")+"</small>";
  d.onclick=()=>{if(RO)return;if(bmode){clickBonus(s.id);return}if(pmode){togglePass(s.id);return}if(sel===null)sel=s.id;else if(sel===s.id)sel=null;else{const k=ek(sel,s.id);edges.has(k)?edges.delete(k):edges.add(k);sel=null}draw();panel()};w.append(d)}}
function panel(msg){const p=$("panel");if(!M)return;let h="<b>"+M.name+"</b><br>";
 if(M.problems)h+="<div id=problems>Import said: "+M.problems.join("\n")+"</div>";
 if(RO)h+="<div id=ok>Confirmed map: read-only (start the checker with --allow-reconfirm to change it).</div>";
 if(!RO){h+=`<hr><button class="${pmode?"on":""}" onclick=setPmode(!pmode)>Passage mode (key P): ${pmode?"ON":"off"}</button><button class="${bmode?"on":""}" onclick=setBmode(!bmode)>Bonus mode (key B): ${bmode?"ON":"off"}</button>`;
  if(bmode){h+="<br>Click the space the attacker stands on, then the adjacent space it hits: toggles +1 for that direction only (high ground). Bonuses: "+(BON.map(b=>b.from+"&rarr;"+b.to+" +"+b.value).join(", ")||"none")+"<br>"}
  if(pmode){h+="<br>Click spaces to add or remove them from the selected group (padlock = secret passage: move only, not adjacent).<br>";
   PASS.forEach((g,i)=>{h+=`<button class="${i===cur?"on":""}" onclick=pickGroup(${i})>group ${i+1}: ${g.join(",")||"empty"}</button>`});
   h+=`<br><button onclick=newGroup()>New group</button><button onclick=dropGroup()>Delete group</button>`}}
 if(sel!==null&&!RO&&!pmode&&!bmode){const s=M.spaces[sel];h+="<hr>Space "+sel+"<br>";
  for(const z of ZN)h+=`<label><input type=checkbox ${s.zones.includes(z)?"checked":""} onchange="zone(${sel},'${z}',this.checked)"> ${z}</label>`;
  h+="<br>";for(const n of ["1","2","3","4"])h+=`<button onclick="start('${n}',${sel})">start ${n}</button>`;
  h+=`<button onclick="clearStart(${sel})">no start</button>`}
 h+=RO?"<hr>":"<hr><button onclick=check()>Check</button><button onclick=confirmMap()>Confirm (write)</button><div id=problems>"+(msg||"")+"</div>";p.innerHTML=h}
function setBmode(on){bmode=on;if(on)pmode=false;bsel=null;sel=null;draw();panel()}
function clickBonus(id){if(bsel===null){bsel=id}else if(bsel===id){bsel=null}else{const i=BON.findIndex(b=>b.from===bsel&&b.to===id);if(i>=0)BON.splice(i,1);else if(!edges.has(ek(bsel,id))){const m="Spaces "+bsel+" and "+id+" are not adjacent: a bonus needs an edge";bsel=null;draw();return panel(m)}else BON.push({from:bsel,to:id,value:1});bsel=null}draw();panel()}
function setPmode(on){pmode=on;if(on)bmode=false;sel=null;if(on&&!PASS.length)PASS.push([]);draw();panel()}
function togglePass(id){const other=PASS.findIndex((g,i)=>i!==cur&&g.includes(id));if(other>=0)return panel("Space "+id+" is already in group "+(other+1));
 if(!PASS.length)PASS.push([]);const g=PASS[cur],i=g.indexOf(id);if(i>=0)g.splice(i,1);else g.push(id);draw();panel()}
function pickGroup(i){cur=i;draw();panel()}
function newGroup(){PASS.push([]);cur=PASS.length-1;draw();panel()}
function dropGroup(){PASS.splice(cur,1);cur=0;draw();panel()}
addEventListener("keydown",e=>{if(M&&!RO&&!/INPUT|TEXTAREA/.test(e.target.tagName)){const k=e.key.toLowerCase();if(k==="p")setPmode(!pmode);else if(k==="b")setBmode(!bmode)}});
function zone(id,z,on){const s=M.spaces[id];s.zones=on?[...new Set([...s.zones,z])]:s.zones.filter(x=>x!==z);draw();panel()}
function start(n,id){M.starts[n]=id;draw();panel()}
function clearStart(id){for(const k in M.starts)if(M.starts[k]===id)delete M.starts[k];draw();panel()}
async function check(){const r=await api("/api/check/"+key,body());panel(r.problems.length?r.problems.join("\n"):"Structural checks pass.")}
async function confirmMap(){const r=await api("/api/confirm/"+key,body());if(r.written){panel("Written: "+key+" is verified.");init()}else panel(r.problems.join("\n"))}
init();
</script>"""


class Handler(BaseHTTPRequestHandler):
    maps_dir = MAPS_DIR
    images_dir: Path
    expected: dict = {}
    zones: list[str] = []
    allow_reconfirm = False

    def log_message(self, *args):          # keep the console quiet
        pass

    def _local_only(self) -> bool:
        host = (self.headers.get("Host") or "").split(":")[0]
        origin = self.headers.get("Origin")
        return host in ("127.0.0.1", "localhost") and (origin is None or urlparse(origin).hostname in ("127.0.0.1", "localhost"))

    def _discard_body(self) -> None:
        """After a refusal, drops what the client already sent (briefly) so closing does not reset its connection."""
        length = self.headers.get("Content-Length", "")
        if length.isdigit():
            self.connection.settimeout(0.2)
            try:
                self.rfile.read(min(int(length), MAX_BODY))
            except OSError:
                pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, obj, code: int = 200) -> None:
        self._send(code, json.dumps(obj).encode("utf-8"), "application/json")

    def do_GET(self):
        if not self._local_only():
            return self._send(403, b"local only", "text/plain")
        path = urlparse(self.path).path
        try:
            if path == "/":
                return self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            if path == "/api/maps":
                return self._json({"maps": list_maps(self.maps_dir), "zones": self.zones, "reconfirm": self.allow_reconfirm})
            if path.startswith("/api/map/"):
                return self._json(map_view(self.maps_dir, path.rsplit("/", 1)[1]))
            if path.startswith("/image/"):
                found = image_path(self.images_dir, self.maps_dir, path.rsplit("/", 1)[1])
                if found is None:
                    return self._send(404, b"image not in --images", "text/plain")
                data = found.read_bytes()
                return self._send(200, data, image_type(data[:8]))
        except (OSError, ValueError, KeyError):
            return self._send(404, b"not found", "text/plain")
        self._send(404, b"not found", "text/plain")

    def do_POST(self):
        if not self._local_only() or self.headers.get("Content-Type") != "application/json":
            self._discard_body()
            return self._send(403, b"local json only", "text/plain")
        length = self.headers.get("Content-Length", "")
        if not length.isdigit() or int(length) > MAX_BODY:
            return self._send(400, b"bad Content-Length", "text/plain")
        raw = self.rfile.read(int(length))
        path = urlparse(self.path).path
        try:
            edit = json.loads(raw)
            if not isinstance(edit, dict):
                raise ValueError("the body must be a JSON object")
            key = _safe_key(path.rsplit("/", 1)[1])
            if path.startswith("/api/check/"):
                data = apply_edit(json.loads((self.maps_dir / f"{key}.json").read_text(encoding="utf-8")), edit)
                return self._json({"problems": validate(data, self.expected.get(key), self.zones)})
            if path.startswith("/api/confirm/"):
                written, problems = confirm(self.maps_dir, key, edit, self.expected.get(key), self.zones,
                                              self.allow_reconfirm)
                return self._json({"written": written, "problems": problems})
        except (OSError, ValueError, KeyError, TypeError) as e:
            return self._json({"problems": [f"rejected: {e}"], "written": False}, 400)
        self._send(404, b"not found", "text/plain")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Local map checker (see the module docstring).")
    ap.add_argument("--images", type=Path, default=os.environ.get("MAP_IMAGES_DIR"), required="MAP_IMAGES_DIR" not in os.environ,
                    help="folder with <imageKey>.img pictures, outside the repo (or MAP_IMAGES_DIR)")
    ap.add_argument("--expected", type=Path, help="unmatched-memory data/maps.json, for the published space/zone counts")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--allow-reconfirm", action="store_true", help="let maps that are already confirmed be edited again")
    args = ap.parse_args(argv)
    images = Path(args.images).resolve()
    if ROOT in images.parents or images == ROOT:
        print("--images must be outside the repository: the map art is not ours to commit", file=sys.stderr)
        return 2
    Handler.images_dir, Handler.expected, Handler.zones = images, load_expected(args.expected), known_zones()
    Handler.allow_reconfirm = args.allow_reconfirm
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Map checker on http://127.0.0.1:{args.port}  (Ctrl+C to stop)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
