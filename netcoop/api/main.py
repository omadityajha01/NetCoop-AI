"""Read-only-ish FastAPI over runs/ (D7). `netcoop serve` -> http://127.0.0.1:8000/docs

Uploads: 10 MB cap, .json/.csv only, stdlib parsers. Incident IDs are server-generated and path params
are validated against the incident_id regex before touching runs/. Structured errors, no stack traces.
"""

from __future__ import annotations

import csv
import io
import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from netcoop.bus.eventlog import EventLog
from netcoop.config import load_config
from netcoop.orchestrator.run import RUNS_DIR, RunOptions, run_incident, safe_run_dir
from netcoop.storage import Store, valid_incident_id

app = FastAPI(title="NetCoop AI", version="1.0.0", description="Multi-agent network fault diagnosis (NMP 1.0)")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["GET", "POST"], allow_headers=["Content-Type"])
RUNS: Path = RUNS_DIR


def _store() -> Store:
    return Store(RUNS / "netcoop.db")


@app.exception_handler(Exception)
async def _unhandled(_req: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL", "detail": "internal error"}})


def _err(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


def _dir(incident_id: str) -> Path:
    if not valid_incident_id(incident_id):
        raise _err(400, "BAD_INCIDENT_ID", "incident_id must match ^INC-[0-9A-Z]{4,12}$")
    d = safe_run_dir(RUNS, incident_id)
    if not d.exists():
        raise _err(404, "NOT_FOUND", "unknown incident")
    return d


@app.post("/incidents")
async def create_incident(request: Request, external: bool = True, filename: str = "upload.json") -> dict[str, Any]:
    cfg = load_config()
    if not filename.lower().endswith((".json", ".csv")):
        raise _err(415, "UNSUPPORTED", "only .json or .csv uploads")
    body = await request.body()
    if len(body) > int(cfg.agents["data"]["max_upload_bytes"]):
        raise _err(413, "TOO_LARGE", "upload exceeds 10 MB")
    res = run_incident(body, cfg, RunOptions(runs_dir=RUNS, external=external, filename=Path(filename).name))
    return res.report


@app.get("/incidents")
def list_incidents(limit: int = 50) -> list[dict[str, Any]]:
    return _store().list_reports(min(max(limit, 1), 500))


@app.get("/incidents/{incident_id}/report")
def get_report(incident_id: str) -> dict[str, Any]:
    return json.loads((_dir(incident_id) / "report.json").read_text(encoding="utf-8"))


@app.get("/incidents/{incident_id}/events")
def get_events(incident_id: str) -> list[dict[str, Any]]:
    return EventLog.read(_dir(incident_id) / "events.jsonl")


def _csv_cell(v: Any) -> str:
    s = "" if v is None else str(v)
    return "'" + s if s[:1] in ("=", "+", "-", "@") else s  # CSV/formula injection guard


@app.get("/incidents/{incident_id}/report.csv", response_class=PlainTextResponse)
def get_report_csv(incident_id: str) -> str:
    rep = get_report(incident_id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["incident_id", "status", "metric", "entity", "value", "unit", "interpretation", "finding_id"])
    for e in rep["supporting_evidence"]:
        w.writerow([_csv_cell(x) for x in (rep["incident_id"], rep["status"], e["metric"], e.get("entity"), e["value"],
                                           e.get("unit"), e["interpretation"], e["finding_id"])])
    return buf.getvalue()


class Feedback(BaseModel):
    action_id: str = Field(pattern=r"^[A-Z]{2,6}-[0-9]{1,3}$")
    decision: str = Field(pattern=r"^(approve|reject)$")
    note: str | None = Field(default=None, max_length=500)  # stored, never prompted


@app.post("/incidents/{incident_id}/feedback")
def post_feedback(incident_id: str, fb: Feedback) -> dict[str, Any]:
    _dir(incident_id)
    fid = _store().add_feedback(incident_id, fb.action_id, fb.decision, fb.note)
    return {"id": fid, "executed": False}


@app.get("/agents")
def agents() -> dict[str, Any]:
    from netcoop.gateway.a2a_gateway import discover

    disc = discover(load_config())
    return {"external": disc.status, "details": disc.details}
