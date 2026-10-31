"""reporting_agent: PS-format report, playbook actions, policy check, limitations.

PS fields are kept exactly; NetCoop extensions are additive.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from netcoop.agents.base import FindingsTool, ReadOnlyContext
from netcoop.agents.correlation import derive_state
from netcoop.config import Config
from netcoop.policy.checker import check_action
from netcoop.policy.validator import scrub
from netcoop.protocol.envelope import SCHEMA_VERSION, Message, error_message, make_message
from netcoop.protocol.findings import Finding, Hypothesis, Prediction
from netcoop.scoring.thresholds import threshold_value

SYNTHETIC = "Synthetic telemetry (organizer generator schema + NetCoop extensions); not campus measurements"
VERIFY = "Root cause requires further verification by an operator before any change"


def interpretation(cfg: Config, f: Finding) -> str:
    label = cfg.metrics[f.metric]["label"]
    word = {"normal": "Normal", "warn": "Elevated", "high": "High", "critical": "Critical"}[f.severity]
    if cfg.metrics[f.metric]["direction"] == "lower_is_worse" and f.severity != "normal":
        word = {"warn": "Degraded", "high": "Poor", "critical": "Very poor"}[f.severity]
    return f"{word} {label}"


def _primary_device(cfg: Config, h: Hypothesis, fmap: dict[str, Finding]) -> str:
    topo = cfg.topology
    if h.entity.type != "link":
        return h.entity.id
    ends = topo.devices_of(h.entity.id)
    counts = {e: sum(1 for fid in h.supporting_finding_ids if fid in fmap and fmap[fid].entity.id == e) for e in ends}
    return sorted(ends, key=lambda e: (-counts[e], ends.index(e)))[0]


def _fmt(text: str, **kw: str) -> str:
    out = text
    for k, v in kw.items():
        out = out.replace("{" + k + "}", v)
    return out


def build_actions(cfg: Config, keys: list[str], h: Hypothesis | None, at: datetime, fmap: dict[str, Finding]
                  ) -> tuple[list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    recommended, blocked, details = [], [], []
    seen: set[str] = set()
    for key in keys:
        for a in cfg.playbook.get(key, {}).get("actions", ()):
            if a["id"] in seen:
                continue
            seen.add(a["id"])
            if h is not None:
                device = _primary_device(cfg, h, fmap)
                text = _fmt(a["text"], entity=h.entity.id, device=device,
                            segment=cfg.topology.segment_of(h.entity.id) or "the segment")
                target = device if a.get("target") == "device" else None
            else:
                text, target = a["text"], None
            res = check_action(cfg, a["action"], target, at)
            details.append({"id": a["id"], "action": a["action"], "target": target, "text": text,
                            "allowed": res.allowed, "rule_id": res.rule_id})
            if res.allowed:
                recommended.append(text)
            else:
                blocked.append({"action": text, "action_id": a["id"], "rule_id": res.rule_id,
                                "reason": f"{a['action'].replace('_', ' ').capitalize()} {target}: blocked by {res.rule_id} ({res.reason})"})
    return recommended, blocked, details


class ReportingAgent:
    agent_id = "reporting_agent"
    capabilities = ["report", "playbook", "policy_check"]

    def __init__(self, cfg: Any = None):
        pass

    def handle(self, msg: Message, ctx: ReadOnlyContext) -> list[Message]:
        if msg.message_type != "task_request" or msg.payload.get("task") != "report":
            return [error_message(sender=self.agent_id, recipient=msg.sender, incident_id=msg.incident_id,
                                  code="MALFORMED", detail="reporting_agent handles task_request report",
                                  offending_message_id=msg.message_id)]
        report = build_report(ctx, msg.payload.get("params", {}))
        return [make_message("report", sender=self.agent_id, recipient="orchestrator", incident_id=msg.incident_id,
                             in_reply_to=msg.message_id, payload={"report": report})]


def build_report(ctx: ReadOnlyContext, params: dict[str, Any]) -> dict[str, Any]:
    cfg = ctx.config
    view: FindingsTool = ctx.tool("findings")
    msgs = view.all()
    st = derive_state(msgs)
    fmap: dict[str, Finding] = {f.finding_id: f for f in st["findings"]}
    agent_of = st["agent_of"]
    diags = [m for m in msgs if m.message_type == "diagnosis"]
    final = next((m for m in reversed(diags) if m.payload.get("phase") == "final"), diags[-1] if diags else None)
    norm = st["norm"] or {}
    limitations: list[str] = [SYNTHETIC]

    if final is None:  # correlation failed: still produce a report with raw findings
        anomalous = [f for f in st["findings"] if f.anomalous]
        ev = [{"metric": f.metric, "value": f.value, "unit": f.unit, "entity": f.entity.id,
               "interpretation": interpretation(cfg, f), "finding_id": f.finding_id} for f in anomalous[:10]]
        limitations.append("correlation_agent failed: raw anomalous findings reported without diagnosis")
        return _assemble(ctx, status="failed", root="Diagnosis failed; raw findings attached", confidence=0.0,
                         category="low", affected=[], evidence=ev, alternatives=[], actions=[], sources=sorted({agent_of[f.finding_id] for f in anomalous}),
                         limitations=limitations, extras={}, norm=norm)

    d = final.payload
    hyps = [Hypothesis.model_validate(h) for h in d["hypotheses"]]
    hmap = {h.hypothesis_id: h for h in hyps}
    preds = [Prediction.model_validate(p) for p in d["predictions"]]
    status = d["status"]
    top = hmap.get(d.get("top_hypothesis_id") or "")
    co = [hmap[i] for i in d.get("co_candidate_ids", []) if i in hmap]
    at = datetime.fromisoformat(norm["incident_time"].replace("Z", "+00:00")) if norm.get("incident_time") else ctx.incident_time

    def label(h: Hypothesis) -> str:
        return str(cfg.signatures[h.fault_type]["label"])

    # ---- root cause + affected
    if status == "diagnosed" and top:
        root = f"{label(top)} on {top.entity.id}"
    elif status == "probable" and len(co) >= 2:
        root = f"{label(co[0])} on {co[0].entity.id} (co-candidate: {label(co[1])[0].lower() + label(co[1])[1:]} on {co[1].entity.id})"
        top = co[0]
    elif status == "no_fault_detected":
        root = "No fault detected: measurements within expected ranges"
    elif d.get("status_reason") == "no_signature_match":
        root = "Insufficient evidence: anomaly present, but no known fault signature matches"
    else:
        root = "Insufficient evidence: data missing to determine a root cause"

    primary = [top] + [h for h in co if h is not top] if top else []
    evidence: list[dict[str, Any]] = []
    ev_ids: set[str] = set()
    for h in primary:
        for fid in h.supporting_finding_ids:
            if fid in fmap and fid not in ev_ids:
                f = fmap[fid]
                ev_ids.add(fid)
                evidence.append({"metric": f.metric, "value": f.value, "unit": f.unit, "entity": f.entity.id,
                                 "interpretation": interpretation(cfg, f), "finding_id": fid,
                                 "source_agent": agent_of.get(fid), "hypothesis": h.fault_type})
    for p in preds:
        if p.outcome == "hit" and p.evidence_finding_id in fmap and p.evidence_finding_id not in ev_ids and top and \
                p.hypothesis_id in {h.hypothesis_id for h in primary}:
            f = fmap[p.evidence_finding_id]
            ev_ids.add(f.finding_id)
            evidence.append({"metric": f.metric, "value": f.value, "unit": f.unit, "entity": f.entity.id,
                             "interpretation": f"{interpretation(cfg, f)} (prediction {p.prediction_id} hit)",
                             "finding_id": f.finding_id, "source_agent": agent_of.get(f.finding_id),
                             "hypothesis": p.fault_type})
    if status == "insufficient_evidence":
        for f in [f for f in st["findings"] if f.anomalous][:8]:
            if f.finding_id not in ev_ids:
                ev_ids.add(f.finding_id)
                evidence.append({"metric": f.metric, "value": f.value, "unit": f.unit, "entity": f.entity.id,
                                 "interpretation": interpretation(cfg, f), "finding_id": f.finding_id,
                                 "source_agent": agent_of.get(f.finding_id), "hypothesis": None})

    topo = cfg.topology
    affected: list[str] = []
    if primary:
        for h in primary:
            if h.entity.type in ("device", "ap", "service"):
                affected.append(h.entity.id)
            for fid in h.supporting_finding_ids:
                e = fmap[fid].entity.id if fid in fmap else None
                if e and topo.type_of(e) in ("device", "ap", "service"):
                    affected.append(e)
            if h.entity.type == "link" and not any(topo.type_of(a) == "device" for a in affected):
                affected.append(topo.devices_of(h.entity.id)[0])
    elif status == "insufficient_evidence":
        affected = list((d.get("scope") or {}).get("affected_devices", []))
    affected = sorted(set(affected))

    # ---- alternatives
    rejected = []
    alternatives = []
    for h in hyps:
        if h in primary:
            continue
        if h.score > 0:
            alternatives.append(f"{label(h)} on {h.entity.id} (score {h.score:.2f})")
        reason = _reject_reason(cfg, h, fmap)
        rejected.append({"fault_type": h.fault_type, "entity": h.entity.id, "score": round(h.score, 2), "reason": reason})

    # ---- actions
    if status in ("diagnosed", "probable") and top:
        keys = [cfg.signatures[h.fault_type]["playbook"] for h in primary]
        recommended, blocked, details = build_actions(cfg, keys, top, at, fmap)
        if len(primary) > 1:  # probable: second candidate actions are generated against its own entity
            r2, b2, d2 = build_actions(cfg, [cfg.signatures[primary[1].fault_type]["playbook"]], primary[1], at, fmap)
            recommended = [r for r in recommended if r not in r2] + [r for r in r2 if r not in recommended]
            recommended = list(dict.fromkeys(recommended))
            blocked += [b for b in b2 if b not in blocked]
            details += d2
    elif status == "no_fault_detected":
        recommended, blocked, details = build_actions(cfg, ["_no_fault"], None, at, fmap)
    else:
        recommended, blocked, details = build_actions(cfg, ["_insufficient_evidence"], None, at, fmap)
        if d.get("missing_signals"):
            recommended.append("Collect: " + ", ".join(d["missing_signals"][:8]))

    # ---- sources
    sources = sorted({e["source_agent"] for e in evidence if e.get("source_agent")})
    if not sources:
        sources = sorted(st["covering_agents"])

    # ---- limitations
    if status in ("diagnosed", "probable"):
        limitations.append(VERIFY)
    if status == "probable":
        limitations.append(f"Margin {d['margin']:.2f} below {cfg.scoring['status']['min_margin']} after prediction rounds; "
                           "two co-candidates reported")
    if status == "insufficient_evidence" and d.get("status_reason") == "no_signature_match":
        best = hyps[0] if hyps else None
        limitations.append("Anomaly present (finding at or above `high`), but no known fault signature matches"
                           + (f" (best: {best.fault_type} {best.score:.2f} < {cfg.scoring['status']['min_top_score']})"
                              if best else ""))
    if status == "insufficient_evidence" and d.get("status_reason") == "data_missing":
        limitations.append("Data missing: the leading hypothesis has less than "
                           f"{cfg.scoring['status']['min_top_coverage']:.0%} of its expected signals observed")
    if status == "insufficient_evidence" and d.get("missing_signals"):
        uncovered = [s for s in d["missing_signals"] if tuple(s.split("@", 1)) not in st["coverage"]]
        limitations.append("Missing signals that would resolve this: " + ", ".join(d["missing_signals"][:8]))
        if uncovered:
            limitations.append("No connected agent can provide: " + ", ".join(uncovered[:8]))
    for m in msgs:
        if m.message_type == "error" and m.payload.get("agent_id"):
            limitations.append(f"{m.payload['agent_id']} failed: {m.payload.get('detail', '')[:160]}")
        for lim in m.limitations:
            if m.sender != "orchestrator" and lim.impact in ("low", "medium", "high"):
                limitations.append(f"{m.sender}: {lim.detail}")
    for agent, state in sorted((params.get("external") or {}).items()):
        if state != "joined":
            limitations.append(f"External agent {agent} {state}; its signals were unavailable")
    for p in preds:
        if p.outcome == "unknown":
            limitations.append(f"Prediction {p.prediction_id} ({p.signal.metric}@{p.signal.entity.id}) could not be checked")
    for c in d.get("conflicts", []):
        if c["type"] in ("C1", "C2"):
            limitations.append(f"{c['type']} conflict: {c['detail']} -> {c['resolution']}")
    for cap in d.get("caps", []):
        limitations.append(f"Confidence capped: {cap}")
    stale = sorted({f.metric + "@" + f.entity.id for f in st["findings"]
                    if f.finding_id in ev_ids and f.data_quality.staleness_s > float(cfg.agents["data"]["staleness_threshold_s"])})
    if stale:
        limitations.append("Stale evidence used: " + ", ".join(stale[:6]))
    limitations = list(dict.fromkeys(scrub(x)[:300] for x in limitations))

    # ---- extensions
    shown = top or (hyps[0] if hyps else None)
    scoring = ({"support": shown.support, "coverage": shown.coverage, "contra": shown.contra, "quality": shown.quality,
                "score": shown.score, "margin": d["margin"]} if shown else
               {"support": 0.0, "coverage": 0.0, "contra": 0.0, "quality": 1.0, "score": 0.0, "margin": d["margin"]})
    predictions = []
    for p in preds:
        thr = threshold_value(cfg, p.signal.metric, p.signal.entity.id, p.expected.ref)
        obs = fmap.get(p.evidence_finding_id or "")
        predictions.append({
            "prediction_id": p.prediction_id, "round": p.round, "hypothesis": p.fault_type,
            "signal": f"{p.signal.metric}@{p.signal.entity.id}",
            "expected": f"{p.expected.op} {p.expected.ref}" + (f" ({thr:g} {cfg.metrics[p.signal.metric]['unit']})" if thr is not None else ""),
            "outcome": p.outcome, "observed": obs.value if obs else None, "evidence_finding_id": p.evidence_finding_id,
        })
    observations = [{"metric": f.metric, "value": f.value, "unit": f.unit, "entity": f.entity.id,
                     "severity": f.severity, "interpretation": interpretation(cfg, f), "finding_id": f.finding_id}
                    for f in st["findings"] if f.anomalous and f.finding_id not in ev_ids][:20]
    if status == "no_fault_detected" and observations:
        limitations.append(f"{len(observations)} warn-level reading(s) below fault thresholds listed under `observations` "
                           "(context only, not evidence)")
    extras = {
        "status_reason": d.get("status_reason"),
        "observations": observations,
        "fault_type": top.fault_type if top and status in ("diagnosed", "probable") else None,
        "confidence_category": d["confidence_category"],
        "scoring": scoring,
        "co_candidates": [{"fault_type": h.fault_type, "entity": h.entity.id, "score": round(h.score, 2)} for h in co],
        "rejected_alternatives": rejected,
        "predictions": predictions,
        "blocked_actions": blocked,
        "action_details": details,
        "missing_signals": d.get("missing_signals", []),
        "conflicts": [{"id": c["conflict_id"], "type": c["type"], "detail": scrub(c["detail"]), "resolution": c["resolution"],
                       "resolved": c["resolved"]} for c in d.get("conflicts", [])],
        "agents": _agent_status(cfg, st, params),
    }
    return _assemble(ctx, status=status, root=root, confidence=float(d["confidence"]), category=d["confidence_category"],
                     affected=affected, evidence=evidence, alternatives=alternatives, actions=recommended, sources=sources,
                     limitations=limitations, extras=extras, norm=norm)


def _reject_reason(cfg: Config, h: Hypothesis, fmap: dict[str, Finding]) -> str:
    if h.contradicting_finding_ids:
        f = fmap.get(h.contradicting_finding_ids[0])
        if f:
            return f"contradicted: {f.metric} {f.value:g} {f.unit} on {f.entity.id} ({f.finding_id})"
    sig = cfg.signatures[h.fault_type]["expects"]
    for fid in h.unmatched_finding_ids:
        f = fmap.get(fid)
        if f and f.metric in sig:
            return f"expected {f.metric} {sig[f.metric]['op']} {sig[f.metric]['ref']}, observed {f.value:g} {f.unit} ({fid})"
    if h.missing_signals:
        return "insufficient support; missing " + ", ".join(h.missing_signals[:3])
    return f"lower score ({h.score:.2f})"


def _agent_status(cfg: Config, st: dict[str, Any], params: dict[str, Any]) -> dict[str, str]:
    out = {}
    for a in st["asked"]:
        out[a] = "failed" if a in st["failed"] else ("completed" if a in st["covering_agents"] else "no_data")
    for a, s in (params.get("external") or {}).items():
        if a not in out:
            out[a] = s
    for a in ("correlation_agent", "reporting_agent"):
        out[a] = "failed" if a in st["failed"] else "completed"
    return dict(sorted(out.items()))


def _assemble(ctx: ReadOnlyContext, *, status: str, root: str, confidence: float, category: str, affected: list[str],
              evidence: list[dict[str, Any]], alternatives: list[str], actions: list[str], sources: list[str],
              limitations: list[str], extras: dict[str, Any], norm: dict[str, Any]) -> dict[str, Any]:
    summary = norm.get("summary", {})
    return {
        "incident_id": ctx.incident_id,
        "status": status,
        "suspected_root_cause": root,
        "confidence": round(confidence, 2),
        "affected_devices": affected,
        "supporting_evidence": evidence,
        "alternative_causes": alternatives,
        "recommended_actions": actions,
        "evidence_sources": sources,
        "limitations": limitations,
        "schema_version": SCHEMA_VERSION,
        "confidence_category": category,
        **{k: v for k, v in extras.items()},
        "normalization_summary": {k: summary.get(k, 0) for k in (
            "records_in", "records_used", "records_quarantined", "observations_used", "renamed", "unit_converted",
            "unit_inferred", "entity_canonicalized", "coerced", "quarantined", "missing_values", "deduped",
            "out_of_window", "version_upcast", "extras")},
        "narrative": None,
    }
