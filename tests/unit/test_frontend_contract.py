"""Frontend contract: generated FRONTEND_API.md is fresh, fixtures are real NMP, `serve --ui` keeps the default,
and the mock API matches the real API's shapes (F1-F4)."""

from __future__ import annotations

import json
import subprocess
import sys
import threading
import typing
import urllib.error
import urllib.request

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import netcoop.api.main as api
from netcoop.api import dashboard as dash
from netcoop.protocol.envelope import Message, MessageType
from tests.conftest import ROOT, cfg_without_external

FIX = ROOT / "docs" / "frontend_fixtures"
INDEX = json.loads((FIX / "index.json").read_text(encoding="utf-8"))
sys.path.insert(0, str(ROOT / "tools"))


@pytest.fixture
def client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(api, "RUNS", tmp_path / "runs")
    monkeypatch.setattr(api, "load_config", lambda: cfg_without_external(cfg))
    import netcoop.orchestrator.run as runmod
    monkeypatch.setattr(runmod, "load_config", lambda: cfg_without_external(cfg))
    monkeypatch.delenv(dash.UI_ENV, raising=False)
    return TestClient(api.app)


# ---------- F1: generated doc ----------
def test_frontend_api_doc_is_generated_and_fresh():
    p = subprocess.run([sys.executable, str(ROOT / "tools" / "gen_frontend_api.py"), "--check"], cwd=ROOT,
                       capture_output=True, text=True, encoding="utf-8")
    assert p.returncode == 0, "docs/FRONTEND_API.md is stale: run `python tools/gen_frontend_api.py`" + p.stderr[-800:]


def test_doc_covers_every_route_and_message_type():
    doc = (ROOT / "docs" / "FRONTEND_API.md").read_text(encoding="utf-8")
    for r in api.app.routes:
        if isinstance(r, APIRoute):
            for m in r.methods:
                assert f"### {m} `{r.path}`" in doc
    for mt in typing.get_args(MessageType):
        assert f"### `{mt}`" in doc
    assert dash.CSP in doc


# ---------- F2: fixtures ----------
def test_fixture_set_is_complete():
    names = {f["name"] for f in INDEX}
    assert names >= {"congestion", "weak_wifi_before", "weak_wifi_after", "interop_llm_hint", "normal",
                     "blocked_action_r1", "approved_action_plan", "resumed_run", "malformed_input_error"}
    by = {f["name"]: f for f in INDEX}
    assert by["normal"]["status"] == "no_fault_detected"
    assert by["weak_wifi_before"]["status"] == "insufficient_evidence" and by["weak_wifi_after"]["status"] == "diagnosed"


@pytest.mark.parametrize("name", [f["name"] for f in INDEX])
def test_fixture_is_a_valid_nmp_log(name):
    lines = (FIX / name / "events.jsonl").read_text(encoding="utf-8").splitlines()
    events = [json.loads(x) for x in lines]
    assert [e["seq"] for e in events] == list(range(1, len(events) + 1))
    for e in events:
        Message.model_validate(e)  # every message is valid NMP
    rep = json.loads((FIX / name / "report.json").read_text(encoding="utf-8"))
    assert {e["incident_id"] for e in events} == {rep["incident_id"]}


def test_fixture_contents():
    def types(n):
        return [json.loads(x)["message_type"] for x in (FIX / n / "events.jsonl").read_text(encoding="utf-8").splitlines()]

    def senders(n):
        return {json.loads(x)["sender"] for x in (FIX / n / "events.jsonl").read_text(encoding="utf-8").splitlines()}

    assert "wireless_agent" not in senders("weak_wifi_before") and "wireless_agent" in senders("weak_wifi_after")
    assert "hint" in types("interop_llm_hint")
    assert types("blocked_action_r1")[-1] == "human_decision" and "remediation_plan" not in types("blocked_action_r1")
    assert "remediation_plan" in types("approved_action_plan")
    assert types("malformed_input_error") == ["error"]
    res = json.loads((FIX / "resumed_run" / "api.json").read_text(encoding="utf-8"))[0]["response"]
    assert res["state"] == "resumed" and res["killed_exit_code"] == 137
    seen = {t for f in INDEX for t in types(f["name"])}
    assert seen == set(typing.get_args(MessageType))  # a real example of every message type


# ---------- F3: serve --ui ----------
def test_default_ui_is_identical(client):
    r = client.get("/")
    assert r.content == (dash.STATIC / "dashboard.html").read_bytes()
    assert r.headers["content-security-policy"] == dash.CSP and r.headers["x-frame-options"] == "DENY"
    assert client.get("/dashboard").content == r.content
    assert client.get("/dashboard/dashboard.js").content == (dash.STATIC / "dashboard.js").read_bytes()
    assert client.get("/ui/index.html").status_code == 404


def test_ui_folder(client, monkeypatch):
    v2 = ROOT / "dashboard_v2"
    monkeypatch.setenv(dash.UI_ENV, str(v2))
    r = client.get("/")
    assert r.content == (v2 / "index.html").read_bytes() and r.headers["content-security-policy"] == dash.CSP
    js = client.get("/ui/app.js")
    assert js.status_code == 200 and js.headers["content-type"].startswith("text/javascript")
    assert js.headers["content-security-policy"] == dash.CSP
    for bad in ("/ui/README.md", "/ui/../netcoop/api/main.py", "/ui/%2e%2e/%2e%2e/.env", "/ui/missing.js"):
        assert client.get(bad).status_code == 404, bad
    assert client.get("/dashboard").content == (dash.STATIC / "dashboard.html").read_bytes()  # built-in still there


def test_cli_ui_requires_index(tmp_path):
    from netcoop.cli import main

    assert main(["serve", "--ui", str(tmp_path)]) == 2


# ---------- F4: mock API ----------
@pytest.fixture
def mock():
    import mock_api

    srv = mock_api.build_server(port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"

    def call(method, path, body=None):
        req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Content-Type": "application/json"} if body is not None else {})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, dict(r.headers), r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode("utf-8")

    yield call
    srv.shutdown()
    srv.server_close()


def test_mock_matches_real_shapes(mock, client):
    import mock_api

    assert mock_api.CSP == dash.CSP and mock_api.SECURITY_HEADERS == dash.SECURITY_HEADERS
    # run + stream framing
    s, _, body = mock("POST", "/scenarios/congestion/run")
    real = client.post("/scenarios/congestion/run?external=false").json()
    run = json.loads(body)
    assert s == 200 and set(run) == set(real) and run["status"] == real["status"]
    s, h, stream = mock("GET", f"/incidents/{run['incident_id']}/stream?delay_ms=0")
    rs = client.get(f"/incidents/{real['incident_id']}/stream").text
    frames = [f for f in stream.strip().split("\n\n")]
    real_frames = [f for f in rs.strip().split("\n\n")]
    assert len(frames) == len(real_frames) and frames[-1] == real_frames[-1]
    assert [f.split("\n")[:2] for f in frames] == [f.split("\n")[:2] for f in real_frames]  # id/event lines identical
    assert h["Content-Type"].startswith("text/event-stream")
    # report, events, list
    assert json.loads(mock("GET", f"/incidents/{run['incident_id']}/report")[2]).keys() == \
        client.get(f"/incidents/{real['incident_id']}/report").json().keys()
    rows = json.loads(mock("GET", "/incidents?limit=5")[2])
    assert set(rows[0]) == set(client.get("/incidents").json()[0])


def test_mock_feedback_and_errors_match_real(mock, client):
    _, _, body = mock("POST", "/scenarios/congestion/run")
    iid = json.loads(body)["incident_id"]
    rid = client.post("/scenarios/congestion/run?external=false").json()["incident_id"]
    for action in ("CONG-1", "CONG-4"):
        m = json.loads(mock("POST", f"/incidents/{iid}/feedback", {"action_id": action, "decision": "approve"})[2])
        r = client.post(f"/incidents/{rid}/feedback", json={"action_id": action, "decision": "approve"}).json()
        assert set(m) == set(r) and (m["plan"] is None) == (r["plan"] is None)
        assert m["policy"]["rule_id"] == r["policy"]["rule_id"]
        if r["plan"]:
            assert m["plan"]["label"] == r["plan"]["label"] and m["plan"]["steps"] == r["plan"]["steps"]
    for method, path, body in [("GET", "/incidents/inc-bad/report", None), ("GET", "/incidents/INC-ZZZZ0000/report", None),
                               ("POST", "/scenarios/nope/run", None),
                               ("POST", f"/incidents/{iid}/feedback", {"action_id": "DNS-9", "decision": "approve"}),
                               ("GET", "/no/such/route", None)]:
        ms, _, mb = mock(method, path, body)
        p = path.replace(iid, rid)
        rr = client.request(method, p, json=body)
        assert ms == rr.status_code and json.loads(mb) == rr.json(), path
    ms, _, mb = mock("POST", f"/incidents/{iid}/feedback", {"action_id": "x", "decision": "maybe"})
    rr = client.post(f"/incidents/{rid}/feedback", json={"action_id": "x", "decision": "maybe"})
    assert ms == rr.status_code == 422 and [e["loc"] for e in json.loads(mb)["detail"]] == [e["loc"] for e in rr.json()["detail"]]


def test_mock_agent_join_switches_weak_wifi(mock):
    assert json.loads(mock("POST", "/scenarios/weak_wifi/run")[2])["status"] == "insufficient_evidence"
    assert json.loads(mock("GET", "/agents")[2])["external"]["wireless_agent"] == "unreachable"
    mock("POST", "/mock/agent/join")
    assert json.loads(mock("GET", "/agents")[2])["external"]["wireless_agent"] == "joined"
    assert json.loads(mock("POST", "/scenarios/weak_wifi/run")[2])["status"] == "diagnosed"
