"""`netcoop replay <incident_id>`: re-run from the stored input + recorded external exchanges and compare
report.json byte-for-byte (LLM off)."""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from netcoop.bus.eventlog import EventLog
from netcoop.config import Config, load_config
from netcoop.gateway.transport import ReplayTransport
from netcoop.orchestrator.run import RUNS_DIR, Orchestrator, RunOptions, dump_report, safe_run_dir


@dataclass
class ReplayResult:
    incident_id: str
    report_identical: bool
    events_identical: bool
    detail: str


def _strip(events: list[dict]) -> list[dict]:
    return [{k: v for k, v in e.items() if k != "created_at"} for e in events]


def replay(incident_id: str, runs_dir: Path = RUNS_DIR, cfg: Config | None = None) -> ReplayResult:
    cfg = cfg or load_config()
    run_dir = safe_run_dir(runs_dir, incident_id)
    meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
    if meta.get("llm", "off") != "off":
        return ReplayResult(incident_id, False, False, "run used an LLM; byte-identical replay requires NETCOOP_LLM=off")
    raw = (run_dir / meta["input_file"]).read_bytes()
    with tempfile.TemporaryDirectory() as tmp:
        opts = RunOptions(incident_id=incident_id, runs_dir=Path(tmp), external=bool(meta.get("external", True)),
                          transport=ReplayTransport(run_dir / "external.jsonl"), record_external=False, store=False,
                          filename=meta.get("filename"))
        res = Orchestrator(cfg, opts).run(raw)
        new_report = dump_report(res.report)
        new_events = _strip(EventLog.read(Path(tmp) / incident_id / "events.jsonl"))
    old_report = (run_dir / "report.json").read_bytes()
    old_events = _strip(EventLog.read(run_dir / "events.jsonl"))
    same_r = new_report == old_report
    same_e = new_events == old_events
    detail = "identical" if same_r and same_e else (
        f"report {'identical' if same_r else 'DIFFERS'}; events {'identical' if same_e else 'DIFFER'} "
        f"({len(old_events)} vs {len(new_events)})")
    return ReplayResult(incident_id, same_r, same_e, detail)
