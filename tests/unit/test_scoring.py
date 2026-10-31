"""Documented scoring method (§6.3): formula, status rules, confidence category and caps."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from netcoop.protocol.findings import DataQuality, EntityRef, Finding, Window
from netcoop.scoring.confidence import category_for, decide
from netcoop.scoring.hypotheses import index_findings, rank_hypotheses, score_hypothesis

W = Window(start=datetime(2026, 10, 31, 9, 30, tzinfo=UTC), end=datetime(2026, 10, 31, 10, 0, tzinfo=UTC))
_n = iter(range(1, 10_000))


def F(metric, eid, value, etype="device", sev="high", completeness=1.0, coerced=False):
    return Finding(finding_id=f"F-test_agent-{next(_n)}", metric=metric, entity=EntityRef(type=etype, id=eid), value=value,
                   unit="x", window=W, aggregation="p95", sample_count=6, threshold_ref="t", severity=sev,
                   data_quality=DataQuality(completeness=completeness, staleness_s=0, coerced=coerced))


def q(f):
    return f.data_quality.completeness


def test_congestion_formula(cfg):
    fs = [F("link_utilization_pct", "L_HOSTEL_UPLINK", 95, "link"), F("queue_drops_count", "HOSTEL_CORE_SW_01", 500),
          F("latency_ms", "HOSTEL_CORE_SW_01", 40, sev="normal")]  # latency below warn: observed, not matching
    h = score_hypothesis(cfg, "congestion", "L_HOSTEL_UPLINK", index_findings(fs), q)
    # E weights: util 3, drops 3, latency 2, loss 1 = 9
    assert h.support == pytest.approx(6 / 9, abs=1e-4)
    assert h.coverage == pytest.approx(8 / 9, abs=1e-4)
    assert h.contra == 0
    assert h.score == pytest.approx(6 / 9, abs=1e-4)
    assert h.missing_signals == ["packet_loss_pct@L_HOSTEL_UPLINK"]


def test_contradiction_and_quality(cfg):
    fs = [F("link_utilization_pct", "L_HOSTEL_UPLINK", 95, "link", completeness=0.5, coerced=True),
          F("queue_drops_count", "HOSTEL_CORE_SW_01", 500, completeness=0.5),
          F("interface_errors_count", "HOSTEL_CORE_SW_01", 300)]
    h = score_hypothesis(cfg, "congestion", "L_HOSTEL_UPLINK", index_findings(fs), q)
    support = 6 / 9
    contra = 2 / 3  # interface_errors (2) of C weights 2 + 1
    sc = cfg.scoring
    quality = max(sc["quality_floor"], (0.5 + 0.5 + 1.0) / 3 - sc["coerced_penalty"] * 1)
    assert h.score == pytest.approx(max(0, support - sc["contra_penalty"] * contra) * quality, abs=1e-3)


def test_localization_prefers_link_on_tie(cfg):
    fs = [F("link_utilization_pct", "L_HOSTEL_UPLINK", 95, "link"), F("queue_drops_count", "HOSTEL_CORE_SW_01", 500)]
    cands = {("congestion", "L_HOSTEL_UPLINK"): "findings", ("congestion", "HOSTEL_CORE_SW_01"): "findings"}
    hyps = rank_hypotheses(cfg, cands, index_findings(fs), q)
    assert hyps[0].entity.id == "L_HOSTEL_UPLINK"


def _h(cfg, score, cov=1.0, ft="congestion"):
    from netcoop.protocol.findings import Hypothesis
    return Hypothesis(hypothesis_id=f"H-{ft}", fault_type=ft, entity=EntityRef(type="link", id="L_HOSTEL_UPLINK"),
                      score=score, support=score, coverage=cov, contra=0, quality=1)


def test_status_rules(cfg):
    kw = dict(usable_observations=10, failed_agents=[], unresolved_c2=False, data_coverage=1.0)
    # 0. no data at all
    d = decide(cfg, [], high_count=0, usable_observations=0, failed_agents=[], unresolved_c2=False, data_coverage=1)
    assert d.status == "insufficient_evidence" and d.reason == "data_missing"
    # a. leading hypothesis lacks coverage -> data missing (even if its score is high)
    d = decide(cfg, [_h(cfg, 0.9, cov=0.4)], high_count=2, **kw)
    assert d.status == "insufficient_evidence" and d.reason == "data_missing"
    # b. coverage ok, nothing >= high, weak top -> no fault (warn readings become observations)
    assert decide(cfg, [], high_count=0, **kw).status == "no_fault_detected"
    d = decide(cfg, [_h(cfg, 0.3)], high_count=0, **kw)
    assert d.status == "no_fault_detected" and d.reason is None
    # c. coverage ok, something >= high, weak top -> anomaly without a matching signature
    d = decide(cfg, [_h(cfg, 0.3)], high_count=1, **kw)
    assert d.status == "insufficient_evidence" and d.reason == "no_signature_match"
    # d. unchanged
    d = decide(cfg, [_h(cfg, 0.8), _h(cfg, 0.7, ft="device_overload")], high_count=2, **kw)
    assert d.status == "probable" and len(d.co_candidates) == 2
    d = decide(cfg, [_h(cfg, 0.9), _h(cfg, 0.2, ft="device_overload")], high_count=2, **kw)
    assert d.status == "diagnosed" and d.category == "high" and d.confidence == 0.9


def test_category_and_caps(cfg):
    assert category_for(cfg, 0.8, 0.3) == "high"
    assert category_for(cfg, 0.8, 0.2) == "medium"
    assert category_for(cfg, 0.4, 0.9) == "low"
    d = decide(cfg, [_h(cfg, 0.95)], high_count=3, usable_observations=9, failed_agents=["performance_agent"],
               unresolved_c2=False, data_coverage=1)
    assert d.category == "medium" and d.caps
    d = decide(cfg, [_h(cfg, 0.95)], high_count=3, usable_observations=9, failed_agents=[], unresolved_c2=True,
               data_coverage=1)
    assert d.category == "medium"
