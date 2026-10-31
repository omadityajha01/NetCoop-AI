"""§11 PI4: the LLM narrative must be a summary of THIS report, not model reasoning or a partial echo."""

from __future__ import annotations

import json

import pytest

from netcoop.llm.guards import validate_narrative
from netcoop.llm.router import template_narrative
from tests.conftest import ROOT

SNAPS = sorted((ROOT / "demo_snapshots").glob("*/report.json"))


def _rep(step: str) -> dict:
    return json.loads((ROOT / "demo_snapshots" / step / "report.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("meta", [
    "We are given a JSON report. We must write a 2-4 sentence summary about congestion on HOSTEL_CORE_SW_01.",
    "First, the user says: classify congestion on HOSTEL_CORE_SW_01.",
    "Okay, so congestion likely affects HOSTEL_CORE_SW_01.",
    "Let me summarize: congestion on HOSTEL_CORE_SW_01.",
])
def test_reasoning_text_is_rejected(cfg, meta):
    errs = validate_narrative(meta, _rep("01_congestion"), cfg)
    assert any("meta/reasoning" in e for e in errs)


def test_must_name_fault_and_a_real_full_id(cfg):
    rep = _rep("01_congestion")
    good = "Link congestion on L_HOSTEL_UPLINK is the likely cause; queue drops on HOSTEL_CORE_SW_01 suggest egress pressure."
    assert validate_narrative(good, rep, cfg) == []
    assert any("diagnosed fault" in e for e in validate_narrative("Something is wrong on HOSTEL_CORE_SW_01.", rep, cfg))
    assert any("verbatim" in e for e in validate_narrative("Link congestion is the likely cause.", rep, cfg))
    # truncated IDs fail (unknown identifier) and do not count as naming a device
    errs = validate_narrative("Link congestion likely on HOSTEL_CORE.", rep, cfg)
    assert any("unknown identifier HOSTEL_CORE" in e for e in errs) and any("verbatim" in e for e in errs)


def test_status_words_for_no_fault_and_insufficient(cfg):
    assert any("no fault" in e for e in validate_narrative("All good.", _rep("08_normal"), cfg))
    assert validate_narrative("No fault was detected; measurements are within expected ranges.", _rep("08_normal"), cfg) == []
    wifi = _rep("02_wifi_insufficient")
    assert any("insufficient" in e for e in validate_narrative("Wi-Fi is slow at AP_H3.", wifi, cfg))
    assert validate_narrative("The evidence is insufficient at AP_H3; RF signals are missing.", wifi, cfg) == []


@pytest.mark.parametrize("snap", SNAPS, ids=lambda p: p.parent.name)
def test_template_fallback_always_passes_the_strict_check(cfg, snap):
    rep = json.loads(snap.read_text(encoding="utf-8"))
    assert validate_narrative(template_narrative(rep), rep, cfg) == []
