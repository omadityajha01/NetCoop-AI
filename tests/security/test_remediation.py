"""S1 remediation dry-run: human-approved, policy-checked, rendered as text, never executed."""

from __future__ import annotations

import ast
import json
import re

import pytest
from fastapi.testclient import TestClient

import netcoop.api.main as api
from netcoop.orchestrator.replay import replay
from netcoop.protocol.messages import SIMULATED_LABEL
from netcoop.remediation import plan_for, render
from tests.conftest import ROOT, cfg_without_external


@pytest.fixture
def client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(api, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(api, "load_config", lambda: cfg_without_external(cfg))
    import netcoop.orchestrator.run as runmod
    monkeypatch.setattr(runmod, "load_config", lambda: cfg_without_external(cfg))
    return TestClient(api.app)


def _run(client) -> str:
    return client.post("/scenarios/congestion/run?external=false").json()["incident_id"]


def _types(client, iid):
    return [e["message_type"] for e in client.get(f"/incidents/{iid}/events").json()]


def test_plan_only_after_approve_and_report_unchanged(client, tmp_path):
    iid = _run(client)
    before = client.get(f"/incidents/{iid}/report").json()
    assert "remediation_plan" not in _types(client, iid)
    r = client.post(f"/incidents/{iid}/feedback", json={"action_id": "CONG-1", "decision": "reject"}).json()
    assert r["plan"] is None and "remediation_plan" not in _types(client, iid)
    r = client.post(f"/incidents/{iid}/feedback", json={"action_id": "CONG-1", "decision": "approve"}).json()
    events = client.get(f"/incidents/{iid}/events").json()
    plan = events[-1]
    assert plan["message_type"] == "remediation_plan" and plan["seq"] == r["plan_seq"] == r["event_seq"] + 1
    p = plan["payload"]
    assert p["label"] == SIMULATED_LABEL == "SIMULATED – NOT EXECUTED" and p["executed"] is False
    assert p["policy"]["allowed"] is True and p["steps"] and p["rollback"] and p["target"] == "HOSTEL_CORE_SW_01"
    assert p["human_decision_seq"] == r["event_seq"] and plan["in_reply_to"] == events[-2]["message_id"]
    assert client.get(f"/incidents/{iid}/report").json() == before
    assert replay(iid, tmp_path / "runs").report_identical


def test_blocked_action_gets_rule_id_and_no_plan(client):
    iid = _run(client)
    r = client.post(f"/incidents/{iid}/feedback", json={"action_id": "CONG-4", "decision": "approve"}).json()
    assert r["plan"] is None and r["plan_seq"] is None
    assert r["policy"]["allowed"] is False and r["policy"]["rule_id"] == "R1"
    types = _types(client, iid)
    assert types[-1] == "human_decision" and "remediation_plan" not in types


def test_render_is_single_pass_and_literal():
    evil = "{segment}<script>alert(1)</script>; rm -rf / && curl http://x"
    out = render("Reload {target} in {segment}", {"target": evil, "segment": "hostel"})
    assert out == f"Reload {evil} in hostel"  # the injected {segment} is NOT expanded again, nothing interpreted


def test_injected_target_gets_no_plan(cfg, run):
    res = run("congestion")
    rep = json.loads(json.dumps(res.report))
    events = [m.to_json_dict() for m in res.log.all()]
    for evil in ("HOSTEL_CORE_SW_01; reboot all", "<img src=x onerror=alert(1)>", "UNKNOWN_SW_99"):
        for a in rep["action_details"]:
            a["target"] = evil
        plan, policy = plan_for(cfg, rep, events, "CONG-1")
        assert plan is None and policy["allowed"] is False


def test_every_action_verb_has_a_template_and_no_success_wording(cfg):
    verbs = {a["action"] for k, v in cfg.playbook.items() if not k.startswith("_dry") for a in v.get("actions", ())}
    tpl = cfg.playbook["_dry_run"]
    assert verbs <= set(tpl)
    text = json.dumps({k: dict(v) for k, v in tpl.items()}, default=list).lower()
    for banned in ("verified", "fixed", "resolved", "confirmed", "guaranteed", "definitely"):
        assert banned not in text


def test_no_fix_verified_wording_anywhere():
    files = [*ROOT.glob("netcoop/**/*.py"), *ROOT.glob("netcoop/api/static/*"), *ROOT.glob("config/*.yaml"),
             *ROOT.glob("docs/*.md"), ROOT / "README.md"]
    hits = [str(f) for f in files if re.search(r"fix(es|ed)?\s+verified", f.read_text(encoding="utf-8"), re.I)]
    assert not hits


def test_remediation_code_has_no_execution_paths():
    for mod in ("netcoop/remediation.py", "netcoop/hitl.py"):
        tree = ast.parse((ROOT / mod).read_text(encoding="utf-8"))
        names = {n.names[0].name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import)}
        names |= {(n.module or "").split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        assert not names & {"subprocess", "socket", "urllib", "http", "requests", "httpx", "paramiko", "os"}, mod
