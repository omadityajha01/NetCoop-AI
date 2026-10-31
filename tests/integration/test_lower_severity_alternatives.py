"""W2: report-only alternatives for faults whose signature covers the matched symptoms (no decision change)."""

from __future__ import annotations

import json
import random

from eval.organizer_check import load_generator
from eval.organizer_robustness import scaled

GEN = load_generator()
LABEL = "Likely device hardware failure"


def test_weakened_hardware_failure_is_listed_as_alternative(run):
    for seed in (100000, 100001, 100002):
        random.seed(seed)
        rep = run(json.dumps(scaled(GEN, "hardware_failure", 0.25)).encode()).report
        assert rep["fault_type"] != "hardware_failure"  # unchanged decision: it is not the top cause at 25%
        assert any(a.startswith(LABEL) for a in rep["alternative_causes"])
        assert "symptoms also consistent with hardware failure at lower severity" in rep["limitations"]


def test_full_strength_hardware_failure_unchanged(run):
    random.seed(7)
    rep = run(json.dumps(GEN("hardware_failure")).encode()).report
    assert rep["fault_type"] == "hardware_failure" and rep["confidence_category"] == "high"
    assert not any("at lower severity" in lim for lim in rep["limitations"])
