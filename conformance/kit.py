"""NetCoop conformance kit: checks any agent URL speaks NMP (any supported dialect) over A2A.

    python -m conformance.kit http://127.0.0.1:8765      (or: make conformance AGENT_URL=...)
"""

from __future__ import annotations

import json
import sys
import time
import uuid
from dataclasses import dataclass
from typing import Any

from netcoop.config import load_config
from netcoop.gateway.a2a_gateway import a2a_request, extract_data_part
from netcoop.gateway.agent_cards import parse_card
from netcoop.gateway.transport import HttpTransport, TransportError
from netcoop.protocol.envelope import SCHEMA_VERSION
from netcoop.protocol.versions import parse_message

INCIDENT = "INC-CONF0001"
WIDE = {"start": "2000-01-01T00:00:00Z", "end": "2100-01-01T00:00:00Z"}


@dataclass
class Check:
    name: str
    passed: bool
    detail: str
    ms: int


def _envelope(message_type: str, payload: dict[str, Any], **extra: Any) -> dict[str, Any]:
    env = {"schema_version": SCHEMA_VERSION, "message_id": str(uuid.uuid4()), "message_type": message_type,
           "incident_id": INCIDENT, "sender": "orchestrator", "recipient": "agent", "in_reply_to": None,
           "status": "completed", "payload": payload, "limitations": []}
    env.update(extra)
    return env


class Kit:
    def __init__(self, url: str, timeout_s: float | None = None):
        self.url = url.rstrip("/")
        self.cfg = load_config()
        spec = next((s for s in self.cfg.agents.get("external", ()) if s["base_url"].rstrip("/") == self.url), None)
        self.timeout = float(timeout_s or (spec or {}).get("timeout_s", 10))
        self.max_bytes = int((spec or {}).get("max_message_bytes", 262144))
        self.skill_map = dict((spec or {}).get("skill_map", {}))
        self.t = HttpTransport()
        self.rpc_url = self.url + "/"

    def _post(self, body: Any) -> tuple[bytes, int]:
        t0 = time.monotonic()
        raw = self.t.post(self.rpc_url, json.dumps(body).encode(), self.timeout, self.max_bytes, "conformance")
        return raw, int((time.monotonic() - t0) * 1000)

    def _send(self, env: dict[str, Any]) -> tuple[dict[str, Any], int]:
        raw, ms = self._post(a2a_request(env))
        return extract_data_part(raw), ms

    def run(self) -> list[Check]:
        checks: list[Check] = []

        def check(name: str, fn: Any) -> None:
            t0 = time.monotonic()
            try:
                ok, detail = fn()
            except (TransportError, Exception) as exc:  # noqa: BLE001
                ok, detail = False, f"{type(exc).__name__}: {str(exc)[:160]}"
            checks.append(Check(name, ok, detail, int((time.monotonic() - t0) * 1000)))

        def card() -> tuple[bool, str]:
            raw = self.t.get(self.url + "/.well-known/agent-card.json", self.timeout, self.max_bytes, "card")
            c, err = parse_card(raw)
            if c is None:
                return False, err or "invalid"
            self.rpc_url = c.url
            skills = [s.id for s in c.skills]
            mapped = [s for s in skills if s in self.skill_map] if self.skill_map else skills
            return bool(mapped), f"{c.name} v{c.version}; skills {skills}"

        def task() -> tuple[bool, str]:
            env = _envelope("task_request", {"task": "analyze", "window": WIDE, "round": 0, "params": {}})
            data, ms = self._send(env)
            pr = parse_message(data)
            if pr.message is None:
                return False, f"invalid NMP: {pr.error_code} {pr.error_detail}"
            ok = pr.message.message_type in ("finding_report", "coverage_manifest") and ms <= self.timeout * 1000
            ok = ok and pr.message.in_reply_to in (None, env["message_id"])
            return ok, f"{pr.message.message_type} from dialect {pr.source_version} in {ms} ms"

        def evidence() -> tuple[bool, str]:
            env = _envelope("evidence_request", {"round": 1, "reason": "conformance", "prediction_ids": [],
                                                 "requests": [{"metric": "rssi_dbm", "entity": {"type": "ap", "id": "AP_H3"},
                                                               "window": WIDE}]})
            data, ms = self._send(env)
            pr = parse_message(data)
            if pr.message is None:
                return False, f"invalid NMP: {pr.error_code} {pr.error_detail}"
            return pr.message.message_type == "evidence_response", f"{pr.message.message_type} in {ms} ms"

        def malformed() -> tuple[bool, str]:
            body = {"jsonrpc": "2.0", "id": "m1", "method": "message/send",
                    "params": {"message": {"kind": "message", "role": "user", "messageId": str(uuid.uuid4()),
                                           "parts": [{"kind": "data", "data": {"garbage": True}}]}}}
            raw, _ = self._post(body)
            data = extract_data_part(raw)
            pr = parse_message(data)
            got = pr.message.message_type if pr.message else f"unparseable ({pr.error_code})"
            return bool(pr.message and pr.message.message_type == "error"), f"reply: {got}"

        def idempotent() -> tuple[bool, str]:
            env = _envelope("task_request", {"task": "analyze", "window": WIDE, "round": 0, "params": {}})
            a, _ = self._send(env)
            b, _ = self._send(env)
            return a == b, "identical replies" if a == b else "replies differ for duplicate message_id"

        def version() -> tuple[bool, str]:
            env = _envelope("task_request", {"task": "analyze", "window": WIDE, "round": 0, "params": {}})
            data, _ = self._send(env)
            v = data.get("schema_version", data.get("ver"))
            return isinstance(v, str), f"declares {v!r}"

        def unknown_fields() -> tuple[bool, str]:
            env = _envelope("task_request", {"task": "analyze", "window": WIDE, "round": 0, "params": {},
                                             "x_future_payload_field": 1}, x_future_envelope_field={"a": 1})
            env["schema_version"] = "1.7"  # newer MINOR
            data, _ = self._send(env)
            pr = parse_message(data)
            ok = pr.message is not None and pr.message.message_type != "error"
            return ok, "accepted newer MINOR + unknown fields" if ok else f"rejected: {data.get('err') or pr.error_detail}"

        check("serves a valid agent card", card)
        check("answers task_request with valid NMP", task)
        check("answers evidence_request with valid NMP", evidence)
        check("returns error on malformed input", malformed)
        check("idempotent on duplicate message_id", idempotent)
        check("declares schema_version", version)
        check("tolerates unknown fields / newer MINOR", unknown_fields)
        return checks


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: python -m conformance.kit <AGENT_URL>")
        return 2
    checks = Kit(argv[0]).run()
    width = max(len(c.name) for c in checks)
    for c in checks:
        print(f"  {'PASS' if c.passed else 'FAIL'}  {c.name.ljust(width)}  {c.ms:>5} ms  {c.detail}")
    passed = sum(c.passed for c in checks)
    print(f"\nconformance: {passed}/{len(checks)} checks passed for {argv[0]}")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    raise SystemExit(main())
