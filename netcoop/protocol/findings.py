"""NMP v1.0 core value objects: entities, windows, findings, hypotheses, predictions, limitations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field

ENTITY_ID_PATTERN = r"^[A-Za-z0-9_.:\-]{1,64}$"
FINDING_ID_PATTERN = r"^F-[a-z0-9_]+-[0-9]+$"

EntityType = Literal["device", "link", "ap", "service"]
Severity = Literal["normal", "warn", "high", "critical"]
Aggregation = Literal["p95", "mean", "max", "count", "rate"]
SEVERITY_ORDER = {"normal": 0, "warn": 1, "high": 2, "critical": 3}


def _to_utc(v: datetime) -> datetime:
    if v.tzinfo is None:
        raise ValueError("timestamp must be timezone-aware (RFC3339 UTC)")
    return v.astimezone(UTC)


UTCDateTime = Annotated[datetime, AfterValidator(_to_utc)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EntityRef(_Model):
    type: EntityType
    id: str = Field(pattern=ENTITY_ID_PATTERN)

    def key(self) -> str:
        return f"{self.type}:{self.id}"


class Window(_Model):
    start: UTCDateTime
    end: UTCDateTime


class DataQuality(_Model):
    completeness: float = Field(ge=0, le=1)
    staleness_s: float = Field(ge=0)
    coerced: bool = False


class Transform(_Model):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)
    step: str
    field: str
    from_: Any = Field(default=None, alias="from")
    to: Any = None
    reason: str


class Limitation(_Model):
    code: str
    detail: str
    impact: Literal["none", "low", "medium", "high"] = "low"


class Finding(_Model):
    finding_id: str = Field(pattern=FINDING_ID_PATTERN)
    metric: str
    entity: EntityRef
    value: float
    unit: str
    window: Window
    aggregation: Aggregation
    sample_count: int = Field(ge=0)
    threshold_ref: str
    severity: Severity
    data_quality: DataQuality
    transforms: list[Transform] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    source: str | None = None  # NMP 1.0 additive: originating telemetry source (for C1)

    @property
    def anomalous(self) -> bool:
        return SEVERITY_ORDER[self.severity] >= 1


class SignalRef(_Model):
    metric: str
    entity: EntityRef
    window: Window | None = None

    def key(self) -> str:
        return f"{self.metric}@{self.entity.id}"


class Expectation(_Model):
    op: Literal[">=", "<=", "<", ">"]
    ref: Literal["warn", "high", "critical"]


class Prediction(_Model):
    prediction_id: str
    hypothesis_id: str
    fault_type: str
    signal: SignalRef
    expected: Expectation
    outcome: Literal["pending", "hit", "miss", "unknown"] = "pending"
    evidence_finding_id: str | None = None
    round: int = 1


class Hypothesis(_Model):
    hypothesis_id: str
    fault_type: str
    entity: EntityRef
    score: float
    support: float
    coverage: float
    contra: float
    quality: float
    supporting_finding_ids: list[str] = Field(default_factory=list)
    contradicting_finding_ids: list[str] = Field(default_factory=list)
    unmatched_finding_ids: list[str] = Field(default_factory=list)
    missing_signals: list[str] = Field(default_factory=list)
    source: Literal["findings", "hint", "scope"] = "findings"
