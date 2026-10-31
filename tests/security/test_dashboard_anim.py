"""S2 dashboard animation: replay ordering, reduced motion, unchanged CSP, no reflow-heavy animation, text-only."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import netcoop.api.main as api
from netcoop.api.dashboard import CSP, STATIC
from tests.conftest import cfg_without_external

NODE = shutil.which("node")
JS = STATIC / "dashboard.js"
CSS = (STATIC / "dashboard.css").read_text(encoding="utf-8")
CSP_AT_DEMO_FINAL_3 = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
                       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


def node(script: str) -> object:
    if not NODE:
        pytest.skip("node not installed")
    code = f"const d = require({json.dumps(str(JS))});\nconst out = (() => {{ {script} }})();\nprocess.stdout.write(JSON.stringify(out));"
    p = subprocess.run([NODE, "-"], input=code, capture_output=True, text=True, encoding="utf-8", timeout=30)  # stdin: no cmdline limit
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


@pytest.fixture
def client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(api, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(api, "load_config", lambda: cfg_without_external(cfg))
    import netcoop.orchestrator.run as runmod
    monkeypatch.setattr(runmod, "load_config", lambda: cfg_without_external(cfg))
    return TestClient(api.app)


# ---------- replay ordering ----------
def test_reorder_buffer_releases_strictly_in_seq_order():
    out = node("""
      const b = new d.ReorderBuffer(); const got = [];
      for (const s of [3, 1, 2, 2, 6, 4, 1, 5, 8, 7]) for (const e of b.push({seq: s})) got.push(e.seq);
      return got;""")
    assert out == [1, 2, 3, 4, 5, 6, 7, 8]


def test_speeds_and_reduced_motion():
    out = node("return [d.delayFor('1', false), d.delayFor('2', false), d.delayFor('0', false), "
               "d.delayFor('1', true), d.delayFor('2', true)];")
    assert out == [240, 120, 0, 0, 0]  # 2x is twice as fast; reduced motion = no paced animation at all


@pytest.mark.parametrize("delay", [0, 5])
def test_sse_order_is_the_log_order_at_every_speed(client, delay):
    iid = client.post("/scenarios/congestion/run?external=false").json()["incident_id"]
    text = client.get(f"/incidents/{iid}/stream?delay_ms={delay}").text
    seqs = [json.loads(line[6:])["seq"] for line in text.splitlines() if line.startswith("data: {\"created_at\"")]
    assert seqs == list(range(1, len(seqs) + 1)) and len(seqs) >= 20


def test_prediction_flip_happens_at_the_evidence_message(run):
    res = run("congestion")
    events = [m.to_json_dict() for m in res.log.all()]
    out = node(f"""
      const ev = {json.dumps(events)}; const rep = {json.dumps(res.report)};
      const fs = new Map(); for (const e of ev) for (const f of (e.payload.findings || [])) if (!fs.has(f.finding_id)) fs.set(f.finding_id, e.seq);
      return [Object.fromEntries(d.flipSeqs(rep, fs)), d.localizedRoot(ev)];""")
    flips, root = out
    pred_seq = {e["payload"]["prediction"]["prediction_id"]: e["seq"] for e in events if e["message_type"] == "prediction"}
    assert flips and all(flips[p] > pred_seq[p] for p in flips)  # a card never flips before its prediction was logged
    for s in flips.values():
        assert events[s - 1]["message_type"] == "evidence_response"
    assert root == "L_HOSTEL_UPLINK"


def test_transform_rows_show_raw_to_canonical():
    finding = {"metric": "retransmission_pct", "transforms": [
        {"step": "alias", "field": "retx", "from": "retx", "to": "retransmission_pct", "reason": "metrics.yaml alias"},
        {"step": "unit", "field": "retx", "from": "0.208 fraction", "to": "20.8 pct", "reason": "explicit unit"},
        {"step": "entity", "field": "ap", "from": "ap-h3", "to": "AP_H3", "reason": "topology alias"},
        {"step": "unit", "field": "retx", "from": "0.208 fraction", "to": "20.8 pct", "reason": "dup"}]}
    rows = node(f"return d.transformRows([{json.dumps(finding)}], new Set());")
    assert [(r["raw"], r["canon"]) for r in rows] == [("retx", "retransmission_pct"),
                                                      ("retx 0.208 fraction", "retransmission_pct 20.8 pct"),
                                                      ("ap-h3", "AP_H3")]


def test_external_lane_detection():
    assert node("return ['wireless_agent', 'performance_agent', 'triage_agent', 'remediation_planner']"
                ".map(d.isExternal);") == [True, False, False, False]


# ---------- reduced motion, CSP, reflow, text-only ----------
def test_reduced_motion_disables_all_animation():
    block = CSS[CSS.index("@media (prefers-reduced-motion: reduce)"):]
    assert "animation: none !important" in block and "transition: none !important" in block
    js = JS.read_text(encoding="utf-8")
    assert "prefers-reduced-motion: reduce" in js and "delayFor(speed, reducedMotion())" in js


def test_csp_headers_unchanged(client):
    assert CSP == CSP_AT_DEMO_FINAL_3
    for path in ("/", "/dashboard/dashboard.js", "/dashboard/dashboard.css"):
        assert client.get(path).headers["content-security-policy"] == CSP_AT_DEMO_FINAL_3


def test_keyframes_animate_only_transform_opacity_color():
    allowed = {"opacity", "transform", "color", "stroke-opacity"}
    for name, body in re.findall(r"@keyframes\s+([\w-]+)\s*\{(.*?)\}\s*\}", CSS, re.S):
        props = set(re.findall(r"([a-z-]+)\s*:", body))
        assert props <= allowed, (name, props - allowed)  # no width/height/top/left/margin: no layout shift


def test_no_new_libraries_or_html_sinks():
    js = JS.read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", js)
    assert "innerHTML" not in code and "insertAdjacentHTML" not in code and "import " not in code
    assert not re.search(r"https?://(?!www\.w3\.org/2000/svg)", code)
    assert "setAttribute(\"style\"" not in code  # inline style attributes would violate style-src 'self'
