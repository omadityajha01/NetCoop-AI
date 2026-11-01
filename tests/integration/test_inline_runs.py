"""Stateless-host mode (NETCOOP_INLINE_RUNS=1, used by the Vercel entry point): diagnose responses also carry the
run's event log so the browser never needs a second request that another instance might not be able to answer."""

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


def test_default_responses_are_unchanged(client):
    r = client.post("/scenarios/congestion/run").json()
    assert set(r) == {"incident_id", "status"}
    rep = client.post("/incidents?filename=c.json", content=scenario_bytes("congestion")).json()
    assert "run_events" not in rep


def test_inline_mode_returns_report_and_full_event_log(client, monkeypatch):
    monkeypatch.setattr(api, "INLINE_RUNS", True)
    r = client.post("/scenarios/congestion/run").json()
    iid = r["incident_id"]
    assert r["report"] == client.get(f"/incidents/{iid}/report").json()
    assert r["run_events"] == client.get(f"/incidents/{iid}/events").json()
    assert [e["seq"] for e in r["run_events"]] == sorted(e["seq"] for e in r["run_events"])

    up = client.post("/incidents?filename=c.json", content=scenario_bytes("congestion")).json()
    events = up.pop("run_events")
    assert up == client.get(f"/incidents/{up['incident_id']}/report").json()
    assert events == client.get(f"/incidents/{up['incident_id']}/events").json()
