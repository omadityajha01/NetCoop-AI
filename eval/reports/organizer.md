#### Organizer generator (raw, unmodified)

`data/generator/organizer_generator.py`, 500 seeds per fault type, one record per call, full pipeline, no preprocessing. The organizer faults have no mapping to NetCoop signatures, so `latency_spike` / `hardware_failure` are scored on detection (not `no_fault_detected`).

| organizer fault | n | score | committed (diagnosed/probable) | status distribution | label distribution | records quarantined |
|---|---|---|---|---|---|---|
| `normal` | 500 | accuracy 1.0 | 0.0 | no_fault_detected 500 | no_fault_detected 500 | 0 |
| `latency_spike` | 500 | detection 1.0 | 0.0 | insufficient_evidence 500 | insufficient_evidence (no_signature_match) 500 | 0 |
| `hardware_failure` | 500 | detection 1.0 | 0.0 | insufficient_evidence 500 | insufficient_evidence (no_signature_match) 500 | 0 |
