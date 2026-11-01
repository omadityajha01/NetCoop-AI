"""Mock NetCoop API (F4): serves the recorded fixtures on the same endpoints as `netcoop serve`. No backend needed.

    python tools/mock_api.py                      # http://127.0.0.1:8000/  (bundled UI; classic dashboard at /dashboard)
    python tools/mock_api.py --ui dashboard_v2    # your UI folder: index.html at /, files at /ui/<path>
    python tools/mock_api.py --port 8001 --agent joined

Python standard library only (PyYAML is used if installed, for the dry-run templates of actions not in the fixtures).
Data: docs/frontend_fixtures/ (record again with tools/record_fixtures.py). The contract is docs/FRONTEND_API.md.

Behaviour (same paths, bodies, status codes, error shapes, security headers and SSE framing as the real server):
* POST /scenarios/{name}/run returns a NEW incident (INC-MOCK0001, ...) whose events and report are a copy of the
  recorded fixture for that scenario, with incident_id rewritten. weak_wifi uses `weak_wifi_before` until the
  wireless agent has "joined" (`--agent joined`, or POST /mock/agent/join), then `weak_wifi_after`. interop uses
  `interop_llm_hint`.
* GET /incidents/{id}/stream?delay_ms=N replays the event log in seq order with N ms between messages (0–2000, like
  the server). Add &timing=recorded to replay with the gaps between the recorded created_at timestamps (each capped
  at 2 s).
* POST /incidents/{id}/feedback appends a human_decision event. On approve: an action blocked in the report returns
  the policy result (rule id) and no plan. An allowed action appends a remediation_plan ("SIMULATED – NOT
  EXECUTED"), the recorded plan when one exists, otherwise rendered from config/playbook.yaml `_dry_run`.
* Mock-only controls (not in the real API): POST /mock/agent/join, POST /mock/agent/leave, GET /mock/fixtures.
"""

from __future__ import annotations

import argparse
import copy
import csv
import io
import json
import re
import threading
import time
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
# Repo layout (tools/mock_api.py) or the standalone handoff layout (mock_api.py next to frontend_fixtures/).
FIX = HERE / "frontend_fixtures" if (HERE / "frontend_fixtures").is_dir() else ROOT / "docs" / "frontend_fixtures"
STATIC = ROOT / "netcoop" / "api" / "static"  # classic dashboard (/dashboard); absent in the handoff zip
DEFAULT_UI = ROOT / "netcoop" / "api" / "ui"  # default UI like `netcoop serve`; absent in the handoff zip (use --ui)
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                    "X-Frame-Options": "DENY"}
CORS_ORIGINS = ("http://localhost:5173", "http://127.0.0.1:5173")
INCIDENT_RE = re.compile(r"^INC-[0-9A-Z]{4,12}$")
ACTION_RE = re.compile(r"^[A-Z]{2,6}-[0-9]{1,3}$")
SCENARIO_FIXTURE = {"congestion": "congestion", "normal": "normal", "dns_failure": "dns_failure",
                    "dhcp_failure": "dhcp_failure", "interface_fault": "interface_fault", "interop": "interop_llm_hint"}
UI_TYPES = {".html": "text/html", ".js": "text/javascript", ".mjs": "text/javascript", ".css": "text/css",
            ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png", ".jpg": "image/jpeg",
            ".ico": "image/x-icon", ".woff2": "font/woff2", ".txt": "text/plain"}
SIMULATED = "SIMULATED – NOT EXECUTED"


class ApiError(Exception):
    def __init__(self, status: int, code: str, detail: str):
        self.status, self.code, self.detail = status, code, detail


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


class MockState:
    def __init__(self, agent_joined: bool):
        self.lock = threading.Lock()
        self.agent_joined = agent_joined
        self.fixtures = {d.name: self._load(d) for d in sorted(FIX.iterdir()) if (d / "events.jsonl").is_file()}
        self.examples = json.loads((FIX / "api_examples.json").read_text(encoding="utf-8"))
        self.incidents: dict[str, dict[str, Any]] = {}
        for name, f in self.fixtures.items():  # every recorded run is a "past run"
            self.incidents[f["report"]["incident_id"]] = {"events": copy.deepcopy(f["events"]),
                                                         "report": copy.deepcopy(f["report"]), "fixture": name}
        self.counter = 0
        self.feedback_id = 100
        self.recorded_plans = {e["payload"]["action_id"]: e["payload"] for f in self.fixtures.values()
                               for e in f["events"] if e["message_type"] == "remediation_plan"}
        self.dry_run = self._load_dry_run()

    @staticmethod
    def _load(d: Path) -> dict[str, Any]:
        return {"events": [json.loads(x) for x in (d / "events.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()],
                "report": json.loads((d / "report.json").read_text(encoding="utf-8"))}

    @staticmethod
    def _load_dry_run() -> dict[str, Any]:
        standalone = HERE / "dry_run_templates.json"  # shipped in the handoff zip (copy of playbook.yaml _dry_run)
        if standalone.is_file():
            return json.loads(standalone.read_text(encoding="utf-8"))
        try:
            import yaml  # optional

            return (yaml.safe_load((ROOT / "config" / "playbook.yaml").read_text(encoding="utf-8")) or {}).get("_dry_run", {})
        except Exception:  # noqa: BLE001 - optional nicety
            return {}

    # ----- runs -----
    def new_run(self, fixture: str) -> dict[str, Any]:
        f = self.fixtures[fixture]
        with self.lock:
            self.counter += 1
            iid = f"INC-MOCK{self.counter:04d}"
            base = [e for e in f["events"] if e["message_type"] not in ("human_decision", "remediation_plan")]
            events = json.loads(json.dumps(base).replace(f["report"]["incident_id"], iid))
            report = json.loads(json.dumps(f["report"]).replace(f["report"]["incident_id"], iid))
            self.incidents[iid] = {"events": events, "report": report, "fixture": fixture}
        return {"incident_id": iid, "status": report["status"]}

    def get(self, iid: str) -> dict[str, Any]:
        if not INCIDENT_RE.fullmatch(iid):
            raise ApiError(400, "BAD_INCIDENT_ID", "incident_id must match ^INC-[0-9A-Z]{4,12}$")
        if iid not in self.incidents:
            raise ApiError(404, "NOT_FOUND", "unknown incident")
        return self.incidents[iid]

    # ----- HITL -----
    def feedback(self, iid: str, body: Any) -> dict[str, Any]:
        errs = []  # body validation first (422), like FastAPI; then the incident id (400/404)
        if not isinstance(body, dict) or not isinstance(body.get("action_id"), str) or not ACTION_RE.fullmatch(body["action_id"]):
            errs.append({"type": "string_pattern_mismatch", "loc": ["body", "action_id"],
                         "msg": "String should match pattern '^[A-Z]{2,6}-[0-9]{1,3}$'"})
        if not isinstance(body, dict) or body.get("decision") not in ("approve", "reject"):
            errs.append({"type": "string_pattern_mismatch", "loc": ["body", "decision"],
                         "msg": "String should match pattern '^(approve|reject)$'"})
        if errs:
            raise ApiError(422, "", json.dumps(errs))
        inc = self.get(iid)
        rep, aid, decision = inc["report"], body["action_id"], body["decision"]
        details = {a["id"]: a for a in rep.get("action_details", [])}
        blocked = {b["action_id"]: b for b in rep.get("blocked_actions", [])}
        if aid not in details and aid not in blocked:
            raise ApiError(404, "UNKNOWN_ACTION", "action_id is not an action of this incident")
        with self.lock:
            self.feedback_id += 1
            fid = self.feedback_id
            ev = inc["events"]
            seq = ev[-1]["seq"] + 1
            hd = self._msg(iid, "human_decision", "human_operator", "orchestrator", seq, None,
                           {"action_id": aid, "decision": decision, "feedback_id": fid, "executed": False,
                            "note_stored": bool(body.get("note"))})
            ev.append(hd)
            out = {"id": fid, "executed": False, "event_seq": seq, "message_id": hd["message_id"], "policy": None,
                   "plan_seq": None, "plan": None}
            if decision != "approve":
                return out
            at = next((e["payload"]["incident_time"] for e in ev if e["message_type"] == "normalization_summary"), None)
            checked_at = at.replace("Z", "+00:00") if at else None
            d = details.get(aid, {})
            if aid in blocked or d.get("allowed") is False:
                rule = d.get("rule_id") or blocked.get(aid, {}).get("rule_id")
                reason = blocked.get(aid, {}).get("reason", "")
                reason = reason.split("(")[-1].rstrip(")") if "(" in reason else reason
                out["policy"] = {"allowed": False, "rule_id": rule, "reason": reason, "checked_at": checked_at}
                return out
            policy = {"allowed": True, "rule_id": None, "reason": None, "checked_at": checked_at}
            plan = self._plan(aid, d, policy)
            pm = self._msg(iid, "remediation_plan", "remediation_planner", "human_operator", seq + 1, hd["message_id"],
                           {**plan, "human_decision_seq": seq})
            ev.append(pm)
            out.update(policy=policy, plan_seq=seq + 1, plan=pm["payload"])
            return out

    def _plan(self, aid: str, d: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
        rec = self.recorded_plans.get(aid)
        if rec and rec.get("target") == d.get("target"):
            return {k: v for k, v in rec.items() if k not in ("human_decision_seq",)} | {"policy": policy}
        tpl = self.dry_run.get(d.get("action"), {"steps": ["Prepare {action_id} on {target} for review"],
                                                 "rollback": ["Nothing to undo: dry-run only"]})
        params = {"target": d.get("target") or "the affected scope", "segment": "the affected", "action_id": aid}
        render = lambda s: re.sub(r"\{(target|segment|action_id)\}", lambda m: params[m.group(1)], s)  # noqa: E731
        return {"action_id": aid, "action": d.get("action", "inspect"), "target": d.get("target"), "label": SIMULATED,
                "executed": False, "policy": policy, "steps": [render(s) for s in tpl["steps"]],
                "rollback": [render(s) for s in tpl["rollback"]]}

    @staticmethod
    def _msg(iid: str, mtype: str, sender: str, recipient: str, seq: int, reply: str | None, payload: dict[str, Any]):
        return {"created_at": _now(), "extras": {}, "in_reply_to": reply, "incident_id": iid, "limitations": [],
                "message_id": str(uuid.uuid4()), "message_type": mtype, "payload": payload, "recipient": recipient,
                "schema_version": "1.4", "sender": sender, "seq": seq, "status": "completed"}

    def agents(self) -> Any:
        key = "GET /agents (wireless agent joined)" if self.agent_joined else "GET /agents (wireless agent not running)"
        return self.examples[key]

    def list_incidents(self, limit: int) -> list[dict[str, Any]]:
        rows = [{"incident_id": i, "status": v["report"]["status"],  # same fields as the real list (storage.py)
                 "suspected_root_cause": v["report"]["suspected_root_cause"], "confidence": v["report"]["confidence"],
                 "created_at": v["events"][0]["created_at"].replace("Z", "+00:00")}
                for i, v in self.incidents.items()]
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        return rows[:min(max(limit, 1), 500)]


def make_handler(state: MockState, ui: Path | None) -> type[BaseHTTPRequestHandler]:
    if ui is None and (DEFAULT_UI / "index.html").is_file():
        ui = DEFAULT_UI.resolve()  # same default as `netcoop serve`: landing at /, files at /ui/<path>
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        server_version = "netcoop-mock"

        def log_message(self, fmt: str, *args: Any) -> None:
            print("mock:", fmt % args, flush=True)

        # ----- plumbing -----
        def _cors(self) -> None:
            origin = self.headers.get("Origin")
            if origin in CORS_ORIGINS:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")

        def _send(self, status: int, body: bytes, ctype: str, extra: dict[str, str] | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self._cors()
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, obj: Any) -> None:
            self._send(status, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json")

        def _err(self, e: ApiError) -> None:
            if e.status == 422:
                self._json(422, {"detail": json.loads(e.detail)})
            else:
                self._json(e.status, {"detail": {"code": e.code, "detail": e.detail}})

        def _body(self) -> bytes:
            n = int(self.headers.get("Content-Length") or 0)
            return self.rfile.read(n) if n else b""

        def _file(self, p: Path, ctype: str) -> None:
            self._send(200, p.read_bytes(), ctype, {**SECURITY_HEADERS, "Cache-Control": "no-cache"})

        # ----- routes -----
        def do_OPTIONS(self) -> None:  # noqa: N802 - CORS preflight, like Starlette's CORSMiddleware
            self.send_response(200 if self.headers.get("Origin") in CORS_ORIGINS else 400)
            self._cors()
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802
            u = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(u.query).items()}
            parts = [p for p in u.path.split("/") if p]
            try:
                if u.path == "/":
                    if not ui:
                        raise ApiError(404, "NOT_FOUND", "no UI here: start the mock with --ui <folder>")
                    return self._file(ui / "index.html", "text/html; charset=utf-8")
                if u.path == "/dashboard" or parts[:1] == ["dashboard"]:
                    if not (STATIC / "dashboard.html").is_file():
                        raise ApiError(404, "NOT_FOUND", "no classic dashboard here: start the mock with --ui <folder>")
                if u.path == "/dashboard":
                    return self._file(STATIC / "dashboard.html", "text/html; charset=utf-8")
                if parts[:1] == ["dashboard"] and len(parts) == 2:
                    if parts[1] not in ("dashboard.js", "dashboard.css"):
                        raise ApiError(404, "NOT_FOUND", "unknown asset")
                    return self._file(STATIC / parts[1], "text/javascript" if parts[1].endswith(".js") else "text/css")
                if parts[:1] == ["ui"]:
                    if not ui:
                        raise ApiError(404, "NOT_FOUND", "no --ui folder configured")
                    p = (ui / "/".join(parts[1:])).resolve()
                    if not p.is_relative_to(ui) or p.suffix.lower() not in UI_TYPES or not p.is_file():
                        raise ApiError(404, "NOT_FOUND", "unknown asset")
                    return self._file(p, UI_TYPES[p.suffix.lower()])
                if u.path == "/scenarios":
                    return self._json(200, state.examples["GET /scenarios"])
                if u.path == "/topology":
                    return self._json(200, state.examples["GET /topology"])
                if u.path == "/agents":
                    return self._json(200, state.agents())
                if u.path == "/mock/fixtures":
                    return self._json(200, json.loads((FIX / "index.json").read_text(encoding="utf-8")))
                if u.path == "/incidents":
                    return self._json(200, state.list_incidents(int(q.get("limit", 50))))
                if parts[:1] == ["incidents"] and len(parts) == 3:
                    inc = state.get(parts[1])
                    if parts[2] == "report":
                        return self._json(200, inc["report"])
                    if parts[2] == "events":
                        return self._json(200, inc["events"])
                    if parts[2] == "report.csv":
                        return self._send(200, _csv(inc["report"]).encode("utf-8"), "text/plain; charset=utf-8")
                    if parts[2] == "stream":
                        return self._stream(inc, q)
                raise ApiError(404, "NOT_FOUND", "Not Found")
            except ApiError as e:
                if e.code == "NOT_FOUND" and e.detail == "Not Found":
                    return self._json(404, {"detail": "Not Found"})  # FastAPI's shape for unknown routes
                self._err(e)

        def do_POST(self) -> None:  # noqa: N802
            u = urlparse(self.path)
            q = {k: v[-1] for k, v in parse_qs(u.query).items()}
            parts = [p for p in u.path.split("/") if p]
            raw = self._body()
            try:
                if parts[:1] == ["scenarios"] and len(parts) == 3 and parts[2] == "run":
                    name = parts[1]
                    if name == "weak_wifi":
                        external = q.get("external", "true").lower() != "false"
                        fx = "weak_wifi_after" if (external and state.agent_joined) else "weak_wifi_before"
                    elif name in SCENARIO_FIXTURE:
                        fx = SCENARIO_FIXTURE[name]
                    else:
                        raise ApiError(404, "UNKNOWN_SCENARIO", "unknown scenario")
                    return self._json(200, state.new_run(fx))
                if parts[:1] == ["incidents"] and len(parts) == 3 and parts[2] == "feedback":
                    try:
                        body = json.loads(raw or b"null")
                    except ValueError:
                        body = None
                    return self._json(200, state.feedback(parts[1], body))
                if u.path == "/incidents":
                    if not q.get("filename", "upload.json").lower().endswith((".json", ".csv")):
                        raise ApiError(415, "UNSUPPORTED", "only .json or .csv uploads")
                    try:
                        json.loads(raw)
                    except ValueError:
                        r = state.new_run("malformed_input_error")
                        return self._json(200, state.incidents[r["incident_id"]]["report"])
                    raise ApiError(501, "MOCK_UNSUPPORTED", "the mock only replays recorded runs; use POST /scenarios/{name}/run")
                if u.path in ("/mock/agent/join", "/mock/agent/leave"):
                    state.agent_joined = u.path.endswith("join")
                    return self._json(200, {"agent_joined": state.agent_joined})
                raise ApiError(404, "NOT_FOUND", "Not Found")
            except ApiError as e:
                if e.code == "NOT_FOUND" and e.detail == "Not Found":
                    return self._json(404, {"detail": "Not Found"})
                self._err(e)

        def _stream(self, inc: dict[str, Any], q: dict[str, str]) -> None:
            delay = min(max(int(q.get("delay_ms", 0) or 0), 0), 2000) / 1000
            recorded = q.get("timing") == "recorded"
            events = sorted(inc["events"], key=lambda e: e["seq"])
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Connection", "close")
            self._cors()
            self.end_headers()
            self.close_connection = True
            prev = None
            try:
                for e in events:
                    if recorded and prev is not None:
                        gap = (_ts(e["created_at"]) - _ts(prev)) if e.get("created_at") and prev else 0
                        time.sleep(min(max(gap, 0), 2.0))
                    frame = f"id: {e['seq']}\nevent: message\ndata: {json.dumps(e, sort_keys=True, ensure_ascii=True)}\n\n"
                    self.wfile.write(frame.encode("utf-8"))
                    self.wfile.flush()
                    prev = e.get("created_at")
                    if delay and not recorded:
                        time.sleep(delay)
                self.wfile.write(f"event: end\ndata: {json.dumps({'messages': len(events)})}\n\n".encode())
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass

    return H


def _ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def _csv(rep: dict[str, Any]) -> str:  # same columns and formula-injection guard as the real /report.csv
    def cell(v: Any) -> str:
        s = "" if v is None else str(v)
        return "'" + s if s[:1] in ("=", "+", "-", "@") else s

    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["incident_id", "status", "metric", "entity", "value", "unit", "interpretation", "finding_id"])
    for e in rep["supporting_evidence"]:
        w.writerow([cell(x) for x in (rep["incident_id"], rep["status"], e["metric"], e.get("entity"), e["value"],
                                      e.get("unit"), e["interpretation"], e["finding_id"])])
    return buf.getvalue()


def build_server(port: int = 8000, ui: Path | None = None, agent_joined: bool = False) -> ThreadingHTTPServer:
    state = MockState(agent_joined)
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(state, ui))
    srv.daemon_threads = True
    srv.state = state  # type: ignore[attr-defined]
    return srv


def main() -> int:
    ap = argparse.ArgumentParser(description="NetCoop mock API: recorded fixtures, no backend")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--ui", default=None, help="UI folder to serve (index.html at /, files at /ui/<path>)")
    ap.add_argument("--agent", choices=["absent", "joined"], default="absent",
                    help="initial state of the external wireless_agent (toggle with POST /mock/agent/join|leave)")
    a = ap.parse_args()
    ui = Path(a.ui).resolve() if a.ui else None
    if ui and not (ui / "index.html").is_file():
        print(f"error: --ui {a.ui}: no index.html in that folder")
        return 2
    srv = build_server(a.port, ui, a.agent == "joined")
    default_ui = "bundled UI (netcoop/api/ui)" if (DEFAULT_UI / "index.html").is_file() else "none (pass --ui <folder>)"
    print(f"NetCoop mock API on http://127.0.0.1:{a.port}/  ({len(srv.state.fixtures)} fixtures from {FIX}; UI: "  # type: ignore[attr-defined]
          f"{ui or default_ui}; wireless_agent {a.agent}). Ctrl+C to stop.")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
