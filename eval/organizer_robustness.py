"""Answer-key check on organizer data (V1, measurement only; nothing here changes scoring).

    python -m eval.organizer_robustness --seeds 200 --seed-b 100000

1. Severity sweep: WRAP the organizer generator (the file is not edited) and scale each fault's injected deviation
   to 25 / 50 / 75 / 100 % of what the generator injects:  value = base + level x (generated - base), where
   `base` is the midpoint of the generator's own `normal` range for that field (read from its code).
2. Corruption: organizer records through the existing corruption fuzzer (eval/mutate.py), 0-60 %.
3. Calibration bins per source (organizer raw; our generator from eval_B.json).
All on seed range B (disjoint from tuning seeds).
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from typing import Any

from eval.mutate import mutate_bundle
from eval.organizer_check import LABEL_TO_FAULT, load_generator
from netcoop.config import ROOT, load_config, thaw
from netcoop.orchestrator.run import RunOptions, run_incident

REPORTS = ROOT / "eval" / "reports"
LEVELS = (0.25, 0.50, 0.75, 1.00)
RATES = (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6)
# midpoint of the generator's `normal` branch for each field (organizer_generator.py); fields `normal` does not
# emit (interface_errors) have base 0
NORMAL_BASE = {"cpu_utilization_pct": 22.5, "link_utilization_pct": 35.0, "packet_loss_pct": 0.0, "latency_ms": 12.5,
               "jitter_ms": 3.0, "queue_drops": 0, "interface_errors": 0}
FAULT_LABELS = ("latency_spike", "hardware_failure")


def scaled(gen, label: str, level: float) -> dict[str, Any]:
    rec = gen(label)
    if label == "normal" or level >= 1.0:
        return rec
    for k, v in list(rec["metrics"].items()):
        base = NORMAL_BASE.get(k)
        if base is None or not isinstance(v, int | float):
            continue
        new = base + level * (v - base)
        rec["metrics"][k] = int(round(new)) if isinstance(v, int) and not isinstance(v, bool) else round(new, 2)
    return rec


def _cfg():
    base = load_config()
    agents = thaw(base.agents)
    agents["external"] = []
    return base.with_overrides(agents=agents)


def _score(label: str, rep: dict[str, Any]) -> tuple[bool, bool, bool]:
    detected = rep["status"] != "no_fault_detected"
    committed = rep["status"] in ("diagnosed", "probable")
    target = LABEL_TO_FAULT[label]
    correct = (rep["status"] == "no_fault_detected") if target is None else (committed and rep.get("fault_type") == target)
    return detected, committed, correct


def severity_sweep(seeds: int, seed0: int) -> list[dict[str, Any]]:
    gen, cfg = load_generator(), _cfg()
    rows = []
    for label in FAULT_LABELS:
        for level in LEVELS:
            det = com = cor = 0
            outs: Counter = Counter()
            for s in range(seed0, seed0 + seeds):
                random.seed(s)
                rep = run_incident(json.dumps(scaled(gen, label, level)).encode(), cfg,
                                   RunOptions(persist=False, external=False)).report
                d, c, k = _score(label, rep)
                det, com, cor = det + d, com + c, cor + k
                outs[rep.get("fault_type") or rep["status"]] += 1
            rows.append({"label": label, "level": level, "n": seeds, "detected": round(det / seeds, 3),
                         "committed": round(com / seeds, 3), "correct": round(cor / seeds, 3),
                         "outputs": dict(outs.most_common())})
            print(rows[-1])
    return rows


def corruption_curve(seeds: int, seed0: int) -> list[dict[str, Any]]:
    gen, cfg = load_generator(), _cfg()
    labels = tuple(LABEL_TO_FAULT)
    curve = []
    for rate in RATES:
        rng = random.Random(seed0 + int(rate * 100))
        n = cor = wrong = crashed = failed = 0
        for label in labels:
            for s in range(seed0, seed0 + seeds):
                random.seed(s)
                bundle = {"records": [gen(label)]}  # one raw record per incident, exactly as generated
                b = mutate_bundle(bundle, rate, random.Random(rng.random()))
                try:
                    rep = run_incident(json.dumps(b).encode(), cfg, RunOptions(persist=False, external=False)).report
                except Exception:  # noqa: BLE001 - measured, never expected
                    crashed += 1
                    n += 1
                    continue
                _, committed, correct = _score(label, rep)
                n += 1
                cor += correct
                failed += rep["status"] == "failed"
                wrong += committed and not correct
        curve.append({"corruption_rate": rate, "n": n, "accuracy": round(cor / n, 3), "wrong_diagnosis_rate": round(wrong / n, 3),
                      "failed": failed, "crashes": crashed})
        print(curve[-1])
    return curve


def calibration(seeds: int, seed0: int) -> list[dict[str, Any]]:
    """Confidence bins over committed organizer diagnoses, raw generator plus all severity levels."""
    gen, cfg = load_generator(), _cfg()
    pts = []
    for label in FAULT_LABELS:
        for level in LEVELS:
            for s in range(seed0, seed0 + seeds):
                random.seed(s)
                rep = run_incident(json.dumps(scaled(gen, label, level)).encode(), cfg,
                                   RunOptions(persist=False, external=False)).report
                if rep["status"] in ("diagnosed", "probable"):
                    pts.append((rep["confidence"], _score(label, rep)[2]))
    return bins(pts)


def bins(pts: list[tuple[float, bool]]) -> list[dict[str, Any]]:
    out = []
    for lo, hi in ((0.0, 0.5), (0.5, 0.75), (0.75, 0.9), (0.9, 1.01)):
        b = [(c, k) for c, k in pts if lo <= c < hi]
        if b:
            out.append({"bin": f"[{lo:.2f}, {min(hi, 1.0):.2f}]", "n": len(b), "mean_confidence": round(sum(c for c, _ in b) / len(b), 3),
                        "accuracy": round(sum(k for _, k in b) / len(b), 3)})
    return out


def never_overconfident(table: list[dict[str, Any]]) -> bool:
    return all(r["accuracy"] >= r["mean_confidence"] for r in table)


def to_markdown(res: dict[str, Any]) -> str:
    L = ["#### Organizer data: severity sweep (answer-key check)", "",
         "The organizer generator is **wrapped, not edited**: each fault's injected deviation is scaled to 25/50/75/100% "
         "of what the generator injects (`value = normal_midpoint + level × (generated − normal_midpoint)`). "
         f"Seed range B, {res['seeds']} seeds per cell. *Detected* = not `no_fault_detected`; *committed* = diagnosed/probable; "
         "*correct* = committed to the matching fault type.", "",
         "| label | injected severity | detected | committed | correct | outputs |", "|---|---|---|---|---|---|"]
    for r in res["severity"]:
        outs = ", ".join(f"{k} {v}" for k, v in r["outputs"].items())
        L.append(f"| `{r['label']}` | {r['level']:.0%} | {r['detected']} | {r['committed']} | {r['correct']} | {outs} |")
    L += ["", "#### Organizer data: corruption curve", "",
          f"One raw organizer record per incident (all three labels, {res['seeds']} seeds each = {res['corruption'][0]['n']} "
          "per rate) through the corruption fuzzer (`eval/mutate.py`).", "",
          "| corruption rate | accuracy | wrong-diagnosis | failed | crashes |", "|---|---|---|---|---|"]
    for p in res["corruption"]:
        L.append(f"| {p['corruption_rate']:.0%} | {p['accuracy']} | {p['wrong_diagnosis_rate']} | {p['failed']} | {p['crashes']} |")
    L += ["", "#### Confidence vs observed accuracy, per source", ""]
    for name, tab in (("Organizer generator (committed diagnoses, all severity levels)", res["calibration_organizer"]),
                      ("NetCoop extended generator (seed range B)", res["calibration_ours"])):
        ok = never_overconfident(tab)
        L += [f"**{name}**: {'never overconfident' if ok else 'OVERCONFIDENT in at least one bin'}", "",
              "| stated confidence bin | n | mean stated | observed accuracy |", "|---|---|---|---|"]
        L += [f"| {r['bin']} | {r['n']} | {r['mean_confidence']} | {r['accuracy']} |" for r in tab]
        L.append("")
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=200)
    ap.add_argument("--seed-b", type=int, default=100000)
    a = ap.parse_args()
    res = {"seeds": a.seeds, "seed_b": a.seed_b,
           "severity": severity_sweep(a.seeds, a.seed_b),
           "corruption": corruption_curve(a.seeds, a.seed_b),
           "calibration_organizer": calibration(a.seeds, a.seed_b),
           "calibration_ours": json.loads((REPORTS / "eval_B.json").read_text(encoding="utf-8"))["calibration"]}
    res["never_overconfident"] = {"organizer": never_overconfident(res["calibration_organizer"]),
                                  "ours": never_overconfident(res["calibration_ours"])}
    (REPORTS / "organizer_robustness.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    (REPORTS / "organizer_robustness.md").write_text(to_markdown(res), encoding="utf-8")
    print("never_overconfident:", res["never_overconfident"])


if __name__ == "__main__":
    main()
