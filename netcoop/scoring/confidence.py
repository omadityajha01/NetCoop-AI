"""Status rules + confidence category + caps (CLAUDE.md §6.3)."""

from __future__ import annotations

from dataclasses import dataclass, field

from netcoop.config import Config
from netcoop.protocol.findings import Hypothesis


@dataclass
class Decision:
    status: str
    confidence: float
    category: str
    margin: float
    co_candidates: list[str] = field(default_factory=list)
    caps: list[str] = field(default_factory=list)


def category_for(cfg: Config, confidence: float, margin: float) -> str:
    c = cfg.scoring["confidence"]
    if confidence >= float(c["high_min"]) and margin >= float(c["high_min_margin"]):
        return "high"
    if confidence >= float(c["medium_min"]):
        return "medium"
    return "low"


def decide(cfg: Config, hyps: list[Hypothesis], *, anomalous_count: int, usable_observations: int,
           failed_agents: list[str], unresolved_c2: bool, data_coverage: float) -> Decision:
    st = cfg.scoring["status"]
    top = hyps[0] if hyps else None
    second = hyps[1] if len(hyps) > 1 else None
    max_score = top.score if top else 0.0
    margin = round(max_score - (second.score if second else 0.0), 4)
    caps: list[str] = []
    if usable_observations == 0:
        status, conf = "insufficient_evidence", 0.0
    elif anomalous_count == 0 and max_score < float(st["no_fault_max_score"]):
        status = "no_fault_detected"
        # confidence in "no fault" = (1 - best fault score) x share of analysis agents that reported coverage
        conf = round((1.0 - max_score) * data_coverage, 2)
    elif top is None or top.score < float(st["min_top_score"]) or top.coverage < float(st["min_top_coverage"]):
        status, conf = "insufficient_evidence", round(max_score, 2)
    elif margin < float(st["min_margin"]):
        status, conf = "probable", round(top.score, 2)
    else:
        status, conf = "diagnosed", round(top.score, 2)
    cat = category_for(cfg, conf, margin if status not in ("no_fault_detected",) else 1.0)
    if status == "insufficient_evidence":
        cat = "low"
    if failed_agents:
        caps.append(f"agent(s) failed: {', '.join(sorted(failed_agents))}")
    if unresolved_c2:
        caps.append("unresolved C2 state conflict")
    if caps and cat == "high":
        cat = "medium"
    co = [h.hypothesis_id for h in hyps[:2]] if status == "probable" else []
    return Decision(status=status, confidence=conf, category=cat, margin=margin, co_candidates=co, caps=caps)
