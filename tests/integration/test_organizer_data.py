"""T2: raw organizer generator through the full pipeline (no preprocessing)."""

from __future__ import annotations

import json
import random

from eval.organizer_check import load_generator
from netcoop.normalize.pipeline import normalize_bundle

GEN = load_generator()


def _rec(fault, seed):
    random.seed(seed)
    return GEN(fault)


def test_every_organizer_device_id_is_in_topology(cfg):
    ids = {f"SW_CAMPUS_{i}" for i in range(1, 11)}
    assert all(cfg.topology.exists(i) for i in ids)
    seen = {_rec(f, s)["device_id"] for f in ("normal", "latency_spike", "hardware_failure") for s in range(60)}
    assert seen <= ids  # the generator only emits SW_CAMPUS_1..10


def test_organizer_records_are_never_quarantined(cfg):
    for fault in ("normal", "latency_spike", "hardware_failure"):
        for seed in range(20):
            res = normalize_bundle(json.dumps(_rec(fault, seed)).encode(), cfg)
            assert res.records_quarantined == 0 and res.records_used == 1, (fault, seed, res.quarantined)


def test_organizer_normal_is_no_fault(run):
    for seed in range(15):
        assert run(json.dumps(_rec("normal", seed)).encode()).report["status"] == "no_fault_detected"


def test_organizer_labels_map_one_to_one(run):
    """U1: every organizer label maps to exactly one NetCoop outcome (derivation in data/generator/SCHEMA.md)."""
    for label, fault in (("latency_spike", "latency_spike"), ("hardware_failure", "hardware_failure")):
        for seed in range(15):
            rep = run(json.dumps(_rec(label, seed)).encode()).report
            assert rep["status"] == "diagnosed" and rep["fault_type"] == fault, (label, seed, rep["status"])
            assert rep["affected_devices"] == [_rec(label, seed)["device_id"]]


def test_single_record_snapshot_is_complete(run):
    """A one-record input is complete relative to its own cadence (quality is not floored to 0.5)."""
    rep = run(json.dumps(_rec("hardware_failure", 3)).encode()).report
    assert rep["scoring"]["quality"] == 1.0
