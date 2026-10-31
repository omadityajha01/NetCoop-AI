"""Value coercion and unit conversion (steps 4-5). Missing is missing: never 0."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from typing import Any

MISSING_TOKENS = {"", "n/a", "na", "null", "none", "nan", "-", "--", "?", "unknown", "nil"}
_NUM_UNIT = re.compile(r"^\s*([-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?)\s*([A-Za-z%/]+)?\s*$")


class Missing:
    """Sentinel for missing values."""

    def __repr__(self) -> str:  # pragma: no cover
        return "MISSING"


MISSING = Missing()


def coerce_value(raw: Any, value_map: Mapping[str, Any] | None = None) -> tuple[Any, str | None, bool, str | None]:
    """Return (value | MISSING | None-on-bad-type, unit_token, coerced, problem)."""
    if raw is None:
        return MISSING, None, False, None
    if isinstance(raw, bool):
        return (1.0 if raw else 0.0), None, True, None
    if isinstance(raw, int | float):
        if isinstance(raw, float) and (math.isnan(raw) or math.isinf(raw)):
            return MISSING, None, True, None
        return float(raw), None, False, None
    if isinstance(raw, str):
        s = raw.strip()
        if s.lower() in MISSING_TOKENS:
            return MISSING, None, True, None
        if value_map and s.lower() in value_map:
            return float(value_map[s.lower()]), None, True, None
        m = _NUM_UNIT.match(s.replace(",", ""))
        if m:
            v = float(m.group(1))
            if math.isnan(v) or math.isinf(v):
                return MISSING, None, True, None
            return v, (m.group(2) or None), True, None
        return None, None, True, f"not a number: {s[:40]!r}"
    return None, None, False, f"unsupported type {type(raw).__name__}"


def unit_multiplier(spec: Mapping[str, Any], unit_token: str) -> float | None:
    ua = {str(k).lower(): float(v) for k, v in spec.get("unit_aliases", {}).items()}
    ua.setdefault(str(spec["unit"]).lower(), 1.0)
    return ua.get(unit_token.strip().lower())


def infer_batch_multiplier(spec: Mapping[str, Any], values: list[float], min_batch: int = 3) -> tuple[float | None, str]:
    """Infer a unit from batch-level evidence only (never from one value).

    A multiplier is a candidate if every value in the batch is plausible under it. If exactly one
    distinct candidate remains it is used. pct metrics with `fraction_inference` resolve the
    [0,1]-ambiguity in favour of fraction (x100).
    """
    if len(values) < min_batch:
        return None, f"only {len(values)} value(s) without a unit; need >= {min_batch} to infer"
    lo, hi = spec["range"]
    mults = sorted({float(v) for v in spec.get("unit_aliases", {}).values()} | {1.0})
    cands = [m for m in mults if all(lo <= v * m <= hi for v in values)]
    if spec.get("fraction_inference") and 100.0 in cands and all(0 <= v <= 1 for v in values) and max(values) > 0:
        return 100.0, "all values in [0,1] for a percentage metric -> fraction x100"
    if len(cands) == 1:
        return cands[0], f"only multiplier {cands[0]:g} keeps all {len(values)} values in range"
    if not cands:
        return None, "no unit keeps the batch in the plausible range"
    return None, f"ambiguous: multipliers {', '.join(f'{c:g}' for c in cands)} all plausible"
