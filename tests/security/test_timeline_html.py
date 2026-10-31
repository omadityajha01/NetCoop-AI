"""T6 / PI8: the HTML timeline escapes every data value; hostile names render as text."""

from __future__ import annotations

import json

from netcoop.cli import main as cli_main
from netcoop.timeline import render, write_timeline
from tests.conftest import scenario_json

EVIL = "<script>alert(1)</script>"


def test_script_in_device_name_renders_as_text(run, tmp_path):
    b = scenario_json("congestion")
    t = b["incident"]["time"]
    b["records"] += [
        {"timestamp": t, "device_id": EVIL, "metrics": {"latency_ms": 900}},
        {"timestamp": t, "device_id": "SW_CAMPUS_1", "metrics": {"latency_ms": 10, EVIL: "<img src=x onerror=alert(2)>"}},
    ]
    res = run(json.dumps(b).encode())
    out = write_timeline(res.run_dir, tmp_path / "t.html")
    page = out.read_text(encoding="utf-8")
    assert "<script" not in page.lower()          # no script element at all (static file, no JS)
    assert "<img" not in page.lower()
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page  # the hostile device name is visible as text
    assert "&lt;img src=x onerror=alert(2)&gt;" in page
    assert "http://" not in page and "https://" not in page  # no CDN / network references


def test_timeline_sections_and_prediction_pairs(run, tmp_path):
    res = run("congestion")
    page = write_timeline(res.run_dir, tmp_path / "t.html").read_text(encoding="utf-8")
    for section in ("Message timeline", "Predictions → evidence", "Normalization", "Final report", "Blocked by policy"):
        assert section in page
    for p in res.report["predictions"]:
        assert p["prediction_id"] in page
    assert "class='pill hit'" in page


def test_render_escapes_report_fields():
    rep = {"incident_id": "INC-X", "status": "failed\" onmouseover=\"x", "suspected_root_cause": EVIL, "limitations": [EVIL]}
    page = render([], rep)
    assert "<script" not in page.lower() and 'onmouseover="x' not in page


def test_cli_timeline(run, tmp_path):
    res = run("dns_failure")
    out = tmp_path / "x.html"
    assert cli_main(["--runs-dir", str(res.run_dir.parent), "timeline", res.incident_id, "--html", str(out)]) == 0
    assert out.exists()
