"""Dashboard routes (M3, D7): one static vanilla-JS page served by the API, read-only plus "Run scenario".

* No build step, no CDN: /dashboard/* serves three fixed files from netcoop/api/static/ (no user-supplied paths).
* PI8: the page renders every data field with textContent; a strict Content-Security-Policy forbids inline script,
  remote origins and framing.
* SSE (/incidents/{id}/stream) replays the run's event log in `seq` order. It is a view of the log, never a
  second source of truth.
* Run scenario accepts only names of folders in data/scenarios (regex + existence check).
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse

from netcoop.bus.eventlog import EventLog
from netcoop.config import ROOT

STATIC = Path(__file__).parent / "static"
SCEN_DIR = ROOT / "data" / "scenarios"
SCENARIO_RE = re.compile(r"^[a-z][a-z_]{0,39}$")
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SECURITY_HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer",
                    "X-Frame-Options": "DENY"}
_FILES = {"dashboard.js": "text/javascript", "dashboard.css": "text/css"}

router = APIRouter()


def _err(status: int, code: str, detail: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "detail": detail})


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    return HTMLResponse((STATIC / "dashboard.html").read_text(encoding="utf-8"), headers=SECURITY_HEADERS)


@router.get("/dashboard/{name}", include_in_schema=False)
def dashboard_asset(name: str) -> FileResponse:
    if name not in _FILES:  # fixed allowlist: no path from the request reaches the filesystem
        raise _err(404, "NOT_FOUND", "unknown asset")
    return FileResponse(STATIC / name, media_type=_FILES[name], headers=SECURITY_HEADERS)


def scenario_names() -> list[str]:
    return sorted(p.name for p in SCEN_DIR.iterdir() if p.is_dir() and (p / "incident.json").is_file())


def scenario_path(name: str) -> Path:
    if not SCENARIO_RE.fullmatch(name) or name not in scenario_names():
        raise _err(404, "UNKNOWN_SCENARIO", "unknown scenario")
    return SCEN_DIR / name / "incident.json"


@router.get("/scenarios")
def list_scenarios() -> dict[str, Any]:
    return {"scenarios": [{"name": n} for n in scenario_names()]}


def topology_view(topo: Any) -> dict[str, Any]:
    nodes, links = [], []
    for eid in sorted(topo.entities):
        e = topo.entities[eid]
        if e.type == "link":
            if len(e.endpoints) == 2:
                links.append({"id": e.id, "a": e.endpoints[0], "b": e.endpoints[1]})
        elif e.placed:
            nodes.append({"id": e.id, "type": e.type, "segment": e.segment, "role": e.role,
                          "parent": e.upstream or e.attached_to})
    for n in nodes:
        if n["type"] == "service" and n["parent"]:
            links.append({"id": f"{n['id']}~{n['parent']}", "a": n["id"], "b": n["parent"]})
    return {"nodes": nodes, "links": links}


async def sse_events(path: Path, delay_ms: int) -> AsyncIterator[str]:
    events = sorted(EventLog.read(path), key=lambda e: e["seq"])
    for e in events:
        yield f"id: {e['seq']}\nevent: message\ndata: {json.dumps(e, sort_keys=True, ensure_ascii=True)}\n\n"
        if delay_ms:
            await asyncio.sleep(delay_ms / 1000)
    yield f"event: end\ndata: {json.dumps({'messages': len(events)})}\n\n"


def sse_response(path: Path, delay_ms: int) -> StreamingResponse:
    delay = min(max(int(delay_ms), 0), 2000)
    return StreamingResponse(sse_events(path, delay), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Content-Type-Options": "nosniff"})
