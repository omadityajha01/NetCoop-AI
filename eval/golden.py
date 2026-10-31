"""W2 golden test: per-incident fingerprint of the decision fields, before/after a report-only change.

    python -m eval.golden --write eval/reports/golden_before.json
    python -m eval.golden --compare eval/reports/golden_before.json

Incidents: our generator seed range B (280, Wi-Fi via the real Node agent), organizer seed range B (3 x 200), and
organizer hardware_failure at 25/50/75/100 % strength (4 x 200). For each incident: status, confidence,
suspected_root_cause, affected_devices (must be byte-identical), plus alternative_causes / limitations (may differ).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
from pathlib import Path
from typing import Any

from eval.organizer_check import LABEL_TO_FAULT, load_generator
from eval.organizer_robustness import _cfg, scaled
from eval.run_eval import cfg_for, make_incidents, wireless_agent
from netcoop.config import load_config
from netcoop.orchestrator.run import RunOptions, run_incident

DECISION = ("status", "confidence", "suspected_root_cause", "affected_devices")
FREE = ("alternative_causes", "limitations")


_TS = re.compile(r"\d{4}-\d\d-\d\dT[\d:.]+Z")


def _norm(v: Any) -> Any:
    """The organizer generator stamps records with utcnow(), so limitation text carries run-time timestamps."""
    return [_TS.sub("<ts>", x) for x in v] if isinstance(v, list) else v


def fp(rep: dict[str, Any]) -> dict[str, Any]:
    return {k: rep.get(k) for k in DECISION + FREE}


def collect() -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    items = make_incidents(280, 5000)
    with wireless_agent([i for i, _ in items]) as url:
        cfg = cfg_for(load_config(), url)
        for n, (inc, _m) in enumerate(items):
            rep = run_incident(json.dumps(inc.bundle).encode(), cfg, RunOptions(persist=False, external=True)).report
            out[f"ours:{n}:{inc.fault}"] = fp(rep)
    gen, ocfg = load_generator(), _cfg()
    for label in LABEL_TO_FAULT:
        for s in range(100000, 100200):
            random.seed(s)
            rep = run_incident(json.dumps(gen(label)).encode(), ocfg, RunOptions(persist=False, external=False)).report
            out[f"org:{label}:{s}"] = fp(rep)
    for lv in (0.25, 0.5, 0.75, 1.0):
        for s in range(100000, 100200):
            random.seed(s)
            rep = run_incident(json.dumps(scaled(gen, "hardware_failure", lv)).encode(), ocfg,
                               RunOptions(persist=False, external=False)).report
            out[f"hw{lv}:{s}"] = fp(rep)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--write")
    g.add_argument("--compare")
    g.add_argument("--gate", help="milestone GOLDEN GATE: fail on ANY change to decision fields or alternative_causes")
    a = ap.parse_args()
    cur = collect()
    if a.write:
        Path(a.write).write_text(json.dumps(cur, indent=1, sort_keys=True), encoding="utf-8")
        print(f"wrote {len(cur)} incident fingerprints to {a.write}")
        return 0
    if a.gate:
        base = json.loads(Path(a.gate).read_text(encoding="utf-8"))
        assert set(base) == set(cur), "incident sets differ"
        fields = DECISION + ("alternative_causes",)
        diffs = [(k, f) for k in sorted(base) for f in fields if base[k][f] != cur[k][f]]
        print(f"GOLDEN GATE: {len(base)} incidents; fields {', '.join(fields)}; differences: {len(diffs)}")
        for k, f in diffs[:10]:
            print(f"  {k} {f}: {base[k][f]!r} -> {cur[k][f]!r}")
        print("GOLDEN GATE:", "PASS" if not diffs else "FAIL")
        return 1 if diffs else 0
    base = json.loads(Path(a.compare).read_text(encoding="utf-8"))
    assert set(base) == set(cur), "incident sets differ"
    decision_diffs = [k for k in base if any(base[k][f] != cur[k][f] for f in DECISION)]
    free_diffs = [k for k in base if any(_norm(base[k][f]) != _norm(cur[k][f]) for f in FREE)]
    print(f"incidents: {len(base)}; decision fields differ: {len(decision_diffs)}; "
          f"alternative_causes/limitations differ: {len(free_diffs)}")
    for k in decision_diffs[:10]:
        print("  DECISION CHANGED:", k, {f: (base[k][f], cur[k][f]) for f in DECISION if base[k][f] != cur[k][f]})
    by_group: dict[str, int] = {}
    for k in free_diffs:
        by_group[k.split(":")[0]] = by_group.get(k.split(":")[0], 0) + 1
    print("  report-only changes by group:", by_group)
    return 1 if decision_diffs else 0


if __name__ == "__main__":
    sys.exit(main())
