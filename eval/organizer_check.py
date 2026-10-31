"""Organizer-data evaluation: the RAW organizer generator (data/generator/organizer_generator.py, unmodified),
full pipeline, no preprocessing. Seed range A (tuning) and seed range B (report) are disjoint.

    python -m eval.organizer_check --seeds 500 --seed-a 0 --seed-b 100000

Each organizer label maps 1:1 to a NetCoop outcome (see data/generator/SCHEMA.md):
    normal -> no_fault_detected,  latency_spike -> latency_spike,  hardware_failure -> hardware_failure
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import random
import runpy
from collections import Counter
from pathlib import Path

from netcoop.config import ROOT, load_config, thaw
from netcoop.orchestrator.run import RunOptions, run_incident

GEN = ROOT / "data" / "generator" / "organizer_generator.py"
REPORTS = ROOT / "eval" / "reports"
LABEL_TO_FAULT = {"normal": None, "latency_spike": "latency_spike", "hardware_failure": "hardware_failure"}
FAULTS = tuple(LABEL_TO_FAULT)


def load_generator():
    with contextlib.redirect_stdout(io.StringIO()):  # the notebook prints an example on import
        return runpy.run_path(str(GEN))["generate_telemetry"]


def predicted(rep: dict) -> str:
    if rep["status"] in ("diagnosed", "probable"):
        return rep.get("fault_type") or "?"
    return rep["status"] + (f" ({rep['status_reason']})" if rep.get("status_reason") else "")


def run(seeds: int, seed0: int, cfg=None) -> dict:
    gen = load_generator()
    if cfg is None:
        base = load_config()
        agents = thaw(base.agents)
        agents["external"] = []  # the organizer data has no Wi-Fi telemetry
        cfg = base.with_overrides(agents=agents)
    per: dict = {}
    confusion: dict = {}
    for label in FAULTS:
        preds: Counter = Counter()
        committed = correct = quarantined = 0
        for seed in range(seed0, seed0 + seeds):
            random.seed(seed)
            rec = gen(label)  # raw record, exactly as the organizer generator emits it
            rep = run_incident(json.dumps(rec).encode(), cfg, RunOptions(persist=False, external=False)).report
            p = predicted(rep)
            preds[p] += 1
            quarantined += rep.get("normalization_summary", {}).get("records_quarantined", 0)
            is_committed = rep["status"] in ("diagnosed", "probable")
            committed += is_committed
            target = LABEL_TO_FAULT[label]
            correct += (rep["status"] == "no_fault_detected") if target is None else (is_committed and rep.get("fault_type") == target)
        per[label] = {"n": seeds, "accuracy": round(correct / seeds, 3), "committed_rate": round(committed / seeds, 3),
                      "records_quarantined": quarantined}
        confusion[label] = dict(sorted(preds.items()))
    n_fault = sum(per[f]["n"] for f in FAULTS if LABEL_TO_FAULT[f])
    wrong = sum(c for f in FAULTS for p, c in confusion[f].items()
                if (p in load_config().signatures or p == "?") and p != LABEL_TO_FAULT[f])
    healthy_faults = sum(c for f in FAULTS if LABEL_TO_FAULT[f] for p, c in confusion[f].items() if p.startswith("no_fault"))
    normal_fp = sum(c for p, c in confusion["normal"].items() if p in load_config().signatures)
    total = sum(per[f]["n"] for f in FAULTS)
    out = {"seed_start": seed0, "per_label": per, "confusion": confusion,
           "wrong_diagnosis_rate": round(wrong / total, 4),
           "fault_to_no_fault_rate": round(healthy_faults / max(1, n_fault), 4),
           "false_positive_rate_normal": round(normal_fp / per["normal"]["n"], 4),
           "overall_accuracy": round(sum(per[f]["accuracy"] * per[f]["n"] for f in FAULTS) / total, 4)}
    return out


def to_markdown(a: dict, b: dict) -> str:
    L = ["#### Organizer generator (raw, unmodified)", "",
         f"`data/generator/organizer_generator.py`, {b['per_label']['normal']['n']} seeds per label, one record per call, "
         f"full pipeline, no preprocessing. Seed range A (from seed {a['seed_start']}) was used for tuning; the "
         f"numbers below are **seed range B** (from seed {b['seed_start']}). Label → expected outcome: `normal` → "
         "`no_fault_detected`, `latency_spike` → `latency_spike`, `hardware_failure` → `hardware_failure` "
         "(derivation in `data/generator/SCHEMA.md`).", "",
         "| organizer label | n | correct | committed | records quarantined |", "|---|---|---|---|---|"]
    for f, v in b["per_label"].items():
        L.append(f"| `{f}` | {v['n']} | {v['accuracy']} | {v['committed_rate']} | {v['records_quarantined']} |")
    L += ["", f"Wrong-diagnosis rate {b['wrong_diagnosis_rate']}, real fault reported healthy {b['fault_to_no_fault_rate']}, "
          f"false positives on normal {b['false_positive_rate_normal']}.", "",
          "**Confusion (seed range B; rows = organizer label, columns = NetCoop output)**", ""]
    cols = sorted({p for row in b["confusion"].values() for p in row})
    L += ["| label \\ output | " + " | ".join(cols) + " |", "|---|" + "---|" * len(cols)]
    for f, row in b["confusion"].items():
        L.append(f"| `{f}` | " + " | ".join(str(row.get(c, 0)) for c in cols) + " |")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=500)
    ap.add_argument("--seed-a", type=int, default=0)
    ap.add_argument("--seed-b", type=int, default=100000)
    a = ap.parse_args()
    res_a = run(a.seeds, a.seed_a)
    print("A", json.dumps({k: v for k, v in res_a.items() if k != "confusion"}), res_a["confusion"])
    res_b = run(a.seeds, a.seed_b)
    print("B", json.dumps({k: v for k, v in res_b.items() if k != "confusion"}), res_b["confusion"])
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "organizer.json").write_text(json.dumps({"A": res_a, "B": res_b}, indent=2), encoding="utf-8")
    Path(REPORTS / "organizer.md").write_text(to_markdown(res_a, res_b), encoding="utf-8")
    print(f"wrote {REPORTS / 'organizer.md'}")


if __name__ == "__main__":
    main()
