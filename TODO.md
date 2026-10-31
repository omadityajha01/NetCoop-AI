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

## T2: organizer-data truth check

- `python -m eval.organizer_check --seeds 500` runs the raw, unmodified organizer generator (500 seeds × 3 faults)
  through the full pipeline. Results are in `eval/reports/organizer.{json,md}` and the README.
- Result: normal → 100% `no_fault_detected`. `latency_spike` and `hardware_failure` → detected 100%, but 0% committed
  (all `insufficient_evidence (no_signature_match)`).
- **Decision:** organizer faults are scored on *detection*. The organizer gives no mapping from `latency_spike` /
  `hardware_failure` to a NetCoop signature, and we do not invent one.
- **Decision (conditional rule not triggered):** "if organizer device IDs aren't in topology → keep them unplaced".
  They are in topology (`SW_CAMPUS_1..10` were added to `config/topology.yaml` in the initial build), and none are
  quarantined (tested). So the unplaced-entity path was **not** implemented, and quarantine of unknown entities is
  unchanged. Stability before the demo.
- Tests: `tests/integration/test_organizer_data.py`.

## T3: operating point

- Sweep `min_top_score` 0.40–0.70 (step 0.05) on seed range A, n = 280. Rule: highest accuracy with wrong-diagnosis
  ≤ 3% and normal FP ≤ 5%. Eligible on A: 0.55 (acc 0.743), 0.60, 0.65, 0.70. 0.50 is excluded (wrong 3.2%).
  **Chosen: 0.55.**
- Held-out B at 0.55: accuracy 0.796, wrong 1.1%, normal FP 0.0, committed precision 98.5%, fault → no_fault 1.3%
  (T1 guards still hold).
- Trade-off accepted: overall B accuracy 0.846 → 0.796 (more abstentions) in exchange for wrong 2.1% → 1.1% and
  normal FP 5% → 0%.
- Chart: `docs/operating_point.png` (matplotlib, optional extra `[eval]`); data in `eval/reports/sweep.json`.
- The demo scenarios are unchanged at 0.55.

## T4: NMP 1.1

- `SCHEMA_VERSION` 1.0 → **1.1** (MINOR, additive): `Finding.source`, report `observations` + `status_reason`,
  `normalization_summary` message type. 1.0 messages are accepted unchanged (tested). The 0.9 upcaster
  still targets 1.0, and the parser stamps the upcast message with the current MINOR (1.1).
- **Decision:** the bundle (input file) `schema_version` stays at "1.0": only the message protocol changed, and the
  fixtures are unchanged.
- `wireless_agent` untouched (still 0.9). Conformance kit now sends 1.1 envelopes: 7/7 pass.
- docs/schemas regenerated (`$id` …/nmp-1.1/…); README tables regenerated.

## T5: A2A verification

- `tests/a2a_sdk/test_a2a_sdk.py` (marker `a2a_sdk`) is skipped unless `a2a-sdk` is installed. It uses the official
  SDK client (`A2ACardResolver` → `create_client` → `send_message`) against the real Node agent.
  **Result: PASS with a2a-sdk 1.3.0.** The card resolves through the SDK's 0.3 compatibility path, the reply is a
  ROLE_AGENT message with a data part (dialect 0.9), and our parser accepts it.
- Pinned as the optional extra `[a2a] = a2a-sdk==1.3.0`. **No refactor to the SDK.**
- **Decision:** a2a-sdk 1.3.0 requires protobuf ≥ 6, which conflicts with TensorFlow on this machine (it needs < 6).
  The check therefore runs in an isolated venv and is not part of `[dev]`. The accidental global install was
  rolled back: a2a-sdk and its five pulled-in packages were uninstalled, protobuf was restored to 5.29.6, and `pip check` is clean.

## T6: HTML timeline

- `netcoop timeline <id> [--html out]` (`netcoop/timeline.py`): a single static file (inline CSS, **no JS**, no CDN).
  It shows one lane per agent in seq order, prediction → request → response seq triples with hit/miss, normalization
  counters, transforms, quarantine and extras, and a final report panel with blocked actions.
- PI8: every data value goes through `html.escape(quote=True)`. Tests: `tests/security/test_timeline_html.py`
  (`<script>` device name and `<img onerror>` field render as text; zero `<script`/`<img` elements; no http refs).
- **Decision:** the PI6 quarantine reason now includes the truncated raw ID (`repr`, 40 chars), so operators see what
  was rejected. It is escaped in the HTML and scrubbed of certainty words in reports.
- Fix: quarantine code classification is now prefix-based. An unknown ID containing the word "regex" was
  previously misclassified as MALFORMED.

## T7: README wording

- "Calibrated" removed everywhere. The README now says **never overconfident**, with the seed-B bin table (observed
  accuracy ≥ mean stated confidence in every bin), and explicitly "not calibrated: conservative, not matched".
- Eval section order: per-source accuracy (organizer raw vs extended generator), seed-B tables, operating-point
  sweep + chart, degradation curve + registry-off ablation (0.47 clean → 0.29 at 60%).
- Numbers refreshed for min_top_score = 0.55 (committed precision 98.5%, wrong 1.1%, normal FP 0%). The status
  table now references `min_top_score` (0.55) instead of the stale 0.45. CLAUDE.md keeps 0.45 as the documented *initial* value.

## T8: repo + CI

- The git repo already existed (with an `origin` remote added by the user). **Nothing pushed in this run.**
- `.gitignore` already covered runs/, .env, .venv, node_modules, __pycache__ and *.egg-info. `demo_snapshots/` stays tracked (noted in the file).
- Makefile is now a thin wrapper: every target calls `python tasks.py <target>`, so tasks.py is the single source.
  Fuzz uses `FUZZ_N` so the Makefile's exported `N=280` doesn't change it.
- `external_agents/wireless_agent/package-lock.json` added (no dependencies) so `npm ci` works.
- `.github/workflows/ci.yml`: ubuntu + windows, Python 3.11, Node 20 → pip install -e .[dev], npm ci, lint, tests,
  demo, conformance vs the Node agent (bash shell on both OSes).

## Open

- [ ] Fill `policies.yaml` with the campus's real calendar (exam weeks, class hours per segment, SLAs).
- [ ] Dashboard (cut line #1, not started; the API is ready: `/incidents`, `/incidents/{id}/report|events|report.csv`).
- [ ] Congestion remediation *simulation* (stretch, G2).
- [ ] MCP server exposing `diagnose` / `get_report` (stretch, D6).
