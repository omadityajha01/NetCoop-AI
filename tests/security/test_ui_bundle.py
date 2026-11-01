"""Bundled UI (netcoop/api/ui): CSP-safe, text-only (PI8), self-contained, reduced-motion aware; JS helpers tested."""

from __future__ import annotations

import json
import re
import shutil
import subprocess

import pytest
from fastapi.testclient import TestClient

import netcoop.api.main as api
from netcoop.api import dashboard as dash
from tests.conftest import cfg_without_external

UI = dash.DEFAULT_UI
FILES = sorted(p for p in UI.iterdir() if p.is_file())
NODE = shutil.which("node")


@pytest.fixture
def client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(api, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(api, "load_config", lambda: cfg_without_external(cfg))
    import netcoop.orchestrator.run as runmod
    monkeypatch.setattr(runmod, "load_config", lambda: cfg_without_external(cfg))
    monkeypatch.delenv(dash.UI_ENV, raising=False)
    return TestClient(api.app)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_csp_safe_and_text_only(path):
    src = path.read_text(encoding="utf-8")
    code = re.sub(r"//[^\n]*", "", src) if path.suffix == ".js" else src
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "javascript:"):
        assert banned not in code, f"{banned} in {path.name}"
    if path.suffix == ".html":
        assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", src), "inline <script> is blocked by the CSP"
        assert not re.search(r"\sstyle\s*=", src), "style attributes are blocked by style-src 'self'"
        assert not re.search(r"\son[a-z]+\s*=", src), "inline event handlers are blocked by the CSP"
    remote = re.findall(r"https?://[^\s\"')]+", code)
    assert all(u.startswith("http://www.w3.org/") for u in remote), remote  # no CDN, fonts or trackers
    assert "@import" not in code and "fonts.googleapis" not in code


def test_every_referenced_asset_exists_and_is_served(client):
    for html in ("index.html", "dashboard.html"):
        src = (UI / html).read_text(encoding="utf-8")
        refs = re.findall(r'(?:src|href)="(/ui/[^"#?]+)"', src)
        assert refs, html
        for ref in refs:
            r = client.get(ref)
            assert r.status_code == 200, ref
            assert r.headers["content-security-policy"] == dash.CSP
    for html in ("index.html", "dashboard.html"):
        assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in (UI / html).read_text(encoding="utf-8")


def test_reduced_motion_and_cheap_animation():
    for css in ("styles.css", "dashboard.css"):
        src = (UI / css).read_text(encoding="utf-8")
        for name, body in re.findall(r"@keyframes\s+([\w-]+)\s*\{(.*?)\}\s*\}", src, re.S):
            props = set(re.findall(r"([a-z-]+)\s*:", body))
            assert props <= {"opacity", "transform", "stroke-opacity"}, (css, name, props)
    assert "prefers-reduced-motion: reduce" in (UI / "styles.css").read_text(encoding="utf-8")
    for js in ("landing.js", "dashboard.js"):
        assert "prefers-reduced-motion: reduce" in (UI / js).read_text(encoding="utf-8")


def test_dashboard_drives_the_real_endpoints(client):
    js = (UI / "dashboard.js").read_text(encoding="utf-8")
    for path in ("/scenarios", "/topology", "/agents", "/incidents?limit=", "/run?external=", "/stream?delay_ms=",
                 "/report", "/events", "/feedback"):
        assert path in js, path
    iid = client.post("/scenarios/congestion/run?external=false").json()["incident_id"]
    assert client.get(f"/incidents/{iid}/stream?delay_ms=0").status_code == 200


def node(script: str) -> object:
    if not NODE:
        pytest.skip("node not installed")
    code = (f"const D = require({json.dumps(str(UI / 'dashboard.js'))});\n"
            f"const L = require({json.dumps(str(UI / 'landing.js'))});\n"
            f"process.stdout.write(JSON.stringify((() => {{ {script} }})()));")
    p = subprocess.run([NODE, "-"], input=code, capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def test_js_helpers():
    out = node("""
      const b = new D.ReorderBuffer(); const got = [];
      for (const s of [2, 1, 1, 4, 3]) for (const e of b.push({seq: s})) got.push(e.seq);
      return {
        order: got,
        speeds: [D.SPEED_MS[1], D.SPEED_MS[2]],
        external: D.INTERNAL.has('wireless_agent'),
        pick: ['Wi-Fi keeps dropping', 'websites will not open', 'new laptop gets no IP address', 'slow video calls',
               'lab PCs disconnect', 'something odd'].map(L.pickScenario),
        insufficient: L.summarize({status: 'insufficient_evidence', suspected_root_cause: 'Insufficient evidence',
                                   missing_signals: ['rssi_dbm@AP_H3'], confidence: 0.33, confidence_category: 'low'}),
        nofault: L.summarize({status: 'no_fault_detected', confidence: 0, confidence_category: 'low'}),
        steps: L.ORDER,
      };""")
    assert out["order"] == [1, 2, 3, 4]
    assert out["speeds"] == [240, 120] and out["external"] is False
    assert out["pick"] == ["weak_wifi", "dns_failure", "dhcp_failure", "congestion", "interface_fault", "congestion"]
    assert "won't guess" in out["insufficient"] and "rssi_dbm@AP_H3" in out["insufficient"]
    assert out["nofault"].startswith("No fault detected")
    assert out["steps"] == ["normalize", "analyze", "predict", "decide"]


def test_no_certainty_or_execution_claims_in_ui_copy():
    text = " ".join(p.read_text(encoding="utf-8") for p in FILES).lower()
    for banned in ("confirmed", "definitely", "guaranteed", "fix verified", "fixed automatically", "auto-remediat"):
        assert banned not in text, banned


def test_plain_language_layer():
    out = node("""
      const ev = {seq: 16, message_type: 'prediction', sender: 'correlation_agent', recipient: 'orchestrator',
                  payload: {prediction: {fault_type: 'congestion', signal: {metric: 'queue_drops_count', entity: {id: 'SW_1'}},
                                          expected: {op: '>=', ref: 'high'}}}};
      return {
        pred: D.describe(ev),
        task: D.describe({message_type: 'task_request', recipient: 'performance_agent', payload: {task: 'analyze', round: 0}}),
        found: D.describe({message_type: 'finding_report', payload: {findings: [{}, {}, {}]}}),
        none: D.describe({message_type: 'finding_report', payload: {findings: []}}),
        sure: [D.sureWord(1), D.sureWord(0.6), D.sureWord(0.2)],
        problems: Object.keys(D.PROBLEMS).sort(),
        expect: D.expectText({op: '<', ref: 'high'}),
      };""")
    assert out["pred"] == ("Predicts dropped packets on SW_1 will be at or above the high level if it's "
                           "network congestion (link overloaded)")
    assert out["task"] == "Asked Performance agent to check the network"
    assert out["found"] == "Found 3 problems" and out["none"] == "Found nothing unusual"
    assert out["sure"] == ["High", "Medium", "Low"] and out["expect"] == "below the high level"
    from netcoop.api.dashboard import scenario_names

    assert set(scenario_names()) <= set(out["problems"])  # every scenario has a plain-language name


def test_feed_details_for_every_recorded_message():
    """Clicking a feed card shows detailRows(ev): every real message type must render clean rows."""
    import typing
    from pathlib import Path

    from netcoop.protocol.envelope import MessageType

    fix = Path(dash.ROOT) / "docs" / "frontend_fixtures"
    events = [line for p in sorted(fix.glob("*/events.jsonl"))
              for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]
    out = node(f"""
      const res = {{}};
      const isBad = x => typeof x !== 'string' || ['undefined', '[object Object]', 'NaN'].some(w => x.includes(w));
      for (const line of {json.dumps(events)}) {{
        const ev = JSON.parse(line); const rows = D.detailRows(ev);
        const bad = rows.filter(r => r.length !== 2 || r.some(isBad));
        const k = ev.message_type; res[k] = res[k] || {{n: 0, minRows: 99, bad: []}};
        res[k].n += 1; res[k].minRows = Math.min(res[k].minRows, rows.length); res[k].bad.push(...bad.map(b => JSON.stringify(b)));
      }}
      return res;""")

    assert set(out) == set(typing.get_args(MessageType))
    for mt, r in out.items():
        assert not r["bad"], (mt, r["bad"][:3])
        assert r["minRows"] >= 3, mt  # sender/recipient + message + at least one content row
