# NetCoop live demo: run of show

Everything runs on `127.0.0.1` with the LLM off. **No Wi-Fi or internet is needed.**

## Before going on stage (5 min)

```bash
python tasks.py preflight          # 12 red/green checks; must end "PREFLIGHT OK"
```

Preflight checks, in order:
* Python 3.11+ and Node 18+
* dependencies importable
* LLM off, and an allowlist that is loopback-only
* the agent port is free (a stale `wireless_agent` is killed automatically)
* the agent starts, passes conformance 7/7, and stops cleanly
* all 7 scenarios produce their expected outcome with the agent joined
* Wi-Fi without the agent → `insufficient_evidence`
* all 8 fallback snapshots exist

If port 8765 is taken by something else: `python tasks.py present --port 8790`, or set `NETCOOP_AGENT_PORT`.

## Live run

```bash
python tasks.py present            # press Enter between steps; Ctrl-C at any time stops the agent cleanly
```

Every step prints a compact colored summary and writes a static timeline:
`runs/present/INC-DEMO000N/timeline.html` (open it in the browser; no network needed).

| # | Step | Expected on screen | Talking points |
|---|---|---|---|
| 1 | **Congestion** | `diagnosed`, *Likely link congestion … on L_HOSTEL_UPLINK*. Evidence comes from performance + infrastructure agents. Predictions `P-1-1 … HIT`, `P-1-2 … MISS`, `P-1-3 … HIT` | • Six agents exchange typed NMP messages over one bus, and every message is in an append-only event log (show the timeline lanes). • **Predict before you look:** the prediction "interface errors stay low" is logged at seq 15. The evidence request is seq 18 and the answer seq 20. A test fails if that order is ever violated. |
| 2 | **Wi-Fi without the agent** | `insufficient_evidence`; missing signals include `retransmission_pct@AP_H3, rssi_dbm@AP_H3, snr_db@AP_H3` (plus uplink signals for the congestion alternative) | • High packet loss at AP_H3 is real, but no signature matches with the data we have, and no connected agent can provide RF metrics. • We say so instead of guessing, and list exactly which signals would resolve it. |
| 3 | **Start `wireless_agent`** | card `wifi-probe v0.9.3`, skill `wifi-rf-telemetry` | • A different language (Node.js) and a different protocol dialect (v0.9: `signal`, `noise_margin`, `retx` as a fraction, epoch timestamps, `ap-h3`). • It joins mid-session: discovered from the allowlist, no restart. |
| 4 | **Conformance** | 7/7 PASS | • Valid card, valid replies, `error` on malformed input, idempotent on a duplicate `message_id`, tolerates a newer MINOR version. • The same kit runs against any agent URL, and the official `a2a-sdk` 1.3.0 client also talks to this agent. |
| 5 | **Wi-Fi again** | `diagnosed`, *Likely weak Wi-Fi … on AP_H3*; RSSI −78 dBm, SNR 13 dB, retransmissions 28% | • Same incident file; the only change is that an agent joined. • The timeline shows the translation: `version 0.9→1.0`, `noise_margin→snr_db`, `ap-h3→AP_H3`, `retx 0.28 fraction → 28 %`. |
| 6 | **Chaos input** | `diagnosed` device overload on `DEPT_CORE_SW_01`; 48 records in, 36 used, 12 quarantined | • No schema_version, a legacy v0.9 block, latency in seconds, memory as bare fractions, IDs like `dept-core` / `10.20.0.1`, a ghost switch (kept *unplaced*: "device not in topology"), negative latency, a future timestamp, and an injection attempt in a device name. • **Recover what's recoverable, quarantine the rest, never silently drop:** records in = used + quarantined, always (property-tested). |
| 7 | **Policy** | `BLOCKED Reboot HOSTEL_CORE_SW_01: blocked by R1 (Class hours)` | • Recommendations come only from the playbook and pass code-enforced rules. The reboot is shown as *blocked with a rule id*, never silently dropped. • Remediation is never executed. |
| 8 | **Normal network** | `no_fault_detected` | • A healthy network is reported as healthy. Warn-level noise goes to `observations`, never to evidence. |

**Optional step 9, judge mode** (`python tasks.py present --judge`, or on its own: `python tasks.py judge --fault <label|random> --seed <n|random>`).
A judge picks an organizer label (`normal`, `latency_spike`, `hardware_failure`) and any seed. The **raw organizer
generator** produces the record, which goes through the full pipeline with no preprocessing, and the output says whether
it matches the documented mapping (`data/generator/SCHEMA.md`). Talking point: "we don't pick the data, you do."

### Numbers to quote (`eval/reports/`; tuned on seed range A, reported on held-out seed range B)

**Organizer generator** (raw `data/generator/organizer_generator.py`, 500 seeds per label, seed range B):
* `normal` → `no_fault_detected` **100%**; `latency_spike` → latency_spike **100%**; `hardware_failure` → hardware_failure **100%**.
* Wrong diagnoses 0%, false positives 0%, faults reported healthy 0%.

**NetCoop extended generator** (7 classes, 280 incidents, hardened with confounders, gaps and corruption; seed range B):
* Overall accuracy **0.90**. When it commits it is right **98.2%** of the time; the wrong-diagnosis rate is
  **1.4%**, normal false positives **0%**, and a fault is reported healthy in **1.3%** of cases.
* Per class: normal 0.95, congestion 0.8, interface 0.975,
  overload 0.8, Wi-Fi 0.9, DNS 0.95, DHCP 0.95.
* **Never overconfident on our generator** (every confidence bin: observed accuracy ≥ stated confidence). **Not on reduced-severity
  organizer data:** its [0.50, 0.75] bin states 0.6 and observes 0.567. Say this before a judge finds it.
* Robustness: 0.943 → 0.886 with **60%** of input records corrupted; without the alias/unit registry, 0.514 even on clean input.

**Answer-key check on organizer data** (generator wrapped, not edited; seed range B, 200 seeds per cell):

| injected severity | latency_spike correct (detected) | hardware_failure correct (committed) |
|---|---|---|
| 25% | 0.0 (0.0) | 0.0 (1.0) |
| 50% | 0.21 (0.695) | 0.7 (1.0) |
| 75% | 0.645 (0.97) | 1.0 (1.0) |
| 100% | 1.0 (1.0) | 1.0 (1.0) |

* Corruption (organizer records through the fuzzer): accuracy 1.0 at 0% → 0.982 at 60%, **0 wrong diagnoses**, 0 failed runs, 0 crashes.

### Known weaknesses (say them before you're asked)
* **device_overload 0.80** on our generator (target was 0.85). The misses are mostly weakened overloads ending as
  `insufficient_evidence`, plus a few read as congestion.
* **hardware_failure at reduced severity is confidently mislabeled**: at 25% severity it is called `interface_fault`/`congestion`.
  At the generator's own severity it is 100% correct. Scoring was frozen for the demo, so this is reported, not tuned.
* Calibration on organizer data is slightly overconfident in the 0.50–0.75 bin (from that same case).

## Fallback plan

| If… | Do |
|---|---|
| Preflight fails on the agent / port | `python tasks.py present --port 8790`; if Node itself is missing, present steps 1, 2, 6, 7, 8 live and show steps 3–5 from snapshots |
| A live step does not match | The run prints which step. Open `demo_snapshots/<step>/timeline.html` (and `report.json`) and narrate from it |
| Laptop or terminal trouble | `demo_snapshots/` is committed: open the 8 `timeline.html` files from any machine, offline |
| Short on time | Steps 1 → 2 → 3 → 5 → 7 (≈ 2 min) carry the core story: protocol, honesty, hot-plug, policy |

Regenerate the snapshots after any change: `python tasks.py snapshots`.

## Likely judge questions

**"Who generated the test data?"**
Two sources, reported separately:
* The **organizer's own generator**, run raw and unmodified (`data/generator/organizer_generator.py`), 500 seeds per
  label on a held-out seed range. `normal` → `no_fault_detected` 100%,
  `latency_spike` 100%, `hardware_failure`
  100%, with 0 wrong diagnoses. You can check it live: `python tasks.py judge`
  with your own label and seed.
* **Our extended generator** (`eval/generate.py`) for what the organizer's doesn't cover: Wi-Fi, DNS/DHCP, links,
  multi-sample windows. On a held-out range: overall 0.90, right 98.2%
  of the time when it commits, 1.4% wrong diagnoses.

**"You generated part of the eval data yourselves. Isn't that self-graded?"**
For our generator, partly, and the README says so. Three mitigations:
1. Constants are tuned on seed range A and reported on a held-out range B. The selection rule (max accuracy with wrong
   ≤ 3%, normal FP ≤ 5%, faults-reported-healthy ≤ 3%) was fixed before the sweep ran.
2. The generator is hardened with things that hurt us: variable fault intensity, confounders on healthy devices,
   telemetry gaps, lost samples, and 30% of incidents with corrupted records.
3. The organizer's generator is reported separately, untouched, and judges can sample it live.

**"The topology isn't in the organizer's data. Where does it come from?"**
It is **NetCoop-defined**: `config/topology.yaml` models the campus (core router, hostel / department /
lecture-hall switches, APs, DNS/DHCP), and we added the generator's `SW_CAMPUS_1..10` as campus access switches.
It is not invented at run time:
* an input bundle may carry its own `topology`, which is validated and merged (config wins on conflicts, which are reported)
* a device that is in neither is kept *unplaced*: findings are kept, but localization is skipped, the report says
  "device not in topology", and confidence is capped at medium

**"How do the organizer's labels map to your fault types?"**
One to one, derived from the generator code (table in `data/generator/SCHEMA.md`):
* `normal` → `no_fault_detected` (every field below `warn`)
* `latency_spike` → `latency_spike`: latency 150–400 ms and jitter 30–80 ms. Those lower bounds equal our `high`
  thresholds. Drops ≤ 50 and utilization < 85 separate it from congestion.
* `hardware_failure` → `hardware_failure`: CPU 99.9, utilization 100, loss 15–30%, latency 500–1000 ms, drops
  5,000–15,000 plus interface errors. Every resource is saturated at once, so no single-cause signature fits; the
  signature expects them all together.

**"Your signatures came from reading the generator. Isn't that fitting the answer key?"**
The generator *is* the fault specification we were given: "latency spike" and "hardware failure" mean exactly what
its code injects, and we documented the derivation line by line (`data/generator/SCHEMA.md`). What would be overfitting
is never being tested off that exact spec. So we test off it:
* **Severity sweep:** the injected deviation is scaled to 25/50/75/100%. latency_spike degrades into honest abstention
  (21% correct at 50%, no wrong answers). hardware_failure at 25% is mislabeled as
  interface_fault/congestion, and we show that.
* **Corruption:** with 60% of the organizer records corrupted, accuracy is 0.982, with 0 wrong diagnoses.
* **Hold-out:** tuning used seed range A; every number shown is from seed range B, and judges can sample live (`tasks.py judge`).

**"Is your own generator independent?"**
No. Both sources are synthetic: the organizer's generator, and ours, which we wrote ourselves. Our generator adds what
the organizer's lacks (Wi-Fi, DNS/DHCP, links, multi-sample windows) plus things that hurt us (confounders, gaps,
corruption). Its numbers (0.90 overall on held-out seeds) measure internal consistency under realistic
noise, not field accuracy, and the README says so.

**"Why not use the A2A SDK?"**
A2A is our transport; the meaning lives in NMP plus the metric registry. The core speaks the A2A wire shapes (agent
card, JSON-RPC `message/send`, data parts) over the standard library, so the 115 tests run offline with no heavy
dependencies. We verified compatibility with the official `a2a-sdk` 1.3.0 client against our Node agent (optional
test). The SDK pulls protobuf ≥ 6, which conflicts with common ML stacks, so it is an optional extra rather than a core dependency.

**"Why is the core deterministic? Isn't this an AI hackathon?"**
Root cause, confidence and actions must be auditable and reproducible. `netcoop replay` regenerates a report byte for
byte from the event log. The "AI" is in the multi-agent reasoning: competing hypotheses, falsifiable predictions,
evidence requests, conflict resolution and calibrated abstention. None of that needs a language model to make up numbers.

**"Where's the LLM?"**
Optional and off by default (`NETCOOP_LLM=local|cloud`). It has exactly two jobs: classify the free-text complaint
into a fault-type *hint* (which can only add a hypothesis), and write the narrative from the final, validated
report. Its output is allowlisted, and if it names an unknown device or adds a URL we fall back to a template.
Prompt injection in the complaint cannot change the diagnosis (tested).

**"What does insufficient evidence actually mean?"**
One of two precise things, shown as `status_reason`:
* `data_missing`: the leading hypothesis has less than half of its expected signals. The report lists exactly which
  signals would resolve it, and which ones no connected agent can provide.
* `no_signature_match`: something is anomalous at `high` or above, but no known fault pattern scores high enough.

Either way it is a tested, first-class outcome, not a failure.
