"""Threshold lookups: metrics.yaml + policy threshold overrides. Severity derived from thresholds only."""

from __future__ import annotations

from netcoop.config import Config

LEVELS = ("critical", "high", "warn")


def threshold_set(cfg: Config, metric: str, entity_id: str) -> tuple[dict[str, float], str]:
    spec = cfg.metrics[metric]
    etype = cfg.topology.type_of(entity_id)
    ctx = "wireless" if etype == "ap" and "wireless" in spec["thresholds"] else "default"
    if ctx not in spec["thresholds"]:
        ctx = next(iter(spec["thresholds"]))
    th = {k: float(v) for k, v in spec["thresholds"][ctx].items()}
    ref = f"metrics.yaml#{metric}.{ctx}"
    seg = cfg.topology.segment_of(entity_id)
    for rule in cfg.policies.get("rules", ()):
        if rule.get("type") == "threshold_override" and rule.get("metric") == metric and rule.get("segment") == seg:
            for lvl in ("warn", "high", "critical"):
                if lvl in rule:
                    th[lvl] = float(rule[lvl])
            ref = f"policies.yaml#{rule['id']}"
    return th, ref


def threshold_value(cfg: Config, metric: str, entity_id: str, level: str) -> float | None:
    th, _ = threshold_set(cfg, metric, entity_id)
    return th.get(level)


def crosses(direction: str, value: float, thr: float) -> bool:
    return value >= thr if direction == "higher_is_worse" else value <= thr


def severity(cfg: Config, metric: str, entity_id: str, value: float) -> tuple[str, str]:
    th, ref = threshold_set(cfg, metric, entity_id)
    direction = cfg.metrics[metric]["direction"]
    for lvl in LEVELS:
        if lvl in th and crosses(direction, value, th[lvl]):
            return lvl, f"{ref}.{lvl}"
    return "normal", f"{ref}.warn"


def compare(value: float, op: str, thr: float) -> bool:
    return {">=": value >= thr, "<=": value <= thr, ">": value > thr, "<": value < thr}[op]


NEGATE = {">=": "<", "<=": ">", ">": "<=", "<": ">="}
