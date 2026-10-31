"""Report validator (G4) + certainty-language lint (G5). Run before any report is written."""

from __future__ import annotations

import re
from typing import Any

from netcoop.config import Config

PS_FIELDS = {
    "incident_id": str, "status": str, "suspected_root_cause": str, "confidence": (int, float),
    "affected_devices": list, "supporting_evidence": list, "alternative_causes": list,
    "recommended_actions": list, "evidence_sources": list, "limitations": list,
}
STATUSES = ("diagnosed", "probable", "insufficient_evidence", "no_fault_detected", "failed")
BANNED = re.compile(r"\b(confirmed|definitely|certainly|guaranteed)\b", re.IGNORECASE)


def scrub(text: str) -> str:
    """Remove banned certainty words from data-derived strings."""
    return BANNED.sub("[redacted]", text)


def _strings(obj: Any, path: str = ""):
    if isinstance(obj, str):
        yield path, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _strings(v, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _strings(v, f"{path}[{i}]")


def validate_report(report: dict[str, Any], cfg: Config, known_finding_ids: set[str]) -> list[str]:
    errors: list[str] = []
    for k, typ in PS_FIELDS.items():
        if k not in report:
            errors.append(f"missing PS field {k}")
        elif not isinstance(report[k], typ):
            errors.append(f"{k} has wrong type")
    if errors:
        return errors
    if report["status"] not in STATUSES:
        errors.append(f"status {report['status']!r} not allowed")
    if not 0 <= float(report["confidence"]) <= 1:
        errors.append("confidence outside [0,1]")
    for ev in report["supporting_evidence"]:
        fid = ev.get("finding_id") if isinstance(ev, dict) else None
        if fid not in known_finding_ids:
            errors.append(f"supporting_evidence references unknown finding {fid!r}")  # also blocks G7 knowledge-as-evidence
    for d in report["affected_devices"]:
        if not cfg.topology.exists(d):
            errors.append(f"affected device {d!r} not in topology")
    ft = report.get("fault_type")
    if ft is not None and ft not in cfg.signatures:
        errors.append(f"fault_type {ft!r} not in signature enum")
    for alt in report.get("rejected_alternatives", []):
        if alt.get("fault_type") not in cfg.signatures:
            errors.append(f"rejected alternative fault_type {alt.get('fault_type')!r} not in enum")
    if not report["limitations"]:
        errors.append("report must have at least one limitation")
    for path, s in _strings(report):
        if BANNED.search(s):
            errors.append(f"certainty language at {path}")
    return errors
