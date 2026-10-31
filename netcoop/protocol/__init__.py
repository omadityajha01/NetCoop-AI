"""NetCoop Message Protocol (NMP) v1.0: Pydantic models are the source of truth (`make schemas`)."""

from netcoop.protocol.envelope import SCHEMA_VERSION, Message, error_message, make_message
from netcoop.protocol.findings import (
    DataQuality,
    EntityRef,
    Finding,
    Hypothesis,
    Limitation,
    Prediction,
    SignalRef,
    Transform,
    Window,
)

__all__ = [
    "SCHEMA_VERSION",
    "DataQuality",
    "EntityRef",
    "Finding",
    "Hypothesis",
    "Limitation",
    "Message",
    "Prediction",
    "SignalRef",
    "Transform",
    "Window",
    "error_message",
    "make_message",
]
