"""Local interactive research dashboard for the TEM-FLOW numerical core."""

from __future__ import annotations

from ._version import VERSION

import argparse
import csv
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlsplit
from uuid import uuid4
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .core import (
    channel_share_bounds,
    chronic_daily_intake,
    kl_box_projection,
    reference_destination_shares,
)
from .ledger import EvidenceLedger, EvidenceRecord


DATA_DIR = Path(__file__).with_name("data")
EVIDENCE_LOCK = threading.Lock()
TOPOLOGY_LOCK = threading.Lock()


def _comparable_datetime(value: str) -> datetime:
    """Parse ISO input and normalize aware values to naive UTC for comparison."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


HTML = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TEM-FLOW local research dashboard</title>
<style>
:root{--ink:#17232c;--muted:#5d6d78;--paper:#fff;--canvas:#eef3f2;--navy:#174f67;--blue:#2784a5;--amber:#dc9a35;--red:#bc4a3c;--line:#cbd8da}
*{box-sizing:border-box}body{margin:0;background:var(--canvas);color:var(--ink);font:15px/1.45 "Segoe UI",Arial,sans-serif}
header{background:linear-gradient(112deg,#143f51,#1c6978);color:white;padding:22px 30px 18px;box-shadow:0 2px 10px #11313d44}header h1{margin:0 0 3px;font-size:25px}header p{margin:0;color:#d8eef0;max-width:960px}.status{float:right;margin-top:5px;border:1px solid #9dd2d7;border-radius:20px;padding:5px 10px;font-size:13px;background:#ffffff12}
main{max-width:1440px;margin:18px auto;padding:0 18px 40px}.notice{background:#fff8e8;border-left:4px solid var(--amber);padding:10px 13px;margin-bottom:14px;border-radius:4px;color:#544728}.grid{display:grid;grid-template-columns:minmax(520px,1.15fr) minmax(430px,.85fr);gap:14px}.card{background:var(--paper);border:1px solid var(--line);border-radius:8px;padding:16px;box-shadow:0 2px 8px #19394312}.card h2{font-size:18px;margin:0 0 5px;color:#174f67}.card h3{font-size:15px;margin:14px 0 6px}.sub{color:var(--muted);font-size:13px;margin:0 0 12px}
.fields{display:grid;grid-template-columns:repeat(4,minmax(110px,1fr));gap:8px}.field label{display:block;color:#4d606b;font-size:12px;font-weight:650;margin:0 0 3px}.field input{width:100%;height:34px;border:1px solid #b9c9cc;border-radius:4px;padding:5px 7px;background:white;color:var(--ink);font:14px "Segoe UI",Arial,sans-serif}.field input:focus{outline:2px solid #7bbbc7;border-color:#4a95a4}
.table-wrap{overflow:auto;border:1px solid var(--line);border-radius:5px}table{border-collapse:collapse;width:100%;font-size:13px;white-space:nowrap}th{background:#edf4f3;color:#294956;text-align:right;padding:7px 5px;border-bottom:1px solid #b9cccf;font-weight:650}th:first-child,td:first-child{text-align:left}td{padding:4px 5px;border-bottom:1px solid #e2e9e9;text-align:right}td input{width:76px;border:1px solid #cad6d8;border-radius:3px;padding:4px;font:13px "Segoe UI",Arial,sans-serif}td:first-child input{width:128px}.check{width:auto}
button{border:0;border-radius:5px;background:var(--navy);color:white;padding:9px 14px;font-weight:650;font-size:14px;cursor:pointer}button:hover{background:#0f6074}.secondary{background:#e5eeee;color:#264b56}.secondary:hover{background:#d2e3e3}.danger{background:#f7e3df;color:#81372e}.button-row{display:flex;gap:8px;align-items:center;margin-top:11px;flex-wrap:wrap}.message{font-size:13px;color:var(--muted)}.error{color:#a83227;font-weight:650}.download{margin-left:auto}
#flow{width:100%;height:310px;border:1px solid #d3dfe0;border-radius:5px;background:#fbfdfc}.edge{stroke:#72aebb;stroke-opacity:.55;fill:none}.edge.active{stroke:#e68e2d;stroke-opacity:.95;stroke-dasharray:9 7;animation:pulse 1.1s linear 3}.node{fill:#fff;stroke:#1d697b;stroke-width:2}.source{fill:#174f67;stroke:#174f67}.nodeText{font:600 12px "Segoe UI",Arial,sans-serif;fill:#23343c}.sourceText{fill:white}@keyframes pulse{to{stroke-dashoffset:-32}}
.metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:10px 0}.metric{background:#eef6f5;border-radius:5px;padding:9px}.metric b{font-size:18px;color:#174f67;display:block}.metric span{font-size:11px;color:#5a6d75}.bar{height:9px;background:#e3ecec;border-radius:5px;overflow:hidden;min-width:90px}.bar i{display:block;height:100%;background:var(--blue)}.legend{display:flex;gap:15px;font-size:12px;color:#566a73;margin:4px 0 8px}.swatch{display:inline-block;width:13px;height:8px;margin-right:4px}.reference{background:var(--blue)}.bounds{border:2px solid var(--amber)}
details{margin-top:12px;border-top:1px solid #dbe5e5;padding-top:8px}summary{cursor:pointer;font-weight:650;color:#315b66}.formula{font-family:Cambria Math,"Times New Roman",serif;background:#f2f5f4;padding:8px;border-radius:4px;margin:7px 0}.footer{font-size:12px;color:#647780;margin-top:12px}@media(max-width:1000px){.grid{grid-template-columns:1fr}.fields{grid-template-columns:repeat(2,1fr)}}
</style></head>
<body><header><span class="status" id="serverStatus">local core: checking</span><h1>TEM-FLOW</h1><p>Coverage-aware partial identification of spatial food flows and contaminant exposure under sparse domestic data</p></header>
<main><div class="notice"><b>Research demonstrator.</b> Starting values are illustrative and editable; they are not presented as audited Ethiopian estimates. Enter documented values and retain the downloaded snapshot with the evidence trail.</div><div class="grid">
<section class="card"><h2>Scenario and evidence coverage</h2><p class="sub">Define a production source, observed channel distribution and destination covariates. Sharp bounds remain separate from the operational reference allocation.</p>
<div class="fields"><div class="field"><label>Source</label><input id="source" value="Illustrative fishery"></div><div class="field"><label>Commodity / species</label><input id="commodity" value="Fish / selected species"></div><div class="field"><label>Available production (t/y)</label><input id="production" type="number" min="0" step="1" value="1000"></div><div class="field"><label>Channel coverage lower bound, c</label><input id="coverage" type="number" min="0" max="1" step="0.05" value="0.50"></div></div>
<h3>Destination nodes</h3><div class="table-wrap"><table><thead><tr><th>Destination</th><th>Pop.</th><th>Time h</th><th>Market</th><th>Tradition</th><th>Route</th><th>Channel q</th><th>Reach</th></tr></thead><tbody id="destinations"></tbody></table></div><div class="button-row"><button class="secondary" id="addRow">+ Add node</button><button class="danger" id="removeRow">Remove last</button></div>
<h3>Exposure inputs</h3><div class="fields"><div class="field"><label>Edible fraction</label><input id="edible" type="number" min="0" max="1" step="0.01" value="0.55"></div><div class="field"><label>Contaminant</label><input id="contaminant" value="DDE"></div><div class="field"><label>Edible-tissue concentration (mg/kg)</label><input id="concentration" type="number" min="0" step="0.001" value="0.03"></div><div class="field"><label>Adult body weight (kg)</label><input id="bodyweight" type="number" min="1" step="1" value="55"></div><div class="field"><label>Oral slope factor (optional)</label><input id="slope" type="number" min="0" step="0.01" value="0.34"></div></div>
<div class="button-row"><button id="run">Run / update model</button><button class="secondary download" id="download">Download scenario + results</button><span id="message" class="message"></span></div><details><summary>What the model is calculating</summary><div class="formula"><i>P</i><sub>d</sub> = <i>c q</i><sub>d</sub> + (1 − <i>c</i>)<i>u</i><sub>d</sub></div><p class="sub">The coverage lower bound produces marginal destination-share intervals. A gravity/market prior is projected into the feasible bounded simplex by minimum Kullback–Leibler divergence. The reference estimate is operational; the identified interval remains the evidence-supported result.</p></details></section>
<section class="card"><h2>Dynamic source-to-destination view</h2><p class="sub">Orange pulses show the calculated reference flow. Line width is proportional to allocated share.</p><svg id="flow" viewBox="0 0 620 310" role="img" aria-label="Interactive TEM-FLOW route network"></svg><div class="metrics"><div class="metric"><b id="mass">—</b><span>allocated tonnes/year</span></div><div class="metric"><b id="closure">—</b><span>allocation closure error</span></div><div class="metric"><b id="width">—</b><span>mean interval width</span></div></div><div class="legend"><span><i class="swatch reference"></i>reference allocation</span><span><i class="swatch bounds"></i>identified bounds</span></div><div class="table-wrap"><table><thead><tr><th>Destination</th><th>Share interval</th><th>Reference</th><th>kg/person/y interval</th><th>Reference kg/person/y</th><th>Reference cancer risk</th><th>Share</th></tr></thead><tbody id="results"></tbody></table></div><p class="footer">Risk is shown only when an oral slope factor is supplied. It is a screening calculation, not a categorical safe/unsafe classification. Environmental-matrix measurements belong to an alert layer and are not used as edible dose.</p></section>
</div></main>
<script>
const defaults=[{name:'Lakeside population',pop:180000,time:.5,market:.45,tradition:1,route:1,q:.35,reachable:true},{name:'Corridor town',pop:260000,time:2.2,market:.55,tradition:.55,route:1,q:.20,reachable:true},{name:'Regional city',pop:480000,time:4.8,market:.78,tradition:.65,route:.85,q:.15,reachable:true},{name:'Capital market',pop:5500000,time:8,market:1,tradition:.10,route:1,q:.30,reachable:true}];
let lastPayload=null,lastResult=null;function row(d={name:'New destination',pop:100000,time:3,market:.5,tradition:.5,route:.5,q:.1,reachable:true}){const tr=document.createElement('tr'),fields=['name','pop','time','market','tradition','route','q'];fields.forEach(k=>{const td=document.createElement('td'),i=document.createElement('input');i.dataset.k=k;i.value=d[k];i.type=k==='name'?'text':'number';if(k!=='name'){i.min='0';i.step=['market','tradition','route','q'].includes(k)?'.05':'1'}td.append(i);tr.append(td)});const td=document.createElement('td'),c=document.createElement('input');c.type='checkbox';c.className='check';c.dataset.k='reachable';c.checked=d.reachable;td.append(c);tr.append(td);return tr}function add(d){document.getElementById('destinations').append(row(d))}defaults.forEach(add);
function number(id){return Number(document.getElementById(id).value)}function payload(){const ds=[...document.querySelectorAll('#destinations tr')].map(tr=>{const d={};tr.querySelectorAll('input').forEach(i=>d[i.dataset.k]=i.type==='checkbox'?i.checked:(i.dataset.k==='name'?i.value:Number(i.value)));return d});return{source:document.getElementById('source').value,commodity:document.getElementById('commodity').value,production_tonnes:number('production'),coverage_lower:number('coverage'),edible_fraction:number('edible'),contaminant:document.getElementById('contaminant').value,concentration_mg_kg:number('concentration'),body_weight_kg:number('bodyweight'),slope_factor:number('slope'),destinations:ds}}function fmt(x,n=3){if(!Number.isFinite(x))return'—';if(x!==0&&(Math.abs(x)<.001||Math.abs(x)>=10000))return x.toExponential(2);return x.toLocaleString(undefined,{maximumFractionDigits:n})}
async function run(){const msg=document.getElementById('message');msg.textContent='calculating…';msg.className='message';try{lastPayload=payload();const r=await fetch('/api/calculate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(lastPayload)}),data=await r.json();if(!r.ok)throw new Error(data.error||'calculation failed');lastResult=data;render(data);msg.textContent='updated'}catch(e){msg.textContent=e.message;msg.className='message error'}}
function render(data){document.getElementById('mass').textContent=fmt(data.total_reference_tonnes,1);document.getElementById('closure').textContent=fmt(data.closure_error,8);document.getElementById('width').textContent=fmt(data.mean_interval_width,3);const body=document.getElementById('results');body.innerHTML='';data.destinations.forEach(d=>{const tr=document.createElement('tr');tr.innerHTML=`<td>${esc(d.name)}</td><td>${fmt(d.share_lower)}–${fmt(d.share_upper)}</td><td><b>${fmt(d.share_reference)}</b></td><td>${fmt(d.consumption_lower)}–${fmt(d.consumption_upper)}</td><td><b>${fmt(d.consumption_reference)}</b></td><td>${fmt(d.cancer_risk_reference,2)}</td><td><div class="bar"><i style="width:${Math.max(1,d.share_reference*100)}%"></i></div></td>`;body.append(tr)});draw(data)}function draw(data){const s=document.getElementById('flow');s.innerHTML='';const ns='http://www.w3.org/2000/svg',cx=120,cy=155;data.destinations.forEach((d,i)=>{const y=42+i*(226/Math.max(1,data.destinations.length-1)),x=495,p=document.createElementNS(ns,'path');p.setAttribute('d',`M ${cx+48} ${cy} C 285 ${cy}, 345 ${y}, ${x-36} ${y}`);p.setAttribute('class','edge active');p.setAttribute('stroke-width',String(1.5+13*d.share_reference));s.append(p)});const sc=document.createElementNS(ns,'rect');sc.setAttribute('x',cx-63);sc.setAttribute('y',cy-25);sc.setAttribute('width',126);sc.setAttribute('height',50);sc.setAttribute('rx',8);sc.setAttribute('class','source');s.append(sc);textSvg(s,cx,cy+4,data.source,'nodeText sourceText','middle');data.destinations.forEach((d,i)=>{const y=42+i*(226/Math.max(1,data.destinations.length-1)),x=495,c=document.createElementNS(ns,'circle');c.setAttribute('cx',x);c.setAttribute('cy',y);c.setAttribute('r',Math.min(25,9+32*Math.sqrt(d.share_reference)));c.setAttribute('class','node');s.append(c);textSvg(s,535,y+4,d.name,'nodeText','start')})}
function textSvg(s,x,y,t,cls,anchor){const e=document.createElementNS('http://www.w3.org/2000/svg','text');e.setAttribute('x',x);e.setAttribute('y',y);e.setAttribute('class',cls);e.setAttribute('text-anchor',anchor);e.textContent=t;s.append(e)}function esc(v){return String(v).replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]))}document.getElementById('addRow').onclick=()=>add();document.getElementById('removeRow').onclick=()=>{const rows=document.querySelectorAll('#destinations tr');if(rows.length>2)rows[rows.length-1].remove()};document.getElementById('run').onclick=run;document.getElementById('download').onclick=async()=>{if(!lastResult)await run();if(!lastResult)return;const b=new Blob([JSON.stringify({generated_at:new Date().toISOString(),input:lastPayload,result:lastResult},null,2)],{type:'application/json'}),a=document.createElement('a');a.href=URL.createObjectURL(b);a.download='TEMFLOW_scenario_snapshot.json';a.click();URL.revokeObjectURL(a.href)};fetch('/api/health').then(r=>r.json()).then(x=>document.getElementById('serverStatus').textContent=`local core: ${x.version}`).catch(()=>{document.getElementById('serverStatus').textContent='local core: offline'});run();
</script></body></html>"""

# The maintained interface is stored separately so the geographic JavaScript
# and CSS remain auditable. The embedded string above is retained only as the
# pre-map fallback in source history.
HTML = (DATA_DIR / "dashboard_ui.html").read_text(encoding="utf-8")


def _csv_rows(filename: str) -> list[dict[str, str]]:
    with (DATA_DIR / filename).open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(";") if item.strip()]


SOURCE_SPECIES_REGISTER: dict[str, tuple[str, ...]] = {
    # These entries are limited to species/classes explicitly retained in the
    # audited source register. Contaminant-ledger species are added dynamically.
    "KOKA_RES": ("Tilapia", "Catfish", "Carp", "Barb"),
    "BESEKA_LAKE": ("Nile tilapia", "African catfish"),
}

# Capacity metadata are deliberately separate from dated production evidence.
# The 20 kt value is a user-supplied ceiling for the combined Gambella system;
# it must never be loaded as observed catch or repeated across child sources.
SOURCE_CAPACITY_REGISTER: dict[str, dict[str, Any]] = {
    "GAMBELLA_DIFFUSE": {
        "capacity_role": "combined-system potential ceiling",
        "potential_upper_tonnes": 20_000.0,
        "potential_is_observed_production": False,
        "capacity_provenance": "User expertise, 2026-08-19; under-accounted diffuse fishery potential",
    },
    **{
        source_id: {
            "capacity_parent": "GAMBELLA_DIFFUSE",
            "included_in_parent_potential": True,
            "potential_is_observed_production": False,
        }
        for source_id in (
            "AKOBO_PINYUDO_WETLANDS", "PIBOR_FLOODPLAIN", "GILO_FLOODPLAIN",
            "MAJANG_ITANG_BARO_WETLANDS", "TATA_LENTIC", "GOP_LENTIC_UNVERIFIED", "ALWERO_RES",
        )
    },
}

# Qualitative surplus statements are deliberately ranked below quantified
# destination allocations and are dated so the temporal interface does not
# back-cast current expert information into historical views.
SOURCE_SURPLUS_QUALITATIVE_REGISTER: dict[str, dict[str, Any]] = {
    "TURKANA_ETH_LAKE": {
        "observed_at": "2026-08-19", "entered_at": "2026-08-19",
        "label": "Qualitative dominant cross-border surplus; amount unquantified",
        "provenance": "User expertise: most Ethiopian-side surplus is directed to Kenya; domestic share is smaller",
    },
    "GAMBELLA_DIFFUSE": {
        "observed_at": "2026-08-19", "entered_at": "2026-08-19",
        "label": "Qualitative major regional/cross-border surplus; amount unquantified",
        "provenance": "User field expertise; the 20,000 t/y value remains a potential ceiling, not observed surplus",
    },
    "TANA_LAKE": {
        "observed_at": "2026-08-19", "entered_at": "2026-08-19",
        "label": "Qualitative major Addis/cross-border contributor; current surplus amount unquantified",
        "provenance": "User expertise; no claim that Tana currently exceeds GERD",
    },
    "GERD_RIVERS": {
        "observed_at": "2026-08-19", "entered_at": "2026-08-19",
        "label": "Qualitative major Addis/cross-border surplus; amount unquantified",
        "provenance": "User expertise; operational source mass and destination shares remain unmeasured",
    },
}

MULTIMODAL_CORRIDOR_MODES = {
    "C_GAMBELLA_LOCAL": "river-wetland-road/cargo candidate",
    "C_GAMBELLA_SURPLUS": "road-air/cargo candidate",
    "C_GERD_WEST": "road-air/cargo candidate",
    "C_TURKANA_ADDIS": "road-air/cross-border cargo candidate",
}


def _route_geometry_data() -> dict[str, Any]:
    path = DATA_DIR / "ethiopia_route_geometries.json"
    if not path.exists():
        return {
            "geometry_role": "registered node-to-node topology; audited road geometry not yet loaded",
            "attribution": None,
            "edge_geometries": {},
        }
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def load_map_data() -> dict[str, Any]:
    """Load the audited Figure 5 registers into a browser-ready payload."""
    nodes = [
        {
            "id": row["Node ID"],
            "code": row["Map code"],
            "name": row["Display name"],
            "map_class": row["Map class"],
            "role": row["Node role"],
            "tier": row["Absorption prior tier"],
            "corridor_codes": _split(row["Corridor code(s)"]),
            "evidence_state": row["Evidence state"],
            "coordinate_status": row["Coordinate status"],
            "lon": float(row["Longitude"]),
            "lat": float(row["Latitude"]),
        }
        for row in _csv_rows("ethiopia_nodes.csv")
    ]
    sources = [
        {
            "id": row["Source ID"],
            "label": row["Map short label"],
            "name": row["Source/system name"],
            "source_class": row["Source class"],
            "region": row["Region"],
            "corridors": _split(row["Candidate corridor(s)"]),
            "evidence_state": row["Evidence state"],
            "quantity_status": row["Current quantity status"],
            "coordinate_status": row["Coordinate status"],
            "commodity": "fish",
            "reported_species": list(SOURCE_SPECIES_REGISTER.get(row["Source ID"], ())),
            "lon": float(row["Longitude"]),
            "lat": float(row["Latitude"]),
            **SOURCE_CAPACITY_REGISTER.get(row["Source ID"], {}),
        }
        for row in _csv_rows("ethiopia_sources.csv")
    ]
    branch_scopes = {
        "TEND_AWASH": {"C_EASTERN_AWASH": [1, 4]},
        "ABHE_AFAMBO_CLUSTER": {"C_EASTERN_AWASH": [1, 4, 14]},
        "KOKA_RES": {"C_RIFT_ADDIS": [1, 7, 10, 11]},
        "BESEKA_LAKE": {"C_EASTERN_AWASH": [1, 12, 13]},
        "ZIWAY_LAKE": {"C_RIFT_ADDIS": [4, 14, 16, 17], "C_SOUTHWEST_MULTI": []},
        "LANGANO_LAKE_CHILD": {"C_RIFT_ADDIS": [5, 15], "C_SOUTHWEST_MULTI": []},
        "MELKA_WAKENA_RES": {"C_EASTERN_AWASH": [3, 9, 10, 11]},
        "GENALE_DAWA_RES_SYSTEM": {"C_GENALE_DAWA": [1, 2]},
        "GILGEL_GIBE_III_RES": {"C_SOUTHWEST_MULTI": [18, 19]},
        "FINCHA_RES": {"C_FINCHA_WEST": [1]},
        "AMERTI_RES": {"C_FINCHA_WEST": [2]},
        "TEKEZE_RES": {"C_TEKEZE_NORTH": [1, 3, 4, 5]},
        "HASHENGE_LAKE_CHILD": {"C_TEKEZE_NORTH": [2]},
        "GAMBELLA_DIFFUSE": {"C_GAMBELLA_LOCAL": [8, 9], "C_GAMBELLA_SURPLUS": [2, 3]},
        "TATA_LENTIC": {"C_GAMBELLA_LOCAL": [1]},
        "GOP_LENTIC_UNVERIFIED": {"C_GAMBELLA_LOCAL": [2]},
        "ALWERO_RES": {"C_GAMBELLA_LOCAL": [3], "C_GAMBELLA_SURPLUS": [1, 3]},
        "AKOBO_PINYUDO_WETLANDS": {"C_GAMBELLA_LOCAL": [4]},
        "PIBOR_FLOODPLAIN": {"C_GAMBELLA_LOCAL": [5]},
        "GILO_FLOODPLAIN": {"C_GAMBELLA_LOCAL": [6]},
        "MAJANG_ITANG_BARO_WETLANDS": {"C_GAMBELLA_LOCAL": [7]},
    }
    for source in sources:
        source["branch_scope"] = branch_scopes.get(source["id"], {})
    corridors = [
        {
            "id": row["Corridor ID"],
            "code": row["Map corridor code"],
            "name": row["Corridor name"],
            "family": row["Corridor family"],
            "color": row["Figure color"],
            "evidence_state": row["Evidence state"],
            "flow_character": row["User-stated flow character"],
        }
        for row in _csv_rows("ethiopia_corridors.csv")
    ]
    edges = [
        {
            "corridor_id": row["corridor_id"],
            "branch": int(row["branch"]),
            "order": int(row["segment_order"]),
            "from": row["from_id"],
            "to": row["to_id"],
            "evidence_state": row["evidence_state"],
            "qualitative_role": row["qualitative_role"],
        }
        for row in _csv_rows("ethiopia_edges.csv")
    ]
    boundary = json.loads((DATA_DIR / "ethiopia_boundary.geojson").read_text(encoding="utf-8"))
    regional_context = json.loads((DATA_DIR / "regional_context.geojson").read_text(encoding="utf-8"))
    regional_context_sources = json.loads((DATA_DIR / "regional_context_sources.json").read_text(encoding="utf-8"))
    waterbodies = json.loads((DATA_DIR / "ethiopia_waterbodies.geojson").read_text(encoding="utf-8"))
    item_ids = {row["id"] for row in nodes} | {row["id"] for row in sources}
    missing = sorted({edge[key] for edge in edges for key in ("from", "to")} - item_ids)
    if missing:
        raise RuntimeError(f"map edges reference missing items: {', '.join(missing)}")
    route_geometry = _route_geometry_data()
    for index, edge in enumerate(edges):
        geometry = route_geometry.get("edge_geometries", {}).get(str(index), {})
        edge["geometry"] = geometry.get("coordinates")
        default_mode = "multimodal_candidate" if edge["corridor_id"] in MULTIMODAL_CORRIDOR_MODES else "road_candidate"
        edge["transport_mode"] = geometry.get("mode", default_mode)
        edge["geometry_status"] = geometry.get("status", "registered node-sequence geometry")
        edge["mode_note"] = geometry.get("mode_note", MULTIMODAL_CORRIDOR_MODES.get(edge["corridor_id"], "road-constrained geometry pending audited road-layer import"))
    return {
        "bounds": [30.0, -2.0, 53.0, 19.0],
        "nodes": nodes,
        "sources": sources,
        "corridors": corridors,
        "edges": edges,
        "regional_context": regional_context,
        "regional_context_sources": regional_context_sources,
        "regional_labels": [
            {"name": "Sudan", "lon": 31.7, "lat": 15.8, "kind": "country"},
            {"name": "South Sudan", "lon": 32.4, "lat": 6.4, "kind": "country"},
            {"name": "Eritrea", "lon": 38.4, "lat": 16.3, "kind": "country"},
            {"name": "Djibouti", "lon": 42.35, "lat": 11.65, "kind": "country"},
            {"name": "Somalia", "lon": 48.5, "lat": 6.6, "kind": "country"},
            {"name": "Kenya", "lon": 36.0, "lat": 2.9, "kind": "country"},
            {"name": "Yemen", "lon": 45.1, "lat": 15.8, "kind": "country"},
            {"name": "Saudi Arabia", "lon": 42.0, "lat": 18.35, "kind": "country"},
            {"name": "Red Sea", "lon": 42.8, "lat": 17.25, "kind": "water", "rotation": -18},
        ],
        "boundary": boundary,
        "waterbodies": waterbodies,
        "route_geometry": {
            "role": route_geometry.get("geometry_role"),
            "attribution": route_geometry.get("attribution"),
            "generated_at": route_geometry.get("generated_at"),
            "failures": route_geometry.get("failures", []),
        },
        "evidence_boundary": "Candidate topology and qualitative route support; not measured transaction tonnage unless separately documented.",
        "regional_context_attribution": "geoBoundaries gbOpen ADM0; country-specific source, year and licence are retained in the map audit register.",
    }


def _user_topology_path() -> Path:
    return Path.cwd() / "user_data" / "temflow_topology.jsonl"


def load_user_topology() -> tuple[dict[str, Any], ...]:
    """Load append-only user map records without altering the curated registers."""
    path = _user_topology_path()
    if not path.exists():
        return ()
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
                if record.get("kind") not in {"source", "node", "edge", "retirement"} or not isinstance(record.get("item"), dict):
                    raise ValueError("kind/item structure is invalid")
                _comparable_datetime(str(record["entered_at"]))
                _comparable_datetime(str(record["observed_at"]))
                records.append(record)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid topology ledger line {line_number}: {exc}") from exc
    return tuple(records)


def effective_map_data(as_of: str | None = None, axis: str = "observed") -> dict[str, Any]:
    """Merge curated geography with dated, append-only user topology records."""
    if axis not in {"observed", "entered"}:
        raise ValueError("axis must be 'observed' or 'entered'")
    cutoff = _comparable_datetime(as_of or datetime.now(timezone.utc).isoformat())
    field = "observed_at" if axis == "observed" else "entered_at"
    data = json.loads(json.dumps(load_map_data()))
    active = [record for record in load_user_topology() if _comparable_datetime(str(record[field])) <= cutoff]
    active.sort(key=lambda record: (_comparable_datetime(str(record[field])), _comparable_datetime(str(record["entered_at"]))))
    retirement_count = 0
    for record in active:
        item = dict(record["item"])
        if record["kind"] == "retirement":
            target_kind = item.get("target_kind")
            if target_kind == "edge":
                data["edges"] = [
                    edge for edge in data["edges"]
                    if not (
                        edge.get("from") == item.get("from")
                        and edge.get("to") == item.get("to")
                        and edge.get("corridor_id") == item.get("corridor_id")
                        and (item.get("branch") is None or edge.get("branch") == item.get("branch"))
                        and (item.get("order") is None or edge.get("order") == item.get("order"))
                    )
                ]
            elif target_kind in {"source", "node"}:
                target_id = item.get("target_id")
                target = "sources" if target_kind == "source" else "nodes"
                data[target] = [candidate for candidate in data[target] if candidate.get("id") != target_id]
                data["edges"] = [edge for edge in data["edges"] if edge.get("from") != target_id and edge.get("to") != target_id]
            retirement_count += 1
            continue
        item["user_defined"] = True
        item["observed_at"] = record["observed_at"]
        item["entered_at"] = record["entered_at"]
        item["source_uri"] = record["source_uri"]
        target = {"source": "sources", "node": "nodes", "edge": "edges"}[record["kind"]]
        data[target].append(item)
    source_by_id = {source["id"]: source for source in data["sources"]}
    for edge in data["edges"]:
        source = source_by_id.get(edge["from"])
        if source is not None and edge["corridor_id"] not in source["corridors"]:
            source["corridors"].append(edge["corridor_id"])
    data["topology_as_of"] = (as_of or datetime.now(timezone.utc).isoformat())
    data["topology_axis"] = axis
    data["user_topology_count"] = len(active)
    data["topology_retirement_count"] = retirement_count
    _attach_source_display_priorities(data, data["topology_as_of"], axis)
    return data


def _map_coordinate(value: Any, name: str, minimum: float, maximum: float) -> float:
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} must be within the current Ethiopia map extent [{minimum}, {maximum}]")
    return number


def append_topology(payload: dict[str, Any]) -> dict[str, Any]:
    """Append a dated source, node, route or auditable topology retirement."""
    kind = str(payload.get("kind", "")).strip().lower()
    if kind not in {"source", "node", "edge", "retirement"}:
        raise ValueError("kind must be source, node, edge or retirement")
    observed_at = str(payload.get("observed_at", "")).strip()
    _comparable_datetime(observed_at)
    source_uri = str(payload.get("source_uri", "")).strip()
    if not source_uri:
        raise ValueError("an evidence source or local provenance note is required")
    token = uuid4().hex[:10].upper()
    if kind == "source":
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("production-source name is required")
        item = {
            "id": f"USR_SRC_{token}", "label": str(payload.get("label", "")).strip() or name,
            "name": name, "source_class": str(payload.get("source_class", "New production source")).strip(),
            "region": str(payload.get("region", "User registered")).strip(), "corridors": [],
            "evidence_state": "User-entered dated topology record", "quantity_status": "Awaiting production evidence",
            "coordinate_status": "User-entered coordinates",
            "lon": _map_coordinate(payload.get("lon"), "longitude", 32.5, 49.6),
            "lat": _map_coordinate(payload.get("lat"), "latitude", 3.0, 15.5),
        }
    elif kind == "node":
        name = str(payload.get("name", "")).strip()
        if not name:
            raise ValueError("place/node name is required")
        item = {
            "id": f"USR_NODE_{token}", "code": f"U-{token[:5]}", "name": name,
            "map_class": str(payload.get("map_class", "destination_market")).strip(),
            "role": str(payload.get("role", "Consumption destination")).strip(),
            "tier": str(payload.get("tier", "LOCAL_MARKET")).strip(), "corridor_codes": [],
            "evidence_state": "User-entered dated topology record", "coordinate_status": "User-entered coordinates",
            "lon": _map_coordinate(payload.get("lon"), "longitude", 32.5, 49.6),
            "lat": _map_coordinate(payload.get("lat"), "latitude", 3.0, 15.5),
        }
    elif kind == "edge":
        current = effective_map_data(datetime.now(timezone.utc).isoformat(), "entered")
        valid_ids = {item["id"] for item in current["nodes"] + current["sources"]}
        from_id, to_id = str(payload.get("from_id", "")).strip(), str(payload.get("to_id", "")).strip()
        corridor_id = str(payload.get("corridor_id", "")).strip()
        if from_id not in valid_ids or to_id not in valid_ids or from_id == to_id:
            raise ValueError("route endpoints must be two different registered source/place IDs")
        valid_corridors = {corridor["id"] for corridor in current["corridors"]}
        if corridor_id not in valid_corridors:
            raise ValueError("select a registered corridor for the new route link")
        item = {
            "id": f"USR_EDGE_{token}", "corridor_id": corridor_id, "branch": 99, "order": 999,
            "from": from_id, "to": to_id, "evidence_state": "User-entered dated route record",
            "qualitative_role": str(payload.get("role", "Candidate directed commodity route")).strip(),
        }
    else:
        current = effective_map_data(datetime.now(timezone.utc).isoformat(), "entered")
        target_kind = str(payload.get("target_kind", "")).strip().lower()
        reason = str(payload.get("reason", "")).strip()
        if target_kind not in {"source", "node", "edge"}:
            raise ValueError("retirement target must be a source, node or edge")
        if not reason:
            raise ValueError("a reason for topology retirement is required")
        if target_kind in {"source", "node"}:
            target_id = str(payload.get("target_id", "")).strip()
            collection = current["sources"] if target_kind == "source" else current["nodes"]
            if not any(candidate.get("id") == target_id for candidate in collection):
                raise ValueError(f"the selected {target_kind} is not active in the current topology")
            item = {"target_kind": target_kind, "target_id": target_id, "reason": reason}
        else:
            from_id = str(payload.get("from_id", "")).strip()
            to_id = str(payload.get("to_id", "")).strip()
            corridor_id = str(payload.get("corridor_id", "")).strip()
            branch = payload.get("branch")
            order = payload.get("order")
            branch = int(branch) if branch not in {None, ""} else None
            order = int(order) if order not in {None, ""} else None
            matches = [
                edge for edge in current["edges"]
                if edge.get("from") == from_id and edge.get("to") == to_id
                and edge.get("corridor_id") == corridor_id
                and (branch is None or edge.get("branch") == branch)
                and (order is None or edge.get("order") == order)
            ]
            if not matches:
                raise ValueError("the selected route segment is not active in the current topology")
            item = {
                "target_kind": "edge", "from": from_id, "to": to_id, "corridor_id": corridor_id,
                "branch": branch, "order": order, "reason": reason,
            }
    record = {
        "record_id": f"TOPO_{kind.upper()}_{token}", "kind": kind,
        "entered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "observed_at": observed_at,
        "source_uri": source_uri, "item": item,
    }
    with TOPOLOGY_LOCK:
        path = _user_topology_path(); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n")
    return record


def default_temporal_records() -> tuple[EvidenceRecord, ...]:
    """Curated starting ledger; unresolved sampling dates remain explicit."""
    common = {"commodity": "fish", "stage": "consumption/exposure"}
    records = [
        EvidenceRecord(
            "ETH_CONS_PRODUCTION_1990", "1995-01-01", "1990-01-01", "consumption",
            "Breuil_1995_FAO_Fisheries_Circular_890", origin="Arba Minch–Sodo–Hawassa production areas",
            value=8.5, unit="kg/person/year", denominator="historical production-area benchmark",
            metadata={"date_basis": "FAO 1990 value reported by Breuil 1995", "model_use": "documented consumption context"}, **common,
        ),
        EvidenceRecord(
            "ETH_CONS_HAWASSA_2018", "2020-01-01", "2018-01-01", "consumption",
            "Yilma_et_al_2020_Hawassa_consumer_comparator", origin="Lake Hawassa consumer setting",
            value=3.62, unit="kg/person/year", denominator="study comparator",
            metadata={"date_basis": "study period/figure label 2018; publication 2020", "model_use": "documented consumption context"}, **common,
        ),
        EvidenceRecord(
            "ETH_CONS_NATIONAL_2024", "2024-01-01", "2024-01-01", "consumption",
            "Ethiopia_Fisheries_Aquaculture_Master_Plan_2024", origin="Ethiopia",
            value=0.5, unit="kg/person/year", denominator="national planning baseline",
            metadata={"date_basis": "plan/report year", "model_use": "national boundary context"}, **common,
        ),
    ]
    records.extend(
        [
            EvidenceRecord(
                "CHAMO_PRODUCTION_1990_FAO", "1995-01-01", "1990-01-01", "production",
                "https://www.fao.org/4/v6718e/v6718e00.htm", origin="Lake Chamo",
                product="all catch", value=1350.0, unit="t/year",
                metadata={"source_id": "CHAMO_LAKE", "date_basis": "1990 value reported in Breuil 1995 Table 2", "evidence_grade": "B", "model_use": "historical source-mass observation"}, **common,
            ),
            EvidenceRecord(
                "HAWASSA_PRODUCTION_2018_SECONDARY", "2021-01-01", "2018-12-31", "production",
                "https://www.walshmedicalmedia.com/open-access/determinants-of-fish-market-supply-in-the-case-of-lake-hawassa-sidama-national-regional-state-ethiopia-83768.html", origin="Lake Hawassa",
                product="realized production", value=512.0, unit="t/year",
                metadata={"source_id": "HAWASSA_LAKE", "date_basis": "around 2018; secondary numeric claim in primary article", "evidence_grade": "C", "model_use": "broad production prior"}, **common,
            ),
            EvidenceRecord(
                "LANGANO_PRODUCTION_1990_FAO", "1995-01-01", "1990-01-01", "production",
                "https://www.fao.org/4/v6718e/v6718e00.htm", origin="Lake Langano",
                product="all catch", value=320.0, unit="t/year",
                metadata={"source_id": "LANGANO_LAKE_CHILD", "date_basis": "1990 value reported in Breuil 1995 Table 2", "evidence_grade": "B", "model_use": "historical source-mass observation"}, **common,
            ),
            EvidenceRecord(
                "TANA_PRODUCTION_1992_FAO", "1995-01-01", "1992-12-31", "production",
                "https://www.fao.org/4/v6718e/v6718e00.htm", origin="Lake Tana",
                product="all catch", value=1000.0, unit="t/year",
                metadata={"source_id": "TANA_LAKE", "date_basis": "1992/93 value reported in Breuil 1995", "evidence_grade": "B", "model_use": "historical broad production prior"}, **common,
            ),
            EvidenceRecord(
                "HAYQ_PRODUCTION_2017", "2018-11-01", "2017-12-31", "production",
                "https://doi.org/10.1016/j.heliyon.2018.e00949", origin="Lake Hayq",
                product="all catch", value=120.0, unit="t/year",
                metadata={"source_id": "HAYQ_LAKE_CHILD", "date_basis": "2017 annual record in Assefa et al. 2018 Table 5", "evidence_grade": "B", "model_use": "source-mass observation"}, **common,
            ),
            EvidenceRecord(
                "TEKEZE_PRODUCTION_2017", "2018-11-01", "2017-12-31", "production",
                "https://doi.org/10.1016/j.heliyon.2018.e00949", origin="Tekeze Reservoir",
                product="all catch", value=3661.84, unit="t/year",
                metadata={"source_id": "TEKEZE_RES", "date_basis": "2017 annual record in Assefa et al. 2018 Table 5", "evidence_grade": "B", "model_use": "source-mass observation"}, **common,
            ),
            EvidenceRecord(
                "FINCHA_AMERTI_PRODUCTION_2015_SECONDARY", "2024-01-01", "2015-12-31", "production",
                "https://onlinelibrary.wiley.com/doi/10.1002/aff2.168", origin="Fincha-Amerti reservoirs",
                product="all catch", value=130.101, unit="t/year",
                metadata={"source_id": "FINCHA_RES", "date_basis": "2015 or source study period; secondary review", "evidence_grade": "C", "model_use": "broad production prior"}, **common,
            ),
            EvidenceRecord(
                "GILGEL_GIBE_I_PRODUCTION_SECONDARY", "2024-01-01", "2014-12-31", "production",
                "https://onlinelibrary.wiley.com/doi/10.1002/aff2.168", origin="Gilgel Gibe I Reservoir",
                product="all catch", value=45.0, unit="t/year",
                metadata={"source_id": "GILGEL_GIBE_I_RES", "date_basis": "study period not recovered; source year provisionally keyed to cited 2014 study", "evidence_grade": "C", "model_use": "broad production prior"}, **common,
            ),
            EvidenceRecord(
                "CHAMO_ROUTE_ARBAMINCH_STRUCT", "1995-01-01", "1990-01-01", "route",
                "Breuil_1995_FAO_Fisheries_Circular_890", origin="Lake Chamo", destination="Arba Minch", product="local fresh fish",
                metadata={"source_id": "CHAMO_LAKE", "date_basis": "historical production-area evidence", "model_use": "documented structural route; tonnage unquantified"}, **common,
            ),
            EvidenceRecord(
                "CHAMO_ROUTE_ADDIS_2021_CHANNEL", "2024-01-01", "2021-12-31", "route",
                "Ethiopian_fishery_subsector_analysis_2021_fieldwork", origin="Lake Chamo", destination="Addis Ababa", product="wholesaler-traded fillet",
                metadata={"source_id": "CHAMO_LAKE", "date_basis": "2021 wholesaler channel", "model_use": "documented destination topology; total-source share unidentified"}, **common,
            ),
            EvidenceRecord(
                "CHAMO_ROUTE_SODO_HIST", "1995-01-01", "1990-01-01", "route",
                "Breuil_1995_FAO_Fisheries_Circular_890", origin="Lake Chamo", destination="Wolaita Sodo", product="fresh fish",
                metadata={"source_id": "CHAMO_LAKE", "date_basis": "historical production-area grouping", "model_use": "qualitative historical route"}, **common,
            ),
            EvidenceRecord(
                "CHAMO_ROUTE_HAWASSA_HIST", "1995-01-01", "1990-01-01", "route",
                "Breuil_1995_FAO_Fisheries_Circular_890", origin="Lake Chamo", destination="Hawassa City", product="fresh fish",
                metadata={"source_id": "CHAMO_LAKE", "date_basis": "historical production-area grouping", "model_use": "qualitative historical route"}, **common,
            ),
            EvidenceRecord(
                "KOKA_PRODUCTION_1990_FAO", "1995-01-01", "1990-01-01", "production",
                "https://www.fao.org/4/v6718e/v6718e00.htm", origin="Koka Reservoir",
                product="all catch", value=100.0, unit="t/year",
                metadata={"date_basis": "1990 value reported in Breuil 1995 Table 2", "evidence_grade": "B", "model_use": "historical source-mass observation"}, **common,
            ),
            EvidenceRecord(
                "KOKA_PRODUCTION_2021_SECONDARY", "2022-08-17", "2021-01-01", "production",
                "https://pmc.ncbi.nlm.nih.gov/articles/PMC9385613/", origin="Koka Reservoir",
                product="all catch", value=542.0, unit="t/year",
                metadata={"date_basis": "contemporary study description; underlying production source remains secondary", "evidence_grade": "C", "model_use": "broad production prior, not a hard census"}, **common,
            ),
            EvidenceRecord(
                "KOKA_ROUTE_ADAMA_2012_SURVEY", "2016-01-01", "2012-12-31", "route",
                "Market_Chain_Analysis_of_Koka_Reservoir_Fish_2016", origin="Koka Reservoir",
                destination="Adama", product="mixed fresh fish", value=None,
                metadata={"date_basis": "2012 market-chain survey; publication 2016", "sample": "104 fishers and 36 traders", "model_use": "observed destination topology; tonnage unquantified"}, **common,
            ),
            EvidenceRecord(
                "KOKA_ROUTE_ADDIS_2012_SURVEY", "2016-01-01", "2012-12-31", "route",
                "Market_Chain_Analysis_of_Koka_Reservoir_Fish_2016", origin="Koka Reservoir",
                destination="Addis Ababa", product="mixed fresh fish", value=None,
                metadata={"date_basis": "2012 market-chain survey; publication 2016", "sample": "104 fishers and 36 traders", "model_use": "observed destination topology; tonnage unquantified"}, **common,
            ),
            EvidenceRecord(
                "BESEKA_ROUTE_METEHARA_OFFICIAL", "2024-01-01", "2024-01-01", "route",
                "Ethiopia_Adama_Awash_Expressway_ESIA", origin="Lake Beseka fishery",
                destination="Metehara", product="fish", value=None,
                metadata={"date_basis": "official project report publication year; fishery observation date not reported", "model_use": "documented local-consumption topology; tonnage unquantified"}, **common,
            ),
            EvidenceRecord(
                "ZIWAY_PRODUCTION_2018_MARKET_STUDY", "2020-01-01", "2018-12-31", "production",
                "https://doi.org/10.5897/ISABB-JFAS2019.0106", origin="Lake Ziway",
                product="whole fishery as reported by surveyed market-chain study", value=488.9, unit="t/year",
                metadata={"date_basis": "December 2018-May 2019 survey; 2018 production basis", "sample": "90 fishers and 24 traders", "evidence_grade": "B", "model_use": "matched source-mass denominator for reported destination split"}, **common,
            ),
            EvidenceRecord(
                "ZIWAY_ADDIS_TOTAL_SHARE_2018", "2020-01-01", "2018-12-31", "share",
                "https://doi.org/10.5897/ISABB-JFAS2019.0106", origin="Lake Ziway",
                destination="Addis Ababa", product="gutted, filleted and whole fish",
                value=0.4107179382, unit="share of total source production", denominator="488.9 t produced; 485.0 t marketed",
                coverage_lower=485.0 / 488.9,
                metadata={"date_basis": "December 2018-May 2019 survey; 2018 production basis", "measurement_basis": "total_source_share", "share_lower": 0.4067293925, "share_upper": 0.4147064839, "reported_channel_share": 0.41, "model_use": "denominator-corrected direct destination bound"}, **common,
            ),
            EvidenceRecord(
                "ZIWAY_NEAR_URBAN_GROUP_2018", "2020-01-01", "2018-12-31", "share",
                "https://doi.org/10.5897/ISABB-JFAS2019.0106", origin="Lake Ziway",
                destination="Near urban markets from Ziway", product="gutted, filleted and whole fish",
                value=0.59, unit="share within marketed channel", denominator="485.0 t marketed fish",
                coverage_lower=485.0 / 488.9,
                metadata={"date_basis": "December 2018-May 2019 survey; 2018 production basis", "measurement_basis": "destination_group_share", "model_use": "aggregate nearby-market constraint; do not assign uniformly to towns"}, **common,
            ),
            EvidenceRecord(
                "ZIWAY_ROUTE_SHASHEMENE_2019_SURVEY", "2020-01-01", "2019-05-31", "route",
                "https://doi.org/10.5897/ISABB-JFAS2019.0106", origin="Lake Ziway",
                destination="Shashemene", product="fish", value=None,
                metadata={"date_basis": "December 2018-May 2019 survey", "model_use": "named large-volume market topology; destination-specific share unreported"}, **common,
            ),
            EvidenceRecord(
                "ZIWAY_ROUTE_MODJO_2019_SURVEY", "2020-01-01", "2019-05-31", "route",
                "https://doi.org/10.5897/ISABB-JFAS2019.0106", origin="Lake Ziway",
                destination="Modjo", product="fish", value=None,
                metadata={"date_basis": "December 2018-May 2019 survey", "model_use": "named large-volume market topology; destination-specific share unreported"}, **common,
            ),
            EvidenceRecord(
                "ZIWAY_ROUTE_ADAMA_2019_SURVEY", "2020-01-01", "2019-05-31", "route",
                "https://doi.org/10.5897/ISABB-JFAS2019.0106", origin="Lake Ziway",
                destination="Adama", product="fish", value=None,
                metadata={"date_basis": "December 2018-May 2019 survey", "model_use": "named large-volume market topology; destination-specific share unreported"}, **common,
            ),
            EvidenceRecord(
                "ZIWAY_ROUTE_BUTAJIRA_2019_SURVEY", "2020-01-01", "2019-05-31", "route",
                "https://doi.org/10.5897/ISABB-JFAS2019.0106", origin="Lake Ziway",
                destination="Butajira", product="fish", value=None,
                metadata={"date_basis": "December 2018-May 2019 survey", "model_use": "named large-volume market topology; destination-specific share unreported"}, **common,
            ),
            EvidenceRecord(
                "LANGANO_ROUTE_ADDIS_1990_FAO", "1995-01-01", "1990-01-01", "route",
                "https://www.fao.org/4/v6718e/v6718e00.htm", origin="Lake Langano",
                destination="Addis Ababa", product="fish", value=None,
                metadata={"date_basis": "historical sector status reported by Breuil 1995", "model_use": "documented historical destination topology; current share unmeasured"}, **common,
            ),
        ]
    )
    chamo_values = [
        ("TILAPIA_DDE", "Nile tilapia", "DDE", 0.01),
        ("CATFISH_DDE", "Catfish", "DDE", 0.02),
        ("CATFISH_DDD", "Catfish", "DDD", 0.02),
        ("BAGRUS_DDE", "Bagrus docmak", "DDE", 0.02),
        ("BAGRUS_CHLORPYRIFOS", "Bagrus docmak", "chlorpyrifos", 0.24),
        ("NILE_PERCH_DDE", "Nile perch", "DDE", 0.03),
    ]
    for suffix, species, analyte, value in chamo_values:
        records.append(
            EvidenceRecord(
                f"CHAMO_{suffix}_CURRENT_RECORD", "2026-08-19", "2026-08-19", "contaminant",
                "local:Lake_Chamo_pesticide_manuscript", origin="Lake Chamo", species=species,
                product=analyte, matrix="muscle", value=value, unit="mg/kg wet weight",
                metadata={
                    "date_basis": "sampling and laboratory-analysis dates unresolved; dashboard record date is provisional",
                    "model_use": "edible-dose evidence",
                }, **common,
            )
        )
    return tuple(records)


def _user_evidence_path() -> Path:
    return Path.cwd() / "user_data" / "temflow_evidence.jsonl"


def load_user_evidence() -> tuple[EvidenceRecord, ...]:
    path = _user_evidence_path()
    if not path.exists():
        return ()
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                records.append(EvidenceRecord(**json.loads(line)))
            except (TypeError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid evidence ledger line {line_number}: {exc}") from exc
    EvidenceLedger(records)
    return tuple(records)


def all_evidence_records() -> tuple[EvidenceRecord, ...]:
    records = default_temporal_records() + load_user_evidence()
    EvidenceLedger(records)
    return records


def temporal_snapshot(as_of: str, axis: str = "observed") -> dict[str, Any]:
    """Return an append-only evidence snapshot on observation or entry time."""
    if axis not in {"observed", "entered"}:
        raise ValueError("axis must be 'observed' or 'entered'")
    cutoff = _comparable_datetime(as_of)
    records = all_evidence_records()
    field = "observed_at" if axis == "observed" else "entered_at"
    eligible = [record for record in records if _comparable_datetime(getattr(record, field)) <= cutoff]
    superseded = {record.supersedes for record in eligible if record.supersedes}
    active = [record for record in eligible if record.record_id not in superseded]
    encoded = json.dumps([asdict(record) for record in active], sort_keys=True, separators=(",", ":"), default=str).encode()
    dates = [_comparable_datetime(getattr(record, field)) for record in records]
    return {
        "as_of": as_of,
        "axis": axis,
        "records": [asdict(record) for record in active],
        "record_count": len(active),
        "digest": hashlib.sha256(encoded).hexdigest(),
        "date_min": min(dates).date().isoformat(),
        "date_max": max(dates).date().isoformat(),
        "timeline_years": sorted({value.year for value in dates}),
    }


def _normalized_text(value: object) -> str:
    return " ".join("".join(character if character.isalnum() else " " for character in str(value).casefold()).split())


def _source_identity_text(value: object) -> str:
    ignored = {"lake", "reservoir", "fishery", "fisheries", "system", "river", "rivers", "the"}
    return " ".join(token for token in _normalized_text(value).split() if token not in ignored)


def _record_matches_source(record: EvidenceRecord, source: dict[str, Any]) -> bool:
    source_id = _normalized_text(record.metadata.get("source_id", ""))
    if source_id:
        return source_id == _normalized_text(source["id"])
    if not record.origin:
        return False
    observed = _normalized_text(record.origin)
    exact = {_normalized_text(source[key]) for key in ("id", "name", "label")}
    if observed in exact:
        return True
    observed_identity = _source_identity_text(record.origin)
    identities = {_source_identity_text(source[key]) for key in ("name", "label")}
    return bool(observed_identity) and observed_identity in identities


def _record_date(record: EvidenceRecord, axis: str) -> str:
    return record.observed_at if axis == "observed" else record.entered_at


def _latest_cohort(records: list[EvidenceRecord], axis: str) -> list[EvidenceRecord]:
    if not records:
        return []
    latest = max(_record_date(record, axis) for record in records)
    return [record for record in records if _record_date(record, axis) == latest]


def _attach_source_display_priorities(data: dict[str, Any], as_of: str, axis: str) -> None:
    """Rank source display without treating production or potential as surplus.

    Priority classes are ordered by evidential meaning: a quantified direct
    destination allocation, a dated qualitative major-surplus statement, a
    source production record with unknown surplus, route evidence without an
    amount, and an unquantified/candidate source.
    """
    snapshot = temporal_snapshot(as_of, axis)
    records = [EvidenceRecord(**row) for row in snapshot["records"]]
    cutoff = _comparable_datetime(as_of)
    qualitative_date_field = "observed_at" if axis == "observed" else "entered_at"
    for source in data["sources"]:
        matched = [record for record in records if _record_matches_source(record, source)]
        production_cohort = _latest_cohort([
            record for record in matched
            if record.evidence_type == "production" and record.value is not None and record.value >= 0
            and _normalized_text(record.unit or "") in {"t year", "tonnes year", "tonne year"}
        ], axis)
        production_record = production_cohort[-1] if len(production_cohort) == 1 else None
        production_tonnes = float(production_record.value) if production_record else None

        share_cohort = _latest_cohort([
            record for record in matched
            if record.evidence_type == "share" and record.destination and record.value is not None and record.value >= 0
        ], axis)
        quantified_outbound = 0.0
        outbound_records: list[str] = []
        for record in share_cohort:
            basis = record.metadata.get("measurement_basis")
            if basis == "destination_tonnage":
                quantified_outbound += float(record.value)
                outbound_records.append(record.record_id)
            elif basis == "total_source_share" and production_tonnes is not None:
                quantified_outbound += production_tonnes * float(record.value)
                outbound_records.append(record.record_id)

        qualitative = SOURCE_SURPLUS_QUALITATIVE_REGISTER.get(source["id"])
        qualitative_active = bool(
            qualitative
            and _comparable_datetime(str(qualitative[qualitative_date_field])) <= cutoff
        )
        route_count = sum(record.evidence_type == "route" and bool(record.destination) for record in matched)
        if quantified_outbound > 0:
            priority_class = 4
            label = f"Quantified direct destination allocation: {quantified_outbound:.1f} t/y"
            basis = "latest compatible production multiplied by direct total-source shares and/or reported destination tonnage"
            numeric = quantified_outbound
        elif qualitative_active:
            priority_class = 3
            label = str(qualitative["label"])
            basis = str(qualitative["provenance"])
            numeric = production_tonnes or 0.0
        elif production_tonnes is not None:
            priority_class = 2
            label = f"Production recorded ({production_tonnes:.1f} t/y); surplus amount unidentified"
            basis = production_record.record_id if production_record else "latest compatible production record"
            numeric = production_tonnes
        elif route_count:
            priority_class = 1
            label = f"{route_count} documented destination linkage(s); surplus amount unidentified"
            basis = "route evidence without destination tonnage or a total-source share"
            numeric = float(route_count)
        else:
            priority_class = 0
            label = "No quantified surplus or compatible production record retained"
            basis = "candidate/unquantified source"
            numeric = 0.0
        source.update({
            "display_priority_class": priority_class,
            "display_priority_score": priority_class * 1_000_000_000 + numeric,
            "display_priority_label": label,
            "display_priority_basis": basis,
            "quantified_outbound_tonnes": quantified_outbound if quantified_outbound > 0 else None,
            "priority_production_tonnes": production_tonnes,
            "priority_record_ids": outbound_records,
        })


def _record_summary(record: EvidenceRecord) -> dict[str, Any]:
    return {
        "record_id": record.record_id,
        "observed_at": record.observed_at,
        "entered_at": record.entered_at,
        "source_uri": record.source_uri,
        "product": record.product,
        "species": record.species,
        "value": record.value,
        "unit": record.unit,
        "denominator": record.denominator,
        "coverage_lower": record.coverage_lower,
        "measurement_basis": record.metadata.get("measurement_basis"),
    }


def source_evidence_state(
    source_id: str,
    as_of: str,
    axis: str = "observed",
    analyte: str | None = None,
    species: str | None = None,
) -> dict[str, Any]:
    """Resolve the latest compatible source-scoped interface state.

    Missing records remain missing. They are never inherited from a previously
    selected source and are never converted silently to measured zeroes.
    """
    if axis not in {"observed", "entered"}:
        raise ValueError("axis must be 'observed' or 'entered'")
    map_data = load_map_data()
    source = next((item for item in map_data["sources"] if item["id"] == source_id), None)
    if source is None:
        raise ValueError("unknown production source")
    snapshot = temporal_snapshot(as_of, axis)
    all_records = [EvidenceRecord(**record) for record in snapshot["records"]]
    records = [record for record in all_records if _record_matches_source(record, source)]

    production_candidates = [
        record for record in records
        if record.evidence_type == "production" and record.value is not None and record.value >= 0
    ]
    production_cohort = _latest_cohort(production_candidates, axis)
    preferred_production = [
        record for record in production_cohort
        if any(token in _normalized_text(record.product or "") for token in ("all catch", "whole fishery", "total catch"))
    ]
    selected_production = (preferred_production or production_cohort)
    production_record = selected_production[-1] if len(selected_production) == 1 else None
    production = {
        "status": "reported" if production_record else "missing" if not production_cohort else "ambiguous",
        "value": production_record.value if production_record else None,
        "unit": production_record.unit if production_record else None,
        "record": _record_summary(production_record) if production_record else None,
        "candidate_records": [_record_summary(record) for record in production_cohort],
    }

    species_records = [record for record in records if record.species]
    species_names = list(source.get("reported_species", []))
    for name in sorted({record.species for record in species_records if record.species}, key=str.casefold):
        if _normalized_text(name) not in {_normalized_text(value) for value in species_names}:
            species_names.append(name)
    observed_analytes = sorted({
        record.product for record in records
        if record.evidence_type == "contaminant" and record.product
    }, key=str.casefold)

    contaminant_candidates = [
        record for record in records
        if record.evidence_type == "contaminant"
        and record.value is not None
        and record.value >= 0
        and _normalized_text(record.matrix or "") in {"muscle", "edible tissue", "whole edible product"}
        and (not analyte or _normalized_text(record.product or "") == _normalized_text(analyte))
        and (not species or species == "__all__" or _normalized_text(record.species or "") == _normalized_text(species))
    ]
    contaminant_cohort = _latest_cohort(contaminant_candidates, axis)
    contaminant_record = max(contaminant_cohort, key=lambda record: float(record.value or 0), default=None)
    contaminant = {
        "status": "reported" if contaminant_record else "missing",
        "selection_rule": "maximum across the latest compatible species cohort" if species in (None, "", "__all__") else "latest compatible species record",
        "value": contaminant_record.value if contaminant_record else None,
        "unit": contaminant_record.unit if contaminant_record else None,
        "record": _record_summary(contaminant_record) if contaminant_record else None,
        "cohort_records": [_record_summary(record) for record in contaminant_cohort],
    }

    share_records = [
        record for record in records
        if record.evidence_type == "share" and record.destination and record.value is not None and record.value >= 0
    ]
    share_cohort = _latest_cohort(share_records, axis)
    node_names = {_normalized_text(node["name"]): node["name"] for node in map_data["nodes"]}
    individual_records = [record for record in share_cohort if _normalized_text(record.destination) in node_names]
    direct_records = [
        record for record in individual_records
        if record.metadata.get("measurement_basis") in {"total_source_share", "destination_tonnage"}
    ]
    channel_records = [
        record for record in individual_records
        if record.metadata.get("measurement_basis") in {None, "", "channel_share"}
    ]
    destination_constraints: list[dict[str, Any]] = []
    coverage_value = 0.0
    coverage_basis = "no compatible destination-resolved share evidence; c=0"
    coverage_records: list[EvidenceRecord] = []
    if direct_records:
        central_values: list[tuple[EvidenceRecord, float, float, float]] = []
        production_value = float(production_record.value) if production_record and production_record.value else None
        for record in direct_records:
            basis = record.metadata.get("measurement_basis")
            if basis == "destination_tonnage":
                if not production_value:
                    continue
                share = float(record.value) / production_value
            else:
                share = float(record.value)
            uncertainty = max(0.0, float(record.metadata.get("relative_uncertainty_fraction", 0) or 0))
            reported_lower = record.metadata.get("share_lower")
            reported_upper = record.metadata.get("share_upper")
            lower = float(reported_lower) if reported_lower is not None else max(0.0, share * (1 - uncertainty))
            upper = float(reported_upper) if reported_upper is not None else min(1.0, share * (1 + uncertainty))
            central_values.append((record, share, lower, upper))
        coverage_value = min(1.0, sum(value[2] for value in central_values))
        total_central = sum(value[1] for value in central_values)
        for record, share, lower, upper in central_values:
            destination_constraints.append({
                "destination": node_names[_normalized_text(record.destination)],
                "q": share / total_central if total_central else 0.0,
                "direct_share_lower": lower,
                "direct_share_upper": upper,
                "record": _record_summary(record),
            })
        coverage_basis = "sum of destination-resolved lower shares in the latest direct-evidence cohort"
        coverage_records = [value[0] for value in central_values]
    elif channel_records:
        explicit_coverages = [float(record.coverage_lower) for record in channel_records if record.coverage_lower is not None]
        coverage_value = min(explicit_coverages) if explicit_coverages else 0.0
        total = sum(float(record.value) for record in channel_records)
        for record in channel_records:
            destination_constraints.append({
                "destination": node_names[_normalized_text(record.destination)],
                "q": float(record.value) / total if total else 0.0,
                "direct_share_lower": None,
                "direct_share_upper": None,
                "record": _record_summary(record),
            })
        coverage_basis = "explicit coverage lower bound for the latest within-channel destination cohort" if explicit_coverages else "channel shares retained but coverage unreported; c=0"
        coverage_records = channel_records
    broader_mass_coverages = [float(record.coverage_lower) for record in share_cohort if record.coverage_lower is not None]
    unresolved_groups = [record for record in share_cohort if record not in individual_records]
    coverage = {
        "status": "reported" if coverage_records else "conservative_zero",
        "value": coverage_value,
        "basis": coverage_basis,
        "records": [_record_summary(record) for record in coverage_records],
        "broader_mass_coverage": max(broader_mass_coverages) if broader_mass_coverages else None,
        "unresolved_group_records": [_record_summary(record) for record in unresolved_groups],
    }

    route_records = [record for record in records if record.evidence_type == "route" and record.destination]
    return {
        "source": source,
        "as_of": as_of,
        "axis": axis,
        "commodity": source.get("commodity", "fish"),
        "production": production,
        "species": species_names,
        "observed_analytes": observed_analytes,
        "contaminant": contaminant,
        "coverage": coverage,
        "destination_constraints": destination_constraints,
        "documented_route_destinations": sorted({record.destination for record in route_records if record.destination}, key=str.casefold),
        "source_record_count": len(records),
        "ledger_digest": snapshot["digest"],
    }


def append_evidence(payload: dict[str, Any]) -> EvidenceRecord:
    allowed = {"contaminant", "production", "share", "route", "consumption"}
    evidence_type = str(payload.get("evidence_type", "")).strip()
    if evidence_type not in allowed:
        raise ValueError(f"evidence_type must be one of: {', '.join(sorted(allowed))}")
    observed_at = str(payload.get("observed_at", "")).strip()
    _comparable_datetime(observed_at)
    value = payload.get("value")
    if value in ("", None):
        value = None
    else:
        value = float(value)
    coverage = payload.get("coverage_lower")
    if coverage in ("", None):
        coverage = None
    else:
        coverage = float(coverage)
    record = EvidenceRecord(
        record_id=f"USR_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_{uuid4().hex[:8]}",
        entered_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        observed_at=observed_at,
        evidence_type=evidence_type,
        source_uri=str(payload.get("source_uri", "local:user-entered-evidence")).strip(),
        commodity=str(payload.get("commodity", "fish")).strip(),
        origin=str(payload.get("origin", "")).strip() or None,
        destination=str(payload.get("destination", "")).strip() or None,
        species=str(payload.get("species", "")).strip() or None,
        product=str(payload.get("product", "")).strip() or None,
        matrix=str(payload.get("matrix", "")).strip() or None,
        stage=str(payload.get("stage", "consumption/exposure")).strip() or None,
        value=value,
        unit=str(payload.get("unit", "")).strip() or None,
        denominator=str(payload.get("denominator", "")).strip() or None,
        coverage_lower=coverage,
        supersedes=str(payload.get("supersedes", "")).strip() or None,
        metadata=payload.get("metadata", {}) if isinstance(payload.get("metadata", {}), dict) else {},
    )
    record.validate()
    with EVIDENCE_LOCK:
        records = all_evidence_records()
        EvidenceLedger(records + (record,))
        path = _user_evidence_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(asdict(record), sort_keys=True, separators=(",", ":"), default=str) + "\n")
    return record


def _number(value: Any, name: str, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if number != number or number in (float("inf"), float("-inf")):
        raise ValueError(f"{name} must be finite")
    if minimum is not None and number < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    if maximum is not None and number > maximum:
        raise ValueError(f"{name} must be at most {maximum}")
    return number


def _optional_number(value: Any, name: str, minimum: float | None = None, maximum: float | None = None) -> float | None:
    if value in (None, ""):
        return None
    return _number(value, name, minimum, maximum)


def calculate_scenario(payload: dict[str, Any]) -> dict[str, Any]:
    """Calculate evidence bounds, the reference allocation and exposure."""
    destinations = payload.get("destinations")
    if not isinstance(destinations, list) or not 2 <= len(destinations) <= 30:
        raise ValueError("between two and 30 destination nodes are required")
    names, population, travel, market, tradition, route, channel, reachable, direct_lower, direct_upper = ([] for _ in range(10))
    for index, row in enumerate(destinations, start=1):
        name = str(row.get("name", "")).strip()
        if not name:
            raise ValueError(f"destination {index} needs a name")
        names.append(name)
        population.append(_number(row.get("pop"), f"population for {name}", 1))
        travel.append(_number(row.get("time"), f"travel time for {name}", 0.01))
        market.append(_number(row.get("market"), f"market score for {name}", 0))
        tradition.append(_number(row.get("tradition"), f"tradition score for {name}", 0))
        route.append(_number(row.get("route"), f"route support for {name}", 0))
        channel.append(_number(row.get("q"), f"channel share for {name}", 0))
        reachable.append(bool(row.get("reachable", True)))
        direct_lower.append(None if row.get("direct_share_lower") in (None, "") else _number(row.get("direct_share_lower"), f"direct share lower bound for {name}", 0, 1))
        direct_upper.append(None if row.get("direct_share_upper") in (None, "") else _number(row.get("direct_share_upper"), f"direct share upper bound for {name}", 0, 1))
    channel = [value if reach else 0.0 for value, reach in zip(channel, reachable)]
    if sum(channel) <= 0:
        raise ValueError("reachable destinations need positive observed channel share")
    coverage = _number(payload.get("coverage_lower"), "coverage lower bound", 0, 1)
    production = _number(payload.get("production_tonnes"), "production", 0)
    edible = _number(payload.get("edible_fraction"), "edible fraction", 0, 1)
    concentration = _optional_number(payload.get("concentration_mg_kg"), "concentration", 0)
    body_weight = _number(payload.get("body_weight_kg"), "body weight", 1)
    slope = _number(payload.get("slope_factor", 0), "slope factor", 0)
    lower, upper = channel_share_bounds(channel, coverage)
    # A disconnected destination is a structural zero, not merely a very
    # small prior weight. Preserve that exact topology constraint through the
    # KL projection and in the reported identification interval.
    for index, is_reachable in enumerate(reachable):
        if not is_reachable:
            lower[index] = 0.0
            upper[index] = 0.0
    direct_overrides: list[bool] = []
    for index, name in enumerate(names):
        has_direct = direct_lower[index] is not None or direct_upper[index] is not None
        direct_overrides.append(has_direct)
        if not has_direct:
            continue
        if not reachable[index]:
            raise ValueError(f"direct survey evidence for {name} conflicts with its structural-zero route state")
        observed_lower = direct_lower[index] if direct_lower[index] is not None else direct_upper[index]
        observed_upper = direct_upper[index] if direct_upper[index] is not None else direct_lower[index]
        if observed_lower is None or observed_upper is None or observed_lower > observed_upper:
            raise ValueError(f"direct survey interval for {name} is invalid")
        # Compatible direct evidence replaces the former model-derived marginal
        # bound for this destination; it is not clipped back into the old bound.
        lower[index], upper[index] = observed_lower, observed_upper
    if float(lower.sum()) > 1.0 + 1e-10 or float(upper.sum()) < 1.0 - 1e-10:
        raise ValueError("direct survey constraints and remaining route bounds are jointly infeasible under mass conservation")
    prior = reference_destination_shares(population, travel, market, tradition, route, reachable)
    reference = kl_box_projection(prior, lower=lower, upper=upper)
    rows = []
    for i, name in enumerate(names):
        factor = production * edible * 1000.0 / population[i]
        consumption = float(reference[i] * factor)
        dose = chronic_daily_intake([concentration], [consumption], body_weight) if concentration is not None else None
        risk = float(dose * slope) if dose is not None else None
        rows.append({"name": name, "share_lower": float(lower[i]), "share_upper": float(upper[i]), "share_reference": float(reference[i]), "reference_tonnes": float(reference[i] * production), "consumption_lower": float(lower[i] * factor), "consumption_upper": float(upper[i] * factor), "consumption_reference": consumption, "chronic_daily_intake": dose, "cancer_risk_reference": risk, "direct_evidence_override": direct_overrides[i]})
    return {"source": str(payload.get("source", "Source")), "commodity": str(payload.get("commodity", "Commodity")), "coverage_lower": coverage, "total_reference_tonnes": float(sum(row["reference_tonnes"] for row in rows)), "closure_error": float(abs(reference.sum() - 1.0)), "mean_interval_width": float((upper - lower).mean()), "destinations": rows, "interpretation": "Bounds are marginal; endpoints are not generally jointly attainable."}


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = f"TEMFLOWLocal/{VERSION}"

    def _json(self, status: int, value: dict[str, Any]) -> None:
        encoded = json.dumps(value, separators=(",", ":"), allow_nan=False).encode()
        self.send_response(status); self.send_header("Content-Type", "application/json; charset=utf-8"); self.send_header("Content-Length", str(len(encoded))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlsplit(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path in ("/", "/index.html"):
            encoded = HTML.encode(); self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8"); self.send_header("Content-Length", str(len(encoded))); self.send_header("Cache-Control", "no-store"); self.end_headers(); self.wfile.write(encoded)
        elif path == "/api/health":
            self._json(200, {"status": "ok", "version": f"TEM-FLOW {VERSION}"})
        elif path == "/api/map":
            as_of = query.get("as_of", [datetime.now(timezone.utc).isoformat()])[0]
            axis = query.get("axis", ["observed"])[0]
            try:
                self._json(200, effective_map_data(as_of, axis))
            except (ValueError, TypeError) as exc:
                self._json(400, {"error": str(exc)})
        elif path == "/api/evidence":
            as_of = query.get("as_of", [datetime.now(timezone.utc).date().isoformat()])[0]
            axis = query.get("axis", ["observed"])[0]
            try:
                self._json(200, temporal_snapshot(as_of, axis))
            except (ValueError, TypeError) as exc:
                self._json(400, {"error": str(exc)})
        elif path == "/api/source-state":
            as_of = query.get("as_of", [datetime.now(timezone.utc).date().isoformat()])[0]
            axis = query.get("axis", ["observed"])[0]
            source_id = query.get("source_id", [""])[0]
            analyte = query.get("analyte", [None])[0]
            species = query.get("species", [None])[0]
            try:
                self._json(200, source_evidence_state(source_id, as_of, axis, analyte, species))
            except (ValueError, TypeError) as exc:
                self._json(400, {"error": str(exc)})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        if path not in {"/api/calculate", "/api/evidence", "/api/topology"}:
            self._json(404, {"error": "not found"}); return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 1_000_000:
                raise ValueError("invalid request size")
            payload = json.loads(self.rfile.read(length).decode())
            if not isinstance(payload, dict):
                raise ValueError("request body must be an object")
            if path == "/api/calculate":
                self._json(200, calculate_scenario(payload))
            elif path == "/api/topology":
                self._json(201, {"record": append_topology(payload)})
            else:
                self._json(201, {"record": asdict(append_evidence(payload))})
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            self._json(400, {"error": str(exc)})
        except Exception:
            self._json(500, {"error": "unexpected local calculation error"})

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> int:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    url = f"http://{host}:{port}/"
    print(f"TEM-FLOW local dashboard: {url}", flush=True)
    print("Press Ctrl+C in this window to stop.", flush=True)
    if open_browser:
        threading.Timer(0.7, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


def dashboard_parser(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("dashboard", help="run the local interactive research dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="bind address; keep 127.0.0.1 for local-only use")
    parser.add_argument("--port", type=int, default=8765, help="local TCP port")
    parser.add_argument("--no-browser", action="store_true", help="do not open the browser automatically")

