"""correlation_agent: hypotheses, predictions, evidence requests, conflict detection, scoring.

Stateless: every call re-derives state from the read-only event log view (§7.4).
"""

from __future__ import annotations

from typing import Any

from netcoop.agents.base import FindingsTool, ReadOnlyContext
from netcoop.orchestrator.conflicts import ConflictSet, detect_c1, detect_c2
from netcoop.protocol.envelope import Message, error_message, make_message
from netcoop.protocol.findings import EntityRef, Finding, SignalRef
from netcoop.scoring.confidence import decide
from netcoop.scoring.hypotheses import generate_candidates, index_findings, rank_hypotheses
from netcoop.scoring.predictions import plan_round, resolve_outcomes


def derive_state(msgs: list[Message]) -> dict[str, Any]:
    st: dict[str, Any] = {
        "asked": [], "failed": set(), "coverage": {}, "findings": [], "agent_of": {}, "scope": None,
        "norm": None, "refetched": set(), "predicted": set(), "covering_agents": set(),
    }
    for m in msgs:
        t = m.message_type
        if t == "task_request" and m.payload.get("task") == "analyze":
            st["asked"].append(m.recipient)
        elif t == "error" and m.payload.get("agent_id"):
            st["failed"].add(m.payload["agent_id"])
        elif t == "coverage_manifest":
            if m.payload.get("signals"):
                st["covering_agents"].add(m.sender)
            for s in m.payload.get("signals", []):
                st["coverage"].setdefault((s["metric"], s["entity"]["id"]), m.sender)
        elif t in ("finding_report", "evidence_response"):
            for f in m.payload.get("findings", []):
                fo = Finding.model_validate(f)
                if fo.finding_id not in st["agent_of"]:
                    st["findings"].append(fo)
                    st["agent_of"][fo.finding_id] = m.sender
            if t == "finding_report" and m.payload.get("scope"):
                st["scope"] = m.payload["scope"]
        elif t == "normalization_summary":
            st["norm"] = m.payload
        elif t == "evidence_request" and m.payload.get("reason") == "c2_refetch":
            for r in m.payload.get("requests", []):
                st["refetched"].add((r["metric"], r["entity"]["id"]))
        elif t == "prediction":
            p = m.payload["prediction"]
            st["predicted"].add(f"{p['hypothesis_id']}|{p['signal']['metric']}@{p['signal']['entity']['id']}")
    st["asked"] = sorted(set(st["asked"]))
    st["findings"].sort(key=lambda f: f.finding_id)
    return st


class CorrelationAgent:
    agent_id = "correlation_agent"
    capabilities = ["correlate", "predict", "detect_conflicts", "score"]

    def __init__(self, cfg: Any = None):
        pass

    def handle(self, msg: Message, ctx: ReadOnlyContext) -> list[Message]:
        task = msg.payload.get("task") if msg.message_type == "task_request" else None
        if task not in ("correlate", "finalize"):
            return [error_message(sender=self.agent_id, recipient=msg.sender, incident_id=msg.incident_id,
                                  code="MALFORMED", detail="correlation_agent handles task_request correlate|finalize",
                                  offending_message_id=msg.message_id)]
        cfg = ctx.config
        view: FindingsTool = ctx.tool("findings")
        st = derive_state(view.all())
        norm = st["norm"] or {}
        rnd = int(msg.payload.get("round", 0))
        params = msg.payload.get("params", {})

        cs = ConflictSet()
        detect_c1(cfg, st["findings"], st["agent_of"], cs)
        detect_c2(cfg, st["findings"], norm.get("quarantined", []), st["refetched"], cs)
        active = [f for f in st["findings"] if f.finding_id not in cs.losers]
        stale_q = float(cfg.scoring["stale_quality"])

        def quality_of(f: Finding) -> float:
            return min(f.data_quality.completeness, stale_q) if f.finding_id in cs.stale else f.data_quality.completeness

        idx = index_findings(active)
        anomalous = [f for f in active if f.anomalous]
        scope = st["scope"] or {}
        ncu = scope.get("nearest_common_upstream")
        cands = generate_candidates(cfg, anomalous, ncu, scope.get("affected_entities", []), norm.get("hints", []))
        hyps = rank_hypotheses(cfg, cands, idx, quality_of)
        predictions, pnotes = resolve_outcomes(cfg, view.all())

        asked = [a for a in st["asked"]]
        coverage_share = (len([a for a in asked if a in st["covering_agents"] and a not in st["failed"]]) / len(asked)
                          if asked else 0.0)
        failed = sorted(a for a in st["failed"] if a in asked)
        usable = int((norm.get("summary") or {}).get("observations_used", 0)) + len(
            [f for f in st["findings"] if st["agent_of"].get(f.finding_id) not in cfg.agents["internal"]])
        high_count = sum(1 for f in active if f.severity in ("high", "critical"))
        dec = decide(cfg, hyps, high_count=high_count, usable_observations=usable, failed_agents=failed,
                     unresolved_c2=cs.unresolved_c2, data_coverage=coverage_share)

        conflicts = list(cs.conflicts)
        if len(hyps) > 1 and dec.margin < float(cfg.scoring["status"]["min_margin"]) and dec.status not in (
                "no_fault_detected",):
            conflicts.append({
                "conflict_id": "C3-1", "type": "C3",
                "detail": f"{hyps[0].fault_type} vs {hyps[1].fault_type}: margin {dec.margin:.2f}",
                "finding_ids": sorted(set(hyps[0].supporting_finding_ids) | set(hyps[1].supporting_finding_ids)),
                "resolution": ("prediction rounds requested" if task == "correlate"
                               else "still below margin after rounds: both reported as co-candidates"),
                "resolved": task == "correlate" and False,
            })

        # the exact missing signals that would resolve it: every hypothesis with some support, in rank order
        missing: list[str] = []
        pool = [h for h in hyps if h.support > 0] if dec.status in ("insufficient_evidence", "probable") else hyps[:1]
        for h in pool:
            for s in h.missing_signals:
                if s not in missing:
                    missing.append(s)
        missing = missing[:12]

        outputs: list[Message] = []
        plan = None
        if task == "correlate" and params.get("plan") and hyps:
            window = ctx.window
            extra = []
            for metric, eid in cs.refetch:
                agent = st["coverage"].get((metric, eid))
                if agent:
                    extra.append((agent, SignalRef(metric=metric, entity=EntityRef(type=cfg.topology.type_of(eid) or "device",
                                                                                    id=eid), window=window)))
            plan = plan_round(cfg, hyps, idx, st["coverage"], rnd, set(st["predicted"]), window, None)
            for p in plan.predictions:  # P2: predictions are appended before their evidence_request
                outputs.append(make_message("prediction", sender=self.agent_id, recipient="orchestrator",
                                            incident_id=msg.incident_id, in_reply_to=msg.message_id,
                                            payload={"prediction": p.model_dump(mode="json")}))
            for agent in sorted(plan.requests):
                outputs.append(make_message(
                    "evidence_request", sender=self.agent_id, recipient=agent, incident_id=msg.incident_id,
                    in_reply_to=msg.message_id,
                    payload={"round": rnd, "requests": [r.model_dump(mode="json") for r in plan.requests[agent]],
                             "prediction_ids": plan.prediction_ids_by_agent.get(agent, []), "reason": "prediction"}))
            by_agent: dict[str, list[SignalRef]] = {}
            for agent, sref in extra:
                by_agent.setdefault(agent, []).append(sref)
            for agent in sorted(by_agent):
                outputs.append(make_message(
                    "evidence_request", sender=self.agent_id, recipient=agent, incident_id=msg.incident_id,
                    in_reply_to=msg.message_id,
                    payload={"round": rnd, "requests": [r.model_dump(mode="json") for r in by_agent[agent]],
                             "prediction_ids": [], "reason": "c2_refetch"}))
            for u in plan.uncovered:
                if u not in missing and dec.status != "no_fault_detected":
                    missing.append(u)

        top = hyps[0] if hyps else None
        diag = {
            "phase": "final" if task == "finalize" else "interim",
            "round": rnd,
            "status": dec.status,
            "status_reason": dec.reason,
            "hypotheses": [h.model_dump(mode="json") for h in hyps],
            "top_hypothesis_id": top.hypothesis_id if top and dec.status in ("diagnosed", "probable") else None,
            "co_candidate_ids": dec.co_candidates,
            "margin": dec.margin,
            "confidence": dec.confidence,
            "confidence_category": dec.category,
            "caps": dec.caps,
            "conflicts": conflicts,
            "predictions": [p.model_dump(mode="json") for p in predictions],
            "missing_signals": missing if dec.status != "no_fault_detected" else [],
            "anomalous_finding_count": len(anomalous),
            "scope": scope or None,
            "notes": pnotes + [f"coverage share {coverage_share:.2f}"],
        }
        outputs.insert(0, make_message("diagnosis", sender=self.agent_id, recipient="orchestrator",
                                       incident_id=msg.incident_id, in_reply_to=msg.message_id,
                                       status="completed", payload=diag))
        return outputs
