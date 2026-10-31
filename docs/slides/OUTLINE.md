# Slide outline (8 slides)

Charts come from `tools/make_slide_assets.py`, which reads `eval/reports/*` only. All numbers are held-out (seed range B).
Speaker lines are ≤ 20 words.

| # | Title | Bullets | Asset | Speaker line |
|---|---|---|---|---|
| 1 | **Campus faults hide across systems** | • Telemetry is split across switches, monitors and dialects<br>• Operators need one explainable cause, not five dashboards<br>• The PS asks for cooperating agents that admit uncertainty | none (title slide) | "Campus outages span many monitors; no single tool sees the whole fault, so specialized agents must cooperate." |
| 2 | **Architecture: agents on one logged bus** | • 5 internal agents + A2A gateway; every message in an append-only event log<br>• Knowledge lives in `config/*.yaml`; the core is deterministic, and replay is byte-identical<br>• LLM optional and off by default | `docs/architecture.svg` | "Five agents argue over one logged bus; everything they know lives in config, so every report replays byte-identically." |
| 3 | **Interop: NMP 1.1 + A2A + hot-plug** | • NMP 1.1: typed envelope, metric registry, MINOR/MAJOR versioning; 0.9 → 1.0 upcaster<br>• A2A-compatible, verified with `a2a-sdk` 1.3.0; conformance kit 7/7<br>• Node.js `wireless_agent` (dialect v0.9) joins mid-run: Wi-Fi goes `insufficient_evidence` → diagnosed at AP_H3 | `demo_snapshots/05_wifi_diagnosed/timeline.html` (screenshot of the transforms + lanes) | "A Node.js agent speaking an older dialect joins mid-run, passes conformance, and turns insufficient evidence into a diagnosis." |
| 4 | **Predict before you look** | • Each hypothesis logs falsifiable predictions before evidence is requested (congestion: seq 15 → 18 → 20)<br>• Discriminating signals first; hits and misses both enter scoring<br>• Every prediction is in the report, misses included (congestion: 2 hits, 1 miss) | `demo_snapshots/01_congestion/timeline.html` (predictions table) | "Before looking, the correlation agent writes down what it expects; the log proves the order, misses included." |
| 5 | **Results on held-out data** | • Organizer generator (raw, 500 per label): normal, latency spike, hardware failure **100% / 100% / 100%**, 0 wrong<br>• Our harder generator (280): **0.90** overall; right **98.2%** when it commits; **1.4%** wrong<br>• Operating point 0.55 chosen on seed A: **0%** false alarms on healthy networks | `docs/slides/1_accuracy_per_fault.png` (backup: `4_operating_point.png`) | "On the organizer's generator every label is right; on our harder data, committed diagnoses are right 98 percent." |
| 6 | **Robustness: corrupt it, weaken it** | • 60% of records corrupted: organizer **0.982**, ours **0.886**; 0 failed runs, 0 crashes<br>• Alias/unit registry off: **0.514** even on clean input<br>• Weakened hardware failure stays in the top-2 causes: **75%** at 25% strength, **100%** from 50% | `docs/slides/2_degradation_curve.png` (backup: `3_severity_sweep.png`) | "Corrupt sixty percent of records and accuracy barely moves; remove the alias registry and it halves." |
| 7 | **Known weaknesses, with numbers** | • Device overload **0.80** (32/40: 5 abstain, 3 read as congestion)<br>• Weakened hardware failure: always **medium** confidence, named in 100% of reports, but top cause only from 50% strength<br>• Organizer calibration: said **0.60**, right **0.567** in one band; single snapshots: "persistence not verified" | `docs/slides/5_confidence_vs_accuracy.png` (backup: `3_severity_sweep.png`) | "We publish our weak spots with numbers: overload at 0.80, and one confidence band 3.3 points high." |
| 8 | **Measured, not claimed** | • github.com/omadityajha01/NetCoop-AI; stage tag `demo-final-2`; CI green (Ubuntu + Windows)<br>• `python tasks.py preflight` 15/15, `present` 8 steps (+ judge step 9)<br>• Judges: `python tasks.py judge --fault <label> --seed <n>` runs the raw generator live | none (closing slide; optional QR code to the repo) | "Pick any organizer label and seed now; we'll run the raw generator live. Measured, not claimed." |

## Assets

| File | One message |
|---|---|
| `docs/slides/1_accuracy_per_fault.png` | Every organizer label 100%; our hardest classes (overload, congestion) still 80% |
| `docs/slides/2_degradation_curve.png` | 60% corruption barely moves accuracy; without the registry it halves |
| `docs/slides/3_severity_sweep.png` | Weakened faults abstain or stay in the top-2 instead of becoming wrong answers |
| `docs/slides/4_operating_point.png` | 0.55 gives zero false alarms on healthy networks for little accuracy |
| `docs/slides/5_confidence_vs_accuracy.png` | Ours never overconfident; organizer one band 3.3 points under |
| `docs/architecture.svg` | System overview (existing) |

Regenerate: `.venv/Scripts/python tools/make_slide_assets.py` (needs the `[eval]` extra: matplotlib).
Palette: dataviz reference slots blue/orange/aqua, validated for color-vision deficiency. Aqua is below 3:1 contrast, so every
series is direct-labelled and has its own marker and line style.
