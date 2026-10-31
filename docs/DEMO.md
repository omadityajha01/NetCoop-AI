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
| 2 | **Wi-Fi without the agent** | `insufficient_evidence`; missing signals `rssi_dbm@AP_H3, snr_db@AP_H3, retransmission_pct@AP_H3` | • High packet loss at AP_H3 is real, but no signature matches with the data we have, and no connected agent can provide RF metrics. • We say so instead of guessing: across 1,000 raw organizer fault records, NetCoop never committed to a made-up cause. |
| 3 | **Start `wireless_agent`** | card `wifi-probe v0.9.3`, skill `wifi-rf-telemetry` | • A different language (Node.js) and a different protocol dialect (v0.9: `signal`, `noise_margin`, `retx` as a fraction, epoch timestamps, `ap-h3`). • It joins mid-session: discovered from the allowlist, no restart. |
| 4 | **Conformance** | 7/7 PASS | • Valid card, valid replies, `error` on malformed input, idempotent on a duplicate `message_id`, tolerates a newer MINOR version. • The same kit runs against any agent URL, and the official `a2a-sdk` 1.3.0 client also talks to this agent. |
| 5 | **Wi-Fi again** | `diagnosed`, *Likely weak Wi-Fi … on AP_H3*; RSSI −78 dBm, SNR 13 dB, retransmissions 28% | • Same incident file; the only change is that an agent joined. • The timeline shows the translation: `version 0.9→1.0`, `noise_margin→snr_db`, `ap-h3→AP_H3`, `retx 0.28 fraction → 28 %`. |
| 6 | **Chaos input** | `diagnosed` device overload on `DEPT_CORE_SW_01`; 48 records in, 35 used, 13 quarantined | • No schema_version, a legacy v0.9 block, latency in seconds, memory as bare fractions, IDs like `dept-core` / `10.20.0.1`, a ghost switch, negative latency, a future timestamp, and an injection attempt in a device name. • **Recover what's recoverable, quarantine the rest, never silently drop:** records in = used + quarantined, always (property-tested). |
| 7 | **Policy** | `BLOCKED Reboot HOSTEL_CORE_SW_01: blocked by R1 (Class hours)` | • Recommendations come only from the playbook and pass code-enforced rules. The reboot is shown as *blocked with a rule id*, never silently dropped. • Remediation is never executed. |
| 8 | **Normal network** | `no_fault_detected` | • A healthy network is reported as healthy. Warn-level noise goes to `observations`, never to evidence. |

### Numbers to quote (held-out seed range B, 280 generated incidents; `eval/reports/`)

* When NetCoop commits to a diagnosis it is right **98.5%** of the time. The wrong-diagnosis rate is **1.1%**,
  and the false-positive rate on healthy networks is **0%** (operating point `min_top_score = 0.55`, chosen on seed range A).
* Overall accuracy is **0.80**. Most misses are honest `insufficient_evidence` (18%), not wrong answers.
  Localization is right **99.5%** of the time when the fault type is right.
* **Never overconfident:** in every confidence bin, observed accuracy ≥ stated confidence.
* Robustness: accuracy goes 0.81 → 0.76 with **60%** of input records corrupted. Without the alias/unit registry it
  is 0.47 even on clean input.
* Organizer generator (raw): 500/500 healthy records → `no_fault_detected`; 1,000/1,000 fault records detected,
  0 fabricated root causes.

## Fallback plan

| If… | Do |
|---|---|
| Preflight fails on the agent / port | `python tasks.py present --port 8790`; if Node itself is missing, present steps 1, 2, 6, 7, 8 live and show steps 3–5 from snapshots |
| A live step does not match | The run prints which step. Open `demo_snapshots/<step>/timeline.html` (and `report.json`) and narrate from it |
| Laptop or terminal trouble | `demo_snapshots/` is committed: open the 8 `timeline.html` files from any machine, offline |
| Short on time | Steps 1 → 2 → 3 → 5 → 7 (≈ 2 min) carry the core story: protocol, honesty, hot-plug, policy |

Regenerate the snapshots after any change: `python tasks.py snapshots`.

## Likely judge questions

**"You generated the eval data yourselves. Isn't that self-graded?"**
Partly, and we say so in the README. Three mitigations:
1. Constants are tuned on seed range A and reported on a held-out range B. The selection rule (max accuracy with
   wrong ≤ 3% and normal FP ≤ 5%) was fixed before the sweep ran.
2. The generator is hardened with things that hurt us: variable fault intensity, confounders on healthy devices,
   telemetry gaps, lost samples, and 30% of incidents with corrupted records.
3. We report the organizer's raw generator separately. There NetCoop detects every fault but does not claim a
   root cause, because those records max out every signal at once. We show that result instead of hiding it.

**"Why not use the A2A SDK?"**
A2A is our transport; the meaning lives in NMP plus the metric registry. The core speaks the A2A wire shapes (agent
card, JSON-RPC `message/send`, data parts) over the standard library, so the 100+ tests run offline with no heavy
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
