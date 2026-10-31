"""Protocol version detection, MINOR tolerance and MAJOR upcasting (CLAUDE.md §4.4)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from netcoop.protocol.envelope import SCHEMA_VERSION, Message
from netcoop.protocol.findings import Limitation, Transform
from netcoop.protocol.upcasters import UPCASTERS, detect_version_by_shape

ENVELOPE_FIELDS = set(Message.model_fields)
CURRENT_MAJOR, CURRENT_MINOR = (int(x) for x in SCHEMA_VERSION.split("."))


@dataclass
class ParseResult:
    message: Message | None = None
    error_code: str | None = None
    error_detail: str = ""
    error_field: str | None = None
    transforms: list[Transform] = field(default_factory=list)
    limitations: list[Limitation] = field(default_factory=list)
    source_version: str | None = None
    version_inferred: bool = False


def parse_version(v: Any) -> tuple[int, int] | None:
    if not isinstance(v, str):
        return None
    parts = v.strip().split(".")
    if len(parts) != 2 or not all(p.isdigit() for p in parts):
        return None
    return int(parts[0]), int(parts[1])


def upcast(raw: dict[str, Any], version: str) -> tuple[dict[str, Any] | None, list[Transform], str | None]:
    """Run the registered upcaster chain until MAJOR == current. Returns (dict, transforms, error)."""
    transforms: list[Transform] = []
    cur = version
    guard = 0
    while True:
        pv = parse_version(cur)
        if pv is None:
            return None, transforms, f"unparseable schema_version {cur!r}"
        if pv[0] == CURRENT_MAJOR:
            return raw, transforms, None
        fn_spec = UPCASTERS.get(cur)
        if fn_spec is None or guard > 8:
            return None, transforms, f"no upcaster registered from {cur}"
        to_version, fn = fn_spec
        raw, t = fn(raw)
        transforms.extend(t)
        transforms.append(Transform(step="version", field="schema_version", from_=cur, to=to_version,
                                    reason="registered upcaster"))
        cur = to_version
        guard += 1


def parse_message(raw: Any) -> ParseResult:
    """Parse an untrusted dict into an NMP 1.x Message. Never raises."""
    res = ParseResult()
    if not isinstance(raw, dict):
        res.error_code, res.error_detail = "MALFORMED", "message is not a JSON object"
        return res
    version = raw.get("schema_version")
    if version is None and isinstance(raw.get("ver"), str):
        version = raw["ver"]  # pre-1.0 dialects name it `ver`
    if version is None:
        version = detect_version_by_shape(raw)
        if version is None:
            res.error_code, res.error_detail, res.error_field = (
                "MISSING_FIELD", "schema_version missing and no shape detector matched", "schema_version")
            return res
        res.version_inferred = True
        res.limitations.append(Limitation(code="VERSION_INFERRED",
                                          detail=f"schema_version missing; inferred {version} from message shape",
                                          impact="low"))
    res.source_version = version
    pv = parse_version(version)
    if pv is None:
        res.error_code, res.error_detail, res.error_field = (
            "SCHEMA_VERSION_UNSUPPORTED", f"unparseable schema_version {version!r}", "schema_version")
        return res
    data = dict(raw)
    if pv[0] != CURRENT_MAJOR:
        data, t, err = upcast(data, version)
        res.transforms.extend(t)
        if err or data is None:
            res.error_code, res.error_detail, res.error_field = "SCHEMA_VERSION_UNSUPPORTED", err or "", "schema_version"
            return res
    elif pv[1] > CURRENT_MINOR:
        res.limitations.append(Limitation(code="MINOR_VERSION_NEWER",
                                          detail=f"message is {version}; parsed as {SCHEMA_VERSION}", impact="low"))
    data["schema_version"] = data.get("schema_version") if pv[0] == CURRENT_MAJOR else SCHEMA_VERSION
    if res.version_inferred:
        data["schema_version"] = SCHEMA_VERSION
    unknown = sorted(k for k in data if k not in ENVELOPE_FIELDS)
    if unknown:
        extras = dict(data.get("extras") or {})
        for k in unknown:
            extras[k] = data.pop(k)
        data["extras"] = extras
        res.limitations.append(Limitation(code="UNKNOWN_FIELDS",
                                          detail=f"unknown envelope fields kept in extras: {', '.join(unknown)[:200]}",
                                          impact="none"))
    missing = [k for k in ("message_id", "message_type", "incident_id", "sender", "recipient", "payload")
               if k not in data]
    if missing:
        res.error_code, res.error_detail, res.error_field = "MISSING_FIELD", f"missing {missing[0]}", missing[0]
        return res
    try:
        res.message = Message.model_validate(data)
    except ValidationError as exc:
        first = exc.errors()[0]
        loc = ".".join(str(x) for x in first.get("loc", ()))
        res.error_code = "BAD_TYPE" if first.get("type", "").endswith("type") else "MALFORMED"
        res.error_detail = f"{loc}: {first.get('msg', '')}"[:300]
        res.error_field = loc or None
        return res
    except (ValueError, TypeError) as exc:  # pragma: no cover - defensive
        res.error_code, res.error_detail = "MALFORMED", str(exc)[:300]
        return res
    return res
