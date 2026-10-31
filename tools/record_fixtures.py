"""Record frontend fixtures from the REAL backend (F2): `python tools/record_fixtures.py [--llm]`.

Drives the actual FastAPI app in-process (same code as `netcoop serve`) against a temporary runs/ directory and
writes, per fixture, under docs/frontend_fixtures/<name>/:
  events.jsonl  the run's event log, verbatim (this is exactly what /incidents/{id}/events and /stream serve)
  report.json   the final report, verbatim
  api.json      every HTTP exchange of the flow: method, path, status, request body, response body
plus docs/frontend_fixtures/index.json (what each fixture shows) and api_examples.json (the other endpoints, and
real error responses).

External agent: weak_wifi_before needs NO agent on 127.0.0.1:8765. The script then starts the Node wireless agent
itself for weak_wifi_after and stops it (only that PID). `--llm` records interop with NETCOOP_LLM=local
(Ollama + llama3.2:3b must be running). Without it, interop is recorded with the LLM off and the fixture says so.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "docs" / "frontend_fixtures"
AGENT_CARD = "http://127.0.0.1:8765/.well-known/agent-card.json"


def agent_up() -> bool:
    try:
        urllib.request.urlopen(AGENT_CARD, timeout=1)
        return True
    except OSError:
        return False


class Recorder:
    def __init__(self, client: Any, runs: Path):
        self.c, self.runs = client, runs
        self.exchanges: list[dict[str, Any]] = []

    def call(self, method: str, path: str, body: Any = None, raw: bytes | None = None) -> Any:
        if raw is not None:
            r = self.c.request(method, path, content=raw)
        else:
            r = self.c.request(method, path, json=body)
        ctype = r.headers.get("content-type", "")
        resp = r.json() if ctype.startswith("application/json") else r.text
        self.exchanges.append({"method": method, "path": path, "request": body if raw is None else "<incident bundle>",
                               "status": r.status_code, "response": resp})
        return resp

    def save(self, name: str, incident_id: str, about: dict[str, Any]) -> dict[str, Any]:
        d = OUT / name
        d.mkdir(parents=True, exist_ok=True)
        src = self.runs / incident_id
        (d / "events.jsonl").write_bytes((src / "events.jsonl").read_bytes().replace(b"\r\n", b"\n"))
        (d / "report.json").write_bytes((src / "report.json").read_bytes().replace(b"\r\n", b"\n"))
        (d / "api.json").write_text(json.dumps(self.exchanges, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        rep = json.loads((src / "report.json").read_text(encoding="utf-8"))
        n = sum(1 for x in (src / "events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())
        self.exchanges = []
        return {"name": name, "incident_id": incident_id, "status": rep["status"], "fault_type": rep.get("fault_type"),
                "confidence": rep["confidence"], "messages": n, **about}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--llm", action="store_true", help="record interop with NETCOOP_LLM=local (Ollama must run)")
    a = ap.parse_args()
    if agent_up():
        print("error: something is already serving 127.0.0.1:8765; stop it so weak_wifi_before records with no agent",
              file=sys.stderr)
        return 2
    os.environ.pop("NETCOOP_LLM", None)

    from fastapi.testclient import TestClient

    import netcoop.api.main as api

    runs = Path(tempfile.mkdtemp(prefix="netcoop-fixtures-"))
    api.RUNS = runs
    rec = Recorder(TestClient(api.app), runs)
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    index: list[dict[str, Any]] = []
    examples: dict[str, Any] = {}

    def run(scenario: str) -> str:
        return rec.call("POST", f"/scenarios/{scenario}/run?external=true")["incident_id"]

    def scenario_fixture(name: str, scenario: str, about: str) -> str:
        iid = run(scenario)
        rec.call("GET", f"/incidents/{iid}/report")
        index.append(rec.save(name, iid, {"scenario": scenario, "about": about}))
        return iid

    examples["GET /scenarios"] = rec.call("GET", "/scenarios")
    examples["GET /topology"] = rec.call("GET", "/topology")
    examples["GET /agents (wireless agent not running)"] = rec.call("GET", "/agents")
    rec.exchanges = []

    cong = scenario_fixture("congestion", "congestion", "Link congestion on L_HOSTEL_UPLINK: 3 predictions "
                            "(2 hit, 1 miss), one action blocked by R1 in the report")
    scenario_fixture("weak_wifi_before", "weak_wifi", "Wi-Fi complaint, external wireless_agent NOT running: "
                     "insufficient_evidence with missing_signals rssi_dbm/snr_db/retransmission_pct@AP_H3")
    scenario_fixture("normal", "normal", "Healthy network: no_fault_detected")
    for extra in ("dns_failure", "dhcp_failure", "interface_fault"):
        scenario_fixture(extra, extra, f"{extra} scenario (extra, so the mock can serve every scenario)")

    # weak_wifi after the Node agent joins (A2A)
    node = shutil.which("node")
    agent = subprocess.Popen([node, str(ROOT / "external_agents" / "wireless_agent" / "server.js")],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(40):
            if agent_up():
                break
            time.sleep(0.25)
        examples["GET /agents (wireless agent joined)"] = rec.call("GET", "/agents")
        rec.exchanges = []
        scenario_fixture("weak_wifi_after", "weak_wifi", "Same incident after the Node wireless_agent (dialect 0.9) "
                         "joined via A2A: diagnosed weak_wifi on AP_H3; its findings carry version/alias/unit/entity "
                         "transforms")
    finally:
        agent.terminate()
        agent.wait(timeout=10)

    # interop (chaos input + injected complaint), optionally with the LLM triage hint
    if a.llm:
        os.environ["NETCOOP_LLM"] = "local"
        os.environ.setdefault("NETCOOP_LOCAL_MODEL", "llama3.2:3b")
    try:
        scenario_fixture("interop_llm_hint" if a.llm else "interop", "interop",
                         ("Messy multi-dialect input with an injected complaint; NETCOOP_LLM=local llama3.2:3b: "
                          "triage_agent sends an advisory `hint` (dns_failure); the diagnosis is unchanged "
                          "(device_overload, deterministic_scoring)") if a.llm else
                         "Messy multi-dialect input; LLM off (re-record with --llm for the hint)")
    finally:
        os.environ.pop("NETCOOP_LLM", None)

    # blocked action (R1): approve the reboot
    iid = run("congestion")
    rec.call("POST", f"/incidents/{iid}/feedback", {"action_id": "CONG-4", "decision": "approve"})
    rec.call("GET", f"/incidents/{iid}/events")
    index.append(rec.save("blocked_action_r1", iid, {"scenario": "congestion", "about": "Approve CONG-4 (reboot "
                          "HOSTEL_CORE_SW_01): human_decision is logged, the policy check blocks it by R1 (Class "
                          "hours), no remediation_plan"}))

    # approved action -> remediation_plan, then a reject
    iid = run("congestion")
    rec.call("POST", f"/incidents/{iid}/feedback", {"action_id": "CONG-1", "decision": "approve", "note": "go"})
    rec.call("POST", f"/incidents/{iid}/feedback", {"action_id": "CONG-2", "decision": "reject"})
    rec.call("GET", f"/incidents/{iid}/events")
    index.append(rec.save("approved_action_plan", iid, {"scenario": "congestion", "about": "Approve CONG-1: "
                          "human_decision + remediation_plan 'SIMULATED – NOT EXECUTED' (steps + rollback); then reject "
                          "CONG-2: human_decision only. The report is unchanged"}))

    # resumed run: hard kill right after round 0, then `netcoop resume`
    rdir = Path(tempfile.mkdtemp(prefix="netcoop-resume-"))
    rid = "INC-RESUMED1"
    kill = rdir / "kill.py"
    kill.write_text("import os, sys\nfrom pathlib import Path\nsys.path.insert(0, sys.argv[4])\n"
                    "import netcoop.agents.correlation as c\nfrom netcoop.orchestrator.run import RunOptions, run_incident\n"
                    "c.CorrelationAgent.handle = lambda self, m, ctx: os._exit(137)\n"
                    "run_incident(Path(sys.argv[1]).read_bytes(), opts=RunOptions(incident_id=sys.argv[3], "
                    "runs_dir=Path(sys.argv[2]), external=False, filename='incident.json'))\n", encoding="utf-8")
    data = ROOT / "data" / "scenarios" / "congestion" / "incident.json"
    k = subprocess.run([sys.executable, str(kill), str(data), str(rdir), rid, str(ROOT)], capture_output=True, timeout=120)
    killed = sum(1 for x in (rdir / rid / "events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip())
    from netcoop.orchestrator.resume import resume

    r = resume(rid, rdir)
    shutil.copytree(rdir / rid, runs / rid)
    rec.exchanges = [{"method": "CLI", "path": f"netcoop resume {rid}", "request": None, "status": 0,
                      "response": {"state": r.state, "kept": r.kept, "appended": r.appended, "detail": r.detail,
                                   "killed_exit_code": k.returncode, "messages_before_resume": killed}}]
    index.append(rec.save("resumed_run", rid, {"scenario": "congestion", "about": f"Process killed (exit {k.returncode}) "
                          f"at the first correlation task after round 0 with {killed} messages logged; `netcoop resume` "
                          f"kept them and appended {r.appended}. report.json is byte-identical to an uninterrupted run"}))

    # malformed upload: the normalizer emits an NMP `error`; the run still returns a report with status `failed`
    bad = rec.call("POST", "/incidents?external=false&filename=broken.json", raw=b'{"records": [ this is not json')
    index.append(rec.save("malformed_input_error", bad["incident_id"], {"scenario": None, "about": "Upload of invalid "
                          "JSON: an `error` message (code MALFORMED) from the normalizer; HTTP 200 with a report whose "
                          "status is `failed`"}))

    examples["GET /incidents?limit=50"] = rec.call("GET", "/incidents?limit=50")
    examples["GET /incidents/{id}/report.csv"] = rec.call("GET", f"/incidents/{cong}/report.csv")
    examples["errors"] = {
        "400 bad incident_id": rec.call("GET", "/incidents/inc-bad/report"),
        "404 unknown incident": rec.call("GET", "/incidents/INC-ZZZZ0000/report"),
        "404 unknown scenario": rec.call("POST", "/scenarios/nope/run"),
        "404 unknown action": rec.call("POST", f"/incidents/{cong}/feedback", {"action_id": "DNS-9", "decision": "approve"}),
        "422 validation": rec.call("POST", f"/incidents/{cong}/feedback", {"action_id": "x", "decision": "maybe"}),
        "415 upload type": rec.call("POST", "/incidents?filename=a.exe", raw=b"{}"),
        "200 with status failed (malformed upload)": {k: v for k, v in rec.call("POST", "/incidents?external=false",
                                                                                 raw=b"not json").items()
                                                       if k in ("incident_id", "status", "suspected_root_cause",
                                                                "limitations")},
    }
    (OUT / "api_examples.json").write_text(json.dumps(examples, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (OUT / "index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    for f in index:
        print(f"{f['name']:<22} {f['incident_id']:<14} {f['status']:<22} {f['messages']:>3} msgs  {f['about'][:60]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
