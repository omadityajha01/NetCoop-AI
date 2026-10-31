"""Typed payloads per message_type (NMP v1.0)."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from netcoop.protocol.findings import (
    EntityRef,
    Finding,
    Hypothesis,
    Prediction,
    SignalRef,
    Window,
)

ERROR_CODES = (
    "SCHEMA_VERSION_UNSUPPORTED",
    "MISSING_FIELD",
    "BAD_TYPE",
    "BAD_UNIT",
    "UNKNOWN_ENTITY",
    "MALFORMED",
    "TIMEOUT",
    "TOO_LARGE",
    "AGENT_FAILED",
    "INVALID_OUTPUT",
    "RATE_LIMITED",
)


class _P(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TaskRequestPayload(_P):
    task: Literal["analyze", "scope", "correlate", "finalize", "report", "triage"]
    window: Window
    round: int = 0
    params: dict[str, Any] = Field(default_factory=dict)


class RawObservation(_P):
    """A raw record carried by external agents; normalized by the receiver before use."""

    model_config = ConfigDict(extra="allow")


class Scope(_P):
    affected_entities: list[str]
    affected_devices: list[str]
    nearest_common_upstream: str | None
    segments: list[str]


class FindingReportPayload(_P):
    round: int = 0
    findings: list[Finding] = Field(default_factory=list)
    observations: list[dict[str, Any]] | None = None  # only before normalization (external agents)
    scope: Scope | None = None


class CoverageSignal(_P):
    metric: str
    entity: EntityRef


class CoverageManifestPayload(_P):
    signals: list[CoverageSignal] = Field(default_factory=list)


class PredictionPayload(_P):
    prediction: Prediction


class EvidenceRequestPayload(_P):
    round: int
    requests: list[SignalRef]
    prediction_ids: list[str] = Field(default_factory=list)
    reason: str = "prediction"


class EvidenceResponsePayload(_P):
    round: int = 0
    findings: list[Finding] = Field(default_factory=list)
    observations: list[dict[str, Any]] | None = None
    unavailable: list[SignalRef] = Field(default_factory=list)


class Conflict(_P):
    conflict_id: str
    type: Literal["C1", "C2", "C3"]
    detail: str
    finding_ids: list[str] = Field(default_factory=list)
    resolution: str
    resolved: bool
    winner_finding_id: str | None = None
    loser_finding_ids: list[str] = Field(default_factory=list)
    stale_finding_ids: list[str] = Field(default_factory=list)


class DiagnosisPayload(_P):
    phase: Literal["interim", "final"]
    round: int
    status: Literal["diagnosed", "probable", "insufficient_evidence", "no_fault_detected", "failed"]
    status_reason: Literal["data_missing", "no_signature_match"] | None = None
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    top_hypothesis_id: str | None = None
    co_candidate_ids: list[str] = Field(default_factory=list)
    margin: float = 0.0
    confidence: float = 0.0
    confidence_category: Literal["high", "medium", "low"] = "low"
    caps: list[str] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    predictions: list[Prediction] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    anomalous_finding_count: int = 0
    scope: Scope | None = None
    notes: list[str] = Field(default_factory=list)


class ReportPayload(_P):
    report: dict[str, Any]


class ErrorPayload(_P):
    code: str
    detail: str
    offending_message_id: str | None = None
    field: str | None = None
    agent_id: str | None = None


class NormalizationSummaryPayload(_P):
    input_sha256: str
    incident_time: str
    incident_time_inferred: bool
    window: Window
    summary: dict[str, int]
    quarantined: list[dict[str, Any]] = Field(default_factory=list)
    extras: list[dict[str, Any]] = Field(default_factory=list)
    complaint_present: bool = False
    hints: list[str] = Field(default_factory=list)


class HintPayload(_P):
    """LLM triage hint (NMP 1.2). Advisory only: it can ADD a hypothesis for the agents to test (PI5), never decide."""

    fault_type: str = Field(min_length=1, max_length=40)
    rationale: str = Field(max_length=200)
    model: str | None = Field(default=None, max_length=60)


PAYLOAD_MODELS: dict[str, type[BaseModel]] = {
    "task_request": TaskRequestPayload,
    "finding_report": FindingReportPayload,
    "coverage_manifest": CoverageManifestPayload,
    "prediction": PredictionPayload,
    "evidence_request": EvidenceRequestPayload,
    "evidence_response": EvidenceResponsePayload,
    "diagnosis": DiagnosisPayload,
    "report": ReportPayload,
    "error": ErrorPayload,
    "normalization_summary": NormalizationSummaryPayload,
    "hint": HintPayload,
}
