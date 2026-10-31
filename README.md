# NetCoop AI: multi-agent network fault diagnosis

Specialized agents analyze synthetic campus telemetry (IIT Bhubaneswar scenario). They exchange structured
findings over a documented protocol (**NMP 1.0**), test competing hypotheses by asking each other for
discriminating evidence, and produce **one JSON diagnostic report**. The report contains evidence, alternative
causes, a documented confidence score, limitations and policy-checked recommendations.

> **Transport: A2A (borrowed). Semantics: NMP + metric registry (designed).**

Three things we optimized for:

1. **Hot-plug external agent.** `wireless_agent` is written in **Node.js** and speaks an older dialect (**v0.9**)
   with its own field names. It joins mid-session over A2A, passes the conformance kit live, and **changes the
   diagnosis**: without it the Wi-Fi scenario is `insufficient_evidence`; with it, `diagnosed`.
2. **Predict before you look.** Each hypothesis logs falsifiable predictions to the event log *before* the
   evidence is requested. Hits and misses are scored, and every prediction appears in the report.
3. **Measured, not claimed.** Per-fault accuracy, a confusion matrix, calibration and a degradation curve under
   corrupted input are all produced by `make eval` / `make fuzz` on generated incidents, never on the demo fixtures.

The core is deterministic: root cause, confidence, conflicts and actions are computed by code. The LLM is
optional and **off by default** (it can only add a hint and write the narrative).

---

## Quick start

```bash
make setup              # pip install -e .[dev]   (no GPU, no API key)
make demo               # all 7 scenarios end-to-end via the CLI, LLM off
make test               # unit + integration + security + property, offline
```

There is no `make` on Windows; every target also exists as `python tasks.py <target>` (`python tasks.py demo`).

The **hot-plug demo** (the Wi-Fi scenario):

```bash
netcoop diagnose data/scenarios/weak_wifi/incident.json          # -> insufficient_evidence (no Wi-Fi signals)
node external_agents/wireless_agent/server.js                     # start the external agent (other terminal)
make conformance AGENT_URL=http://127.0.0.1:8765                  # 7/7 checks pass
netcoop diagnose data/scenarios/weak_wifi/incident.json          # -> diagnosed: weak Wi-Fi at AP_H3
```

Other CLI commands:

```bash
netcoop diagnose data/scenarios/congestion/incident.json --timeline   # message timeline, predictions, blocked actions
netcoop replay <incident_id>                                           # byte-identical report.json re-run
netcoop agents refresh                                                 # re-check the allowlist; new agents join the next run
netcoop feedback <incident_id> CONG-1 approve --note "ok"              # non-blocking HITL (nothing is executed)
netcoop serve                                                          # read-only API on :8000 (/docs)
```

Requirements: Python ≥ 3.11 and Node ≥ 18 (only for the external agent; everything else runs without it).

## Scenarios (sample data)

| Scenario | File | Expected outcome |
|---|---|---|
| Normal operation | `data/scenarios/normal/incident.json` | `no_fault_detected` |
| Link congestion | `data/scenarios/congestion/incident.json` | `diagnosed` congestion on `L_HOSTEL_UPLINK`; reboot blocked by R1 (class hours) |
| Weak Wi-Fi | `data/scenarios/weak_wifi/incident.json` | `insufficient_evidence` → `diagnosed` once `wireless_agent` joins |
| Interface fault | `data/scenarios/interface_fault/incident.json` | `diagnosed` interface fault on `L_DEPT_ACC_01`; disruptive actions blocked by R4 (exams) |
| DNS failure | `data/scenarios/dns_failure/incident.json` | `diagnosed` DNS failure on `DNS_01`; L3 latency/loss predicted normal → hits |
| DHCP failure | `data/scenarios/dhcp_failure/incident.json` | `diagnosed` DHCP failure on `DHCP_01` |
| Interoperability failure | `data/scenarios/interop/incident.json` | `diagnosed` device overload on `DEPT_CORE_SW_01` from mixed dialects, units, IDs, a legacy v0.9 block, garbage and an injection attempt |

`python -m eval.generate --fixtures` regenerates all fixtures deterministically. The organizer's Colab generator is
exported verbatim to `data/generator/organizer_generator.py`, and its field contract is in `data/generator/SCHEMA.md`.
Its output (`cpu_utilization_pct`, `queue_drops`, `interface_errors`, `status`, …) is accepted as-is.

---

## Architecture

```
                 incident bundle (.json/.csv, any dialect)
                                 │
                       ┌─────────▼─────────┐
                       │    normalizer     │  parse → version/upcast → aliases → units → coercion →
                       │  (recover / quar- │  plausibility → entities → time → dedupe → validate
                       │  antine, never    │  every step = Transform; never silently drop, never invent
                       │  silently drop)   │
                       └─────────┬─────────┘
                                 │ normalization_summary
 ┌───────────────────────────────▼──────────────────────────────────────────────────────────┐
 │  in-process message bus ── every message appended to runs/<id>/events.jsonl (seq) first │
 │                                                                                          │
 │  performance_agent   infrastructure_agent   connectivity_agent    correlation_agent      │
 │  (latency, loss,     (CPU, mem, errors,     (scope, nearest       (hypotheses, conflicts,│
 │   util, jitter)       drops, flaps, up)      upstream, DNS/DHCP)   predictions, scoring)  │
 │                                                                    reporting_agent        │
 │                                                                    (playbook, policy, PS  │
 │                                                                     report, limitations)  │
 └──────────────────────────────────────┬───────────────────────────────────────────────────┘
                                        │ NMP envelope inside an A2A data part (JSON-RPC message/send)
                              ┌─────────▼──────────┐   allowlist-only discovery, card validation,
                              │   A2A gateway      │   size cap 256 KB, timeout, rate limit,
                              │ + 0.9→1.0 upcaster │   same normalizer, no tools, never in prompts
                              └─────────┬──────────┘
                                        │ HTTP
                              ┌─────────▼──────────┐
                              │  wireless_agent    │  Node.js, dialect v0.9:
                              │  ("wifi-probe")    │  {"ver":"0.9","obs":[{"ap":"ap-h3","signal":-78,...}]}
                              └────────────────────┘
```

### Agent responsibilities

| agent_id | Owns | Where |
|---|---|---|
| `performance_agent` | latency, jitter, packet loss, throughput, link utilization | internal |
| `infrastructure_agent` | device status, CPU, memory, interface/CRC errors, link flaps, egress queue drops | internal |
| `connectivity_agent` | DNS/DHCP service health; scope of impact + nearest common upstream node | internal |
| `wireless_agent` | RSSI, SNR, retransmissions, client count per AP | **external** (Node.js, A2A, dialect v0.9) |
| `correlation_agent` | hypotheses, conflict detection (C1–C3), predictions, evidence requests, scoring | internal |
| `reporting_agent` | PS-format report, playbook actions, policy check, limitations | internal |

Agents are **pure**: messages in, messages out. They never call each other, keep no global state, and do I/O
only through the read-only tools granted in `config/agents.yaml` (`telemetry`, `topology`, `findings`).
Every threshold, alias and weight comes from `config/`. All analysis agents always run; nothing can skip one.

**Round-0 rule:** in the first pass, analysis agents publish only anomalous findings (severity ≥ warn) plus a
coverage manifest. Normal values are available only through `evidence_request`. This keeps predictions honest:
a prediction is made before the agent shows the value.

---

## Protocol: NetCoop Message Protocol (NMP) 1.0

Pydantic v2 models (`netcoop/protocol/`) are the source of truth. `make schemas` exports JSON Schemas to
`docs/schemas/`, and external agents should be pointed at those, not at the Python. The tables below are
generated from config by `make docs`.

### Envelope (every message)

<!-- BEGIN GENERATED: envelope -->
| Field | Type | Meaning |
|---|---|---|
| `schema_version` | "MAJOR.MINOR" | Protocol version of this message (1.0) |
| `message_id` | uuid | Unique; receivers are idempotent on duplicates (content-derived UUIDv4) |
| `message_type` | enum | `task_request`, `finding_report`, `coverage_manifest`, `prediction`, `evidence_request`, `evidence_response`, `diagnosis`, `report`, `error`, `normalization_summary` |
| `incident_id` | str | Server-generated, `^INC-[0-9A-Z]{4,12}$` |
| `sender / recipient` | agent_id | `recipient` may be `orchestrator` |
| `in_reply_to` | uuid | null | `message_id` this responds to |
| `seq` | int | Assigned by the event log on append (monotonic per run); agents never set it |
| `created_at` | RFC3339 UTC | Stamped by the event log on append |
| `status` | enum | `completed`, `partial`, `failed`, `insufficient_data` |
| `payload` | object | Typed per `message_type` (see docs/schemas/) |
| `limitations` | list[Limitation] | `{code, detail, impact}` |
| `extras` | object | Unknown fields from newer MINOR versions, kept (never silently dropped) |
<!-- END GENERATED: envelope -->

Payloads per `message_type`: `task_request {task, window, round, params}`, `finding_report {round, findings[], scope?}`,
`coverage_manifest {signals[{metric, entity}]}`, `prediction {prediction}`, `evidence_request {round, requests[{metric, entity, window}], prediction_ids}`,
`evidence_response {round, findings[], unavailable[]}`, `diagnosis {phase, status, hypotheses[], conflicts[], predictions[], …}`,
`report {report}`, `error {code, detail, offending_message_id, field, agent_id}`, `normalization_summary {…}`.
Error codes: `SCHEMA_VERSION_UNSUPPORTED, MISSING_FIELD, BAD_TYPE, BAD_UNIT, UNKNOWN_ENTITY, MALFORMED, TIMEOUT, TOO_LARGE, AGENT_FAILED, INVALID_OUTPUT, RATE_LIMITED`.

### Finding

<!-- BEGIN GENERATED: finding -->
| Field | Type | Meaning |
|---|---|---|
| `finding_id` | str | `F-<agent>-<n>`, unique per run |
| `metric` | str | Canonical name; must exist in `metrics.yaml` |
| `entity` | EntityRef | `{type, id}`; type ∈ device, link, ap, service; id exists in topology |
| `value` | float | Aggregated value, canonical unit |
| `unit` | str | Canonical unit from `metrics.yaml` |
| `window` | Window | `{start, end}` UTC span of the samples used |
| `aggregation` | Literal | p95, mean, max, count, rate (from `metrics.yaml`) |
| `sample_count` | int | Samples aggregated |
| `threshold_ref` | str | e.g. `metrics.yaml#latency_ms.wireless.high` or `policies.yaml#R2.high` |
| `severity` | Literal | normal, warn, high, critical: derived from thresholds only |
| `data_quality` | DataQuality | `{completeness 0–1, staleness_s, coerced}` |
| `transforms` | list | Every normalization step applied to the underlying data |
| `source_refs` | list | Raw record references (`records[i].field`) |
| `source` | str | None | Originating telemetry source (snmp, probe, wifi-probe…); used for C1 conflicts |
<!-- END GENERATED: finding -->

### Metric registry (`config/metrics.yaml`): names, units, meanings, aliases, thresholds

<!-- BEGIN GENERATED: metrics -->
| Metric | Unit | Aggregation | Direction | Range | Thresholds warn/high/critical | Aliases | Meaning |
|---|---|---|---|---|---|---|---|
| `latency_ms` | ms | p95 | higher is worse | 0–60000 | default: 50 / 150 / 500; wireless: 80 / 200 / 600 | `rtt_ms`, `delay_ms`, `ping_ms`, `latency_msec`, `avg_latency_ms`, `latency`, `rtt`, `delay`, `ping` | Round-trip time probe->entity, aggregated over the window |
| `jitter_ms` | ms | p95 | higher is worse | 0–60000 | default: 15 / 30 / 80; wireless: 25 / 50 / 100 | `jitter_msec`, `pdv_ms`, `jitter`, `pdv` | Variation in latency (mean absolute delta between consecutive probes) |
| `packet_loss_pct` | pct | mean | higher is worse | 0–100 | default: 1 / 3 / 10; wireless: 2 / 5 / 15 | `loss_pct`, `packet_loss_percent`, `pkt_loss_pct`, `packetloss_pct`, `packet_loss`, `loss`, `pkt_loss`, `packetloss` | Share of probe packets lost in the window |
| `throughput_mbps` | mbps | mean | lower is worse | 0–400000 | default: 20 / 5 / 1 | `throughput_mbit`, `bandwidth_mbps`, `goodput_mbps`, `throughput`, `bandwidth`, `goodput` | Measured goodput across the entity in the window |
| `link_utilization_pct` | pct | p95 | higher is worse | 0–100 | default: 70 / 85 / 95 | `utilization_pct`, `util_pct`, `link_util_pct`, `bandwidth_utilization_pct`, `if_util_pct`, `utilization`, `util`, `link_util`, `link_utilization` | Egress utilization of the link relative to its capacity |
| `cpu_pct` | pct | p95 | higher is worse | 0–100 | default: 70 / 85 / 95 | `cpu_utilization_pct`, `cpu_util_pct`, `cpu_usage_pct`, `cpu_percent`, `cpu`, `cpu_util`, `cpu_usage`, `cpu_load` | Control-plane CPU utilization of the device |
| `memory_pct` | pct | p95 | higher is worse | 0–100 | default: 75 / 90 / 97 | `memory_utilization_pct`, `mem_pct`, `mem_util_pct`, `memory_usage_pct`, `memory`, `mem`, `mem_usage` | Memory utilization of the device |
| `queue_drops_count` | count | max | higher is worse | 0–100000000 | default: 50 / 100 / 1000 | `queue_drops`, `egress_drops`, `egress_queue_drops`, `output_drops`, `qdrops` | Packets dropped from egress queues per sample interval |
| `interface_errors_count` | count | max | higher is worse | 0–100000000 | default: 10 / 50 / 200 | `interface_errors`, `if_errors`, `iface_errors`, `port_errors`, `input_errors` | Input+output interface errors per sample interval |
| `crc_errors_count` | count | max | higher is worse | 0–100000000 | default: 5 / 20 / 100 | `crc_errors`, `crc`, `fcs_errors` | Frames with bad CRC per sample interval |
| `link_flaps_count` | count | max | higher is worse | 0–100000 | default: 1 / 3 / 10 | `link_flaps`, `flaps`, `flap_count`, `link_state_changes` | Link up/down transitions per sample interval |
| `device_up` | bool | mean | lower is worse | 0–1 | default: 0.99 / 0.5 / 0 | `device_status_up`, `is_up`, `up` | 1 if the device reported up in the sample, 0 if down; window value is the mean |
| `rssi_dbm` | dbm | p95 | lower is worse | -120–0 | wireless: -67 / -75 / -85; default: -67 / -75 / -85 | `rssi`, `signal`, `signal_dbm`, `signal_strength_dbm` | Received signal strength of clients at the AP |
| `snr_db` | db | p95 | lower is worse | -20–90 | wireless: 25 / 15 / 8; default: 25 / 15 / 8 | `snr`, `noise_margin`, `noise_margin_db` | Signal-to-noise ratio of clients at the AP |
| `retransmission_pct` | pct | mean | higher is worse | 0–100 | wireless: 10 / 20 / 40; default: 10 / 20 / 40 | `retransmissions_pct`, `retry_pct`, `retx_pct`, `retry_rate_pct`, `retx`, `retransmissions`, `retries`, `retry_rate` | Share of 802.11 frames retransmitted at the AP |
| `client_count` | count | max | higher is worse | 0–2000 | wireless: 40 / 60 / 90; default: 40 / 60 / 90 | `clients`, `num_clients`, `associated_clients`, `sta_count` | Number of clients associated to the AP |
| `dns_failure_pct` | pct | mean | higher is worse | 0–100 | default: 2 / 10 / 40 | `dns_fail_pct`, `dns_error_pct`, `dns_failure_rate_pct`, `dns_failure_rate`, `dns_failures` | Share of DNS queries that failed or timed out (synthetic probe) |
| `dhcp_failure_pct` | pct | mean | higher is worse | 0–100 | default: 2 / 10 / 40 | `dhcp_fail_pct`, `dhcp_error_pct`, `dhcp_failure_rate_pct`, `dhcp_failure_rate`, `dhcp_failures` | Share of DHCP DISCOVER/REQUEST exchanges that did not complete |
<!-- END GENERATED: metrics -->

"Aliases" whose name implies the unit (`rtt_ms`) map directly. "Ambiguous" aliases (`latency`, `rtt`, `utilization`)
need an explicit unit (a suffix like `"0.28s"` or a `units` map), or **batch-level** inference. A unit is inferred
only if exactly one unit keeps every value in the batch plausible, or if a `*_pct` metric has every value in [0,1].
It is never inferred from a single value. Otherwise the field is quarantined.

### Versioning

* **MINOR bump:** accepted. Unknown fields go to `extras` with a warning limitation.
* **MAJOR mismatch:** the registered upcaster chain runs (`upcasters.py`, `0.9 → 1.0`). With no upcaster the reply is `error SCHEMA_VERSION_UNSUPPORTED`.
* **Missing `schema_version`:** shape detectors (`1.0` envelope shape, `0.9` `from`+`obs` shape) apply, and the version is logged as inferred.

**Dialect 0.9 → 1.0** (the `wireless_agent` speaks it; *do not fix it*):

| 0.9 | 1.0 | How |
|---|---|---|
| `ver` / `inc` / `from` / `re` | `schema_version` / `incident_id` / `sender` / `in_reply_to` | upcaster |
| `obs[]` | `payload.observations[]` (normalized → findings by the gateway) | upcaster |
| `signal` | `rssi_dbm` | metric registry alias |
| `noise_margin` | `snr_db` | metric registry alias |
| `retx` (fraction) | `retransmission_pct` (×100) | upcaster declares unit `fraction`; `unit_aliases` converts |
| `ts` (epoch s) | RFC3339 UTC | upcaster |
| `ap-h3` | `AP_H3` | topology alias (case/separator-insensitive) |
| `dev`, `rtt` (s), `loss`, `cpu` (fractions) | `device_id`, `latency_ms`, `packet_loss_pct`, `cpu_pct` | legacy wired probes |

### A2A transport

The gateway (`netcoop/gateway/`) uses A2A wire shapes over stdlib HTTP:
* the Agent Card at `<base>/.well-known/agent-card.json`
* JSON-RPC 2.0 `message/send`
* the NMP envelope in `Message.parts[{kind:"data"}]`

Card skills map to NMP capabilities through `config/agents.yaml` (`wifi-rf-telemetry → metric:rssi_dbm, …`).
Discovery is **only** from that allowlist, and a card whose `url` leaves the allowlisted origin is rejected.

**Conformance kit:** `make conformance AGENT_URL=…`, or `pytest conformance/` with `AGENT_URL` set. It checks that the agent:
* serves a valid card
* answers `task_request` and `evidence_request` with valid NMP within the timeout
* returns an `error` on malformed input
* is idempotent on a duplicate `message_id`
* declares `schema_version`
* tolerates unknown fields and a newer MINOR version

---

## Orchestration

1. **Ingest → normalize**, which emits `normalization_summary`.
2. **Round 0:** `task_request` goes to *all* analysis agents in parallel: internal agents plus every allowlisted external agent that is reachable now (hot-plug). Timeouts come from `agents.yaml`, with one retry.
3. `connectivity_agent` computes the **scope**: affected entities, devices, segments and the nearest common upstream node.
4. `correlation_agent` builds hypotheses from anomalous findings, scope and (optional) hints. It detects conflicts, then logs predictions and evidence requests.
5. **Evidence rounds:** at most 2 rounds, at most 3 predictions and 6 evidence requests per round. A second round runs only while the case is unresolved (insufficient, probable, margin < 0.15, or an unresolved C2).
6. **Final scoring** produces `diagnosis`. Then `reporting_agent` runs playbook → policy check → report, and the **validator** checks it before anything is written.
7. `report.json`, `events.jsonl`, `input.*`, `meta.json` and `external.jsonl` are written under `runs/<incident_id>/`, and the report is also stored in SQLite.

State is **derived from the event log**. `seq` is assigned on append, before delivery. Message ids are
content-derived UUIDv4s. `netcoop replay <id>` re-runs from the stored input plus the recorded external
exchanges, and checks that `report.json` and the event sequence are byte-identical.

### Conflict resolution

| Type | Detection | Resolution |
|---|---|---|
| **C1 value** | Same metric + entity from different sources, overlapping windows, relative difference > 20% | Keep the fresher value, then the higher `sample_count`, then `source_priority`. The loser goes to limitations and is excluded from scoring |
| **C2 state** | A device reports `down` but has newer telemetry; or metrics arrive for links absent from topology | Mark the status stale (quality 0.5) and send one re-fetch `evidence_request`. If still unresolved, confidence is capped. Unknown links are quarantined (topology is never invented) |
| **C3 hypothesis** | margin(top, second) < 0.15 | Prediction rounds. If still < 0.15: `probable` with both co-candidates plus the missing discriminating data |

### Failure handling

* An analysis agent that times out, crashes or returns invalid output (after one retry) is marked `failed` and an `error` message is logged. The run continues, the report gets "`<agent>` failed: `<reason>`", and the confidence category is capped at medium.
* If correlation fails, the report has status `failed` but still contains the raw anomalous findings.
* Malformed input fails safely with a `failed` report that explains why (`MALFORMED`, `TOO_LARGE`, `SCHEMA_VERSION_UNSUPPORTED`, …).
* Every loop is bounded by config: rounds, requests per round, and a total bus message cap.

---

## Correlation and scoring (documented method)

Fault signatures (`config/signatures.yaml`):

<!-- BEGIN GENERATED: signatures -->
| fault_type | Report label | Expects (op ref ×weight) | Contradicts | Entity |
|---|---|---|---|---|
| `congestion` | Likely link congestion causing egress queue drops | `link_utilization_pct` >= high ×3, `queue_drops_count` >= high ×3, `latency_ms` >= warn ×2, `packet_loss_pct` >= warn ×1 | `interface_errors_count` >= high ×2, `cpu_pct` >= high ×1 | link, device |
| `interface_fault` | Likely physical interface fault causing errors and packet loss | `interface_errors_count` >= high ×3, `crc_errors_count` >= warn ×2, `link_flaps_count` >= warn ×2, `packet_loss_pct` >= warn ×2 | `link_utilization_pct` >= high ×2 | link, device |
| `device_overload` | Likely device overload (CPU exhaustion) causing drops across interfaces | `cpu_pct` >= high ×3, `queue_drops_count` >= high ×2, `memory_pct` >= warn ×1, `latency_ms` >= warn ×1 | `link_utilization_pct` >= high ×2, `interface_errors_count` >= high ×1 | device |
| `weak_wifi` | Likely weak Wi-Fi signal at the access point causing retransmissions | `rssi_dbm` <= high ×3, `snr_db` <= high ×2, `retransmission_pct` >= high ×3, `latency_ms` >= warn ×1, `packet_loss_pct` >= warn ×1 | `link_utilization_pct` >= high ×2, `client_count` >= high ×1 | ap |
| `dns_failure` | Likely DNS service failure causing name-resolution errors | `dns_failure_pct` >= high ×4 | `latency_ms` >= high ×2, `packet_loss_pct` >= high ×2 | service |
| `dhcp_failure` | Likely DHCP service failure preventing new address leases | `dhcp_failure_pct` >= high ×4 | `latency_ms` >= high ×2, `packet_loss_pct` >= high ×2 | service |
<!-- END GENERATED: signatures -->

Signals are matched on the hypothesis entity and its topology neighbours (link ↔ endpoints, AP ↔ uplink,
service ↔ host switch). For each fault type the best-localized candidate entity is kept; on ties the more
specific type wins (link before device).

```
support  = Σ w_s [s ∈ E observed & matches]  / Σ w_s [s ∈ E]
coverage = Σ w_s [s ∈ E observed]            / Σ w_s [s ∈ E]
contra   = Σ w_c [c ∈ C observed & present]  / max(Σ w_c [c ∈ C], 1)
quality  = max(0.5, mean(completeness of used findings) − 0.05 × n_coerced_used)
score    = clamp(support − contra_penalty × contra, 0, 1) × quality
margin   = score(top) − score(second)
```

Completeness is `samples / (window / interval)`, capped at 0.5 for stale data (older than 900 s).

| Condition (in order) | Status |
|---|---|
| no usable observations, **or** coverage(top) < 0.50 | `insufficient_evidence` (`status_reason: data_missing`) + the exact missing signals |
| coverage ok, **no** finding ≥ `high`, top score < 0.45 | `no_fault_detected`; warn-level readings listed under `observations` (not evidence) |
| coverage ok, **some** finding ≥ `high`, top score < 0.45 | `insufficient_evidence` (`status_reason: no_signature_match`) |
| margin < 0.15 after prediction rounds | `probable`, top 2 reported as co-candidates |
| otherwise | `diagnosed` (wording stays "Likely …") |

`confidence` = score(top), rounded to 2 dp. `confidence_category` is `high` if ≥ 0.75 and margin ≥ 0.25,
`medium` if ≥ 0.50, otherwise `low`. Any `failed` agent or unresolved C2 conflict caps it at `medium`. For
`no_fault_detected`, confidence = (1 − best fault score) × the share of analysis agents that reported coverage.

**Predictions (P1–P5):**
* A prediction may only reference a signal not yet in that hypothesis's evidence.
* It is appended to the log **before** its evidence request.
* Scoring rejects any prediction whose `seq` is after its evidence response (tested by tampering with the log).
* Discriminating signals come first: signals the top two hypotheses expect in opposite directions.
* Hits and misses enter scoring as ordinary observed evidence, and `unknown` becomes a limitation.

Final constants (`config/scoring.yaml`; tuned on seed range A only):

<!-- BEGIN GENERATED: constants -->
| Constant | Value |
|---|---|
| contra_penalty | 1.0 |
| quality_floor | 0.5 |
| coerced_penalty | 0.05 |
| stale_quality | 0.5 |
| status.min_top_score | 0.45 |
| status.min_top_coverage | 0.5 |
| status.min_margin | 0.15 |
| confidence.high_min | 0.75 |
| confidence.high_min_margin | 0.25 |
| confidence.medium_min | 0.5 |
| conflicts.c1_relative_diff | 0.2 |
<!-- END GENERATED: constants -->

---

## Evaluation (`make eval`, `make fuzz`)

Incidents come from `eval/generate.py`, which reuses the organizer's record shape. `harden()` then makes them
realistic:
* variable fault intensity (pulled toward normal)
* confounders on unrelated entities (busy-but-healthy links, CPU spikes, latency bumps)
* telemetry gaps (a key signal not collected)
* up to 25% lost samples

30% of incidents additionally get 5–30% of their records corrupted. Wi-Fi telemetry is served by the **real Node.js
`wireless_agent`**. Constants were tuned on **seed range A** (`python -m eval.run_eval tune`, grid in
`eval/reports/tune_A.json`); the numbers below are from the held-out **seed range B**.

### Accuracy by data source

Two data sources are evaluated separately:

| Source | Fault types it produces | Ground truth |
|---|---|---|
| **Organizer generator** (`data/generator/`, raw, unmodified) | `normal`, `latency_spike`, `hardware_failure` (one record per call, `SW_CAMPUS_1..10`) | `normal` only; the two faults have no mapping to a NetCoop signature |
| **NetCoop extended generator** (`eval/generate.py` + `harden()`) | `normal`, `congestion`, `interface_fault`, `device_overload`, `weak_wifi`, `dns_failure`, `dhcp_failure` | exact fault type + location |

<!-- BEGIN GENERATED: organizer -->
#### Organizer generator (raw, unmodified)

`data/generator/organizer_generator.py`, 500 seeds per fault type, one record per call, full pipeline, no preprocessing. The organizer faults have no mapping to NetCoop signatures, so `latency_spike` / `hardware_failure` are scored on detection (not `no_fault_detected`).

| organizer fault | n | score | committed (diagnosed/probable) | status distribution | label distribution | records quarantined |
|---|---|---|---|---|---|---|
| `normal` | 500 | accuracy 1.0 | 0.0 | no_fault_detected 500 | no_fault_detected 500 | 0 |
| `latency_spike` | 500 | detection 1.0 | 0.0 | insufficient_evidence 500 | insufficient_evidence (no_signature_match) 500 | 0 |
| `hardware_failure` | 500 | detection 1.0 | 0.0 | insufficient_evidence 500 | insufficient_evidence (no_signature_match) 500 | 0 |
<!-- END GENERATED: organizer -->

**What this shows:**
* On raw organizer data NetCoop **detects** every fault (never `no_fault_detected`) but **does not commit** to a
  root cause: all 1,000 fault records end as `insufficient_evidence (no_signature_match)`. Healthy records are
  100% `no_fault_detected`.
* This is the intended behavior on that data. `hardware_failure` maxes *every* signal (CPU 99.9, utilization 100,
  interface errors, drops), so each signature is contradicted by another's symptom. `latency_spike` has high
  latency, but utilization stays below `high` and queue drops are normal, so no signature matches.
* A single sample per window also caps data quality at 0.5. NetCoop reports the anomaly and the missing
  discriminating signals instead of guessing.

### Extended generator (held-out seed range B)

<!-- BEGIN GENERATED: eval -->
#### Seed range B (held-out report)

seed 5000, 280 generated incidents (30% with 5–30 % corrupted records), wireless_agent: node.

| Metric | Value |
|---|---|
| n | 280 |
| overall accuracy | 0.846 |
| macro accuracy | 0.846 |
| precision when diagnosed | 0.972 |
| wrong diagnosis rate | 0.021 |
| fault to no fault rate | 0.013 |
| normal accuracy | 0.625 |
| false positive rate normal | 0.05 |
| insufficient evidence rate | 0.121 |
| localization accuracy | 0.995 |
| accuracy on mutated inputs | 0.845 |
| mutated share | 0.3 |
| crashes | 0 |
| mean ms per incident | 43.5 |

**Per fault**

| fault | n | accuracy | insufficient_evidence | probable |
|---|---|---|---|---|
| normal | 40 | 0.625 | 0.325 | 0.0 |
| congestion | 40 | 0.825 | 0.15 | 0.05 |
| interface_fault | 40 | 1.0 | 0.0 | 0.0 |
| device_overload | 40 | 0.8 | 0.1 | 0.25 |
| weak_wifi | 40 | 0.675 | 0.275 | 0.05 |
| dns_failure | 40 | 1.0 | 0.0 | 0.0 |
| dhcp_failure | 40 | 1.0 | 0.0 | 0.0 |

**Confusion matrix** (rows = truth, columns = predicted)

| truth \ pred | congestion | device_overload | dhcp_failure | dns_failure | insufficient_evidence | interface_fault | no_fault_detected | weak_wifi |
|---|---|---|---|---|---|---|---|---|
| normal | 1 | 1 | 0 | 0 | 13 | 0 | 25 | 0 |
| congestion | 33 | 0 | 0 | 0 | 6 | 0 | 1 | 0 |
| interface_fault | 0 | 0 | 0 | 0 | 0 | 40 | 0 | 0 |
| device_overload | 4 | 32 | 0 | 0 | 4 | 0 | 0 | 0 |
| weak_wifi | 0 | 0 | 0 | 0 | 11 | 0 | 2 | 27 |
| dns_failure | 0 | 0 | 0 | 40 | 0 | 0 | 0 | 0 |
| dhcp_failure | 0 | 0 | 40 | 0 | 0 | 0 | 0 | 0 |

**Calibration** (diagnosed/probable only)

| confidence bin | n | mean confidence | observed accuracy |
|---|---|---|---|
| [0.00, 0.50] | 9 | 0.476 | 0.778 |
| [0.50, 0.75] | 62 | 0.626 | 0.952 |
| [0.75, 0.90] | 66 | 0.83 | 0.985 |
| [0.90, 1.00] | 81 | 0.992 | 1.0 |

| confidence_category | n | observed accuracy |
|---|---|---|
| high | 147 | 0.993 |
| medium | 62 | 0.952 |
| low | 9 | 0.778 |
<!-- END GENERATED: eval -->

**Reading the numbers honestly:**
* Most errors are *abstentions*, not wrong answers: when NetCoop does commit to a diagnosis it is right
  ~97% of the time, and the wrong-diagnosis rate is ~2%.
* `normal` accuracy is the weakest class: confounders put readings at or above `high` on healthy networks (a busy
  link, a CPU spike). Those runs correctly report `insufficient_evidence (no_signature_match)`: something is
  anomalous but matches no fault. Warn-only readings yield `no_fault_detected`, with the readings under `observations`.
* Confidence is **under-confident**: in every bin, observed accuracy ≥ mean stated confidence.
* Operating point: tuning on A preferred `contra_penalty = 1.0` at `min_top_score = 0.45`. `min_top_score = 0.60`
  removes false positives on normal (FP 0.0 on A) at the cost of ~10 points of accuracy. See `eval/reports/tune_A.json`.

<!-- BEGIN GENERATED: fuzz -->
#### Degradation under corrupted input

70 incidents (seed 9000); each record corrupted with probability = rate using: renamed fields, swapped units, bare fractions, legacy v0.9 blocks, missing values, mangled IDs, dropped fields, missing schema_version. Ablation column: same pipeline with the metric registry's aliases and unit aliases removed.

| corruption rate | accuracy | precision when diagnosed | insufficient_evidence | FP on normal | values recovered | records quarantined | failed | crashes | accuracy w/o registry | |
|---|---|---|---|---|---|---|---|---|---|---|
| 0% | 0.786 | 0.946 | 0.171 | 0.0 | 0 | 0.0 % | 0 | 0 | 0.457 | `████████████████` |
| 10% | 0.786 | 0.964 | 0.186 | 0.0 | 808 | 0.4 % | 0 | 0 | 0.457 | `████████████████` |
| 20% | 0.8 | 0.947 | 0.157 | 0.0 | 1798 | 0.6 % | 0 | 0 | 0.443 | `████████████████` |
| 30% | 0.786 | 0.964 | 0.186 | 0.0 | 2739 | 1.0 % | 0 | 0 | 0.429 | `████████████████` |
| 40% | 0.786 | 0.964 | 0.186 | 0.0 | 3703 | 1.2 % | 0 | 0 | 0.457 | `████████████████` |
| 50% | 0.786 | 0.946 | 0.171 | 0.0 | 5241 | 1.9 % | 0 | 0 | 0.429 | `████████████████` |
| 60% | 0.771 | 0.963 | 0.2 | 0.0 | 6358 | 2.1 % | 0 | 0 | 0.414 | `███████████████` |
<!-- END GENERATED: fuzz -->

Accuracy stays flat because the normalizer *recovers* what is recoverable: thousands of values are converted,
inferred, canonicalized or upcast per sweep step. Without the registry's aliases and unit aliases, accuracy drops to ~0.45
even on clean input, because the organizer generator's own field names (`cpu_utilization_pct`, `queue_drops`,
`interface_errors`) are not canonical. Corruption causes zero crashes and zero failed runs.

---

## Error handling and robustness (normalization pipeline)

Runs in this order, and every step records `Transform{step, field, from, to, reason}`:

1. **Parse:** stdlib JSON/CSV, 10 MB cap; non-UTF-8 → `MALFORMED`.
2. **Version:** detect → upcast (embedded v0.9 blocks inside bundles are expanded too).
3. **Field aliases** from `metrics.yaml`. Unknown fields → `extras` + warning. The generator's `status` label is kept but never used as evidence.
4. **Units:** explicit unit → `unit_aliases`; missing → batch inference only; otherwise quarantine.
5. **Coercion:** `"280ms"` → 280 ms. `"N/A"`, `""`, `null` and `NaN` → **missing, never 0**.
6. **Plausibility:** an out-of-range value (negative latency, utilization > 100, RSSI > 0) quarantines the record.
7. **Entities:** PI6 regex, then topology aliases (case- and separator-insensitive, IPs too). An unknown entity → quarantine + `UNKNOWN_ENTITY`.
8. **Time:** everything to UTC (epoch s/ms, offsets, naive → UTC + logged). More than 5 min in the future → quarantine. Older than the window → counted. Staleness is computed relative to the incident time.
9. **Dedupe** on (entity, metric, timestamp, source).
10. **Validate** against the Pydantic models.

Invariant (tested, and property-tested with `hypothesis`): `records_in == records_used + records_quarantined`.
Every coercion sets `data_quality.coerced`, lowers quality, and appears in `limitations`.

## Guardrails and security

* **Remediation is never executed:** actions are recommendations from `playbook.yaml` only.
* **Policies are code-enforced hard rules** (`config/policies.yaml`):

<!-- BEGIN GENERATED: policies -->
| Rule | Type | Applies to | When | Reason |
|---|---|---|---|---|
| R1 | forbidden_action | reboot on core_switch | 09:00-17:00 mon,tue,wed,thu,fri | Class hours |
| R2 | threshold_override | latency_ms in lecture_halls | warn 30, high 50 | Lecture-hall streaming SLA |
| R3 | forbidden_action | config_change, reboot, restart_service on core_router | always | Core router changes require change-advisory-board approval |
| R4 | forbidden_action | reboot, restart_service, move_port, replace_optic on any | 2026-11-16–2026-11-28 | End-semester examination period: no disruptive changes |
| R5 | forbidden_action | restart_service, failover on service | 08:00-22:00 | Campus services may only be restarted outside 08:00-22:00 unless the duty officer approves |
<!-- END GENERATED: policies -->

* **Validator (G4):** every `supporting_evidence` references an existing `finding_id` (so config or playbook text can never be evidence), every affected device exists in topology, and every `fault_type` is in the enum.
* **G5 lint:** "confirmed / definitely / certainly / guaranteed" are banned, and every report has at least one limitation.
* **Prompt injection (§11):**
  * the LLM is off by default and can only classify the complaint into an enum (a hint that can only *add* a hypothesis) or write the narrative from the validated report
  * complaint text is truncated, tag-stripped and wrapped
  * outputs are allowlisted (known IDs only, no URLs or code); otherwise the deterministic template is used
* **External output is untrusted:** same normalizer, owned metrics only, findings recomputed with *our* registry (agent-authored findings are ignored), 256 KB cap, timeout, rate limit, no tools.
* **API:** 10 MB uploads, `.json`/`.csv` only, incident IDs validated before touching `runs/` (path traversal blocked), parameterized SQLite, CSV formula-injection guard, localhost CORS, structured errors.
* The `tests/security/` suite (PI9) covers:
  * injection in a device name
  * injection in the complaint, with LLM off and with LLM mocked
  * malicious external agents: oversized, wrong types, instruction text, SQL-ish metric name, fake findings, spoofed incident, non-JSON
  * LLM output naming an unknown device
  * path traversal

  Each attack must leave the report identical to the clean baseline, or fail safely: the agent is marked failed and confidence is capped.

## Report format

The PS fields are kept exactly: `incident_id, status, suspected_root_cause, confidence, affected_devices,
supporting_evidence, alternative_causes, recommended_actions, evidence_sources, limitations`.
These extensions are additive:
* `schema_version`, `fault_type`, `confidence_category`, `status_reason` (`data_missing` | `no_signature_match`)
* `observations` (warn-level readings not used as evidence)
* `scoring{support, coverage, contra, quality, score, margin}`
* `co_candidates`, `rejected_alternatives`, `predictions`
* `blocked_actions` (with `rule_id`), `action_details`
* `missing_signals`, `conflicts`, `agents`
* `normalization_summary`, `narrative`

`status` ∈ `diagnosed | probable | insufficient_evidence | no_fault_detected | failed`.

## Testing

| Command | What it does |
|---|---|
| `make test` | 92 tests (incl. parametrized security cases + 3 property tests × 200–250 examples), offline, ~25 s: one test per PS scenario, normalizer (every alias, every unit conversion, upcaster, quarantine paths, never-silently-drop), property tests, prediction honesty (seq ordering, no prediction on seen signals, tamper rejection), replay determinism, report validator, policy, PI9 security, API |
| `make demo` | All scenarios via the CLI |
| `make eval` / `make fuzz` | Measured accuracy, calibration, degradation curve → `eval/reports/` |
| `make conformance AGENT_URL=…` | Conformance kit |
| `make schemas` / `make docs` | JSON Schemas; README tables from config |

Tests that need Node start the real `wireless_agent` on a free port, and are skipped if Node is missing.

## Repository layout

```
config/            metrics, signatures, playbook, policies, agents, topology, scoring (all knowledge lives here)
netcoop/           protocol/ normalize/ bus/ orchestrator/ agents/ scoring/ policy/ gateway/ llm/ api/ cli.py
external_agents/wireless_agent/   Node.js agent, dialect v0.9 (+ data/demo.json)
conformance/       conformance kit (runnable against any agent URL)
data/generator/    organizer generator (verbatim) + SCHEMA.md
data/scenarios/    7 fixed scenario fixtures
eval/              generate.py, mutate.py, run_eval.py, reports/
tests/             unit/ integration/ security/ property/
docs/schemas/      exported JSON Schemas
runs/<id>/         events.jsonl, report.json, input, meta.json, external.jsonl (gitignored)
```

## Limitations

* All telemetry is synthetic. The topology in `config/topology.yaml` is a NetCoop-defined model of the campus,
  and thresholds and weights are tuned on generated data.
* The eval generator is ours, so accuracy measures internal consistency under realistic noise, not field performance.
* A2A is implemented as wire shapes over stdlib HTTP (the documented fallback), not via `a2a-sdk`; see `TODO.md`.
* The optional LLM paths (Ollama / Anthropic API) are implemented but not exercised in CI beyond mocked tests.
