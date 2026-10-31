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

## T9: clean-clone check

- `git clone` of the local repo into a temp dir → fresh venv → `pip install -e .[dev]` → `npm ci` (lockfile from T8)
  → `tasks.py test` (all pass), `tasks.py demo` (7/7 scenarios as expected), conformance 7/7 vs a freshly started agent.
- No absolute paths in tracked files (`git grep` for `C:\` / user paths: none).
- Fix: `.gitattributes` (`* text=auto eol=lf`). This machine has `core.autocrlf=true`, so Windows checkouts would
  otherwise get CRLF. Verified the clone has LF.
- Found: an agent I had started earlier for the T5 probe was still listening on 8765 and silently joined the clone's demo.
  Both stray processes were stopped by PID. This motivates T10's stale-agent cleanup, which matches on the
  `wireless_agent/server.js` command line, not just the port.

## T10: live-demo hardening

- `netcoop/present.py`, dispatched by `python tasks.py preflight | present | snapshots` (and the Makefile).
- **preflight:** 12 checks. Python/Node versions, deps, LLM off, loopback-only allowlist, port free (stale agent
  killed), agent start → conformance 7/7 → all 7 scenarios → clean stop, Wi-Fi-without-agent baseline, 8/8
  snapshot folders. Prints red/green and exits non-zero on any failure.
- **present:** the 8 scripted steps with Enter between, a compact colored summary, and a `timeline.html` per step
  (`runs/present/`). The agent is always stopped in `finally`. `--port` / `NETCOOP_AGENT_PORT`; `--auto` skips the pauses.
- **Decision: stale-agent cleanup only kills our own processes.** It matches `wireless_agent` + `server.js` + port on
  the process command line (PowerShell CIM on Windows, `ps` elsewhere), never "all node.exe". If the port is busy
  with anything else, present refuses and suggests `--port`.
- **Decision:** present/preflight output is ASCII-only (a `·` bullet rendered as `�` in a cp1252 console).
- **Decision:** step 7 (policy) reuses the step-1 congestion report (R1 blocks the HOSTEL_CORE_SW_01 reboot) instead of a new run.
- **Decision:** the port override is applied by passing a config override in-process. The allowlist is not
  read from the environment by the core.
- `demo_snapshots/` (tracked): `report.json` + `timeline.html` per step, `output.txt` for agent start and conformance.
- `docs/DEMO.md`: run of show with real seed-B numbers, the fallback plan, and judge Q&A.
- Tests: `tests/integration/test_present.py` (auto run into a temp dir on a free port; process matcher ignores unrelated node processes).

## U1: organizer fault types (P0)

- SCHEMA.md now lists exactly what each organizer label does to each field, plus the 1:1 label → outcome mapping
  and its derivation.
- Two signatures + playbook entries were derived from the generator code: `latency_spike` (latency + jitter ≥ high; contradicted
  by drops > warn or utilization ≥ high) and `hardware_failure` (everything critical + interface errors).
- **Signatures alone were not enough. The blocker was not scoring discrimination but data quality:** a one-record
  input had completeness 1/6, so quality was floored at 0.5 and the score capped at 0.50 < min_top_score 0.55
  (support 1.0, coverage 1.0, contra 0, margin ≥ 0.39).
- **Decision: the "explains" term was NOT added** (it would not change a quality-capped score). Instead,
  completeness is measured against the cadence the input delivers:
  `expected = min(window/interval, max samples of any signal in this input)`. Documented in CLAUDE.md §6.3,
  README and SCHEMA.md.
- Our-generator regression found on A: weakened congestion became latency_spike (wrong 3.2% > guard). It was fixed in
  signatures.yaml only: the latency_spike contradictions were narrowed to drops > warn and utilization ≥ high (the redundant ones diluted contra).
- Organizer seed B (500/label): normal 1.0, latency_spike
  1.0, hardware_failure 1.0
  (targets ≥ 0.90 / ≥ 0.95 ✓). Wrong 0.0, FP 0.0,
  fault→healthy 0.0.
- Our generator seed B: overall 0.796 → 0.8, committed precision
  0.985 → 0.98, wrong 0.011 →
  0.014, normal FP 0.0 → 0.0
  (no metric dropped more than 2 points ✓).

## U2: unknown devices + input topology

- An unknown **device** ID (passes PI6) is no longer quarantined. It is normalized to a stable id (upper-case,
  separators → `_`), so `sw-campus-11`, `Sw.Campus.11` and `SW_CAMPUS_11` are one device. It is registered for this
  run as `Entity(placed=False)`: no links, no upstream, so localization is a no-op. `Finding.placed=false`, plus a
  "device not in topology" limitation. The confidence category is capped at medium when the leading hypothesis (or its evidence) involves it.
- **Decision:** only devices are kept unplaced. Unknown links, APs and services stay quarantined (CLAUDE.md C2:
  "metrics for links absent from topology" is unchanged). PI6 regex failures (injection strings) stay quarantined as MALFORMED.
- **Decision:** input topology is merged **additively**, and on a conflicting attribute **config wins** (+ a limitation),
  rather than input-overrides-config. Reason: roles drive policy (R1 blocks rebooting a core switch), so untrusted
  incident data must not be able to demote a device to dodge a rule (tested). New entities and aliases are added. Any
  validation error rejects the whole input topology with a limitation; the run continues.
- `Finding.placed` added to NMP 1.1 (additive; 1.1 has not been released yet).
- Tests: `tests/integration/test_unplaced_topology.py` (SW_CAMPUS_11, random ID, case/separator variants,
  localization skipped, injection still quarantined, input topology places a device, a conflict keeps the config role,
  invalid topology rejected).

## U3: Wi-Fi and device_overload

- Seed A confusion: weak_wifi → insufficient 12, no_fault 3. device_overload → insufficient 14, congestion 6.
  Top pair: **device_overload ↔ insufficient_evidence (no_signature_match)**. Causes: (1) CPU lands in the warn band once
  intensity is reduced (signature wanted ≥ high); (2) a busy-but-healthy *neighbouring* link contradicted overload
  via `link_utilization_pct ≥ high`. Wi-Fi: RF values in the warn band once intensity is reduced.
- Fixed in signatures.yaml only: device_overload `cpu_pct ≥ warn` and contradiction only at `link_utilization ≥ critical`;
  weak_wifi `rssi/snr/retransmissions` at `warn` (healthy APs sit well clear: RSSI −62…−45, SNR 28–40, retx 1–6%).
- Seed A after: wrong 2.5%, normal FP 5.0% (at the guard, not over), fault→healthy 0.8%.
  Seed B: weak_wifi 0.625 → **0.90** ✓, device_overload 0.675 → **0.80** (target 0.85 **not reached**; kept as best:
  A's normal FP is already at the 5% limit, so a further loosening would trade a guard for accuracy).
  Organizer A unchanged (100% / 100% / 100%).

## U4: normal

- Breakdown of normal misses on seed A (18): 16 `insufficient_evidence (no_signature_match)`, 1 → device_overload, 1 → congestion.
  13 of 18 had a **single isolated high reading** (the only anomalous signal on its entity).
- Rule implemented (config-driven, `scoring.yaml: uncorroborated_high_ratio: 1.25`; `sufficient_alone: true` on
  `dns_failure_pct` / `dhcp_failure_pct` in signatures.yaml). A lone high reading below 1.25× its threshold on a
  non-sufficient-alone metric no longer counts toward rule (c); it is an `observation`. Documented in CLAUDE.md §6.3 + README.
- **Decision:** "only anomalous signal on the entity" means one distinct metric; several sources of the same metric still count as one signal.
- Seed A: normal 0.55 → 0.925; guards: wrong 2.5%, FP 5.0%, fault→healthy 1.7% ✓. Seed B: normal 0.625 → **0.95** ✓.
  Organizer A unchanged (100%).

## U5: re-eval

- Sweep re-run on seed A with all three guards in the selection rule (wrong ≤ 3%, normal FP ≤ 5%, fault→healthy ≤ 3%).
  It still picks **0.55** (0.50 fails on A with normal FP 7.5%). No constant changed, so CLAUDE.md §6.3 constants are unchanged; the §6.3 *text*
  was updated in U1 (completeness) and U4 (uncorroborated high).
- Full eval: our generator (A/B), organizer (A/B, 500 per label), fuzz, `docs/operating_point.png`.
  README tables are now generated, including the sweep table (previously static). The README prose and DEMO.md numbers
  are rebuilt from the reports.

## U6: judge mode

- `python tasks.py judge --fault <normal|latency_spike|hardware_failure|random> --seed <n|random>` runs the raw organizer
  generator → full pipeline → summary + timeline (`runs/judge/`), and states whether the result matches the
  documented label mapping (non-zero exit if not). Random choices use `SystemRandom`.
- `python tasks.py present --judge` adds an **optional** step 9 (prompts for label/seed). **Decision:** opt-in, so the
  default 8-step script, the snapshots and preflight are unchanged.
- U1's target was met (organizer B 100/100/100), so judge mode was added as instructed.

## U7: refresh + freeze

- demo_snapshots/ regenerated (8/8 steps matched). Preflight 12/12; `present --judge` ran all 9 steps.
- DEMO.md judge Q&A added: "who generated the test data" (both sources + numbers), "the topology is NetCoop-defined",
  "how organizer labels map to fault types". The self-graded answer was updated (the organizer generator is now
  diagnosed, not just detected). Step 2 and step 6 rows were corrected to the current outputs (missing-signal order;
  48/36/12 records since the ghost switch is kept unplaced).
- Clean-clone check (fresh clone + fresh venv + `npm ci`): 115 tests pass, demo as expected, preflight 12/12 on
  port 8781 (includes conformance 7/7), judge mode matches. Tagged `demo-safe-2`.

## V1: answer-key check on organizer data (measurement only; FREEZE respected)

- `eval/organizer_robustness.py` (`python tasks.py robustness`). The generator is wrapped, not edited; each fault's
  deviation is scaled to 25/50/75/100% from the midpoint of the generator's own normal range. Seed range B, 200 seeds per cell.
- latency_spike correct: 25% 0.0, 50% 0.21, 75% 0.645, 100% 1.0. Misses are abstentions, never wrong.
- hardware_failure correct: 25% 0.0, 50% 0.7, 75% 1.0, 100% 1.0.
  **At 25–50% it is committed but mislabeled** (interface_fault / congestion). This is reported as a known weakness,
  **not tuned** (scoring frozen).
- Corruption on organizer records: 1.0 → 0.982 at 60%, 0 wrong, 0 failed, 0 crashes.
- Calibration per source: ours never overconfident; organizer **overconfident** in the 0.50–0.75 bin (0.60 stated vs
  0.567 observed). The README/DEMO wording was changed to per-source, and scoring was not touched.
- Reporting only: limitation "single snapshot: persistence not verified" when every device has exactly one sample time
  (`single_snapshot_limitation`). `tests/integration/test_single_snapshot.py` proves that status, confidence, scoring,
  evidence and actions are identical with and without it.
- DEMO.md: severity + corruption tables, the "answer key" and "independent generator" Q&A, and known weaknesses (overload 0.80,
  reduced-severity hardware_failure, organizer calibration bin).

## Open

- [ ] Fill `policies.yaml` with the campus's real calendar (exam weeks, class hours per segment, SLAs).
- [ ] Dashboard (cut line #1, not started; the API is ready: `/incidents`, `/incidents/{id}/report|events|report.csv`).
- [ ] Congestion remediation *simulation* (stretch, G2).
- [ ] MCP server exposing `diagnose` / `get_report` (stretch, D6).
