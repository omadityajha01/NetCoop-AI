# Organizer generator: field contract

Source: `organizer_generator.py`, exported verbatim from the organizer's Colab notebook
*Mock-data-builder-netScoopAI.ipynb* on 2026-10-31. It is one function,
`generate_telemetry(fault_type)`, that returns **one record per call**.

## Record shape

```json
{
  "timestamp": "2026-10-31T10:57:13.544050Z",
  "device_id": "SW_CAMPUS_8",
  "metrics": {
    "cpu_utilization_pct": 99.9,
    "link_utilization_pct": 100.0,
    "packet_loss_pct": 24.74,
    "latency_ms": 749.09,
    "queue_drops": 12911,
    "interface_errors": 354
  },
  "status": "Critical"
}
```

| Field | Type | Values / unit | Canonical NetCoop mapping |
|---|---|---|---|
| `timestamp` | str | ISO-8601, naive `utcnow()` + `"Z"` (UTC) | record time |
| `device_id` | str | `SW_CAMPUS_1` … `SW_CAMPUS_10` | entity `{type: device}`; IDs added to `config/topology.yaml` |
| `status` | str | `Healthy`, `Warning`, `Critical` | **not** a measurement: it is the generator's own label. Kept in `extras` with a limitation; never used as evidence (G7) |
| `metrics.cpu_utilization_pct` | float | % (0–100) | `cpu_pct` (alias) |
| `metrics.link_utilization_pct` | float | % (0–100) | `link_utilization_pct` (canonical) |
| `metrics.packet_loss_pct` | float | % | `packet_loss_pct` (canonical) |
| `metrics.latency_ms` | float | ms | `latency_ms` (canonical) |
| `metrics.jitter_ms` | float | ms | `jitter_ms` (canonical); absent in `hardware_failure` |
| `metrics.queue_drops` | int | count | `queue_drops_count` (alias) |
| `metrics.interface_errors` | int | count | `interface_errors_count` (alias); only in `hardware_failure` |

## Fault types and value ranges

| `fault_type` | cpu | util | loss | latency | jitter | queue_drops | interface_errors | status |
|---|---|---|---|---|---|---|---|---|
| `normal` (default) | 10–35 | 20–50 | 0.0 | 5–20 | 1–5 | 0 | – | Healthy |
| `latency_spike` | 40–70 | 60–85 | 0.1–1.5 | 150–400 | 30–80 | 0–50 | – | Warning |
| `hardware_failure` | 99.9 | 100.0 | 15–30 | 500–1000 | – | 5000–15000 | 100–500 | Critical |

## Label → field effects (exact, from the code)

Compared with NetCoop thresholds (`config/metrics.yaml`, default context):

| Field | `normal` | `latency_spike` | `hardware_failure` |
|---|---|---|---|
| `cpu_utilization_pct` → `cpu_pct` | uniform(10, 35): normal | uniform(40, 70): normal (warn ≥ 70) | **99.9**: critical (≥ 95) |
| `link_utilization_pct` | uniform(20, 50): normal | uniform(60, 85): normal/warn (high ≥ 85 only at the edge) | **100.0**: critical (≥ 95) |
| `packet_loss_pct` | 0.0: normal | uniform(0.1, 1.5): normal/warn | uniform(15, 30): **critical** (≥ 10) |
| `latency_ms` | uniform(5, 20): normal | uniform(150, 400): **high** (≥ 150) | uniform(500, 1000): **critical** (≥ 500) |
| `jitter_ms` | uniform(1, 5): normal | uniform(30, 80): **high** (≥ 30) | *not emitted* |
| `queue_drops` → `queue_drops_count` | 0: normal | randint(0, 50): normal (never > warn 50) | randint(5000, 15000): **critical** (≥ 1000) |
| `interface_errors` → `interface_errors_count` | *not emitted* | *not emitted* | randint(100, 500): **high/critical** (≥ 50) |
| `status` (label, kept in extras) | Healthy | Warning | Critical |
| `device_id` | SW_CAMPUS_1..10 | SW_CAMPUS_1..10 | SW_CAMPUS_1..10 |

## Label → NetCoop outcome (1:1)

| Organizer label | NetCoop outcome | Signature (`config/signatures.yaml`) | Derivation |
|---|---|---|---|
| `normal` | `no_fault_detected` | none | every field is below `warn` |
| `latency_spike` | `latency_spike` | expects `latency_ms ≥ high` (×3), `jitter_ms ≥ high` (×3); contradicts `queue_drops_count > warn` (×2), `link_utilization_pct ≥ high` (×2) | The only fields the label pushes to `high` are latency and jitter, and their generator lower bounds (150 ms, 30 ms) equal our `high` thresholds. Drops stay ≤ 50 and utilization < 85, which is exactly what separates it from congestion. |
| `hardware_failure` | `hardware_failure` | expects `interface_errors_count ≥ high` (×3), `cpu_pct`, `link_utilization_pct`, `packet_loss_pct`, `queue_drops_count ≥ critical` (×2 each), `latency_ms ≥ critical` (×1) | The label saturates *every* resource at once and adds interface errors. No single-cause signature (congestion / overload / interface fault) fits, because each is contradicted by another's symptom. The new signature expects all of them together. |

Playbook entries: `latency_spike` (path/QoS inspection) and `hardware_failure` (hardware logs, failover, RMA; reboot
only after diagnostics) in `config/playbook.yaml`.

**Single-record inputs.** Each generator call is one sample, and data completeness is measured against the cadence the
input delivers (CLAUDE.md §6.3), so a snapshot is complete and is not penalized for having one sample.

Measured (raw generator, seed range B, 500 seeds per label): `eval/reports/organizer.md`.

## What the generator does NOT provide

The things below are missing, so NetCoop's extended generator (`eval/generate.py`) adds them.
It uses the **same record shape and field names** and extends only through `metrics.yaml` aliases.

- topology: no links or upstream relations. The topology in `config/topology.yaml` is **NetCoop-defined**, and `SW_CAMPUS_1..10` were added to it.
- Wi-Fi metrics (RSSI/SNR/retransmissions): served by the external `wireless_agent` in dialect v0.9
- DNS/DHCP service metrics
- multiple samples per window (one call = one record)
- link-level entities (`link_id`), CRC errors, link flaps, memory

## Notes

- `datetime.utcnow()` is deprecated in Python 3.12+ but still produces UTC.
- No seed is set in the notebook, so its output is non-deterministic. Our generator seeds every RNG (G9).
