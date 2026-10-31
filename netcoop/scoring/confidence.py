"""Status rules + confidence category + caps (CLAUDE.md §6.3, revised T1).

Status rules, evaluated in order:
  0. no usable observations                                          -> insufficient_evidence (data_missing)
  a. coverage(top) < min_top_coverage                                -> insufficient_evidence (data_missing)
  b. no finding >= high  AND  top score < min_top_score              -> no_fault_detected (warn findings -> `observations`)
  c. some finding >= high AND  top score < min_top_score             -> insufficient_evidence (no_signature_match)
  d. margin < min_margin                                             -> probable
     otherwise                                                       -> diagnosed
"""

from __future__ import annotations

from dataclasses import dataclass, field

from netcoop.config import Config
from netcoop.protocol.findings import Hypothesis

DATA_MISSING = "data_missing"
NO_SIGNATURE_MATCH = "no_signature_match"


@dataclass
class Decision:
    status: str
    confidence: float
    category: str
    margin: float
    co_candidates: list[str] = field(default_factory=list)
    caps: list[str] = field(default_factory=list)
    reason: str | None = None


def category_for(cfg: Config, confidence: float, margin: float) -> str:
    c = cfg.scoring["confidence"]
    if confidence >= float(c["high_min"]) and margin >= float(c["high_min_margin"]):
        return "high"
    if confidence >= float(c["medium_min"]):
        return "medium"
    return "low"


def decide(cfg: Config, hyps: list[Hypothesis], *, high_count: int, usable_observations: int,
           failed_agents: list[str], unresolved_c2: bool, data_coverage: float,
           extra_caps: list[str] | None = None) -> Decision:
    """`high_count` = number of active findings with severity >= high."""
    st = cfg.scoring["status"]
    top = hyps[0] if hyps else None
    second = hyps[1] if len(hyps) > 1 else None
    max_score = top.score if top else 0.0
    margin = round(max_score - (second.score if second else 0.0), 4)
    min_top = float(st["min_top_score"])
    caps: list[str] = []
    reason: str | None = None
    if usable_observations == 0:
        status, conf, reason = "insufficient_evidence", 0.0, DATA_MISSING
    elif top is not None and top.coverage < float(st["min_top_coverage"]):
        status, conf, reason = "insufficient_evidence", round(max_score, 2), DATA_MISSING
    elif top is None or top.score < min_top:
        if high_count == 0:
            status = "no_fault_detected"
            # confidence in "no fault" = (1 - best fault score) x share of analysis agents that reported coverage
            conf = round((1.0 - max_score) * data_coverage, 2)
        else:
            status, conf, reason = "insufficient_evidence", round(max_score, 2), NO_SIGNATURE_MATCH
    elif margin < float(st["min_margin"]):
        status, conf = "probable", round(top.score, 2)
    else:
        status, conf = "diagnosed", round(top.score, 2)
    cat = category_for(cfg, conf, margin if status != "no_fault_detected" else 1.0)
    if status == "insufficient_evidence":
        cat = "low"
    if failed_agents:
        caps.append(f"agent(s) failed: {', '.join(sorted(failed_agents))}")
    if unresolved_c2:
        caps.append("unresolved C2 state conflict")
    if status in ("diagnosed", "probable"):
        caps.extend(extra_caps or [])
    if caps and cat == "high":
        cat = "medium"
    co = [h.hypothesis_id for h in hyps[:2]] if status == "probable" else []
    return Decision(status=status, confidence=conf, category=cat, margin=margin, co_candidates=co, caps=caps, reason=reason)
