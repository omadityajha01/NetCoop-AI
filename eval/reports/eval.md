## Seed range A (tuning)

seed 1000, 280 generated incidents (24% with 5–30 % corrupted records), wireless_agent: node.

| Metric | Value |
|---|---|
| n | 280 |
| overall accuracy | 0.811 |
| macro accuracy | 0.811 |
| precision when diagnosed | 0.932 |
| wrong diagnosis rate | 0.054 |
| fault to no fault rate | 0.013 |
| normal accuracy | 0.575 |
| false positive rate normal | 0.1 |
| insufficient evidence rate | 0.125 |
| localization accuracy | 1.0 |
| accuracy on mutated inputs | 0.838 |
| mutated share | 0.243 |
| crashes | 0 |
| mean ms per incident | 45.6 |

**Per fault**

| fault | n | accuracy | insufficient_evidence | probable |
|---|---|---|---|---|
| normal | 40 | 0.575 | 0.325 | 0.0 |
| congestion | 40 | 0.875 | 0.125 | 0.05 |
| interface_fault | 40 | 0.975 | 0.025 | 0.05 |
| device_overload | 40 | 0.6 | 0.125 | 0.225 |
| weak_wifi | 40 | 0.65 | 0.275 | 0.05 |
| dns_failure | 40 | 1.0 | 0.0 | 0.0 |
| dhcp_failure | 40 | 1.0 | 0.0 | 0.025 |

**Confusion matrix** (rows = truth, columns = predicted)

| truth \ pred | congestion | device_overload | dhcp_failure | dns_failure | insufficient_evidence | interface_fault | no_fault_detected | weak_wifi |
|---|---|---|---|---|---|---|---|---|
| normal | 3 | 1 | 0 | 0 | 13 | 0 | 23 | 0 |
| congestion | 35 | 0 | 0 | 0 | 5 | 0 | 0 | 0 |
| interface_fault | 0 | 0 | 0 | 0 | 1 | 39 | 0 | 0 |
| device_overload | 11 | 24 | 0 | 0 | 5 | 0 | 0 | 0 |
| weak_wifi | 0 | 0 | 0 | 0 | 11 | 0 | 3 | 26 |
| dns_failure | 0 | 0 | 0 | 40 | 0 | 0 | 0 | 0 |
| dhcp_failure | 0 | 0 | 40 | 0 | 0 | 0 | 0 | 0 |

**Calibration** (diagnosed/probable only)

| confidence bin | n | mean confidence | observed accuracy |
|---|---|---|---|
| [0.00, 0.50] | 13 | 0.471 | 0.538 |
| [0.50, 0.75] | 64 | 0.617 | 0.891 |
| [0.75, 0.90] | 61 | 0.823 | 0.967 |
| [0.90, 1.00] | 81 | 0.99 | 1.0 |

| confidence_category | n | observed accuracy |
|---|---|---|
| high | 142 | 0.986 |
| medium | 64 | 0.891 |
| low | 13 | 0.538 |

## Seed range B (held-out report)

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
