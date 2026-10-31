"""Optional LLM (NETCOOP_LLM=off|local|cloud, default off). Two jobs only (§10):
1. classify the complaint into fault_types ∪ {unknown}: a HINT that can only add a hypothesis;
2. write the `narrative` from the final, validated report.
It never chooses root cause, confidence, status or actions, has no tools, and never sees raw telemetry
or external-agent strings. On any failure: retry once, then the deterministic template.
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request
from typing import Any

from netcoop.config import Config
from netcoop.llm.guards import sanitize_complaint, validate_classification, validate_narrative
from netcoop.llm.prompts import classify_messages, narrative_messages

TIMEOUT_S = 20
MAX_TOKENS = 300


def mode() -> str:
    m = os.environ.get("NETCOOP_LLM", "off").strip().lower()
    return m if m in ("off", "local", "cloud") else "off"


def _post(url: str, body: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:  # noqa: S310 - fixed endpoints from env/config
        return json.loads(resp.read(1_000_000).decode())


def _call(system: str, user: str) -> str:
    m = mode()
    if m == "local":
        base = os.environ.get("NETCOOP_OLLAMA_URL", "http://127.0.0.1:11434")
        out = _post(f"{base}/api/generate", {"model": os.environ.get("NETCOOP_LOCAL_MODEL", "llama3.1:8b"),
                                             "system": system, "prompt": user, "stream": False,
                                             "options": {"temperature": 0, "num_predict": MAX_TOKENS}}, {})
        return str(out.get("response", ""))
    if m == "cloud":
        key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY not set")
        out = _post("https://api.anthropic.com/v1/messages",
                    {"model": os.environ.get("NETCOOP_CLOUD_MODEL", "claude-haiku-5-5"), "max_tokens": MAX_TOKENS,
                     "temperature": 0, "system": system, "messages": [{"role": "user", "content": user}]},
                    {"x-api-key": key, "anthropic-version": "2023-06-01"})
        return "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
    raise RuntimeError("LLM off")


def _redact(text: str, cfg: Config) -> tuple[str, dict[str, str]]:
    """PI7: NETCOOP_REDACT=1 replaces canonical IDs with tokens before cloud calls."""
    if os.environ.get("NETCOOP_REDACT") != "1":
        return text, {}
    mapping: dict[str, str] = {}
    for i, eid in enumerate(sorted(cfg.topology.entities, key=len, reverse=True)):
        if eid in text:
            tok = f"ENT_{i:03d}"
            mapping[tok] = eid
            text = re.sub(rf"\b{re.escape(eid)}\b", tok, text)
    return text, mapping


def classify_complaint(complaint: str | None, cfg: Config) -> tuple[list[str], dict[str, Any]]:
    log: dict[str, Any] = {"job": "classify", "mode": mode(), "fallback": True}
    if not complaint or mode() == "off":
        return [], log
    system, user = classify_messages(sanitize_complaint(complaint), list(cfg.fault_types) + ["unknown"])
    for _attempt in range(2):
        t0 = time.monotonic()
        try:
            label = validate_classification(_call(system, user), cfg)
        except Exception:  # noqa: BLE001 - any failure -> retry/fallback
            label = None
        log["latency_ms"] = round((time.monotonic() - t0) * 1000)
        if label is not None:
            log["fallback"] = False
            return ([label] if label != "unknown" else []), log
    return [], log


def template_narrative(report: dict[str, Any]) -> str:
    st = report["status"]
    if st in ("diagnosed", "probable"):
        ev = ", ".join(f"{e['metric']}={e['value']:g} on {e['entity']}" for e in report["supporting_evidence"][:3])
        s = (f"{report['suspected_root_cause']} (confidence {report['confidence']:.2f}, "
             f"{report.get('confidence_category', 'low')}). Key evidence: {ev}.")
        preds = report.get("predictions", [])
        if preds:
            hits = sum(1 for p in preds if p["outcome"] == "hit")
            s += f" {hits} of {len(preds)} logged predictions were hits."
        return s
    if st == "insufficient_evidence":
        miss = ", ".join(report.get("missing_signals", [])[:4]) or "additional telemetry"
        return f"The evidence is not sufficient for a reliable diagnosis. Signals that would resolve it: {miss}."
    if st == "no_fault_detected":
        return "All analysed measurements are within expected ranges; no fault was detected."
    return "The diagnosis could not be completed; see limitations."


def write_narrative(report: dict[str, Any], cfg: Config) -> tuple[str, dict[str, Any]]:
    log: dict[str, Any] = {"job": "narrative", "mode": mode(), "fallback": True}
    if mode() == "off":
        return template_narrative(report), log
    system, user = narrative_messages(report)
    user, mapping = _redact(user, cfg) if mode() == "cloud" else (user, {})
    for _attempt in range(2):
        t0 = time.monotonic()
        try:
            text = _call(system, user).strip()
            for tok, eid in mapping.items():
                text = text.replace(tok, eid)
            errs = validate_narrative(text, report, cfg)
        except Exception as exc:  # noqa: BLE001
            text, errs = "", [str(exc)[:80]]
        log["latency_ms"] = round((time.monotonic() - t0) * 1000)
        if not errs:
            log["fallback"] = False
            return text, log
        log["rejected"] = errs[:3]
    return template_narrative(report), log
