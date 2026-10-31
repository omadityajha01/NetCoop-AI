## Seed range A (tuning)

seed 1000, 280 generated incidents (24% with 5–30 % corrupted records), wireless_agent: node.

| Metric | Value |
|---|---|
| n | 280 |
| overall accuracy | 0.743 |
| macro accuracy | 0.743 |
| precision when diagnosed | 0.964 |
| wrong diagnosis rate | 0.025 |
| fault to no fault rate | 0.013 |
| normal accuracy | 0.575 |
| false positive rate normal | 0.025 |
| insufficient evidence rate | 0.221 |
| localization accuracy | 1.0 |
| accuracy on mutated inputs | 0.779 |
| mutated share | 0.243 |
| crashes | 0 |
| mean ms per incident | 47.9 |

**Per fault**

| fault | n | accuracy | insufficient_evidence | probable |
|---|---|---|---|---|
| normal | 40 | 0.575 | 0.4 | 0.0 |
| congestion | 40 | 0.825 | 0.175 | 0.0 |
| interface_fault | 40 | 0.9 | 0.1 | 0.025 |
| device_overload | 40 | 0.5 | 0.35 | 0.1 |
| weak_wifi | 40 | 0.6 | 0.325 | 0.0 |
| dns_failure | 40 | 0.9 | 0.1 | 0.0 |
| dhcp_failure | 40 | 0.9 | 0.1 | 0.0 |

**Confusion matrix** (rows = truth, columns = predicted)

| truth \ pred | congestion | device_overload | dhcp_failure | dns_failure | insufficient_evidence | interface_fault | no_fault_detected | weak_wifi |
|---|---|---|---|---|---|---|---|---|
| normal | 1 | 0 | 0 | 0 | 16 | 0 | 23 | 0 |
| congestion | 33 | 0 | 0 | 0 | 7 | 0 | 0 | 0 |
| interface_fault | 0 | 0 | 0 | 0 | 4 | 36 | 0 | 0 |
| device_overload | 6 | 20 | 0 | 0 | 14 | 0 | 0 | 0 |
| weak_wifi | 0 | 0 | 0 | 0 | 13 | 0 | 3 | 24 |
| dns_failure | 0 | 0 | 0 | 36 | 4 | 0 | 0 | 0 |
| dhcp_failure | 0 | 0 | 36 | 0 | 4 | 0 | 0 | 0 |

**Confidence vs observed accuracy** (diagnosed/probable only)

| confidence bin | n | mean confidence | observed accuracy |
|---|---|---|---|
| [0.50, 0.75] | 50 | 0.649 | 0.9 |
| [0.75, 0.90] | 61 | 0.823 | 0.967 |
| [0.90, 1.00] | 81 | 0.99 | 1.0 |

| confidence_category | n | observed accuracy |
|---|---|---|
| high | 142 | 0.986 |
| medium | 50 | 0.9 |

## Seed range B (held-out report)

seed 5000, 280 generated incidents (30% with 5–30 % corrupted records), wireless_agent: node.

| Metric | Value |
|---|---|
| n | 280 |
| overall accuracy | 0.796 |
| macro accuracy | 0.796 |
| precision when diagnosed | 0.985 |
| wrong diagnosis rate | 0.011 |
| fault to no fault rate | 0.013 |
| normal accuracy | 0.625 |
| false positive rate normal | 0.0 |
| insufficient evidence rate | 0.182 |
| localization accuracy | 0.995 |
| accuracy on mutated inputs | 0.774 |
| mutated share | 0.3 |
| crashes | 0 |
| mean ms per incident | 45.9 |

**Per fault**

| fault | n | accuracy | insufficient_evidence | probable |
|---|---|---|---|---|
| normal | 40 | 0.625 | 0.375 | 0.0 |
| congestion | 40 | 0.8 | 0.175 | 0.05 |
| interface_fault | 40 | 0.975 | 0.025 | 0.0 |
| device_overload | 40 | 0.675 | 0.25 | 0.125 |
| weak_wifi | 40 | 0.6 | 0.35 | 0.0 |
| dns_failure | 40 | 0.95 | 0.05 | 0.0 |
| dhcp_failure | 40 | 0.95 | 0.05 | 0.0 |

**Confusion matrix** (rows = truth, columns = predicted)

| truth \ pred | congestion | device_overload | dhcp_failure | dns_failure | insufficient_evidence | interface_fault | no_fault_detected | weak_wifi |
|---|---|---|---|---|---|---|---|---|
| normal | 0 | 0 | 0 | 0 | 15 | 0 | 25 | 0 |
| congestion | 32 | 0 | 0 | 0 | 7 | 0 | 1 | 0 |
| interface_fault | 0 | 0 | 0 | 0 | 1 | 39 | 0 | 0 |
| device_overload | 3 | 27 | 0 | 0 | 10 | 0 | 0 | 0 |
| weak_wifi | 0 | 0 | 0 | 0 | 14 | 0 | 2 | 24 |
| dns_failure | 0 | 0 | 0 | 38 | 2 | 0 | 0 | 0 |
| dhcp_failure | 0 | 0 | 38 | 0 | 2 | 0 | 0 | 0 |

**Confidence vs observed accuracy** (diagnosed/probable only)

| confidence bin | n | mean confidence | observed accuracy |
|---|---|---|---|
| [0.50, 0.75] | 54 | 0.644 | 0.963 |
| [0.75, 0.90] | 66 | 0.83 | 0.985 |
| [0.90, 1.00] | 81 | 0.992 | 1.0 |

| confidence_category | n | observed accuracy |
|---|---|---|
| high | 147 | 0.993 |
| medium | 54 | 0.963 |
