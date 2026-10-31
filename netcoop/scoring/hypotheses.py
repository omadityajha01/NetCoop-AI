"""Hypothesis generation + documented scoring (CLAUDE.md §6.3).

    support  = Σ w_s [s ∈ E observed & matches]  / Σ w_s [s ∈ E]
    coverage = Σ w_s [s ∈ E observed]            / Σ w_s [s ∈ E]
    contra   = Σ w_c [c ∈ C observed & present]  / max(Σ w_c [c ∈ C], 1)
    quality  = max(floor, mean(completeness of used findings) − penalty × n_coerced_used)
    score    = clamp(support − contra_penalty × contra, 0, 1) × quality
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from netcoop.config import Config
from netcoop.protocol.findings import EntityRef, Finding, Hypothesis
from netcoop.scoring.thresholds import compare, threshold_value

FindingIndex = dict[tuple[str, str], list[Finding]]


def index_findings(findings: Iterable[Finding]) -> FindingIndex:
    idx: FindingIndex = defaultdict(list)
    for f in findings:
        idx[(f.metric, f.entity.id)].append(f)
    for v in idx.values():
        v.sort(key=lambda f: f.finding_id)
    return idx


def best_finding(idx: FindingIndex, metric: str, entities: Iterable[str], op: str) -> Finding | None:
    cands = [f for e in sorted(entities) for f in idx.get((metric, e), [])]
    if not cands:
        return None
    if op in (">=", ">"):
        return sorted(cands, key=lambda f: (-f.value, f.finding_id))[0]
    return sorted(cands, key=lambda f: (f.value, f.finding_id))[0]


def target_entities(cfg: Config, metric: str, entity_id: str) -> list[str]:
    """Entities (hypothesis entity first) where `metric` can be measured for this hypothesis."""
    topo = cfg.topology
    allowed = set(cfg.metrics[metric].get("entity_types", ()))
    return [e for e in topo.related_ordered(entity_id) if topo.type_of(e) in allowed]


def entity_fits(cfg: Config, fault_type: str, entity_id: str) -> bool:
    sig = cfg.signatures[fault_type]
    ent = cfg.topology.get(entity_id)
    if ent is None or ent.type not in sig["entity"]:
        return False
    kind = sig.get("service_kind")
    return not (kind and ent.kind != kind)


@dataclass
class SignalEval:
    metric: str
    kind: str  # expects | contradicts
    weight: float
    op: str
    ref: str
    finding: Finding | None
    matches: bool

    @property
    def observed(self) -> bool:
        return self.finding is not None


def evaluate_signals(cfg: Config, fault_type: str, entity_id: str, idx: FindingIndex) -> list[SignalEval]:
    sig = cfg.signatures[fault_type]
    rel = cfg.topology.related(entity_id)
    out: list[SignalEval] = []
    for kind in ("expects", "contradicts"):
        for metric, s in sorted(sig.get(kind, {}).items()):
            f = best_finding(idx, metric, rel, s["op"])
            matches = False
            if f is not None:
                thr = threshold_value(cfg, metric, f.entity.id, s["ref"])
                matches = thr is not None and compare(f.value, s["op"], thr)
            out.append(SignalEval(metric, kind, float(s["weight"]), s["op"], s["ref"], f, matches))
    return out


def score_hypothesis(cfg: Config, fault_type: str, entity_id: str, idx: FindingIndex,
                     quality_of: Callable[[Finding], float], source: str = "findings") -> Hypothesis:
    sc = cfg.scoring
    evals = evaluate_signals(cfg, fault_type, entity_id, idx)
    E = [e for e in evals if e.kind == "expects"]
    C = [e for e in evals if e.kind == "contradicts"]
    wE = sum(e.weight for e in E) or 1.0
    wC = sum(e.weight for e in C)
    support = sum(e.weight for e in E if e.matches) / wE
    coverage = sum(e.weight for e in E if e.observed) / wE
    contra = sum(e.weight for e in C if e.matches) / max(wC, 1.0)
    used = [e.finding for e in E if e.matches] + [e.finding for e in C if e.matches]
    used = [f for f in used if f is not None]
    if used:
        q = sum(quality_of(f) for f in used) / len(used) - float(sc["coerced_penalty"]) * sum(
            1 for f in used if f.data_quality.coerced)
        quality = max(float(sc["quality_floor"]), min(1.0, q))
    else:
        quality = 1.0
    score = max(0.0, min(1.0, support - float(sc["contra_penalty"]) * contra)) * quality
    missing = []
    for e in E:
        if not e.observed:
            tgt = target_entities(cfg, e.metric, entity_id)
            missing.append(f"{e.metric}@{tgt[0] if tgt else entity_id}")
    etype = cfg.topology.type_of(entity_id) or "device"
    return Hypothesis(
        hypothesis_id=f"H-{fault_type}-{entity_id}",
        fault_type=fault_type,
        entity=EntityRef(type=etype, id=entity_id),
        score=round(score, 4),
        support=round(support, 4),
        coverage=round(coverage, 4),
        contra=round(contra, 4),
        quality=round(quality, 4),
        supporting_finding_ids=sorted({e.finding.finding_id for e in E if e.matches and e.finding}),
        contradicting_finding_ids=sorted({e.finding.finding_id for e in C if e.matches and e.finding}),
        unmatched_finding_ids=sorted({e.finding.finding_id for e in evals if e.finding and not e.matches}),
        missing_signals=missing,
        source=source,
    )


def generate_candidates(cfg: Config, anomalous: list[Finding], ncu: str | None, scope_entities: list[str],
                        hints: list[str]) -> dict[tuple[str, str], str]:
    """(fault_type, entity_id) -> source. Candidates come only from anomalous findings, scope and hints."""
    topo = cfg.topology
    cands: dict[tuple[str, str], str] = {}
    triggered: set[str] = set()
    for f in anomalous:
        for ft, sig in cfg.signatures.items():
            if f.metric not in sig.get("expects", {}):
                continue
            triggered.add(ft)
            for e in sorted(topo.related(f.entity.id) | {f.entity.id}):
                if entity_fits(cfg, ft, e):
                    cands.setdefault((ft, e), "findings")
    if ncu:
        for ft in sorted(triggered):
            if entity_fits(cfg, ft, ncu):
                cands.setdefault((ft, ncu), "scope")
    pool = sorted(set(scope_entities) | ({ncu} if ncu else set()))
    for ft in sorted(set(hints) & set(cfg.signatures)):  # PI5: hints only ADD candidates
        for e in pool:
            for r in sorted(topo.related(e) | {e}):
                if entity_fits(cfg, ft, r):
                    cands.setdefault((ft, r), "hint")
    return cands


def rank_hypotheses(cfg: Config, cands: dict[tuple[str, str], str], idx: FindingIndex,
                    quality_of: Callable[[Finding], float]) -> list[Hypothesis]:
    """Score all candidates; keep the best-localized entity per fault type; rank by score."""
    best: dict[str, Hypothesis] = {}
    best_key: dict[str, tuple] = {}
    for (ft, e), src in sorted(cands.items()):
        h = score_hypothesis(cfg, ft, e, idx, quality_of, src)
        # ties go to the more specific entity type listed first in the signature (e.g. link before device)
        pref = list(cfg.signatures[ft]["entity"]).index(h.entity.type)
        key = (h.score, h.coverage, -len(h.missing_signals), -pref)
        if ft not in best or key > best_key[ft]:
            best[ft], best_key[ft] = h, key
    return sorted(best.values(), key=lambda h: (-h.score, -h.coverage, h.fault_type))
