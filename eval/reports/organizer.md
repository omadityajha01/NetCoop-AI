#### Organizer generator (raw, unmodified)

`data/generator/organizer_generator.py`, 500 seeds per label, one record per call, full pipeline, no preprocessing. Seed range A (from seed 0) was used for tuning; the numbers below are **seed range B** (from seed 100000). Label → expected outcome: `normal` → `no_fault_detected`, `latency_spike` → `latency_spike`, `hardware_failure` → `hardware_failure` (derivation in `data/generator/SCHEMA.md`).

| organizer label | n | correct | committed | records quarantined |
|---|---|---|---|---|
| `normal` | 500 | 1.0 | 0.0 | 0 |
| `latency_spike` | 500 | 1.0 | 1.0 | 0 |
| `hardware_failure` | 500 | 1.0 | 1.0 | 0 |

Wrong-diagnosis rate 0.0, real fault reported healthy 0.0, false positives on normal 0.0.

**Confusion (seed range B; rows = organizer label, columns = NetCoop output)**

| label \ output | hardware_failure | latency_spike | no_fault_detected |
|---|---|---|---|
| `normal` | 0 | 0 | 500 |
| `latency_spike` | 0 | 500 | 0 |
| `hardware_failure` | 500 | 0 | 0 |
