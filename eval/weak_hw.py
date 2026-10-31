"""W1/W2: weakened organizer `hardware_failure` (measurement only).

    python -m eval.weak_hw --seeds 200 --seed-b 100000 [--out weak_hw]

The organizer generator is wrapped (eval/organizer_robustness.scaled), never edited. For each strength level and
held-out seed: status, confidence_category, status_reason, top cause, whether hardware_failure is listed in
alternative_causes, and the rank of the true label among all scored hypotheses.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from typing import Any

from eval.organizer_check import load_generator
from eval.organizer_robustness import _cfg, scaled
from netcoop.config import ROOT
from netcoop.orchestrator.run import RunOptions, run_incident

REPORTS = ROOT / "eval" / "reports"
TRUE = "hardware_failure"


def rank_of_true(rep: dict[str, Any]) -> int | None:
    """1 = top cause. Then co-candidates, then rejected alternatives by score. None = never hypothesized."""
    order: list[str] = []
    if rep.get("fault_type"):
        order.append(rep["fault_type"])
    order += [c["fault_type"] for c in rep.get("co_candidates", []) if c["fault_type"] not in order]
    for r in sorted(rep.get("rejected_alternatives", []), key=lambda r: -r["score"]):
        if r["fault_type"] not in order:
            order.append(r["fault_type"])
    return order.index(TRUE) + 1 if TRUE in order else None


def hw_in_alternatives(rep: dict[str, Any], label: str) -> bool:
    return any(a.startswith(label) for a in rep.get("alternative_causes", []))


def run(levels: tuple[float, ...], seeds: int, seed0: int) -> dict[str, Any]:
    gen, cfg = load_generator(), _cfg()
    label = str(cfg.signatures[TRUE]["label"])
    out: dict[str, Any] = {"levels": {}, "incidents": {}}
    for lv in levels:
        st, cat, why, top, ranks = Counter(), Counter(), Counter(), Counter(), Counter()
        in_alt = top2 = 0
        rows = []
        for s in range(seed0, seed0 + seeds):
            random.seed(s)
            rep = run_incident(json.dumps(scaled(gen, TRUE, lv)).encode(), cfg, RunOptions(persist=False, external=False)).report
            r = rank_of_true(rep)
            is_top = rep.get("fault_type") == TRUE
            alt = hw_in_alternatives(rep, label)
            st[rep["status"]] += 1
            cat[rep["confidence_category"]] += 1
            why[rep.get("status_reason") or "-"] += 1
            top[rep.get("fault_type") or rep["status"]] += 1
            ranks[str(r) if r else "absent"] += 1
            in_alt += alt
            top2 += bool(is_top or alt or (r is not None and r <= 2 and alt))
            rows.append({"seed": s, "status": rep["status"], "category": rep["confidence_category"],
                         "reason": rep.get("status_reason"), "top": rep.get("fault_type") or rep["status"],
                         "hw_in_alternatives": alt, "rank": r, "confidence": rep["confidence"],
                         "suspected_root_cause": rep["suspected_root_cause"], "affected_devices": rep["affected_devices"],
                         "alternative_causes": rep["alternative_causes"]})
        not_top = seeds - top[TRUE]
        out["levels"][str(lv)] = {
            "n": seeds, "status": dict(st), "confidence_category": dict(cat), "status_reason": dict(why),
            "top_cause": dict(top.most_common()), "rank_of_true": dict(sorted(ranks.items())),
            "hw_in_alternatives": in_alt, "hw_missing_from_alternatives_when_not_top": round(
                sum(1 for x in rows if x["top"] != TRUE and not x["hw_in_alternatives"]) / max(1, not_top), 3),
            "true_in_top2_shown": round(sum(1 for x in rows if x["top"] == TRUE or x["hw_in_alternatives"]) / seeds, 3),
        }
        out["incidents"][str(lv)] = rows
        print(lv, json.dumps(out["levels"][str(lv)]))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--seed-b", type=int, default=100000)
    ap.add_argument("--levels", default="0.25,0.5")
    ap.add_argument("--out", default="weak_hw")
    a = ap.parse_args()
    res = run(tuple(float(x) for x in a.levels.split(",")), a.seeds, a.seed_b)
    (REPORTS / f"{a.out}.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(f"wrote {REPORTS / (a.out + '.json')}")


if __name__ == "__main__":
    main()
