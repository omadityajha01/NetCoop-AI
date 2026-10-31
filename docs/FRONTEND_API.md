# NetCoop frontend API contract

> **Generated** by `python tools/gen_frontend_api.py` from the code (FastAPI app, Pydantic models, module constants) and from fixtures recorded on the real backend (`tools/record_fixtures.py`). Do not edit by hand; a test fails if this file is stale.

Protocol: NMP **1.4**. Base URL: `http://127.0.0.1:<port>` (`netcoop serve --port 8000`, the default; it binds loopback only). Mock without a backend: `python tools/mock_api.py` (same endpoints, recorded data; see [Mock](#mock-api-no-backend)).

Contents: [Endpoints](#endpoints) · [Errors](#error-shapes) · [SSE stream](#sse-stream) · [Message payloads](#message-payloads-by-message_type) · [Flows](#flows) · [Security headers](#security-headers-csp-cors) · [Static UI](#static-ui-files) · [Fixtures](#fixtures) · [Mock](#mock-api-no-backend) · [Glossary](#glossary)

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/incidents` | Upload an incident bundle (JSON/CSV bytes, 10 MB max) and run a diagnosis; returns the full report. |
| POST | `/scenarios/{name}/run` | Run one built-in scenario (the dashboard's only write action). Same pipeline as the CLI; LLM per env. |
| GET | `/topology` | Configured topology as nodes (id, type, segment, role, parent) and links (id, a, b) for drawing. |
| GET | `/incidents/{incident_id}/stream` | Server-sent events: the run's event log in `seq` order, then `event: end`. |
| GET | `/incidents` | Past runs, newest first (limit 1-500). |
| GET | `/incidents/{incident_id}/report` | The final diagnostic report of a run. |
| GET | `/incidents/{incident_id}/events` | The run's complete event log (every NMP message, in seq order), including post-run HITL messages. |
| GET | `/incidents/{incident_id}/report.csv` | Supporting evidence as CSV (formula-injection safe). |
| POST | `/incidents/{incident_id}/feedback` | Approve/reject an action (non-blocking HITL). Approve re-runs the policy check; allowed -> dry-run plan. |
| GET | `/agents` | External agents from the allowlist and whether each is reachable now (joined) or not. |
| GET | `/` | UI static file (see [Static UI](#static-ui-files)) |
| GET | `/dashboard` | UI static file (see [Static UI](#static-ui-files)) |
| GET | `/ui/{path:path}` | UI static file (see [Static UI](#static-ui-files)) |
| GET | `/dashboard/{name}` | UI static file (see [Static UI](#static-ui-files)) |
| GET | `/docs` | FastAPI's generated docs / OpenAPI document |
| GET | `/redoc` | FastAPI's generated docs / OpenAPI document |
| GET | `/openapi.json` | FastAPI's generated docs / OpenAPI document |

### POST `/incidents`

Upload an incident bundle (JSON/CSV bytes, 10 MB max) and run a diagnosis; returns the full report.

| Parameter | In | Type | Required | Default |
|---|---|---|---|---|
| `external` | query | boolean | no | True |
| `filename` | query | string | no | upload.json |

Request body: the raw incident bundle (JSON or CSV bytes, ≤ 10 MB), same format as `data/scenarios/<name>/incident.json`. The response is the full report (see `docs/frontend_fixtures/*/report.json`). Invalid input still answers **200** with `status: failed`.

Response `200` (real example):
```json
{
  "incident_id": "INC-LNPPZSZE",
  "status": "failed",
  "suspected_root_cause": "Diagnosis failed",
  "confidence": 0.0,
  "affected_devices": [],
  "supporting_evidence": [],
  "alternative_causes": [],
  "recommended_actions": [
    "Fix the input or agent failure listed in limitations and re-run"
  ],
  "evidence_sources": [],
  "limitations": [
    "Synthetic telemetry (organizer generator schema + NetCoop extensions); not campus measurements",
    "Input rejected (MALFORMED): invalid JSON: Expecting value at line 1"
  ],
  "schema_version": "1.4",
  "confidence_category": "low",
  "fault_type": null,
  "narrative": null
}
```

### POST `/scenarios/{name}/run`

Run one built-in scenario (the dashboard's only write action). Same pipeline as the CLI; LLM per env.

| Parameter | In | Type | Required | Default |
|---|---|---|---|---|
| `name` | path | string | yes |  |
| `external` | query | boolean | no | True |

Response `200` (real example):
```json
{
  "incident_id": "INC-LWP6J7WP",
  "status": "diagnosed"
}
```

### GET `/topology`

Configured topology as nodes (id, type, segment, role, parent) and links (id, a, b) for drawing.

Response `200` (real example):
```json
{
  "nodes": [
    {
      "id": "AP_H1",
      "type": "ap",
      "segment": "hostel",
      "role": "access_point",
      "parent": "HOSTEL_ACC_SW_01"
    },
    "… 25 more"
  ],
  "links": [
    {
      "id": "L_AP_H1",
      "a": "AP_H1",
      "b": "HOSTEL_ACC_SW_01"
    },
    "… 24 more"
  ]
}
```

### GET `/incidents/{incident_id}/stream`

Server-sent events: the run's event log in `seq` order, then `event: end`.

| Parameter | In | Type | Required | Default |
|---|---|---|---|---|
| `incident_id` | path | string | yes |  |
| `delay_ms` | query | integer | no | 0 |

Response: `text/event-stream`, see [SSE stream](#sse-stream).

### GET `/incidents`

Past runs, newest first (limit 1-500).

| Parameter | In | Type | Required | Default |
|---|---|---|---|---|
| `limit` | query | integer | no | 50 |

Response `200` (real example):
```json
[
  {
    "incident_id": "INC-LNPPZSZE",
    "status": "failed",
    "suspected_root_cause": "Diagnosis failed",
    "confidence": 0.0,
    "created_at": "2026-10-31T21:28:38.021783+00:00"
  },
  {
    "incident_id": "INC-LWP6J7WP2",
    "status": "diagnosed",
    "suspected_root_cause": "Likely link congestion causing egress queue drops on L_HOSTEL_UPLINK",
    "confidence": 1.0,
    "created_at": "2026-10-31T21:28:37.242229+00:00"
  }
]
```

### GET `/incidents/{incident_id}/report`

The final diagnostic report of a run.

| Parameter | In | Type | Required | Default |
|---|---|---|---|---|
| `incident_id` | path | string | yes |  |

Response `200` (real example):
```json
{
  "incident_id": "INC-LWP6J7WP",
  "status": "diagnosed",
  "suspected_root_cause": "Likely link congestion causing egress queue drops on L_HOSTEL_UPLINK",
  "confidence": 1.0,
  "affected_devices": [
    "HOSTEL_CORE_SW_01"
  ],
  "supporting_evidence": [
    {
      "metric": "queue_drops_count",
      "value": 528.0,
      "unit": "count",
      "entity": "HOSTEL_CORE_SW_01",
      "interpretation": "High egress queue drops",
      "finding_id": "F-infrastructure_agent-39",
      "source_agent": "infrastructure_agent",
      "hypothesis": "congestion"
    },
    "… 4 more"
  ],
  "alternative_causes": [
    "Likely physical interface fault causing errors and packet loss on L_HOSTEL_ACC_01 (score 0.22)",
    "… 2 more"
  ],
  "recommended_actions": [
    "Inspect upstream and egress link utilization on L_HOSTEL_UPLINK",
    "… 2 more"
  ],
  "evidence_sources": [
    "infrastructure_agent",
    "performance_agent"
  ],
  "limitations": [
    "Synthetic telemetry (organizer generator schema + NetCoop extensions); not campus measurements",
    "… 3 more"
  ],
  "schema_version": "1.4",
  "decision_source": "deterministic_scoring",
  "confidence_category": "high",
  "status_reason": null,
  "observations": [
    {
      "metric": "latency_ms",
      "value": 114.16,
      "unit": "ms",
      "entity": "HOSTEL_ACC_SW_01",
      "severity": "warn",
      "interpretation": "Elevated network latency",
      "finding_id": "F-performance_agent-13"
    },
    "… 2 more"
  ],
  "fault_type": "congestion",
  "scoring": {
    "support": 1.0,
    "coverage": 1.0,
    "contra": 0.0,
    "quality": 1.0,
    "score": 1.0,
    "margin": 0.7778
  },
  "co_candidates": [],
  "rejected_alternatives": [
    {
      "fault_type": "interface_fault",
      "entity": "L_HOSTEL_ACC_01",
  … (truncated; full example in the fixture file)
```

### GET `/incidents/{incident_id}/events`

The run's complete event log (every NMP message, in seq order), including post-run HITL messages.

| Parameter | In | Type | Required | Default |
|---|---|---|---|---|
| `incident_id` | path | string | yes |  |

Response `200` (real example):
```json
[
  {
    "created_at": "2026-10-31T21:28:34.069890Z",
    "extras": {},
    "in_reply_to": null,
    "incident_id": "INC-LWP6J7WP1",
    "limitations": [
      {
        "code": "FIELDS_RENAMED",
        "detail": "204 field(s) mapped from aliases to canonical names",
        "impact": "none"
      }
    ],
    "message_id": "73ef15fb-bba8-44c4-99a5-24f57aff04d6",
    "message_type": "normalization_summary",
    "payload": {
      "complaint_present": true,
      "extras": [],
      "hints": [],
      "incident_time": "2026-10-28T05:30:00Z",
      "incident_time_inferred": false,
      "input_sha256": "5d9fe4fecf5fb3509a78e80dfb81ff3e5409f3bb8f4c84a577aab4d3df6778d2",
      "quarantined": [],
      "summary": {
        "coerced": 0,
        "deduped": 0,
        "entity_canonicalized": 0,
        "extras": 0,
        "missing_values": 0,
        "observations_used": 456,
        "out_of_window": 0,
        "quarantined": 0,
        "records_in": 108,
        "records_quarantined": 0,
        "records_used": 108,
        "renamed": 204,
        "unit_converted": 0,
        "unit_inferred": 0,
        "unknown_fields": 0,
        "version_upcast": 0
      },
      "window": {
        "end": "2026-10-28T05:30:00Z",
        "start": "2026-10-28T05:00:00Z"
      }
    },
    "recipient": "orchestrator",
    "schema_version": "1.4",
    "sender": "normalizer",
    "seq": 1,
    "status": "completed"
  },
  "… 27 more"
]
```

### GET `/incidents/{incident_id}/report.csv`

Supporting evidence as CSV (formula-injection safe).

| Parameter | In | Type | Required | Default |
|---|---|---|---|---|
| `incident_id` | path | string | yes |  |

Response: `text/plain` CSV (cells starting with `= + - @` are prefixed with `'`). Real example:
```
incident_id,status,metric,entity,value,unit,interpretation,finding_id
INC-LWP6J7WP,diagnosed,queue_drops_count,HOSTEL_CORE_SW_01,528.0,count,High egress queue drops,F-infrastructure_agent-39
INC-LWP6J7WP,diagnosed,latency_ms,HOSTEL_CORE_SW_01,286.44,ms,High network latency,F-performance_agent-15
INC-LWP6J7WP,diagnosed,link_utilization_pct,L_HOSTEL_UPLINK,98.31,pct,Critical link utilization,F-performance_agent-21
```

### POST `/incidents/{incident_id}/feedback`

Approve/reject an action (non-blocking HITL). Approve re-runs the policy check; allowed -> dry-run plan.

| Parameter | In | Type | Required | Default |
|---|---|---|---|---|
| `incident_id` | path | string | yes |  |

Request body (JSON Schema, from the code):
```json
{
  "properties": {
    "action_id": {
      "type": "string",
      "pattern": "^[A-Z]{2,6}-[0-9]{1,3}$",
      "title": "Action Id"
    },
    "decision": {
      "type": "string",
      "pattern": "^(approve|reject)$",
      "title": "Decision"
    },
    "note": {
      "anyOf": [
        {
          "type": "string",
          "maxLength": 500
        },
        {
          "type": "null"
        }
      ],
      "title": "Note"
    }
  },
  "type": "object",
  "required": [
    "action_id",
    "decision"
  ],
  "title": "Feedback"
}
```

Response `200` (real example):
```json
{
  "id": 1,
  "executed": false,
  "event_seq": 28,
  "message_id": "66bdbce8-7aea-4270-96cc-fc8abdc18c59",
  "policy": {
    "allowed": false,
    "rule_id": "R1",
    "reason": "Class hours",
    "checked_at": "2026-10-28T05:30:00+00:00"
  },
  "plan_seq": null,
  "plan": null
}
```

### GET `/agents`

External agents from the allowlist and whether each is reachable now (joined) or not.

Response `200` (real example):
```json
{
  "external": {
    "wireless_agent": "joined"
  },
  "details": {
    "wireless_agent": {
      "base_url": "http://127.0.0.1:8765",
      "card_name": "wifi-probe",
      "card_version": "0.9.3",
      "capabilities": [
        "metric:rssi_dbm",
        "metric:snr_db",
        "metric:retransmission_pct",
        "metric:client_count"
      ]
    }
  }
}
```

Without the agent running, the same call returns:
```json
{
  "external": {
    "wireless_agent": "unreachable"
  },
  "details": {
    "wireless_agent": {
      "base_url": "http://127.0.0.1:8765",
      "error": "TIMEOUT"
    }
  }
}
```

## Error shapes

Handled errors: `{"detail": {"code": <CODE>, "detail": <text>}}`. Body validation errors: FastAPI's `422 {"detail": [ {type, loc, msg, input, ctx} ]}`. Unknown routes: `404 {"detail": "Not Found"}`. Any unhandled exception: `500 {"error": {"code": "INTERNAL", "detail": "internal error"}}` (no stack traces). Real responses:

* **400 bad incident_id**: `{"detail": {"code": "BAD_INCIDENT_ID", "detail": "incident_id must match ^INC-[0-9A-Z]{4,12}$"}}`
* **404 unknown incident**: `{"detail": {"code": "NOT_FOUND", "detail": "unknown incident"}}`
* **404 unknown scenario**: `{"detail": {"code": "UNKNOWN_SCENARIO", "detail": "unknown scenario"}}`
* **404 unknown action**: `{"detail": {"code": "UNKNOWN_ACTION", "detail": "action_id is not an action of this incident"}}`
* **422 validation**: `{"detail": [{"type": "string_pattern_mismatch", "loc": ["body", "action_id"], "msg": "String should match pattern '^[A-Z]{2,6}-[0-9]{1,3}$'", "input": "x", "ctx": {"pattern": "^[A-Z]{2,6}-[0-9]{1,3}$"}}, {"type": "string_pattern_mismatch", "loc": ["body", "decision"], "msg": "String should match pat`
* **415 upload type**: `{"detail": {"code": "UNSUPPORTED", "detail": "only .json or .csv uploads"}}`
* **200 with status failed (malformed upload)**: `{"incident_id": "INC-PTH2D67T", "status": "failed", "suspected_root_cause": "Diagnosis failed", "limitations": ["Synthetic telemetry (organizer generator schema + NetCoop extensions); not campus measurements", "Input rejected (MISSING_FIELD): no usable timestamps and no incident.time; cannot place t`

## SSE stream

`GET /incidents/{incident_id}/stream?delay_ms=<0..2000>`: replays the run's event log (`events.jsonl`) in `seq` order, then ends. The run is already complete when you stream it: start a run, get its `incident_id`, then open the stream. `delay_ms` (clamped to 0–2000) is the pause after each message; the built-in dashboard uses 240 (1×) and 120 (2×). Headers: `Content-Type: text/event-stream`, `Cache-Control: no-cache`.

Event names: `message` (one NMP message as JSON in `data`, `id` = its `seq`) and a final `end` (`data: {"messages": <count>}`). Exact frames produced by the server code (first two messages of the `normal` fixture, data shortened here):

```
id: 1
event: message
data: {"created_at": "2026-10-31T21:28:20.415784Z", "extras": {}, "in_reply_to": null, "incident_id": "INC-Q3BLERDV", "limitations": [{"code": "FIELDS_RENAMED", "deta …

id: 2
event: message
data: {"created_at": "2026-10-31T21:28:21.920057Z", "extras": {}, "in_reply_to": null, "incident_id": "INC-Q3BLERDV", "limitations": [], "message_id": "d386b95d-e0d3- …

event: end
data: {"messages": 18}
```

Clients should parse each `data` as one JSON document, order by `seq` (the server already sends them in order) and render every string as text. Device names and limitations can contain anything the input contained. Messages appended after the report (`human_decision`, `remediation_plan`) are in the log too: re-open the stream or `GET /incidents/{id}/events` after approving.

### Envelope (every message)

| Field | Type |
|---|---|
| `schema_version` | string matching `^[0-9]+\.[0-9]+$` |
| `message_id` | string |
| `message_type` | `task_request`, `finding_report`, `coverage_manifest`, `prediction`, `evidence_request`, `evidence_response`, `diagnosis`, `report`, `error`, `normalization_summary`, `hint`, `human_decision`, `remediation_plan` |
| `incident_id` | string matching `^INC-[0-9A-Z]{4,12}$` |
| `sender` | string matching `^[a-z][a-z0-9_]{1,40}$` |
| `recipient` | string matching `^[a-z][a-z0-9_]{1,40}$` |
| `in_reply_to` | string or null |
| `seq` | integer or null |
| `created_at` | string (date-time) or null |
| `status` | `completed`, `partial`, `failed`, `insufficient_data` |
| `payload` | object |
| `limitations` | array of object |
| `extras` | object |

`message_type` ∈ `task_request`, `finding_report`, `coverage_manifest`, `prediction`, `evidence_request`, `evidence_response`, `diagnosis`, `report`, `error`, `normalization_summary`, `hint`, `human_decision`, `remediation_plan`. JSON Schema: `docs/schemas/envelope.schema.json`.

## Message payloads by message_type

Every example below is the first real message of that type in a recorded fixture (long lists shortened). Schemas: `docs/schemas/payload.<message_type>.schema.json`.

### `task_request`

Payload fields (TaskRequestPayload): `task`, `window`, `round`, `params`.

Real example (`docs/frontend_fixtures/normal/events.jsonl`, seq 2):
```json
{
  "seq": 2,
  "message_type": "task_request",
  "sender": "orchestrator",
  "recipient": "connectivity_agent",
  "status": "completed",
  "payload": {
    "params": {},
    "round": 0,
    "task": "analyze",
    "window": {
      "end": "2026-10-26T06:00:00Z",
      "start": "2026-10-26T05:30:00Z"
    }
  }
}
```

### `finding_report`

Payload fields (FindingReportPayload): `round`, `findings`, `observations`, `scope`.

Real example (`docs/frontend_fixtures/normal/events.jsonl`, seq 5):
```json
{
  "seq": 5,
  "message_type": "finding_report",
  "sender": "connectivity_agent",
  "recipient": "orchestrator",
  "status": "completed",
  "payload": {
    "findings": [],
    "observations": null,
    "round": 0,
    "scope": null
  }
}
```

### `coverage_manifest`

Payload fields (CoverageManifestPayload): `signals`.

Real example (`docs/frontend_fixtures/normal/events.jsonl`, seq 6):
```json
{
  "seq": 6,
  "message_type": "coverage_manifest",
  "sender": "connectivity_agent",
  "recipient": "orchestrator",
  "status": "completed",
  "payload": {
    "signals": [
      {
        "entity": {
          "id": "DHCP_01",
          "type": "service"
        },
        "metric": "dhcp_failure_pct"
      },
      {
        "entity": {
          "id": "DNS_01",
          "type": "service"
        },
        "metric": "dns_failure_pct"
      }
    ]
  }
}
```

### `prediction`

Payload fields (PredictionPayload): `prediction`.

Real example (`docs/frontend_fixtures/congestion/events.jsonl`, seq 15):
```json
{
  "seq": 15,
  "message_type": "prediction",
  "sender": "correlation_agent",
  "recipient": "orchestrator",
  "status": "completed",
  "payload": {
    "prediction": {
      "evidence_finding_id": null,
      "expected": {
        "op": "<",
        "ref": "high"
      },
      "fault_type": "congestion",
      "hypothesis_id": "H-congestion-L_HOSTEL_UPLINK",
      "outcome": "pending",
      "prediction_id": "P-1-1",
      "round": 1,
      "signal": {
        "entity": {
          "id": "HOSTEL_CORE_SW_01",
          "type": "device"
        },
        "metric": "interface_errors_count",
        "window": {
          "end": "2026-10-28T05:30:00Z",
          "start": "2026-10-28T05:00:00Z"
        }
      }
    }
  }
}
```

### `evidence_request`

Payload fields (EvidenceRequestPayload): `round`, `requests`, `prediction_ids`, `reason`.

Real example (`docs/frontend_fixtures/congestion/events.jsonl`, seq 18):
```json
{
  "seq": 18,
  "message_type": "evidence_request",
  "sender": "correlation_agent",
  "recipient": "infrastructure_agent",
  "status": "completed",
  "payload": {
    "prediction_ids": [
      "P-1-1",
      "P-1-2"
    ],
    "reason": "prediction",
    "requests": [
      {
        "entity": {
          "id": "HOSTEL_CORE_SW_01",
          "type": "device"
        },
        "metric": "interface_errors_count",
        "window": {
          "end": "2026-10-28T05:30:00Z",
          "start": "2026-10-28T05:00:00Z"
        }
      },
      "… 3 more"
    ],
    "round": 1
  }
}
```

### `evidence_response`

Payload fields (EvidenceResponsePayload): `round`, `findings`, `observations`, `unavailable`.

Real example (`docs/frontend_fixtures/congestion/events.jsonl`, seq 20):
```json
{
  "seq": 20,
  "message_type": "evidence_response",
  "sender": "infrastructure_agent",
  "recipient": "orchestrator",
  "status": "completed",
  "payload": {
    "findings": [
      {
        "aggregation": "max",
        "data_quality": {
          "coerced": false,
          "completeness": 1.0,
          "staleness_s": 0.0
        },
        "entity": {
          "id": "HOSTEL_CORE_SW_01",
          "type": "device"
        },
        "finding_id": "F-infrastructure_agent-10001",
        "metric": "interface_errors_count",
        "placed": true,
        "sample_count": 6,
        "severity": "normal",
        "source": "input",
        "source_refs": [
          "records[22].interface_errors",
          "… 5 more"
        ],
        "threshold_ref": "metrics.yaml#interface_errors_count.default.warn",
        "transforms": [
          {
            "field": "interface_errors",
            "from": "interface_errors",
            "reason": "metrics.yaml alias",
            "step": "alias",
            "to": "interface_errors_count"
          }
        ],
        "unit": "count",
        "value": 2.0,
        "window": {
          "end": "2026-10-28T05:30:00Z",
          "start": "2026-10-28T05:05:00Z"
        }
      },
      "… 3 more"
    ],
    "observations": null,
    "round": 1,
    "unavailable": []
  }
}
```

### `diagnosis`

Payload fields (DiagnosisPayload): `phase`, `round`, `status`, `status_reason`, `hypotheses`, `top_hypothesis_id`, `co_candidate_ids`, `margin`, `confidence`, `confidence_category`, `caps`, `conflicts`, `predictions`, `missing_signals`, `anomalous_finding_count`, `scope`, `notes`.

Real example (`docs/frontend_fixtures/normal/events.jsonl`, seq 14):
```json
{
  "seq": 14,
  "message_type": "diagnosis",
  "sender": "correlation_agent",
  "recipient": "orchestrator",
  "status": "completed",
  "payload": {
    "anomalous_finding_count": 0,
    "caps": [],
    "co_candidate_ids": [],
    "confidence": 1.0,
    "confidence_category": "high",
    "conflicts": [],
    "hypotheses": [],
    "margin": 0.0,
    "missing_signals": [],
    "notes": [
      "coverage share 1.00"
    ],
    "phase": "interim",
    "predictions": [],
    "round": 1,
    "scope": {
      "affected_devices": [],
      "affected_entities": [],
      "nearest_common_upstream": null,
      "segments": []
    },
    "status": "no_fault_detected",
    "status_reason": null,
    "top_hypothesis_id": null
  }
}
```

### `report`

Payload fields (ReportPayload): `report`.

Real example (`docs/frontend_fixtures/normal/events.jsonl`, seq 18):
```json
{
  "seq": 18,
  "message_type": "report",
  "sender": "reporting_agent",
  "recipient": "orchestrator",
  "status": "completed",
  "payload": {
    "report": {
      "action_details": [
        {
          "action": "monitor",
          "allowed": true,
          "id": "GEN-2",
          "rule_id": null,
          "target": null,
          "text": "No action required; continue monitoring"
        }
      ],
      "affected_devices": [],
      "agents": {
        "connectivity_agent": "completed",
        "correlation_agent": "completed",
        "infrastructure_agent": "completed",
        "performance_agent": "completed",
        "reporting_agent": "completed",
        "wireless_agent": "unreachable"
      },
      "alternative_causes": [],
      "blocked_actions": [],
      "co_candidates": [],
      "confidence": 1.0,
      "confidence_category": "high",
      "conflicts": [],
      "decision_source": "deterministic_scoring",
      "evidence_sources": [
        "connectivity_agent",
        "… 2 more"
      ],
      "fault_type": null,
      "incident_id": "INC-Q3BLERDV",
      "limitations": [
        "Synthetic telemetry (organizer generator schema + NetCoop extensions); not campus measurements",
        "External agent wireless_agent unreachable; its signals were unavailable"
      ],
      "missing_signals": [],
      "narrative": null,
      "normalization_summary": {
        "coerced": 0,
        "deduped": 0,
        "entity_canonicalized": 0,
        "extras": 0,
        "missing_values": 0,
        "observations_used": 720,
        "out_of_window": 0,
        "quarantined": 0,
        "records_in": 150,
        "records_quarantined": 0,
        "records_used": 150,
        "renamed": 354,
        "unit_converted": 0,
        "unit_inferred": 0,
        "ver
  … (truncated; full example in the fixture file)
```

### `error`

Payload fields (ErrorPayload): `code`, `detail`, `offending_message_id`, `field`, `agent_id`.

Real example (`docs/frontend_fixtures/malformed_input_error/events.jsonl`, seq 1):
```json
{
  "seq": 1,
  "message_type": "error",
  "sender": "normalizer",
  "recipient": "orchestrator",
  "status": "failed",
  "payload": {
    "agent_id": null,
    "code": "MALFORMED",
    "detail": "invalid JSON: Expecting value at line 1",
    "field": null,
    "offending_message_id": null
  }
}
```

### `normalization_summary`

Payload fields (NormalizationSummaryPayload): `input_sha256`, `incident_time`, `incident_time_inferred`, `window`, `summary`, `quarantined`, `extras`, `complaint_present`, `hints`.

Real example (`docs/frontend_fixtures/normal/events.jsonl`, seq 1):
```json
{
  "seq": 1,
  "message_type": "normalization_summary",
  "sender": "normalizer",
  "recipient": "orchestrator",
  "status": "completed",
  "payload": {
    "complaint_present": true,
    "extras": [],
    "hints": [],
    "incident_time": "2026-10-26T06:00:00Z",
    "incident_time_inferred": false,
    "input_sha256": "86c2b24475478eb083c74aa1443288c12596041d8e29d01fb7415010ec34b940",
    "quarantined": [],
    "summary": {
      "coerced": 0,
      "deduped": 0,
      "entity_canonicalized": 0,
      "extras": 0,
      "missing_values": 0,
      "observations_used": 720,
      "out_of_window": 0,
      "quarantined": 0,
      "records_in": 150,
      "records_quarantined": 0,
      "records_used": 150,
      "renamed": 354,
      "unit_converted": 0,
      "unit_inferred": 0,
      "unknown_fields": 0,
      "version_upcast": 0
    },
    "window": {
      "end": "2026-10-26T06:00:00Z",
      "start": "2026-10-26T05:30:00Z"
    }
  }
}
```

### `hint`

Payload fields (HintPayload): `fault_type`, `rationale`, `model`.

Real example (`docs/frontend_fixtures/interop_llm_hint/events.jsonl`, seq 12):
```json
{
  "seq": 12,
  "message_type": "hint",
  "sender": "triage_agent",
  "recipient": "orchestrator",
  "status": "completed",
  "payload": {
    "fault_type": "dns_failure",
    "model": "llama3.2:3b",
    "rationale": "The word \"slow\" suggests the fault type 'dns_failure'."
  }
}
```

### `human_decision`

Payload fields (HumanDecisionPayload): `action_id`, `decision`, `feedback_id`, `executed`, `note_stored`.

Real example (`docs/frontend_fixtures/approved_action_plan/events.jsonl`, seq 28):
```json
{
  "seq": 28,
  "message_type": "human_decision",
  "sender": "human_operator",
  "recipient": "orchestrator",
  "status": "completed",
  "payload": {
    "action_id": "CONG-1",
    "decision": "approve",
    "executed": false,
    "feedback_id": 2,
    "note_stored": true
  }
}
```

### `remediation_plan`

Payload fields (RemediationPlanPayload): `action_id`, `action`, `target`, `label`, `executed`, `policy`, `steps`, `rollback`, `human_decision_seq`.

Real example (`docs/frontend_fixtures/approved_action_plan/events.jsonl`, seq 29):
```json
{
  "seq": 29,
  "message_type": "remediation_plan",
  "sender": "remediation_planner",
  "recipient": "human_operator",
  "status": "completed",
  "payload": {
    "action": "inspect",
    "action_id": "CONG-1",
    "executed": false,
    "human_decision_seq": 28,
    "label": "SIMULATED – NOT EXECUTED",
    "policy": {
      "allowed": true,
      "checked_at": "2026-10-28T05:30:00+00:00",
      "reason": null,
      "rule_id": null
    },
    "rollback": [
      "Close the read-only session to HOSTEL_CORE_SW_01; nothing was changed"
    ],
    "steps": [
      "Open a read-only session to HOSTEL_CORE_SW_01",
      "… 2 more"
    ],
    "target": "HOSTEL_CORE_SW_01"
  }
}
```

## Flows

**Start a run and get its incident_id.** `POST /scenarios/{name}/run?external=true` → `{incident_id, status}` (names from `GET /scenarios`). The call returns when the diagnosis is complete. Then `GET /incidents/{incident_id}/stream?delay_ms=240` for the animated replay and `GET /incidents/{id}/report` for the final report. Upload your own bundle with `POST /incidents` (body = bundle bytes; response = report, whose `incident_id` you use the same way). incident_ids are generated by the server (`^INC-[0-9A-Z]{4,12}$`).

**List / reopen past runs.** `GET /incidents?limit=50` (newest first; `limit` 1–500) → rows `{incident_id, status, suspected_root_cause, confidence, created_at}`. Reopen one with its `/report`, `/events` or `/stream`.

**Approve / reject an action.** Action ids are in the report: `action_details[].id` (allowed and blocked, each with `allowed` and `rule_id`) and `blocked_actions[].action_id`. `POST /incidents/{id}/feedback` `{action_id, decision: approve|reject, note?}` (note ≤ 500 chars, stored in SQLite, never put in the log). Response `{id, executed: false, event_seq, message_id, policy, plan_seq, plan}`:

* reject → a `human_decision` event; `policy`/`plan` are null;
* approve of an action the policy blocks → `human_decision`; `policy: {allowed: false, rule_id, reason, checked_at}`; `plan: null` (fixture `blocked_action_r1`);
* approve of an allowed action → `human_decision` + `remediation_plan` labelled "SIMULATED – NOT EXECUTED" with `steps` and `rollback` (fixture `approved_action_plan`).

Nothing is executed, and the report never changes. An `action_id` that is not in the report → `404 UNKNOWN_ACTION`.

`human_decision` payload fields: `action_id`, `decision`, `feedback_id`, `executed`, `note_stored`.

**External agents / A2A join.** `GET /agents` → `external: {agent_id: status}` (`joined` or `unreachable`; the allowlist is `config/agents.yaml`) and `details` (card name/version and capabilities when joined, or the error). Discovery runs on each call and at the start of each run, so an agent that starts later joins the **next** run with no restart. In a run, a joined agent is a `sender` that is not one of NetCoop's internal agents (here `wireless_agent`); its messages carry the limitation `DIALECT_TRANSLATED` and its findings carry `version`/`alias`/`unit`/`entity` transforms (fixture `weak_wifi_after`).

**Agent list.** Internal agents (`config/agents.yaml`): `connectivity_agent`, `correlation_agent`, `infrastructure_agent`, `normalizer`, `orchestrator`, `performance_agent`, `reporting_agent`, `triage_agent`. Post-run senders: `human_operator` (human_decision), `remediation_planner` (remediation_plan). `triage_agent` only runs when `NETCOOP_LLM` is not `off` and the bundle has a complaint.

## Security headers (CSP, CORS)

UI responses (`/`, `/dashboard`, `/dashboard/*`, `/ui/*`) carry, verbatim:
```
Content-Security-Policy: default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
X-Frame-Options: DENY
```
CORS (Starlette `CORSMiddleware`), verbatim from the code:
```
{"allow_origins": ["http://localhost:5173", "http://127.0.0.1:5173"], "allow_methods": ["GET", "POST"], "allow_headers": ["Content-Type"]}
```
So a UI served by `netcoop serve` itself (same origin) needs no CORS; a dev server on port 5173 is allowed. The CSP means no inline `<script>`, no `style=""` attributes, no CDN or remote fonts, and every request goes to the same origin.

## Static UI files

* Built-in dashboard: `netcoop/api/static/` → `/` and `/dashboard` (dashboard.html), `/dashboard/<name>` for `dashboard.js`, `dashboard.css` (fixed allowlist).
* `netcoop serve --ui <folder>`: `<folder>/index.html` at `/`, any file under the folder at `/ui/<path>` (extensions .css .html .ico .jpg .js .json .mjs .png .svg .txt .woff2; resolved path must stay inside the folder). `/dashboard` still serves the built-in UI. New UIs go in `dashboard_v2/` (a starter is there). Without `--ui`, behaviour is unchanged and `/ui/*` is 404.

## Fixtures

`docs/frontend_fixtures/<name>/`: `events.jsonl` (exactly what `/events` and `/stream` serve), `report.json`, `api.json` (every HTTP exchange of the flow). `index.json` lists them; `api_examples.json` has the other endpoints and real errors. Re-record: `python tools/record_fixtures.py --llm`.

| Fixture | incident_id | status | messages | What it shows |
|---|---|---|---|---|
| `congestion` | INC-LWP6J7WP | diagnosed | 27 | Link congestion on L_HOSTEL_UPLINK: 3 predictions (2 hit, 1 miss), one action blocked by R1 in the report |
| `weak_wifi_before` | INC-3MX2CGBG | insufficient_evidence | 30 | Wi-Fi complaint, external wireless_agent NOT running: insufficient_evidence with missing_signals rssi_dbm/snr_db/retransmission_pct@AP_H3 |
| `normal` | INC-Q3BLERDV | no_fault_detected | 18 | Healthy network: no_fault_detected |
| `dns_failure` | INC-FQD7PRLB | diagnosed | 24 | dns_failure scenario (extra, so the mock can serve every scenario) |
| `dhcp_failure` | INC-UPUDVYA2 | diagnosed | 24 | dhcp_failure scenario (extra, so the mock can serve every scenario) |
| `interface_fault` | INC-QPKVQ6JL | diagnosed | 27 | interface_fault scenario (extra, so the mock can serve every scenario) |
| `weak_wifi_after` | INC-3MX2CGBG1 | diagnosed | 30 | Same incident after the Node wireless_agent (dialect 0.9) joined via A2A: diagnosed weak_wifi on AP_H3; its findings carry version/alias/unit/entity transforms |
| `interop_llm_hint` | INC-AAQTTVKO | diagnosed | 28 | Messy multi-dialect input with an injected complaint; NETCOOP_LLM=local llama3.2:3b: triage_agent sends an advisory `hint` (dns_failure); the diagnosis is unchanged (device_overload, deterministic_scoring) |
| `blocked_action_r1` | INC-LWP6J7WP1 | diagnosed | 28 | Approve CONG-4 (reboot HOSTEL_CORE_SW_01): human_decision is logged, the policy check blocks it by R1 (Class hours), no remediation_plan |
| `approved_action_plan` | INC-LWP6J7WP2 | diagnosed | 30 | Approve CONG-1: human_decision + remediation_plan 'SIMULATED – NOT EXECUTED' (steps + rollback); then reject CONG-2: human_decision only. The report is unchanged |
| `resumed_run` | INC-RESUMED1 | diagnosed | 27 | Process killed (exit 137) at the first correlation task after round 0 with 13 messages logged; `netcoop resume` kept them and appended 14. report.json is byte-identical to an uninterrupted run |
| `malformed_input_error` | INC-LNPPZSZE | failed | 1 | Upload of invalid JSON: an `error` message (code MALFORMED) from the normalizer; HTTP 200 with a report whose status is `failed` |

## Mock API (no backend)

```
python tools/mock_api.py                     # http://127.0.0.1:8000/, built-in dashboard
python tools/mock_api.py --ui dashboard_v2   # your UI
python tools/mock_api.py --port 8080 --agent joined
```
Standard library only. Same endpoints, bodies, errors, headers and SSE framing. `POST /scenarios/{name}/run` returns a new `INC-MOCKnnnn` copy of the recorded run. `weak_wifi` returns the *before* fixture until `POST /mock/agent/join` (or `--agent joined`), then *after*; `interop` includes the LLM hint. The stream honours `delay_ms`; `&timing=recorded` replays the recorded gaps between messages. Feedback appends `human_decision` and, for allowed approvals, `remediation_plan`, like the server. Mock-only: `POST /mock/agent/join|leave`, `GET /mock/fixtures`. `POST /incidents` replays the malformed-input fixture for invalid JSON and answers `501 MOCK_UNSUPPORTED` for anything else.

## Glossary

* **incident**: one diagnosis run over one input bundle, identified by `incident_id`; its event log is the source of truth.
* **finding**: one agent's measured observation: `finding_id`, `metric` (`config/metrics.yaml`), `entity {type, id}`, `value` + canonical `unit`, `window`, `aggregation`, `severity` (`normal`, `warn`, `high`, `critical`), `data_quality`, `transforms`, `source_refs`.
* **hypothesis**: a candidate `fault_type` attached to an entity, scored `score = clamp(support − contra_penalty × contra, 0, 1) × quality` from expected / contradicting signals in `config/signatures.yaml`; carries `supporting_finding_ids`, `contradicting_finding_ids`, `missing_signals`.
* **prediction**: logged before its evidence is requested; outcome `pending`, `hit`, `miss`, `unknown`. **hit** = the evidence matched the expectation (counts as support), **miss** = it did not (counts against), **unknown** = nobody could provide the signal.
* **normalization transform**: one recorded change to raw input: `{step, field, from, to, reason}`, step ∈ `version`, `alias`, `unit`, `entity`, … (e.g. `retx` `0.208 fraction` → `retransmission_pct` `20.8 pct`). Unrecoverable data is quarantined, never silently dropped.
* **conflict** (`C1`, `C2`, `C3`): **C1** value: the same metric and entity differ by more than 20%, so the fresher value wins (then sample count, then source priority). **C2** state: a device is reported `down` but has newer telemetry, or a metric names a link missing from the topology; the source is marked stale. **C3** hypothesis: the top two scores are within the margin; prediction rounds try to separate them.
* **status** (`diagnosed`, `probable`, `insufficient_evidence`, `no_fault_detected`, `failed`): `diagnosed` = a signature matched with enough coverage and margin; `probable` = the top two are closer than 0.15 (both reported); `insufficient_evidence` = coverage below 0.5 (`status_reason: data_missing`) or an anomaly that matches no signature (`no_signature_match`); `no_fault_detected` = nothing ≥ high and top score below 0.55; `failed` = the input or an agent failed. Wording is always "Likely …".
* **confidence_category** (`high`, `medium`, `low`): `high` if confidence ≥ 0.75 and margin ≥ 0.25; `medium` if ≥ 0.5; otherwise `low`. It is capped at `medium` when an agent failed or a C2 conflict is unresolved. `confidence` = top score, 2 decimals.
* **decision_source**: always `deterministic_scoring`. An LLM `hint` can only add a hypothesis to test, never set the cause, confidence, status or actions.

