"""Plausibility checks (step 6)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def check_range(spec: Mapping[str, Any], value: float) -> str | None:
    lo, hi = spec["range"]
    if value < lo or value > hi:
        return f"value {value:g} outside plausible range [{lo}, {hi}] {spec['unit']}"
    return None
