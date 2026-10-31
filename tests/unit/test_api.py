"""API security (§12): upload limits, id validation, CSV injection guard, structured errors, HITL feedback."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import netcoop.api.main as api
from tests.conftest import cfg_without_external, scenario_bytes


@pytest.fixture
def client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(api, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(api, "load_config", lambda: cfg_without_external(cfg))
    import netcoop.orchestrator.run as runmod
    monkeypatch.setattr(runmod, "load_config", lambda: cfg_without_external(cfg))
    return TestClient(api.app)


def test_upload_and_read(client):
    r = client.post("/incidents?external=false", content=scenario_bytes("congestion"))
    assert r.status_code == 200
    rep = r.json()
    iid = rep["incident_id"]
    assert rep["status"] == "diagnosed"
    assert client.get(f"/incidents/{iid}/report").json()["incident_id"] == iid
    assert client.get(f"/incidents/{iid}/events").json()[0]["seq"] == 1
    assert any(x["incident_id"] == iid for x in client.get("/incidents").json())
    fb = client.post(f"/incidents/{iid}/feedback", json={"action_id": "CONG-1", "decision": "approve", "note": "ok"})
    assert {k: fb.json()[k] for k in ("id", "executed")} == {"id": 1, "executed": False}


def test_path_traversal_and_bad_ids(client):
    for bad in ("..%2F..%2Fetc", "INC-..", "inc-0001", "INC-0001%00"):
        r = client.get(f"/incidents/{bad}/report")
        assert r.status_code in (400, 404)
        assert "Traceback" not in r.text


def test_upload_type_and_size(client):
    assert client.post("/incidents?filename=x.exe", content=b"{}").status_code == 415
    assert client.post("/incidents", content=b"[" + b" " * (10 * 1024 * 1024 + 10) + b"]").status_code == 413


def test_csv_formula_injection_guard():
    assert api._csv_cell("=HYPERLINK(1)") == "'=HYPERLINK(1)"
    assert api._csv_cell("@SUM") == "'@SUM"
    assert api._csv_cell("plain") == "plain"


def test_feedback_validation(client):
    iid = client.post("/incidents?external=false", content=scenario_bytes("normal")).json()["incident_id"]
    r = client.post(f"/incidents/{iid}/feedback", json={"action_id": "x; DROP TABLE", "decision": "approve"})
    assert r.status_code == 422
