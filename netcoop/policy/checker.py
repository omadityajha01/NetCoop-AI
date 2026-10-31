"""Hard-rule policy checker (G3). Rules come from config/policies.yaml and are enforced in code."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from netcoop.config import Config

WEEKDAYS = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    rule_id: str | None = None
    reason: str | None = None


def _offset(s: str) -> timedelta:
    sign = -1 if s.startswith("-") else 1
    hh, mm = s.lstrip("+-").split(":")
    return sign * timedelta(hours=int(hh), minutes=int(mm))


def _in_window(t: time, window: str) -> bool:
    a, b = window.split("-")
    start = time.fromisoformat(a.strip())
    end = time.fromisoformat(b.strip())
    if start <= end:
        return start <= t < end
    return t >= start or t < end  # wraps midnight


def check_action(cfg: Config, action: str, target_id: str | None, at: datetime) -> PolicyResult:
    pol = cfg.policies
    local = at + _offset(str(pol.get("timezone_offset", "+00:00")))
    role = cfg.topology.role_of(target_id) if target_id else None
    for rule in pol.get("rules", ()):
        if rule.get("type") != "forbidden_action":
            continue
        actions = rule["action"] if isinstance(rule["action"], tuple | list) else (rule["action"],)
        if action not in actions:
            continue
        tr = rule.get("target_role", "any")
        if tr != "any" and tr != role:
            continue
        if rule.get("window") and not _in_window(local.time().replace(tzinfo=None), rule["window"]):
            continue
        if rule.get("weekdays") and WEEKDAYS[local.weekday()] not in rule["weekdays"]:
            continue
        if rule.get("dates"):
            d0, d1 = (date.fromisoformat(d) for d in rule["dates"])
            if not (d0 <= local.date() <= d1):
                continue
        return PolicyResult(False, rule["id"], rule.get("reason", ""))
    return PolicyResult(True)
