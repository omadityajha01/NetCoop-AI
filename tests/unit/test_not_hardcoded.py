"""'Not hard-coded': generated incidents, uploads and edits go through the real pipeline (asserted via the API)."""

from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

import netcoop.api.main as api
from tests.conftest import cfg_without_external, scenario_json


@pytest.fixture
def client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(api, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(api, "load_config", lambda: cfg_without_external(cfg))
    import netcoop.orchestrator.run as runmod
    monkeypatch.setattr(runmod, "load_config", lambda: cfg_without_external(cfg))
    return TestClient(api.app)


def _hash(client, iid):
    return next(e for e in client.get(f"/incidents/{iid}/events").json()
                if e["message_type"] == "normalization_summary")["payload"]["input_sha256"]


def test_random_seed_differs_across_runs(client):
    seeds = {client.get("/generate").json()["seed"] for _ in range(4)}
    assert len(seeds) > 1  # SystemRandom: 4 draws from 1e6 values are never all equal in practice


def test_explicit_seed_is_reproducible_and_runs_the_real_pipeline(client):
    a = client.get("/generate?fault=hardware_failure&seed=4242").json()
    b = client.get("/generate?fault=hardware_failure&seed=4242").json()
    assert a["seed"] == 4242 and a["fault"] == "hardware_failure"
    assert {k: v for k, v in a["record"].items() if k != "timestamp"} == \
        {k: v for k, v in b["record"].items() if k != "timestamp"}  # the generator stamps utcnow(); data is seeded
    rep = client.post("/incidents?external=false&filename=generated.json", content=json.dumps(a["record"]).encode()).json()
    assert rep["status"] == "diagnosed" and rep["fault_type"] == "hardware_failure"
    assert client.get(f"/incidents/{rep['incident_id']}/input").json()["json"] == a["record"]


@pytest.mark.parametrize("query, code", [("fault=nope", 400), ("seed=abc", 400), ("seed=-1", 400), ("seed=1234567890", 400)])
def test_generate_rejects_bad_parameters(client, query, code):
    assert client.get(f"/generate?{query}").status_code == code


def test_edited_value_changes_the_input_hash(client):
    b = scenario_json("congestion")
    r1 = client.post("/incidents?external=false", content=json.dumps(b).encode()).json()
    e = copy.deepcopy(b)
    e["records"][0]["metrics"]["latency_ms"] = e["records"][0]["metrics"]["latency_ms"] + 1
    r2 = client.post("/incidents?external=false", content=json.dumps(e).encode()).json()
    assert _hash(client, r1["incident_id"]) != _hash(client, r2["incident_id"])


def test_editing_interface_errors_high_on_congestion_flips_to_interface_fault(client):
    b = scenario_json("congestion")
    before = client.post("/incidents?external=false", content=json.dumps(b).encode()).json()
    assert (before["status"], before["fault_type"]) == ("diagnosed", "congestion")
    for r in b["records"]:
        if r.get("device_id") == "HOSTEL_CORE_SW_01" and "interface_errors" in (r.get("metrics") or {}):
            r["metrics"]["interface_errors"] = 200
    after = client.post("/incidents?external=false&filename=edited.json", content=json.dumps(b).encode()).json()
    assert after["fault_type"] == "interface_fault" and after["status"] in ("diagnosed", "probable")
    assert after["confidence"] < before["confidence"]


def test_upload_goes_through_normalizer_validation(client):
    bad = client.post("/incidents?external=false&filename=mine.json", content=b'{"records": [ not json').json()
    assert bad["status"] == "failed"
    events = client.get(f"/incidents/{bad['incident_id']}/events").json()
    assert [e["message_type"] for e in events] == ["error"] and events[0]["payload"]["code"] == "MALFORMED"
    assert client.post("/incidents?filename=x.exe", content=b"{}").status_code == 415
    assert client.post("/incidents?filename=big.json", content=b" " * (10 * 1024 * 1024 + 1)).status_code == 413
    ok = client.post("/incidents?external=false&filename=mine.json", content=json.dumps(scenario_json("dns_failure")).encode())
    assert ok.json()["fault_type"] == "dns_failure"


def test_input_endpoints(client):
    raw = client.get("/scenarios/congestion/input").json()
    assert raw == scenario_json("congestion")
    assert client.get("/scenarios/nope/input").status_code == 404
    assert client.get("/incidents/inc-bad/input").status_code == 400
