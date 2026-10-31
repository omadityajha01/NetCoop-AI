"""One test per PS scenario: status + root cause + key evidence."""

from __future__ import annotations

from tests.conftest import cfg_with_external_url


def evidence_metrics(rep):
    return {e["metric"] for e in rep["supporting_evidence"]}


def test_normal(run):
    rep = run("normal").report
    assert rep["status"] == "no_fault_detected"
    assert rep["supporting_evidence"] == [] and rep["affected_devices"] == []
    assert rep["recommended_actions"]


def test_congestion(run):
    rep = run("congestion").report
    assert rep["status"] == "diagnosed" and rep["fault_type"] == "congestion"
    assert "congestion" in rep["suspected_root_cause"] and "L_HOSTEL_UPLINK" in rep["suspected_root_cause"]
    assert {"link_utilization_pct", "queue_drops_count", "latency_ms"} <= evidence_metrics(rep)
    assert "HOSTEL_CORE_SW_01" in rep["affected_devices"]
    assert set(rep["evidence_sources"]) >= {"performance_agent", "infrastructure_agent"}  # multiple agents, one diagnosis
    assert any(p["outcome"] == "hit" for p in rep["predictions"])


def test_weak_wifi_without_external_agent_is_insufficient(run):
    rep = run("weak_wifi").report
    assert rep["status"] == "insufficient_evidence"
    assert {"rssi_dbm@AP_H3", "snr_db@AP_H3", "retransmission_pct@AP_H3"} <= set(rep["missing_signals"])
    assert rep["confidence_category"] == "low"


def test_weak_wifi_with_external_agent_is_diagnosed(run, cfg, wireless_agent):
    res = run("weak_wifi", config=cfg_with_external_url(cfg, wireless_agent), external=True)
    rep = res.report
    assert res.external_status == {"wireless_agent": "joined"}
    assert rep["status"] == "diagnosed" and rep["fault_type"] == "weak_wifi"
    assert rep["affected_devices"] == ["AP_H3"]
    assert {"rssi_dbm", "snr_db", "retransmission_pct"} <= evidence_metrics(rep)
    assert "wireless_agent" in rep["evidence_sources"]
    # the dialect mismatch was translated, not fixed at the source
    wf = [f for m in res.log.by_type("finding_report") if m.sender == "wireless_agent" for f in m.payload["findings"]]
    steps = {t["step"] for f in wf for t in f["transforms"]}
    assert {"version", "alias", "entity"} <= steps


def test_interface_fault(run):
    rep = run("interface_fault").report
    assert rep["status"] == "diagnosed" and rep["fault_type"] == "interface_fault"
    assert {"interface_errors_count", "crc_errors_count", "link_flaps_count"} <= evidence_metrics(rep)
    assert any(b["rule_id"] == "R4" for b in rep["blocked_actions"])  # exam period


def test_dns_failure(run):
    rep = run("dns_failure").report
    assert rep["status"] == "diagnosed" and rep["fault_type"] == "dns_failure"
    assert rep["affected_devices"] == ["DNS_01"]
    assert "dns_failure_pct" in evidence_metrics(rep)
    assert all(p["outcome"] == "hit" for p in rep["predictions"])  # L3 latency/loss normal, as predicted


def test_dhcp_failure(run):
    rep = run("dhcp_failure").report
    assert rep["status"] == "diagnosed" and rep["fault_type"] == "dhcp_failure"
    assert "dhcp_failure_pct" in evidence_metrics(rep)


def test_interoperability_failure(run):
    res = run("interop")
    rep = res.report
    assert rep["status"] in ("diagnosed", "probable")
    assert rep["fault_type"] == "device_overload"
    assert "DEPT_CORE_SW_01" in rep["affected_devices"]
    ns = rep["normalization_summary"]
    assert ns["records_in"] == ns["records_used"] + ns["records_quarantined"]
    assert ns["renamed"] > 0 and ns["unit_converted"] > 0 and ns["unit_inferred"] > 0 and ns["version_upcast"] == 1
    assert any(c["type"] == "C1" for c in rep["conflicts"])
    assert any(c["type"] == "C2" for c in rep["conflicts"])
    text = " ".join(rep["limitations"])
    assert "quarantined" in text and "converted" in text
    # injected complaint text has no effect (LLM off; complaint is never evidence)
    assert "dns" not in rep["suspected_root_cause"].lower()
