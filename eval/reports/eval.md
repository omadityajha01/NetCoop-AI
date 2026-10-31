## Seed range A (tuning)

seed 1000, 280 generated incidents (24% with 5–30 % corrupted records), wireless_agent: node.

| Metric | Value |
|---|---|
| n | 280 |
| overall accuracy | 0.804 |
| macro accuracy | 0.804 |
| precision when diagnosed | 0.967 |
| wrong diagnosis rate | 0.025 |
| fault to no fault rate | 0.008 |
| normal accuracy | 0.55 |
| false positive rate normal | 0.05 |
| insufficient evidence rate | 0.164 |
| localization accuracy | 1.0 |
| accuracy on mutated inputs | 0.838 |
| mutated share | 0.243 |
| crashes | 0 |
| mean ms per incident | 59.4 |

**Per fault**

| fault | n | accuracy | insufficient_evidence | probable |
|---|---|---|---|---|
| normal | 40 | 0.55 | 0.4 | 0.0 |
| congestion | 40 | 0.825 | 0.15 | 0.025 |
| interface_fault | 40 | 0.9 | 0.1 | 0.025 |
| device_overload | 40 | 0.7 | 0.2 | 0.125 |
| weak_wifi | 40 | 0.85 | 0.1 | 0.025 |
| dns_failure | 40 | 0.9 | 0.1 | 0.0 |
| dhcp_failure | 40 | 0.9 | 0.1 | 0.0 |

**Confusion matrix** (rows = truth, columns = predicted)

| truth \ pred | congestion | device_overload | dhcp_failure | dns_failure | insufficient_evidence | interface_fault | latency_spike | no_fault_detected | weak_wifi |
|---|---|---|---|---|---|---|---|---|---|
| normal | 1 | 1 | 0 | 0 | 16 | 0 | 0 | 22 | 0 |
| congestion | 33 | 0 | 0 | 0 | 6 | 0 | 1 | 0 | 0 |
| interface_fault | 0 | 0 | 0 | 0 | 4 | 36 | 0 | 0 | 0 |
| device_overload | 4 | 28 | 0 | 0 | 8 | 0 | 0 | 0 | 0 |
| weak_wifi | 0 | 0 | 0 | 0 | 4 | 0 | 0 | 2 | 34 |
| dns_failure | 0 | 0 | 0 | 36 | 4 | 0 | 0 | 0 | 0 |
| dhcp_failure | 0 | 0 | 36 | 0 | 4 | 0 | 0 | 0 | 0 |

**Confidence vs observed accuracy** (diagnosed/probable only)

| confidence bin | n | mean confidence | observed accuracy |
|---|---|---|---|
| [0.50, 0.75] | 55 | 0.644 | 0.909 |
| [0.75, 0.90] | 65 | 0.828 | 0.969 |
| [0.90, 1.00] | 90 | 0.987 | 1.0 |

| confidence_category | n | observed accuracy |
|---|---|---|
| high | 153 | 0.993 |
| medium | 57 | 0.895 |

## Seed range B (held-out report)

seed 5000, 280 generated incidents (30% with 5–30 % corrupted records), wireless_agent: node.

| Metric | Value |
|---|---|
| n | 280 |
| overall accuracy | 0.857 |
| macro accuracy | 0.857 |
| precision when diagnosed | 0.982 |
| wrong diagnosis rate | 0.014 |
| fault to no fault rate | 0.008 |
| normal accuracy | 0.625 |
| false positive rate normal | 0.0 |
| insufficient evidence rate | 0.121 |
| localization accuracy | 0.995 |
| accuracy on mutated inputs | 0.857 |
| mutated share | 0.3 |
| crashes | 0 |
| mean ms per incident | 59.5 |

**Per fault**

| fault | n | accuracy | insufficient_evidence | probable |
|---|---|---|---|---|
| normal | 40 | 0.625 | 0.375 | 0.0 |
| congestion | 40 | 0.8 | 0.15 | 0.125 |
| interface_fault | 40 | 0.975 | 0.025 | 0.0 |
| device_overload | 40 | 0.8 | 0.125 | 0.1 |
| weak_wifi | 40 | 0.9 | 0.075 | 0.0 |
| dns_failure | 40 | 0.95 | 0.05 | 0.0 |
| dhcp_failure | 40 | 0.95 | 0.05 | 0.0 |

**Confusion matrix** (rows = truth, columns = predicted)

| truth \ pred | congestion | device_overload | dhcp_failure | dns_failure | insufficient_evidence | interface_fault | latency_spike | no_fault_detected | weak_wifi |
|---|---|---|---|---|---|---|---|---|---|
| normal | 0 | 0 | 0 | 0 | 15 | 0 | 0 | 25 | 0 |
| congestion | 32 | 0 | 0 | 0 | 6 | 0 | 1 | 1 | 0 |
| interface_fault | 0 | 0 | 0 | 0 | 1 | 39 | 0 | 0 | 0 |
| device_overload | 3 | 32 | 0 | 0 | 5 | 0 | 0 | 0 | 0 |
| weak_wifi | 0 | 0 | 0 | 0 | 3 | 0 | 0 | 1 | 36 |
| dns_failure | 0 | 0 | 0 | 38 | 2 | 0 | 0 | 0 | 0 |
| dhcp_failure | 0 | 0 | 38 | 0 | 2 | 0 | 0 | 0 | 0 |

**Confidence vs observed accuracy** (diagnosed/probable only)

| confidence bin | n | mean confidence | observed accuracy |
|---|---|---|---|
| [0.50, 0.75] | 56 | 0.646 | 0.964 |
| [0.75, 0.90] | 73 | 0.829 | 0.973 |
| [0.90, 1.00] | 90 | 0.99 | 1.0 |

| confidence_category | n | observed accuracy |
|---|---|---|
| high | 163 | 0.988 |
| medium | 56 | 0.964 |
