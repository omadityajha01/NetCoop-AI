"""Remediation dry-run (S1): a human-approved, policy-checked plan that is NEVER executed.

Flow (on an existing `human_decision` approve):
1. look up the approved action in report.json (`action_details`, `blocked_actions`);
2. run policy/checker.py at the incident time, the same time the report used. If blocked, return the rule id and
   reason and emit no plan;
3. if allowed, render the action verb's `_dry_run` template from playbook.yaml and emit an NMP `remediation_plan`
   labelled "SIMULATED – NOT EXECUTED", with its steps and a rollback step.

Nothing is executed: this module imports no network or subprocess code, and it never touches report.json.
Parameters are validated topology IDs. Substitution is single-pass and literal, so a value containing `{...}` is
never expanded again. Every string is rendered as text by the dashboard (PI8).
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from netcoop.config import Config
from netcoop.policy.checker import check_action

_PLACEHOLDER = re.compile(r"\{(target|segment|action_id)\}")
ID_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")  # PI6


def render(template: str, params: dict[str, str]) -> str:
    """Single-pass literal substitution: values are inserted as-is and never re-scanned for placeholders."""
    return _PLACEHOLDER.sub(lambda m: params.get(m.group(1), m.group(0)), template)


def _incident_time(events: list[dict[str, Any]]) -> datetime | None:
    for e in events:
        if e.get("message_type") == "normalization_summary" and e["payload"].get("incident_time"):
            return datetime.fromisoformat(e["payload"]["incident_time"].replace("Z", "+00:00"))
    return None


def plan_for(cfg: Config, report: dict[str, Any], events: list[dict[str, Any]], action_id: str
             ) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Return (plan_payload_without_seq or None, policy_result)."""
    detail = next((a for a in report.get("action_details", []) if a.get("id") == action_id), None)
    if detail is None:
        return None, {"allowed": False, "rule_id": None, "reason": "action not in this report"}
    target = detail.get("target")
    if target is not None and (not isinstance(target, str) or not ID_RE.fullmatch(target) or not cfg.topology.exists(target)):
        return None, {"allowed": False, "rule_id": None, "reason": "target is not a known topology entity"}
    at = _incident_time(events)
    if at is None:
        return None, {"allowed": False, "rule_id": None, "reason": "incident time unknown"}
    res = check_action(cfg, detail["action"], target, at)
    policy = {"allowed": res.allowed, "rule_id": res.rule_id, "reason": res.reason, "checked_at": at.isoformat()}
    if not res.allowed:
        return None, policy
    tpl = cfg.playbook.get("_dry_run", {}).get(detail["action"])
    if tpl is None:
        return None, {**policy, "allowed": False, "reason": f"no dry-run template for action {detail['action']}"}
    params = {"target": target or "the affected scope", "segment": (cfg.topology.segment_of(target) if target else None)
              or "the affected", "action_id": action_id}
    plan = {"action_id": action_id, "action": detail["action"], "target": target, "policy": policy,
            "steps": [render(s, params) for s in tpl["steps"]], "rollback": [render(s, params) for s in tpl["rollback"]]}
    return plan, policy


def load_events(path: Any) -> list[dict[str, Any]]:
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
