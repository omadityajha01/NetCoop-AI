"""Policy checker (G3) + report validator (G4) + certainty lint (G5)."""

from __future__ import annotations

import copy
from datetime import UTC, datetime

from netcoop.policy.checker import check_action
from netcoop.policy.validator import validate_report


def test_r1_class_hours(cfg):
    wed_11_ist = datetime(2026, 10, 28, 5, 30, tzinfo=UTC)
    wed_19_ist = datetime(2026, 10, 28, 13, 30, tzinfo=UTC)
    sat_11_ist = datetime(2026, 10, 31, 5, 30, tzinfo=UTC)
    assert check_action(cfg, "reboot", "HOSTEL_CORE_SW_01", wed_11_ist).rule_id == "R1"
    assert check_action(cfg, "reboot", "HOSTEL_CORE_SW_01", wed_19_ist).allowed
    assert check_action(cfg, "reboot", "HOSTEL_CORE_SW_01", sat_11_ist).allowed
    assert check_action(cfg, "reboot", "HOSTEL_ACC_SW_01", wed_11_ist).allowed  # access switch, not core
    assert check_action(cfg, "inspect", "HOSTEL_CORE_SW_01", wed_11_ist).allowed


def test_r3_r4_r5(cfg):
    at = datetime(2026, 10, 28, 20, 0, tzinfo=UTC)
    assert check_action(cfg, "config_change", "CORE_RTR_01", at).rule_id == "R3"
    exam = datetime(2026, 11, 20, 20, 0, tzinfo=UTC)
    assert check_action(cfg, "move_port", "DEPT_ACC_SW_01", exam).rule_id == "R4"
    day = datetime(2026, 10, 30, 8, 0, tzinfo=UTC)  # 13:30 IST
    assert check_action(cfg, "restart_service", "DNS_01", day).rule_id == "R5"


def test_blocked_action_not_recommended(run):
    rep = run("congestion").report
    assert any(b["rule_id"] == "R1" for b in rep["blocked_actions"])
    blocked_texts = {b["action"] for b in rep["blocked_actions"]}
    assert not blocked_texts & set(rep["recommended_actions"])
    assert "Reboot HOSTEL_CORE_SW_01: blocked by R1 (Class hours)" in [b["reason"] for b in rep["blocked_actions"]]


def test_validator_rejects_unknown_device_and_finding(cfg, run):
    res = run("congestion")
    rep = res.report
    known = {f["finding_id"] for m in res.log.by_type("finding_report", "evidence_response") for f in m.payload["findings"]}
    assert validate_report(rep, cfg, known) == []
    bad = copy.deepcopy(rep)
    bad["affected_devices"].append("ROUTER_FROM_MARS")
    assert any("not in topology" in e for e in validate_report(bad, cfg, known))
    bad = copy.deepcopy(rep)
    bad["supporting_evidence"].append({"metric": "x", "value": 1, "interpretation": "config says so", "finding_id": "playbook.yaml"})
    assert any("unknown finding" in e for e in validate_report(bad, cfg, known))
    bad = copy.deepcopy(rep)
    bad["fault_type"] = "aliens"
    assert any("signature enum" in e for e in validate_report(bad, cfg, known))
    bad = copy.deepcopy(rep)
    bad["limitations"] = []
    assert validate_report(bad, cfg, known)


def test_certainty_language_banned(cfg, run):
    res = run("congestion")
    rep = copy.deepcopy(res.report)
    known = {f["finding_id"] for m in res.log.by_type("finding_report", "evidence_response") for f in m.payload["findings"]}
    for word in ("confirmed", "Definitely", "certainly", "guaranteed"):
        rep["suspected_root_cause"] = f"Congestion {word}"
        assert any("certainty" in e for e in validate_report(rep, cfg, known))


def test_all_demo_reports_pass_lint(cfg, run):
    from netcoop.policy.validator import BANNED

    for name in ("normal", "congestion", "weak_wifi", "interface_fault", "dns_failure", "dhcp_failure", "interop"):
        rep = run(name).report
        assert rep["limitations"], name
        assert not BANNED.search(str(rep)), name
