"""NMP v1.0 envelope. Every message on the bus and over the gateway is one of these."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from netcoop.protocol.findings import Limitation, UTCDateTime
from netcoop.protocol.messages import PAYLOAD_MODELS

# 1.1 (MINOR, additive): Finding.source, report `observations` + `status_reason`, `normalization_summary` message type.
# 1.0 messages are still accepted unchanged; 0.9 is upcast via upcasters.py.
# 1.2 (MINOR, additive): `hint` message type (LLM triage agent; hints only ADD hypotheses).
# 1.3 (MINOR, additive): `human_decision` message type (non-blocking HITL record, appended after the report).
# 1.4 (MINOR, additive): `remediation_plan` message type (dry-run, human-approved, policy-checked, never executed).
SCHEMA_VERSION = "1.4"
INCIDENT_ID_PATTERN = r"^INC-[0-9A-Z]{4,12}$"
AGENT_ID_PATTERN = r"^[a-z][a-z0-9_]{1,40}$"

MessageType = Literal[
    "task_request",
    "finding_report",
    "coverage_manifest",
    "prediction",
    "evidence_request",
    "evidence_response",
    "diagnosis",
    "report",
    "error",
    "normalization_summary",
    "hint",
    "human_decision",
    "remediation_plan",
]
Status = Literal["completed", "partial", "failed", "insufficient_data"]


class Message(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = Field(default=SCHEMA_VERSION, pattern=r"^[0-9]+\.[0-9]+$")
    message_id: str
    message_type: MessageType
    incident_id: str = Field(pattern=INCIDENT_ID_PATTERN)
    sender: str = Field(pattern=AGENT_ID_PATTERN)
    recipient: str = Field(pattern=AGENT_ID_PATTERN)
    in_reply_to: str | None = None
    seq: int | None = None
    created_at: UTCDateTime | None = None
    status: Status = "completed"
    payload: dict[str, Any]
    limitations: list[Limitation] = Field(default_factory=list)
    extras: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _check(self) -> Message:
        try:
            uuid.UUID(self.message_id)
        except ValueError as exc:
            raise ValueError("message_id must be a UUID") from exc
        model = PAYLOAD_MODELS[self.message_type]
        # validate + canonicalize payload (dict form keeps the log JSON-native)
        self.payload = model.model_validate(self.payload).model_dump(mode="json", by_alias=True)
        return self

    def typed(self) -> Any:
        return PAYLOAD_MODELS[self.message_type].model_validate(self.payload)

    def to_json_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


def deterministic_uuid4(*parts: Any) -> str:
    """UUIDv4-formatted id derived from content, so runs are reproducible (G9)."""
    h = hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode()).digest()
    return str(uuid.UUID(bytes=h[:16], version=4))


def make_message(
    message_type: str,
    *,
    sender: str,
    recipient: str,
    incident_id: str,
    payload: Any,
    in_reply_to: str | None = None,
    status: str = "completed",
    limitations: list[Limitation] | None = None,
    salt: Any = None,
) -> Message:
    if isinstance(payload, BaseModel):
        payload = payload.model_dump(mode="json", by_alias=True)
    mid = deterministic_uuid4(incident_id, sender, recipient, message_type, in_reply_to, payload, salt)
    return Message(
        message_id=mid,
        message_type=message_type,
        incident_id=incident_id,
        sender=sender,
        recipient=recipient,
        in_reply_to=in_reply_to,
        status=status,
        payload=payload,
        limitations=limitations or [],
    )


def error_message(
    *,
    sender: str,
    recipient: str,
    incident_id: str,
    code: str,
    detail: str,
    offending_message_id: str | None = None,
    field: str | None = None,
    agent_id: str | None = None,
) -> Message:
    return make_message(
        "error",
        sender=sender,
        recipient=recipient,
        incident_id=incident_id,
        in_reply_to=offending_message_id,
        status="failed",
        payload={
            "code": code,
            "detail": detail[:500],
            "offending_message_id": offending_message_id,
            "field": field,
            "agent_id": agent_id,
        },
    )
