"""Event-sourced orchestrator (§7.1). Orchestrator state is derived from the event log."""

from __future__ import annotations

import base64
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any

from netcoop.agents.base import FindingsTool, ReadOnlyContext, TelemetryTool, make_context
from netcoop.agents.connectivity import ConnectivityAgent
from netcoop.agents.correlation import CorrelationAgent
from netcoop.agents.infrastructure import InfrastructureAgent
from netcoop.agents.performance import PerformanceAgent
from netcoop.agents.reporting import SYNTHETIC, ReportingAgent
from netcoop.bus.bus import Bus, BusBoundExceeded
from netcoop.bus.eventlog import EventLog
from netcoop.config import ROOT, Config, load_config
from netcoop.gateway.a2a_gateway import discover
from netcoop.gateway.transport import HttpTransport, RecordingTransport, Transport
from netcoop.llm import router as llm
from netcoop.normalize.pipeline import NormalizationError, normalize_bundle
from netcoop.normalize.timefix import rfc3339
from netcoop.orchestrator.rounds import max_rounds, needs_more_rounds
from netcoop.policy.validator import scrub, validate_report
from netcoop.protocol.envelope import (
    INCIDENT_ID_PATTERN,
    SCHEMA_VERSION,
    Message,
    error_message,
    make_message,
)
from netcoop.storage import Store

RUNS_DIR = ROOT / "runs"
INTERNAL_AGENTS = {
    "performance_agent": PerformanceAgent,
    "infrastructure_agent": InfrastructureAgent,
    "connectivity_agent": ConnectivityAgent,
}
_ID_RE = re.compile(INCIDENT_ID_PATTERN)


@dataclass
class RunOptions:
    incident_id: str | None = None
    runs_dir: Path = RUNS_DIR
    external: bool = True
    transport: Transport | None = None
    persist: bool = True
    filename: str | None = None
    record_external: bool = True
    store: bool = True


@dataclass
class RunResult:
    incident_id: str
    report: dict[str, Any]
    run_dir: Path | None
    log: EventLog
    external_status: dict[str, str] = field(default_factory=dict)


def dump_report(report: dict[str, Any]) -> bytes:
    return (json.dumps(report, indent=2, ensure_ascii=True) + "\n").encode("utf-8")


def new_incident_id(sha256: str, runs_dir: Path) -> str:
    base = "INC-" + base64.b32encode(bytes.fromhex(sha256)[:5]).decode().rstrip("=")
    if not (runs_dir / base).exists():
        return base
    for i in range(1, 36 ** 3):
        n, s = i, ""
        while n:
            n, r = divmod(n, 36)
            s = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"[r] + s
        cand = f"{base}{s}"
        if not (runs_dir / cand).exists():
            return cand
    raise RuntimeError("incident id space exhausted")


def safe_run_dir(runs_dir: Path, incident_id: str) -> Path:
    if not _ID_RE.fullmatch(incident_id or ""):
        raise ValueError("invalid incident_id")
    p = (runs_dir / incident_id).resolve()
    if p.parent != runs_dir.resolve():
        raise ValueError("invalid incident_id path")
    return p


def _input_bytes(data: bytes | str | dict | list) -> bytes:
    if isinstance(data, bytes):
        return data
    if isinstance(data, str):
        return data.encode("utf-8")
    return json.dumps(data, sort_keys=True).encode("utf-8")


class Orchestrator:
    def __init__(self, cfg: Config, opts: RunOptions):
        self.cfg = cfg
        self.opts = opts

    def run(self, data: bytes | str | dict | list) -> RunResult:
        cfg, opts = self.cfg, self.opts
        raw = _input_bytes(data)
        sha = hashlib.sha256(raw).hexdigest()
        opts.runs_dir.mkdir(parents=True, exist_ok=True)
        incident_id = opts.incident_id or new_incident_id(sha, opts.runs_dir)
        run_dir = safe_run_dir(opts.runs_dir, incident_id) if opts.persist else None
        log = EventLog(run_dir / "events.jsonl" if run_dir else None)
        bus = Bus(log, max_messages=int(cfg.agents["rounds"]["max_bus_messages"]), retries=int(cfg.agents.get("retries", 1)))
        try:
            report, ext_status = self._run(raw, sha, incident_id, log, bus, run_dir)
        except BusBoundExceeded as exc:
            report, ext_status = self._failed_report(incident_id, f"run aborted: {exc}"), {}
        finally:
            bus.close()
        if run_dir is not None:
            self._persist(run_dir, raw, sha, incident_id, report, ext_status)
        return RunResult(incident_id=incident_id, report=report, run_dir=run_dir, log=log, external_status=ext_status)

    # ------------------------------------------------------------------
    def _run(self, raw: bytes, sha: str, incident_id: str, log: EventLog, bus: Bus, run_dir: Path | None
             ) -> tuple[dict[str, Any], dict[str, str]]:
        cfg, opts = self.cfg, self.opts
        # 1. ingest -> normalize
        try:
            norm = normalize_bundle(raw, cfg, filename=opts.filename)
        except NormalizationError as exc:
            bus.publish(error_message(sender="normalizer", recipient="orchestrator", incident_id=incident_id,
                                      code=exc.code, detail=exc.detail))
            return self._failed_report(incident_id, f"Input rejected ({exc.code}): {exc.detail}"), {}
        hints, _llm_log = llm.classify_complaint(norm.complaint, cfg)
        window = norm.window
        assert window is not None and norm.incident_time is not None
        bus.publish(make_message(
            "normalization_summary", sender="normalizer", recipient="orchestrator", incident_id=incident_id,
            limitations=norm.limitations,
            payload={"input_sha256": sha, "incident_time": rfc3339(norm.incident_time),
                     "incident_time_inferred": norm.incident_time_inferred, "window": window.model_dump(mode="json"),
                     "summary": norm.summary, "quarantined": [q.as_dict() for q in norm.quarantined][:500],
                     "extras": norm.extras[:200], "complaint_present": bool(norm.complaint), "hints": hints}))

        tools = {"telemetry": TelemetryTool(norm.observations), "topology": cfg.topology, "findings": FindingsTool(log)}
        handlers: dict[str, tuple[Any, float]] = {}
        for aid in cfg.analysis_agents:
            handlers[aid] = (INTERNAL_AGENTS[aid](cfg).handle, float(cfg.agents["internal"][aid]["timeout_s"]))
        correlation = CorrelationAgent(cfg)
        reporting = ReportingAgent(cfg)

        def ctx_for(aid: str, rnd: int) -> ReadOnlyContext:
            return make_context(cfg, aid, tools, incident_id=incident_id, incident_time=norm.incident_time,
                                window=window, round=rnd)

        # 2. external discovery (allowlist only) -> hot-plug into this run
        ext_status: dict[str, str] = {}
        if opts.external and cfg.agents.get("external"):
            transport = opts.transport or HttpTransport()
            if run_dir is not None and opts.record_external:
                transport = RecordingTransport(transport, run_dir / "external.jsonl")
            disc = discover(cfg, transport)
            ext_status = dict(disc.status)
            for ra in disc.agents:
                handlers[ra.agent_id] = (ra.handle, ra.timeout_s)
        else:
            ext_status = {spec["agent_id"]: "disabled" for spec in cfg.agents.get("external", ())}

        def task(recipient: str, name: str, rnd: int, params: dict[str, Any] | None = None) -> Message:
            return make_message("task_request", sender="orchestrator", recipient=recipient, incident_id=incident_id,
                                payload={"task": name, "window": window.model_dump(mode="json"), "round": rnd,
                                         "params": params or {}}, salt=rnd)

        def ctx_any(aid: str, rnd: int) -> Any:
            if aid in cfg.agents["internal"]:
                return ctx_for(aid, rnd)
            # external agents get no tools (§8): the gateway only needs window + incident time
            return ReadOnlyContext(incident_id=incident_id, incident_time=norm.incident_time, window=window,
                                   config=cfg, tools=MappingProxyType({}), round=rnd)

        # 3. round 0: all analysis agents in parallel (D9: nothing can skip an agent)
        analysis = sorted(handlers)
        bus.deliver_many([(aid, handlers[aid][0], task(aid, "analyze", 0), ctx_any(aid, 0), handlers[aid][1])
                          for aid in analysis])
        anomalous_entities = sorted({f["entity"]["id"] for m in log.by_type("finding_report")
                                     for f in m.payload.get("findings", []) if f["severity"] != "normal"})
        bus.deliver("connectivity_agent", handlers["connectivity_agent"][0],
                    task("connectivity_agent", "scope", 0, {"entities": anomalous_entities}),
                    ctx_for("connectivity_agent", 0), handlers["connectivity_agent"][1])

        # 4-5. correlate, conflicts, prediction/evidence rounds (bounded)
        corr_t = float(cfg.agents["internal"]["correlation_agent"]["timeout_s"])
        corr_failed = False
        rnd = 1
        plan = True
        while True:
            d = bus.deliver("correlation_agent", correlation.handle,
                            task("correlation_agent", "correlate", rnd, {"plan": plan}), ctx_for("correlation_agent", rnd), corr_t)
            if d.failed:
                corr_failed = True
                break
            diag = next(m for m in d.outputs if m.message_type == "diagnosis").payload
            reqs = [m for m in d.outputs if m.message_type == "evidence_request"]
            if not plan or not reqs:
                break
            items = []
            for r in reqs:
                if r.recipient in handlers:
                    items.append((r.recipient, handlers[r.recipient][0], r, ctx_any(r.recipient, rnd), handlers[r.recipient][1]))
            bus.deliver_many(items)
            rnd += 1
            plan = rnd <= max_rounds(cfg) and needs_more_rounds(cfg, diag)
        # 6. final scoring
        if not corr_failed:
            d = bus.deliver("correlation_agent", correlation.handle,
                            task("correlation_agent", "finalize", rnd, {"plan": False}), ctx_for("correlation_agent", rnd), corr_t)
            corr_failed = d.failed
        # 7. reporting -> validator
        d = bus.deliver("reporting_agent", reporting.handle,
                        task("reporting_agent", "report", rnd, {"external": ext_status, "correlation_failed": corr_failed}),
                        ctx_for("reporting_agent", rnd), float(cfg.agents["internal"]["reporting_agent"]["timeout_s"]))
        rep_msg = next((m for m in d.outputs if m.message_type == "report"), None)
        if rep_msg is None:
            return self._failed_report(incident_id, "reporting_agent failed"), ext_status
        report = dict(rep_msg.payload["report"])
        narrative, _nlog = llm.write_narrative(report, cfg)
        report["narrative"] = scrub(narrative)
        known = {f["finding_id"] for m in log.by_type("finding_report", "evidence_response") for f in m.payload.get("findings", [])}
        errors = validate_report(report, cfg, known)
        if errors:
            bus.publish(error_message(sender="orchestrator", recipient="orchestrator", incident_id=incident_id,
                                      code="INVALID_OUTPUT", detail="report rejected by validator: " + "; ".join(errors)[:400],
                                      agent_id="reporting_agent"))
            return self._failed_report(incident_id, "report rejected by validator: " + "; ".join(errors)[:200]), ext_status
        return report, ext_status

    def _failed_report(self, incident_id: str, why: str) -> dict[str, Any]:
        report = {
            "incident_id": incident_id, "status": "failed", "suspected_root_cause": "Diagnosis failed",
            "confidence": 0.0, "affected_devices": [], "supporting_evidence": [], "alternative_causes": [],
            "recommended_actions": ["Fix the input or agent failure listed in limitations and re-run"],
            "evidence_sources": [], "limitations": [SYNTHETIC, scrub(why)[:300]], "schema_version": SCHEMA_VERSION,
            "confidence_category": "low", "fault_type": None, "narrative": None,
        }
        return report

    def _persist(self, run_dir: Path, raw: bytes, sha: str, incident_id: str, report: dict[str, Any],
                 ext_status: dict[str, str]) -> None:
        ext = ".csv" if (self.opts.filename or "").lower().endswith(".csv") else ".json"
        (run_dir / f"input{ext}").write_bytes(raw)
        (run_dir / "report.json").write_bytes(dump_report(report))
        meta = {"incident_id": incident_id, "input_file": f"input{ext}", "input_sha256": sha, "llm": llm.mode(),
                "external": self.opts.external, "external_status": ext_status, "filename": self.opts.filename}
        (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, sort_keys=True), encoding="utf-8")
        if not self.opts.store:
            return
        try:
            Store(self.opts.runs_dir / "netcoop.db").save_report(report)
        except Exception:  # noqa: BLE001 - storage must never fail a diagnosis
            pass


def run_incident(data: bytes | str | dict | list, cfg: Config | None = None, opts: RunOptions | None = None) -> RunResult:
    return Orchestrator(cfg or load_config(), opts or RunOptions()).run(data)
