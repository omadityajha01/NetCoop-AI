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
    return errs
