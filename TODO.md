# TODO / decision log

Decisions taken where CLAUDE.md left room ("choose the simpler option and log it"), plus open items.

## Decisions logged

- **Generator export (done).** The organizer Colab notebook is one function, `generate_telemetry(fault_type)`,
  with faults normal / latency_spike / hardware_failure. It is exported verbatim to `data/generator/organizer_generator.py`
  with its contract in `SCHEMA.md`. It has no topology, Wi-Fi, DNS/DHCP, links or multi-sample windows, so
  `eval/generate.py` extends it using the same record shape and field names.
- **Topology.** The generator has none, so `config/topology.yaml` is NetCoop-defined. It includes the generator's
  `SW_CAMPUS_1..10` IDs as campus access switches. Links are derived from each device's `uplink`.
- **`wireless_agent` language: Node.js.** Go is not installed on the build machine; Node 24 is, and the agent uses no dependencies.
- **A2A: cut-line fallback used (§8).** We implement the A2A wire shapes (Agent Card at
  `/.well-known/agent-card.json`, JSON-RPC 2.0 `message/send`, `Message.parts[kind=data]`, A2A protocolVersion 0.3 field
  names) over stdlib HTTP rather than `a2a-sdk`. This keeps `make test` offline and dependency-light.
  *Open:* pin `a2a-sdk` and verify field names against its docs if the team wants the SDK.
- **`normalization_summary` message type** was added to the NMP 1.0 enum, so ingestion is an event in the log like everything else.
- **`Finding.source`** (optional) was added so C1 can compare sources of the same metric/entity.
- **Round-0 rule refinement.** If *any* source of a (metric, entity) is anomalous, all sources of that signal are
  published in round 0, so value conflicts (C1) are visible. Non-anomalous signals stay hidden until requested.
- **Dedupe key** is (entity, metric, timestamp, **source**), so cross-source disagreements reach C1 instead of being deduped away.
- **External agents cannot author findings.** The gateway recomputes findings from the agent's observations with our
  registry and thresholds, and only for metrics the allowlist says it owns.
- **Message IDs** are content-derived UUIDv4s and `created_at` is stamped by the event log. This makes replay deterministic.
- **`no_fault_detected` confidence** = (1 − best fault score) × share of analysis agents with coverage (the spec defines confidence only via the top score).
- **`config/scoring.yaml`** was added to hold the §6.3 constants (they must be tunable, not hardcoded).
- **No `make` on Windows**, so `tasks.py` mirrors every Makefile target.
- **Tuning:** grid on seed range A (`eval/reports/tune_A.json`), objective = macro accuracy − 2 × wrong-diagnosis rate,
  declared before running. Result: `contra_penalty` 0.5 → **1.0**; other constants unchanged. Reported on seed range B.

## T1: status rules revised (normal scenario)

- The §6.3 rule "no anomalous findings and max < 0.20 → no_fault" made any warn-level reading on a healthy
  network `insufficient_evidence`. New order:
  - (0) no usable observations, or (a) coverage(top) < 0.50 → `insufficient_evidence`, `status_reason: data_missing`
  - (b) nothing ≥ high and top < `min_top_score` → `no_fault_detected`
  - (c) something ≥ high and top < `min_top_score` → `insufficient_evidence`, `status_reason: no_signature_match`
  - (d) probable/diagnosed unchanged
- **Decision:** when there are no hypotheses at all, rule (a) has no "top" to check, so it is skipped. Rule (0)
  still catches the case with no data.
- **Decision:** the report field `observations` = anomalous findings not cited as supporting evidence (any
  status, max 20), plus the new `status_reason` field. Both are additive (see T4 for the version bump).
- `no_fault_max_score` was removed from scoring.yaml (unused under the new rules).
- **Decision:** the "anomalous" count used by rule (b) now means severity ≥ high; warn-level findings never block `no_fault_detected`.
- Re-tuned on seed range A (same grid): best is unchanged (min_top_score 0.45, min_margin 0.15 (tie), contra_penalty 1.0).

| Seed B (n=280) | before T1 | after T1 |
|---|---|---|
| overall accuracy | 0.818 | 0.846 |
| normal accuracy | 0.425 | 0.625 |
| congestion / interface / overload / wifi / dns / dhcp | 0.825 / 1.0 / 0.8 / 0.675 / 1.0 / 1.0 | 0.825 / 1.0 / 0.8 / 0.675 / 1.0 / 1.0 |
| committed precision (when diagnosed/probable) | 0.972 | 0.972 |
| wrong-diagnosis rate | 0.021 | 0.021 |
| fault → no_fault_detected | 0.000 | 0.013 |
| normal false-positive rate | 0.05 | 0.05 |

Guards: precision ≥ 95% ✓; fault → no_fault ≤ 3% ✓.

## Open

- [ ] Fill `policies.yaml` with the campus's real calendar (exam weeks, class hours per segment, SLAs).
- [ ] Pin `a2a-sdk` (optional; see above).
- [ ] Dashboard (cut line #1, not started; the API is ready: `/incidents`, `/incidents/{id}/report|events|report.csv`).
- [ ] Congestion remediation *simulation* (stretch, G2).
- [ ] MCP server exposing `diagnose` / `get_report` (stretch, D6).
- [ ] Optional: make `min_top_score = 0.60` a selectable "strict" operating point (FP 0 on normal in tuning).
