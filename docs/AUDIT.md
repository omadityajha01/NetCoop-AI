# Judge's-eye audit (branch `slides`, read-only against `demo-final-2` = 4984d6c)

Method:
* every claim below is backed by a path in the repo at 4984d6c
* numbers were checked by script against `eval/reports/*` (plus `demo_snapshots/*` and the test collector where noted)
* links were checked against `git ls-files` with exact case, and the live GitHub URLs were fetched

Nothing on `main` was changed.

## 1. PS deliverables (§7)

| Deliverable | Status | Evidence |
|---|---|---|
| Source repo with implementation, dependencies, setup instructions, test scripts | ✅ | https://github.com/omadityajha01/NetCoop-AI · `pyproject.toml` (deps + extras) · `README.md` § Quick start · `tasks.py`, `Makefile` · `tests/` (127 tests) · `.github/workflows/ci.yml` (ubuntu + windows, green) |
| README: agent responsibilities | ✅ | `README.md` § Agent responsibilities (line 121) |
| README: communication interfaces | ✅ | `README.md` § Protocol NMP 1.1 (142), Envelope (148), Finding (173), Metric registry (195), Versioning (225), A2A transport (251); `docs/schemas/*.json` (14 files) |
| README: orchestration | ✅ | `README.md` § Orchestration (276), Conflict resolution (290) |
| README: evidence correlation | ✅ | `README.md` § Correlation and scoring (307) |
| README: error handling | ✅ | `README.md` § Failure handling (298), Error handling and robustness (618), Guardrails and security (642) |
| README: workflow | ✅ (no section literally titled "Workflow") | `README.md` § Architecture diagram (top + 87) and the 7-step run sequence in § Orchestration (276) |
| Sample data and test cases (normal + multiple faults) | ✅ | `data/scenarios/{normal,congestion,weak_wifi,interface_fault,dns_failure,dhcp_failure,interop}/incident.json`; `data/generator/organizer_generator.py` (verbatim) + `SCHEMA.md`; `tests/integration/test_scenarios.py` (one test per scenario) |
| **Demo video (3–5 min)** | ❌ **MISSING** | Only the script exists: `docs/VIDEO_SCRIPT.md` (4:30, measured timings) and `python tasks.py present --auto`. No recording is in the repo or linked from the README. |
| Working prototype (CLI or dashboard) | ✅ | `netcoop/cli.py` (`netcoop diagnose/demo/replay/timeline/...`), `python tasks.py present`, read-only API `netcoop/api/main.py` |

## 2. Minimum acceptance criteria (§9)

| Criterion | Status | Evidence |
|---|---|---|
| ≥ 2 collaborating agents with distinct responsibilities | ✅ | `netcoop/agents/{performance,infrastructure,connectivity,correlation,reporting}.py` + `external_agents/wireless_agent/server.js` |
| Structured communication between agents | ✅ | `netcoop/protocol/envelope.py`, `messages.py`, `findings.py`; `docs/schemas/`; every message logged in `runs/<id>/events.jsonl` (`netcoop/bus/eventlog.py`) |
| Evidence from multiple agents → one diagnosis | ✅ | `tests/integration/test_scenarios.py:25` asserts `evidence_sources ⊇ {performance_agent, infrastructure_agent}`; `:43` adds `wireless_agent` |
| ≥ 1 malformed / missing / incompatible input handled | ✅ | `data/scenarios/interop/incident.json`; `tests/unit/test_normalizer.py::test_never_silently_drop_interop`; `tests/integration/test_failures_replay.py::test_malformed_input_fails_safely`; `tests/property/` |
| Report with root cause, supporting evidence, recommended action | ✅ | `netcoop/agents/reporting.py`; `netcoop/policy/validator.py`; examples in `demo_snapshots/*/report.json` |
| Reproducible run on supplied / documented data | ✅ | `README.md` § Quick start; `netcoop replay` (`netcoop/orchestrator/replay.py`); `tests/integration/test_failures_replay.py::test_replay_byte_identical`, `::test_same_input_same_report` |

Also from PS §4/§6: insufficient evidence is a first-class outcome (`tests/integration/test_scenarios.py::test_weak_wifi_without_external_agent_is_insufficient`), and the confidence method is documented (`README.md` § Correlation and scoring).

## 3. Number cross-check

All 11 generated README blocks (`metrics, signatures, policies, envelope, finding, eval, sweep, organizer_robustness,
organizer, fuzz, constants`) are **in sync** with `eval/reports/*`. Hand-written numbers were checked one by one. Matches
include: seed-B precision 98.2%, wrong 1.4%, FP 0%, fault→healthy 1.3%, overall 0.90; per-class values; calibration
bins; fuzz 0.943 → 0.886, registry-off 0.514 → 0.329; sweep 0.55 and 7.5%; organizer 100/100/100; severity 0.21 / 0.695;
hardware failure at 25% = 150 + 50; organizer corruption 0.982 (min 0.975); organizer bin 0.60 vs 0.567;
weak hardware failure all-medium, top-2 0.75 / 1.00; golden 1,680; run 244.7 s / 34 s.

**Mismatches:**

| file:line | stated | actual (source) |
|---|---|---|
| `README.md:695` | "115 tests" | **127** (`pytest --collect-only`) |
| `README.md:695` | "~40 s" | **~50 s** (49.6 s measured for the full suite) |
| `docs/DEMO.md:185` | "the 115 tests" | **127** |
| `README.md:487` | hardware_failure at reduced severity "is *confidently mislabeled*" | all 400 weakened cases are **medium** confidence (`eval/reports/weak_hw_after.json`) |
| `README.md:488` | "At 25% severity every record is diagnosed" | **150 probable + 50 diagnosed**; in the 150 hardware failure is the named co-candidate (`weak_hw_before.json`, `organizer_robustness.json`) |
| `docs/DEMO.md:45` | "retransmissions 28%" | **28.3%** (`demo_snapshots/05_wifi_diagnosed/report.json`) |
| `docs/DEMO.md:45` | example transform "`retx 0.28 fraction → 28 %`" | illustrative, not literal; the actual transforms read e.g. `0.208 fraction → 20.8 pct` (`runs/present/INC-DEMO0005/events.jsonl`) |

No mismatches in `docs/VIDEO_SCRIPT.md` (generated from the reports) or `docs/RUNBOOK.md`.

## 4. Links and images

* Relative Markdown links and images in README, DEMO, RUNBOOK, VIDEO_SCRIPT, SCHEMA, demo_snapshots/README and TODO:
  **7/7 resolve** to tracked files with exact case (Linux-safe). There are 0 broken links.
* Backticked file paths in those docs: all exist (the only non-path hit is the method name `message/send`).
* Live: `docs/architecture.svg` (blob + raw), `docs/operating_point.png` (raw) and the CI badge all return **HTTP 200** on GitHub.

## 5. Doc-only fixes awaiting approval (not applied)

1. `README.md:695`: `115 tests` → `127 tests`, and `~40 s` → `~50 s`
2. `docs/DEMO.md:185`: `so the 115 tests run offline` → `so the 127 tests run offline`
3. `README.md:487`: `* **Known weakness:** \`hardware_failure\` at reduced severity is *confidently mislabeled*. At 25% severity every`
   → `* **Known weakness:** \`hardware_failure\` at reduced severity is *mislabeled at medium confidence*. At 25% severity every`
4. `README.md:488`: `record is diagnosed, but as \`interface_fault\` (75%) or \`congestion\` (25%); at 50%, 30% are \`interface_fault\`.`
   → `record is committed (150 probable with hardware_failure as co-candidate, 50 diagnosed), but the top cause is \`interface_fault\` (75%) or \`congestion\` (25%); at 50%, 30% are \`interface_fault\`.`
5. `docs/DEMO.md:45`: `retransmissions 28%` → `retransmissions 28.3%`, and `` `retx 0.28 fraction → 28 %` `` → `` `retx` fraction → pct (e.g. 0.208 → 20.8) ``
