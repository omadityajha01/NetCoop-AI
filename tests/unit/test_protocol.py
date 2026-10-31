"""NMP envelope, versioning (MINOR tolerance, MAJOR upcast, shape detection), schema export."""

from __future__ import annotations

import uuid

from netcoop.docs import export_schemas
from netcoop.protocol.envelope import Message, make_message
from netcoop.protocol.versions import parse_message

WIN = {"start": "2026-10-31T09:30:00Z", "end": "2026-10-31T10:00:00Z"}


def env(**over):
    base = {"schema_version": "1.0", "message_id": str(uuid.uuid4()), "message_type": "task_request",
            "incident_id": "INC-0001", "sender": "orchestrator", "recipient": "performance_agent",
            "payload": {"task": "analyze", "window": WIN}}
    base.update(over)
    return base


def test_valid_message_roundtrip():
    pr = parse_message(env())
    assert pr.message is not None and pr.message.payload["task"] == "analyze"


def test_minor_bump_unknown_fields_to_extras():
    pr = parse_message(env(schema_version="1.4", future_field={"x": 1}))
    assert pr.message is not None
    assert pr.message.extras == {"future_field": {"x": 1}}
    assert {lim.code for lim in pr.limitations} >= {"MINOR_VERSION_NEWER", "UNKNOWN_FIELDS"}


def test_major_without_upcaster_is_unsupported():
    pr = parse_message(env(schema_version="2.0"))
    assert pr.message is None and pr.error_code == "SCHEMA_VERSION_UNSUPPORTED"


def test_missing_version_detected_by_shape():
    e = env()
    del e["schema_version"]
    pr = parse_message(e)
    assert pr.message is not None and pr.version_inferred
    pr = parse_message({"from": "wifi-probe", "inc": "INC-0001", "obs": []})
    assert pr.message is not None and pr.source_version == "0.9"
    pr = parse_message({"hello": "world"})
    assert pr.error_code == "MISSING_FIELD"


def test_upcast_0_9_message():
    pr = parse_message({"ver": "0.9", "inc": "INC-0001", "from": "wifi-probe", "q": "evidence",
                        "obs": [{"ap": "ap-h3", "signal": -78, "ts": 1793440000}], "na": [{"ap": "ap-h3", "sig": "retx"}]})
    m = pr.message
    assert m.message_type == "evidence_response" and m.schema_version == "1.0"
    assert m.payload["observations"][0]["timestamp"].endswith("Z")
    assert m.payload["observations"][0]["units"] == {"signal": "dbm"}
    assert any(t.step == "version" for t in pr.transforms)


def test_bad_payload_is_rejected_with_code():
    pr = parse_message(env(payload={"task": "analyze", "window": "yesterday"}))
    assert pr.message is None and pr.error_code in ("BAD_TYPE", "MALFORMED")
    pr = parse_message(env(incident_id="../../etc/passwd"))
    assert pr.message is None
    pr = parse_message("not a dict")
    assert pr.error_code == "MALFORMED"


def test_message_ids_are_deterministic_uuid4():
    a = make_message("error", sender="orchestrator", recipient="orchestrator", incident_id="INC-0001",
                     payload={"code": "TIMEOUT", "detail": "x"})
    b = make_message("error", sender="orchestrator", recipient="orchestrator", incident_id="INC-0001",
                     payload={"code": "TIMEOUT", "detail": "x"})
    assert a.message_id == b.message_id and uuid.UUID(a.message_id).version == 4


def test_schema_export(tmp_path, monkeypatch):
    import netcoop.docs as docs
    monkeypatch.setattr(docs, "SCHEMA_DIR", tmp_path)
    paths = export_schemas()
    assert any(p.name == "envelope.schema.json" for p in paths)
    assert Message.model_json_schema()["properties"]["message_type"]
