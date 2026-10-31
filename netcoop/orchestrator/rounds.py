"""Prediction/evidence round control. Every loop is bounded by config (§7.3)."""

from __future__ import annotations

from typing import Any

from netcoop.config import Config


def needs_more_rounds(cfg: Config, diag: dict[str, Any]) -> bool:
    st = cfg.scoring["status"]
    if diag["status"] in ("insufficient_evidence", "probable"):
        return True
    if diag["status"] == "diagnosed" and diag["margin"] < float(st["min_margin"]):
        return True
    return any(c["type"] == "C2" and not c["resolved"] for c in diag.get("conflicts", []))


def max_rounds(cfg: Config) -> int:
    return int(cfg.agents["rounds"]["max_rounds"])
