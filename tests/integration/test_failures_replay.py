"""Failure handling (§7.3), determinism + replay (§7.4, G9)."""

from __future__ import annotations

import json
import time

from netcoop.agents.correlation import CorrelationAgent
from netcoop.agents.performance import PerformanceAgent
from netcoop.config import thaw
from netcoop.orchestrator.replay import replay
from netcoop.orchestrator.run import dump_report


def test_agent_crash_is_logged_and_caps_confidence(run, monkeypatch):
    calls = {"n": 0}

    def boom(self, msg, ctx):
        calls["n"] += 1
        raise RuntimeError("simulated crash")

    monkeypatch.setattr(PerformanceAgent, "analyze", boom)
    res = run("congestion")
    rep = res.report
    assert calls["n"] == 2  # one retry
    errs = [m for m in res.log.by_type("error") if m.payload["agent_id"] == "performance_agent"]
    assert errs and errs[0].payload["code"] == "AGENT_FAILED"
    assert rep["agents"]["performance_agent"] == "failed"
    assert any("performance_agent failed" in lim for lim in rep["limitations"])
    assert rep["confidence_category"] != "high"
    assert rep["status"] != "failed"  # the run continues


def test_agent_timeout(run, cfg, monkeypatch):
    agents = thaw(cfg.agents)
    agents["internal"]["infrastructure_agent"]["timeout_s"] = 0.2
    fast = cfg.with_overrides(agents=agents)
    from netcoop.agents.infrastructure import InfrastructureAgent

    def slow(self, msg, ctx):
        time.sleep(0.6)
        return []

    monkeypatch.setattr(InfrastructureAgent, "analyze", slow)
    res = run("congestion", config=fast)
    errs = [m for m in res.log.by_type("error") if m.payload["agent_id"] == "infrastructure_agent"]
    assert errs and errs[0].payload["code"] == "TIMEOUT"
    assert res.report["agents"]["infrastructure_agent"] == "failed"


def test_invalid_agent_output(run, monkeypatch):
    monkeypatch.setattr(PerformanceAgent, "analyze", lambda self, msg, ctx: [{"not": "a message"}])
    res = run("congestion")
    errs = [m for m in res.log.by_type("error") if m.payload["agent_id"] == "performance_agent"]
    assert errs and errs[0].payload["code"] == "INVALID_OUTPUT"


def test_correlation_failure_still_reports_raw_findings(run, monkeypatch):
    def boom(self, msg, ctx):
        raise RuntimeError("correlation down")

    monkeypatch.setattr(CorrelationAgent, "handle", boom)
    rep = run("congestion").report
    assert rep["status"] == "failed"
    assert rep["supporting_evidence"], "raw anomalous findings must still be reported"
    assert any("correlation_agent failed" in lim for lim in rep["limitations"])


def test_malformed_input_fails_safely(run):
    for bad in (b"{not json", b"\xff\xfe", b'{"schema_version": "9.0", "records": []}', b'{"records": "nope"}'):
        rep = run(bad).report
        assert rep["status"] == "failed"
        assert any("Input rejected" in lim for lim in rep["limitations"])


def test_same_input_same_report(run):
    a = run("interop", incident_id="INC-DETERM01").report
    b = run("interop", incident_id="INC-DETERM02").report
    a["incident_id"] = b["incident_id"] = "X"
    assert dump_report(a) == dump_report(b)


def test_replay_byte_identical(run, tmp_path):
    for name in ("congestion", "interop", "weak_wifi"):
        res = run(name)
        r = replay(res.incident_id, tmp_path / "runs")
        assert r.report_identical and r.events_identical, r.detail


def test_replay_with_external_agent(run, cfg, tmp_path, wireless_agent):
    from tests.conftest import cfg_with_external_url

    c = cfg_with_external_url(cfg, wireless_agent)
    res = run("weak_wifi", config=c, external=True)
    assert res.report["status"] == "diagnosed"
    r = replay(res.incident_id, tmp_path / "runs", cfg=c)  # served from external.jsonl, agent not contacted
    assert r.report_identical, r.detail
    saved = json.loads((tmp_path / "runs" / res.incident_id / "report.json").read_text())
    assert saved["status"] == "diagnosed"
