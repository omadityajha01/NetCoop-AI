## Degradation under corrupted input

70 incidents (seed 9000); each record corrupted with probability = rate using: renamed fields, swapped units, bare fractions, legacy v0.9 blocks, missing values, mangled IDs, dropped fields, missing schema_version. Ablation column: same pipeline with the metric registry's aliases and unit aliases removed.

| corruption rate | accuracy | precision when diagnosed | insufficient_evidence | FP on normal | values recovered | records quarantined | failed | crashes | accuracy w/o registry | |
|---|---|---|---|---|---|---|---|---|---|---|
| 0% | 0.786 | 0.946 | 0.171 | 0.0 | 0 | 0.0 % | 0 | 0 | 0.457 | `████████████████` |
| 10% | 0.786 | 0.964 | 0.186 | 0.0 | 808 | 0.4 % | 0 | 0 | 0.457 | `████████████████` |
| 20% | 0.8 | 0.947 | 0.157 | 0.0 | 1798 | 0.6 % | 0 | 0 | 0.443 | `████████████████` |
| 30% | 0.786 | 0.964 | 0.186 | 0.0 | 2739 | 1.0 % | 0 | 0 | 0.429 | `████████████████` |
| 40% | 0.786 | 0.964 | 0.186 | 0.0 | 3703 | 1.2 % | 0 | 0 | 0.457 | `████████████████` |
| 50% | 0.786 | 0.946 | 0.171 | 0.0 | 5241 | 1.9 % | 0 | 0 | 0.429 | `████████████████` |
| 60% | 0.771 | 0.963 | 0.2 | 0.0 | 6358 | 2.1 % | 0 | 0 | 0.414 | `███████████████` |
