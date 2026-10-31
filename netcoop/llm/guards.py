"""Input sanitization (PI1) and output allowlisting (PI4) for the optional LLM."""

from __future__ import annotations

import re
from typing import Any

from netcoop.config import Config
from netcoop.policy.validator import BANNED

MAX_COMPLAINT = 1000
MAX_NARRATIVE = 1200
_TAGS = re.compile(r"<[^>]{0,200}>")
_URL = re.compile(r"(https?://|www\.|ftp://)", re.IGNORECASE)
_ID_TOKEN = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b|\bF-[a-z_]+-\d+\b")


def sanitize_complaint(text: Any) -> str:
    """Truncate, strip tag-like sequences and angle brackets, wrap as data."""
    s = str(text or "")[:MAX_COMPLAINT]
    s = _TAGS.sub(" ", s).replace("<", " ").replace(">", " ")
    s = re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", " ", s)
    return f"<complaint>{s.strip()}</complaint>"


def validate_classification(raw: Any, cfg: Config) -> str | None:
    if not isinstance(raw, str):
        return None
    v = raw.strip().strip('"').strip().lower()
    allowed = set(cfg.fault_types) | {"unknown"}
    return v if v in allowed else None


def validate_narrative(text: Any, report: dict[str, Any], cfg: Config) -> list[str]:
    errs: list[str] = []
    if not isinstance(text, str) or not text.strip():
        return ["empty"]
    if len(text) > MAX_NARRATIVE:
        errs.append("too long")
    if _URL.search(text):
        errs.append("contains URL")
    if "```" in text or "`" in text or "<" in text:
        errs.append("contains code/markup")
    if BANNED.search(text):
        errs.append("certainty language")
    known = set(cfg.topology.entities) | {e.get("finding_id") for e in report.get("supporting_evidence", [])}
    known |= set(cfg.fault_types) | {m.upper() for m in cfg.metrics}
    for tok in _ID_TOKEN.findall(text):
        if tok not in known and tok.lower() not in cfg.metrics:
            errs.append(f"unknown identifier {tok}")
            break
    errs += _content_errors(text, report)
    return errs


def validate_rationale(text: Any, cfg: Config) -> list[str]:
    """Hint rationale (shown in the timeline/report, never used for decisions): short plain text, no URLs/code/markup,
    no certainty words, no identifiers that are not in topology, not model reasoning."""
    if not isinstance(text, str) or not text.strip():
        return ["empty"]
    errs: list[str] = []
    if len(text) > 200:
        errs.append("too long")
    if _URL.search(text):
        errs.append("contains URL")
    if "`" in text or "<" in text or ">" in text:
        errs.append("contains code/markup")
    if BANNED.search(text):
        errs.append("certainty language")
    if _META.match(text):
        errs.append("meta/reasoning text")
    for tok in _ID_TOKEN.findall(text):
        if tok not in cfg.topology.entities and tok.lower() not in cfg.metrics and tok.lower() not in cfg.fault_types:
            errs.append(f"unknown identifier {tok}")
            break
    return errs


# Reasoning / meta text a model emits instead of a summary ("We are given a JSON report...")
_META = re.compile(r"^\s*(we are given|we must|we need to|first,? the user|the user (says|wants|asks)|let me|let's|"
                   r"okay|ok,|alright|i will|i'll|i need to|here is|here's|sure)", re.IGNORECASE)


def _content_errors(text: str, report: dict[str, Any]) -> list[str]:
    """A narrative must summarize THIS report: no meta/reasoning text, it must name the diagnosed fault (or the
    status when there is no fault) and at least one real entity ID from the report, verbatim."""
    errs: list[str] = []
    if _META.match(text):
        errs.append("meta/reasoning text, not a summary")
    low = text.lower()
    ft = report.get("fault_type")
    status = str(report.get("status", ""))
    if ft:
        flat = low.replace("-", "")  # "Wi-Fi" -> "wifi"
        if not all(w in flat for w in ft.lower().split("_")):  # "dns_failure" matches "DNS service failure"
            errs.append(f"does not name the diagnosed fault {ft}")
    elif status == "no_fault_detected":
        if "no fault" not in low:
            errs.append("does not state that no fault was detected")
    elif status == "insufficient_evidence":
        if "insufficient" not in low and "not sufficient" not in low:
            errs.append("does not state that the evidence is insufficient")
    ids = list(report.get("affected_devices", [])) + [e.get("entity") for e in report.get("supporting_evidence", [])]
    ids = [i for i in dict.fromkeys(ids) if i]
    if ids and not any(re.search(rf"(?<![A-Za-z0-9_]){re.escape(i)}(?![A-Za-z0-9_])", text) for i in ids):
        errs.append("names no real device/entity ID from the report verbatim")
    return errs
