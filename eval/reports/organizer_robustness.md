#### Organizer data: severity sweep (answer-key check)

The organizer generator is **wrapped, not edited**: each fault's injected deviation is scaled to 25/50/75/100% of what the generator injects (`value = normal_midpoint + level × (generated − normal_midpoint)`). Seed range B, 200 seeds per cell. *Detected* = not `no_fault_detected`; *committed* = diagnosed/probable; *correct* = committed to the matching fault type.

| label | injected severity | detected | committed | correct | outputs |
|---|---|---|---|---|---|
| `latency_spike` | 25% | 0.0 | 0.0 | 0.0 | no_fault_detected 200 |
| `latency_spike` | 50% | 0.695 | 0.21 | 0.21 | insufficient_evidence 97, no_fault_detected 61, latency_spike 42 |
| `latency_spike` | 75% | 0.97 | 0.645 | 0.645 | latency_spike 129, insufficient_evidence 65, no_fault_detected 6 |
| `latency_spike` | 100% | 1.0 | 1.0 | 1.0 | latency_spike 200 |
| `hardware_failure` | 25% | 1.0 | 1.0 | 0.0 | interface_fault 150, congestion 50 |
| `hardware_failure` | 50% | 1.0 | 1.0 | 0.7 | hardware_failure 140, interface_fault 60 |
| `hardware_failure` | 75% | 1.0 | 1.0 | 1.0 | hardware_failure 200 |
| `hardware_failure` | 100% | 1.0 | 1.0 | 1.0 | hardware_failure 200 |

#### Organizer data: corruption curve

One raw organizer record per incident (all three labels, 200 seeds each = 600 per rate) through the corruption fuzzer (`eval/mutate.py`).

| corruption rate | accuracy | wrong-diagnosis | failed | crashes |
|---|---|---|---|---|
| 0% | 1.0 | 0.0 | 0 | 0 |
| 10% | 0.998 | 0.0 | 0 | 0 |
| 20% | 0.998 | 0.0 | 0 | 0 |
| 30% | 0.998 | 0.0 | 0 | 0 |
| 40% | 0.988 | 0.0 | 0 | 0 |
| 50% | 0.975 | 0.0 | 0 | 0 |
| 60% | 0.982 | 0.0 | 0 | 0 |

#### Confidence vs observed accuracy, per source

**Organizer generator (committed diagnoses, all severity levels)**: OVERCONFIDENT in at least one bin

| stated confidence bin | n | mean stated | observed accuracy |
|---|---|---|---|
| [0.50, 0.75] | 600 | 0.6 | 0.567 |
| [0.90, 1.00] | 571 | 1.0 | 1.0 |

**NetCoop extended generator (seed range B)**: never overconfident

| stated confidence bin | n | mean stated | observed accuracy |
|---|---|---|---|
| [0.50, 0.75] | 56 | 0.646 | 0.964 |
| [0.75, 0.90] | 73 | 0.829 | 0.973 |
| [0.90, 1.00] | 90 | 0.99 | 1.0 |

