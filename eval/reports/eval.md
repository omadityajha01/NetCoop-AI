## Seed range A (tuning)

seed 1000, 280 generated incidents (24% with 5–30 % corrupted records), wireless_agent: node.

| Metric | Value |
|---|---|
| n | 280 |
| overall accuracy | 0.746 |
| macro accuracy | 0.746 |
| precision when diagnosed | 0.959 |
| wrong diagnosis rate | 0.029 |
| fault to no fault rate | 0.013 |
| normal accuracy | 0.575 |
| false positive rate normal | 0.025 |
| insufficient evidence rate | 0.214 |
| localization accuracy | 1.0 |
| accuracy on mutated inputs | 0.779 |
| mutated share | 0.243 |
| crashes | 0 |
| mean ms per incident | 54.4 |

**Per fault**

| fault | n | accuracy | insufficient_evidence | probable |
|---|---|---|---|---|
| normal | 40 | 0.575 | 0.4 | 0.0 |
| congestion | 40 | 0.825 | 0.15 | 0.025 |
| interface_fault | 40 | 0.9 | 0.1 | 0.025 |
| device_overload | 40 | 0.5 | 0.35 | 0.1 |
| weak_wifi | 40 | 0.625 | 0.3 | 0.025 |
| dns_failure | 40 | 0.9 | 0.1 | 0.0 |
| dhcp_failure | 40 | 0.9 | 0.1 | 0.0 |

**Confusion matrix** (rows = truth, columns = predicted)

| truth \ pred | congestion | device_overload | dhcp_failure | dns_failure | insufficient_evidence | interface_fault | latency_spike | no_fault_detected | weak_wifi |
|---|---|---|---|---|---|---|---|---|---|
| normal | 1 | 0 | 0 | 0 | 16 | 0 | 0 | 23 | 0 |
| congestion | 33 | 0 | 0 | 0 | 6 | 0 | 1 | 0 | 0 |
| interface_fault | 0 | 0 | 0 | 0 | 4 | 36 | 0 | 0 | 0 |
| device_overload | 6 | 20 | 0 | 0 | 14 | 0 | 0 | 0 | 0 |
| weak_wifi | 0 | 0 | 0 | 0 | 12 | 0 | 0 | 3 | 25 |
| dns_failure | 0 | 0 | 0 | 36 | 4 | 0 | 0 | 0 | 0 |
| dhcp_failure | 0 | 0 | 36 | 0 | 4 | 0 | 0 | 0 | 0 |

**Confidence vs observed accuracy** (diagnosed/probable only)

| confidence bin | n | mean confidence | observed accuracy |
|---|---|---|---|
| [0.50, 0.75] | 49 | 0.646 | 0.898 |
| [0.75, 0.90] | 61 | 0.828 | 0.951 |
| [0.90, 1.00] | 84 | 0.987 | 1.0 |

| confidence_category | n | observed accuracy |
|---|---|---|
| high | 145 | 0.979 |
| medium | 49 | 0.898 |

## Seed range B (held-out report)

seed 5000, 280 generated incidents (30% with 5–30 % corrupted records), wireless_agent: node.

| Metric | Value |
|---|---|
| n | 280 |
| overall accuracy | 0.8 |
| macro accuracy | 0.8 |
| precision when diagnosed | 0.98 |
| wrong diagnosis rate | 0.014 |
| fault to no fault rate | 0.013 |
| normal accuracy | 0.625 |
| false positive rate normal | 0.0 |
| insufficient evidence rate | 0.175 |
| localization accuracy | 0.995 |
| accuracy on mutated inputs | 0.786 |
| mutated share | 0.3 |
| crashes | 0 |
| mean ms per incident | 56.8 |

**Per fault**

| fault | n | accuracy | insufficient_evidence | probable |
|---|---|---|---|---|
| normal | 40 | 0.625 | 0.375 | 0.0 |
| congestion | 40 | 0.8 | 0.15 | 0.125 |
| interface_fault | 40 | 0.975 | 0.025 | 0.0 |
| device_overload | 40 | 0.675 | 0.25 | 0.125 |
| weak_wifi | 40 | 0.625 | 0.325 | 0.0 |
| dns_failure | 40 | 0.95 | 0.05 | 0.0 |
| dhcp_failure | 40 | 0.95 | 0.05 | 0.0 |

**Confusion matrix** (rows = truth, columns = predicted)

| truth \ pred | congestion | device_overload | dhcp_failure | dns_failure | insufficient_evidence | interface_fault | latency_spike | no_fault_detected | weak_wifi |
|---|---|---|---|---|---|---|---|---|---|
| normal | 0 | 0 | 0 | 0 | 15 | 0 | 0 | 25 | 0 |
| congestion | 32 | 0 | 0 | 0 | 6 | 0 | 1 | 1 | 0 |
| interface_fault | 0 | 0 | 0 | 0 | 1 | 39 | 0 | 0 | 0 |
| device_overload | 3 | 27 | 0 | 0 | 10 | 0 | 0 | 0 | 0 |
| weak_wifi | 0 | 0 | 0 | 0 | 13 | 0 | 0 | 2 | 25 |
| dns_failure | 0 | 0 | 0 | 38 | 2 | 0 | 0 | 0 | 0 |
| dhcp_failure | 0 | 0 | 38 | 0 | 2 | 0 | 0 | 0 | 0 |

**Confidence vs observed accuracy** (diagnosed/probable only)

| confidence bin | n | mean confidence | observed accuracy |
|---|---|---|---|
| [0.50, 0.75] | 52 | 0.645 | 0.962 |
| [0.75, 0.90] | 67 | 0.829 | 0.97 |
| [0.90, 1.00] | 84 | 0.991 | 1.0 |

| confidence_category | n | observed accuracy |
|---|---|---|
| high | 151 | 0.987 |
| medium | 52 | 0.962 |
