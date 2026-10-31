"""V1: the single-snapshot limitation is reporting only: it never changes status, confidence or scoring."""

from __future__ import annotations

import json
import random

import netcoop.normalize.pipeline as pipeline
from eval.organizer_check import load_generator

GEN = load_generator()
KEYS = ("status", "status_reason", "fault_type", "confidence", "confidence_category", "scoring", "supporting_evidence",
        "affected_devices", "predictions", "recommended_actions")


def _rec(label, seed):
    random.seed(seed)
    return GEN(label)


def test_single_record_gets_the_limitation(run):
    rep = run(json.dumps(_rec("hardware_failure", 1)).encode()).report
    assert any("single snapshot: persistence not verified" in lim for lim in rep["limitations"])


def test_multi_sample_input_does_not(run):
    rep = run("congestion").report
    assert not any("single snapshot" in lim for lim in rep["limitations"])


def test_limitation_changes_nothing_else(run, monkeypatch):
    for label in ("normal", "latency_spike", "hardware_failure"):
        for seed in (3, 4):
            data = json.dumps(_rec(label, seed)).encode()
            with_lim = run(data).report
            monkeypatch.setattr(pipeline, "single_snapshot_limitation", lambda res: None)
            without = run(data).report
            monkeypatch.undo()
            assert {k: with_lim.get(k) for k in KEYS} == {k: without.get(k) for k in KEYS}, (label, seed)
            assert any("single snapshot" in lim for lim in with_lim["limitations"])
            assert not any("single snapshot" in lim for lim in without["limitations"])
