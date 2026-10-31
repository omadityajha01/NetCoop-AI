"""Predict before you look (CLAUDE.md §6.2).

P1 a prediction may only reference a signal not already in that hypothesis's evidence.
P2 the prediction is logged BEFORE its evidence_request; scoring rejects predictions whose seq is
   greater than the matching evidence_response's seq (enforced here, tested).
P3 discriminating signals first (top two hypotheses expect opposite outcomes); ≤3 per round, ≤2 rounds.
P4 hits/misses enter scoring as ordinary observed evidence; unknown lowers coverage + limitation.
P5 every prediction is reported with its outcome.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from netcoop.config import Config
from netcoop.protocol.envelope import Message
from netcoop.protocol.findings import (
    EntityRef,
    Expectation,
    Finding,
    Hypothesis,
    Prediction,
    SignalRef,
    Window,
)
from netcoop.scoring.hypotheses import FindingIndex, best_finding, target_entities
from netcoop.scoring.thresholds import NEGATE, compare, threshold_value


@dataclass
class Plan:
    predictions: list[Prediction] = field(default_factory=list)
    requests: dict[str, list[SignalRef]] = field(default_factory=dict)  # agent_id -> signals
    prediction_ids_by_agent: dict[str, list[str]] = field(default_factory=dict)
    uncovered: list[str] = field(default_factory=list)


def _sig(cfg: Config, h: Hypothesis) -> dict:
    return cfg.signatures[h.fault_type]


def _priority(cfg: Config, metric: str, top: Hypothesis, second: Hypothesis | None) -> int:
    st = _sig(cfg, top)
    if second is None:
        return 1 if metric in st.get("contradicts", {}) else 0
    ss = _sig(cfg, second)
    e1, c1 = metric in st.get("expects", {}), metric in st.get("contradicts", {})
    e2, c2 = metric in ss.get("expects", {}), metric in ss.get("contradicts", {})
    if (e1 and c2) or (c1 and e2):
        return 3  # opposite expectations: strictly discriminating
    if e1 != e2:
        return 2
    if c1 != c2:
        return 1
    return 0


def plan_round(cfg: Config, hyps: list[Hypothesis], idx: FindingIndex, coverage: dict[tuple[str, str], str],
               rnd: int, already_predicted: set[str], window: Window, extra_requests: list[tuple[str, SignalRef]] | None = None
               ) -> Plan:
    rounds = cfg.agents["rounds"]
    max_p = int(rounds["max_predictions_per_round"])
    max_r = int(rounds["max_evidence_requests_per_round"])
    plan = Plan()
    if not hyps:
        return plan
    top = hyps[0]
    second = hyps[1] if len(hyps) > 1 else None
    pool: list[tuple[int, float, str, Hypothesis, str, dict]] = []
    for h in [top] + ([second] if second else []):
        sig = _sig(cfg, h)
        for kind in ("expects", "contradicts"):
            for metric, spec in sig.get(kind, {}).items():
                prio = _priority(cfg, metric, top, second)
                if h is second:
                    prio -= 1  # top hypothesis predictions first
                pool.append((prio, float(spec["weight"]), metric, h, kind, dict(spec)))
    pool.sort(key=lambda x: (-x[0], -x[1], x[2], x[3].fault_type))
    n_req = 0
    seen_signals: set[str] = set()

    def add_request(agent: str, sref: SignalRef) -> bool:
        nonlocal n_req
        key = f"{agent}|{sref.key()}"
        if key in seen_signals:
            return True
        if n_req >= max_r:
            return False
        seen_signals.add(key)
        plan.requests.setdefault(agent, []).append(sref)
        n_req += 1
        return True

    for (sig_key, sref) in extra_requests or []:
        add_request(sig_key, sref)

    for prio, _w, metric, h, kind, spec in pool:
        if len(plan.predictions) >= max_p:
            break
        if prio < 0:
            continue
        rel = cfg.topology.related(h.entity.id)
        if best_finding(idx, metric, rel, spec["op"]) is not None:
            continue  # P1: already in this hypothesis's evidence
        targets = [e for e in target_entities(cfg, metric, h.entity.id) if (metric, e) in coverage]
        if not targets:
            miss = f"{metric}@{(target_entities(cfg, metric, h.entity.id) or [h.entity.id])[0]}"
            if miss not in plan.uncovered:
                plan.uncovered.append(miss)
            continue
        ent = targets[0]
        key = f"{h.hypothesis_id}|{metric}@{ent}"
        if key in already_predicted:
            continue
        op = spec["op"] if kind == "expects" else NEGATE[spec["op"]]
        etype = cfg.topology.type_of(ent) or "device"
        sref = SignalRef(metric=metric, entity=EntityRef(type=etype, id=ent), window=window)
        agent = coverage[(metric, ent)]
        if not add_request(agent, sref):
            break
        pid = f"P-{rnd}-{len(plan.predictions) + 1}"
        plan.predictions.append(Prediction(prediction_id=pid, hypothesis_id=h.hypothesis_id, fault_type=h.fault_type,
                                           signal=sref, expected=Expectation(op=op, ref=spec["ref"]), round=rnd))
        plan.prediction_ids_by_agent.setdefault(agent, []).append(pid)
        already_predicted.add(key)

    # fill remaining request budget with unobserved expected signals of the top two (coverage, no prediction)
    for h in [top] + ([second] if second else []):
        for metric, spec in _sig(cfg, h).get("expects", {}).items():
            if n_req >= max_r:
                break
            rel = cfg.topology.related(h.entity.id)
            if best_finding(idx, metric, rel, spec["op"]) is not None:
                continue
            targets = [e for e in target_entities(cfg, metric, h.entity.id) if (metric, e) in coverage]
            if not targets:
                miss = f"{metric}@{(target_entities(cfg, metric, h.entity.id) or [h.entity.id])[0]}"
                if miss not in plan.uncovered:
                    plan.uncovered.append(miss)
                continue
            ent = targets[0]
            etype = cfg.topology.type_of(ent) or "device"
            add_request(coverage[(metric, ent)], SignalRef(metric=metric, entity=EntityRef(type=etype, id=ent), window=window))
    return plan


def resolve_outcomes(cfg: Config, messages: list[Message]) -> tuple[list[Prediction], list[str]]:
    """Derive outcomes from the log. Returns (predictions, notes). Enforces P2 by seq."""
    preds: list[tuple[int, Prediction]] = []
    for m in messages:
        if m.message_type == "prediction":
            preds.append((m.seq or 0, Prediction.model_validate(m.payload["prediction"])))
    reqs = {m.message_id: m for m in messages if m.message_type == "evidence_request"}
    resps = [m for m in messages if m.message_type == "evidence_response"]
    notes: list[str] = []
    out: list[Prediction] = []
    for pseq, p in sorted(preds, key=lambda x: x[0]):
        req = next((r for r in reqs.values() if p.prediction_id in r.payload.get("prediction_ids", [])), None)
        resp = next((r for r in resps if req and r.in_reply_to == req.message_id), None)
        if req is None or resp is None:
            out.append(p.model_copy(update={"outcome": "unknown" if req is not None else "pending"}))
            continue
        if not (pseq < (req.seq or 0) < (resp.seq or 0)) or pseq > (resp.seq or 0):
            notes.append(f"prediction {p.prediction_id} rejected: logged after its evidence (P2)")
            out.append(p.model_copy(update={"outcome": "unknown"}))
            continue
        match = [Finding.model_validate(f) for f in resp.payload.get("findings", [])
                 if f["metric"] == p.signal.metric and f["entity"]["id"] == p.signal.entity.id]
        if not match:
            out.append(p.model_copy(update={"outcome": "unknown"}))
            continue
        f = sorted(match, key=lambda x: (-x.value if p.expected.op in (">=", ">", "<") else x.value, x.finding_id))[0]
        thr = threshold_value(cfg, p.signal.metric, p.signal.entity.id, p.expected.ref)
        if thr is None:
            out.append(p.model_copy(update={"outcome": "unknown", "evidence_finding_id": f.finding_id}))
            continue
        ok = compare(f.value, p.expected.op, thr)
        out.append(p.model_copy(update={"outcome": "hit" if ok else "miss", "evidence_finding_id": f.finding_id}))
    return out, notes
