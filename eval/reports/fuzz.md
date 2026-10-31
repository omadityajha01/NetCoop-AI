## Degradation under corrupted input

70 incidents (seed 9000); each record corrupted with probability = rate using: renamed fields, swapped units, bare fractions, legacy v0.9 blocks, missing values, mangled IDs, dropped fields, missing schema_version. Ablation column: same pipeline with the metric registry's aliases and unit aliases removed.

| corruption rate | accuracy | precision when diagnosed | insufficient_evidence | FP on normal | values recovered | records quarantined | failed | crashes | accuracy w/o registry | |
|---|---|---|---|---|---|---|---|---|---|---|
| 0% | 0.814 | 0.964 | 0.143 | 0.0 | 0 | 0.0 % | 0 | 0 | 0.471 | `████████████████` |
| 10% | 0.814 | 0.981 | 0.157 | 0.0 | 808 | 0.4 % | 0 | 0 | 0.471 | `████████████████` |
| 20% | 0.814 | 0.964 | 0.143 | 0.0 | 1798 | 0.6 % | 0 | 0 | 0.443 | `████████████████` |
| 30% | 0.814 | 0.981 | 0.157 | 0.0 | 2739 | 1.0 % | 0 | 0 | 0.414 | `████████████████` |
| 40% | 0.757 | 1.0 | 0.229 | 0.0 | 3703 | 1.2 % | 0 | 0 | 0.386 | `███████████████` |
| 50% | 0.771 | 1.0 | 0.214 | 0.0 | 5241 | 1.9 % | 0 | 0 | 0.257 | `███████████████` |
| 60% | 0.757 | 1.0 | 0.229 | 0.0 | 6358 | 2.1 % | 0 | 0 | 0.286 | `███████████████` |
