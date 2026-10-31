"""Organizer-data truth check: the RAW organizer generator (data/generator/organizer_generator.py, unmodified),
>= 500 seeds per fault type, full pipeline, no preprocessing.

    python -m eval.organizer_check --seeds 500

The organizer generator has 3 fault types and no ground-truth mapping to NetCoop's fault signatures, so:
  * `normal` is scored against `no_fault_detected` (exact).
  * `latency_spike` / `hardware_failure` are scored on *detection* (status != no_fault_detected) and the full
    output distribution is reported. No signature label is claimed for them.
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
FAULTS = ("normal", "latency_spike", "hardware_failure")


def load_generator():
    with contextlib.redirect_stdout(io.StringIO()):  # the notebook prints an example on import
        return runpy.run_path(str(GEN))["generate_telemetry"]


def run(seeds: int) -> dict:
    gen = load_generator()
    base = load_config()
    agents = thaw(base.agents)
    agents["external"] = []  # the organizer data has no Wi-Fi telemetry
    cfg = base.with_overrides(agents=agents)
    out: dict = {}
    for fault in FAULTS:
        statuses: Counter = Counter()
        labels: Counter = Counter()
        quarantined = 0
        for seed in range(seeds):
            random.seed(seed)
            rec = gen(fault)  # raw record, exactly as the organizer generator emits it
            rep = run_incident(json.dumps(rec).encode(), cfg, RunOptions(persist=False, external=False)).report
            statuses[rep["status"]] += 1
            labels[rep.get("fault_type") or (rep["status"] + (f" ({rep['status_reason']})" if rep.get("status_reason") else ""))] += 1
            quarantined += rep.get("normalization_summary", {}).get("records_quarantined", 0)
        n = seeds
        detected = n - statuses["no_fault_detected"]
        out[fault] = {
            "n": n,
            "statuses": dict(sorted(statuses.items())),
            "labels": dict(sorted(labels.items())),
            "records_quarantined": quarantined,
            "accuracy" if fault == "normal" else "detection_rate":
                round(statuses["no_fault_detected"] / n, 3) if fault == "normal" else round(detected / n, 3),
            "committed_rate": round((statuses["diagnosed"] + statuses["probable"]) / n, 3),
        }
        print(fault, out[fault])
    return out


def to_markdown(res: dict) -> str:
    L = ["#### Organizer generator (raw, unmodified)", "",
         f"`data/generator/organizer_generator.py`, {res['normal']['n']} seeds per fault type, one record per call, "
         "full pipeline, no preprocessing. The organizer faults have no mapping to NetCoop signatures, so "
         "`latency_spike` / `hardware_failure` are scored on detection (not `no_fault_detected`).", "",
         "| organizer fault | n | score | committed (diagnosed/probable) | status distribution | label distribution | records quarantined |",
         "|---|---|---|---|---|---|---|"]
    for f, v in res.items():
        score = f"accuracy {v['accuracy']}" if f == "normal" else f"detection {v['detection_rate']}"
        st = ", ".join(f"{k} {c}" for k, c in v["statuses"].items())
        lb = ", ".join(f"{k} {c}" for k, c in v["labels"].items())
        L.append(f"| `{f}` | {v['n']} | {score} | {v['committed_rate']} | {st} | {lb} | {v['records_quarantined']} |")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=500)
    a = ap.parse_args()
    res = run(a.seeds)
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "organizer.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    Path(REPORTS / "organizer.md").write_text(to_markdown(res), encoding="utf-8")
    print(f"wrote {REPORTS / 'organizer.md'}")


if __name__ == "__main__":
    main()
