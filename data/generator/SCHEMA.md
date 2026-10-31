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

## What the generator does NOT provide

The things below are missing, so NetCoop's extended generator (`eval/generate.py`) adds them.
It uses the **same record shape and field names** and extends only through `metrics.yaml` aliases.

- topology: no links or upstream relations. The topology is defined in `config/topology.yaml`.
- Wi-Fi metrics (RSSI/SNR/retransmissions): served by the external `wireless_agent` in dialect v0.9
- DNS/DHCP service metrics
- multiple samples per window (one call = one record)
- link-level entities (`link_id`), CRC errors, link flaps, memory

## Notes

- `datetime.utcnow()` is deprecated in Python 3.12+ but still produces UTC.
- No seed is set in the notebook, so its output is non-deterministic. Our generator seeds every RNG (G9).
