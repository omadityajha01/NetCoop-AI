"""A2A gateway: discovery from the allowlist, NMP-over-A2A transport, untrusted-output handling.

Transport: A2A (borrowed). Semantics: NMP + metric registry (designed).
The NMP envelope travels inside an A2A Message data part (JSON-RPC 2.0 `message/send`).
External output is untrusted: size cap, timeout, rate limit, same normalizer + validation, no tools,
and its strings never reach an LLM prompt.
"""

from __future__ import annotations

import json
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from netcoop.agents.base import ROUND_ID_STRIDE, ReadOnlyContext, findings_for
from netcoop.config import Config
from netcoop.gateway.agent_cards import AgentCard, map_capabilities, parse_card, same_origin
from netcoop.gateway.transport import HttpTransport, Transport, TransportError
from netcoop.normalize.pipeline import NormalizationError, normalize_records
from netcoop.protocol.envelope import Message, make_message
from netcoop.protocol.findings import Finding, Limitation, SignalRef, Transform
from netcoop.protocol.versions import parse_message


class RemoteAgentError(RuntimeError):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code


class RateLimiter:
    def __init__(self, per_s: float):
        self.capacity = max(1.0, per_s)
        self.tokens = self.capacity
        self.per_s = per_s
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def take(self) -> bool:
        with self.lock:
            now = time.monotonic()
            self.tokens = min(self.capacity, self.tokens + (now - self.last) * self.per_s)
            self.last = now
            if self.tokens >= 1:
                self.tokens -= 1
                return True
            return False


def a2a_request(envelope: dict[str, Any]) -> dict[str, Any]:
    mid = envelope["message_id"]
    return {
        "jsonrpc": "2.0", "id": mid, "method": "message/send",
        "params": {"message": {"kind": "message", "role": "user", "messageId": mid,
                               "contextId": envelope["incident_id"],
                               "parts": [{"kind": "data", "data": envelope}]}},
    }


def extract_data_part(raw: bytes) -> dict[str, Any]:
    try:
        rpc = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RemoteAgentError("MALFORMED", "response is not UTF-8 JSON") from exc
    if not isinstance(rpc, dict) or rpc.get("jsonrpc") != "2.0":
        raise RemoteAgentError("MALFORMED", "not a JSON-RPC 2.0 response")
    if "error" in rpc:
        err = rpc["error"] if isinstance(rpc["error"], dict) else {}
        raise RemoteAgentError("AGENT_FAILED", f"JSON-RPC error {err.get('code')}: {str(err.get('message'))[:120]}")
    result = rpc.get("result")
    if isinstance(result, dict) and result.get("kind") == "task":  # tolerate Task results: use the status message
        result = (result.get("status") or {}).get("message") or {}
    parts = result.get("parts") if isinstance(result, dict) else None
    if not isinstance(parts, list):
        raise RemoteAgentError("MALFORMED", "A2A message has no parts")
    for p in parts:
        if isinstance(p, dict) and p.get("kind") == "data" and isinstance(p.get("data"), dict):
            return p["data"]
    raise RemoteAgentError("MALFORMED", "A2A message has no data part")


@dataclass
class RemoteAgent:
    agent_id: str
    base_url: str
    rpc_url: str
    card: AgentCard
    capabilities: list[str]
    owns: tuple[str, ...]
    timeout_s: float
    max_bytes: int
    transport: Transport
    limiter: RateLimiter
    cfg: Config
    last_transforms: list[Transform] = field(default_factory=list)

    # same signature as internal agents; called by the bus
    def handle(self, msg: Message, ctx: ReadOnlyContext) -> list[Message]:
        if not self.limiter.take():
            raise RemoteAgentError("RATE_LIMITED", "rate limit exceeded")
        body = json.dumps(a2a_request(msg.to_json_dict()), sort_keys=True).encode()
        if len(body) > self.max_bytes:
            raise RemoteAgentError("TOO_LARGE", "request exceeds size cap")
        try:
            raw = self.transport.post(self.rpc_url, body, self.timeout_s, self.max_bytes, msg.message_id)
        except TransportError as exc:
            raise RemoteAgentError(exc.code, exc.detail) from exc
        data = extract_data_part(raw)
        pr = parse_message(data)
        if pr.message is None:
            raise RemoteAgentError(pr.error_code or "MALFORMED", pr.error_detail)
        reply = pr.message
        if reply.incident_id != msg.incident_id:
            raise RemoteAgentError("MALFORMED", "reply incident_id mismatch")
        if reply.in_reply_to not in (None, msg.message_id):
            raise RemoteAgentError("MALFORMED", "reply in_reply_to does not match request")
        if reply.message_type == "error":
            raise RemoteAgentError("AGENT_FAILED", f"{reply.payload.get('code')}: {reply.payload.get('detail', '')[:120]}")
        return self._translate(msg, reply, pr.transforms, pr.limitations + list(reply.limitations), pr.source_version, ctx)

    def _translate(self, req: Message, reply: Message, transforms: list[Transform], lims: list[Limitation],
                   version: str | None, ctx: ReadOnlyContext) -> list[Message]:
        cfg = self.cfg
        payload = reply.payload
        obs_raw = payload.get("observations") or []
        if not isinstance(obs_raw, list):
            raise RemoteAgentError("BAD_TYPE", "observations must be a list")
        items = [(f"{self.agent_id}:obs[{i}]", o) for i, o in enumerate(obs_raw)]
        try:
            norm = normalize_records(items, cfg, source_default=self.agent_id, incident_time=ctx.incident_time)
        except NormalizationError as exc:
            raise RemoteAgentError(exc.code, exc.detail) from exc
        # external agents may not author findings directly: only owned metrics, recomputed with our registry
        obs = [o for o in norm.observations if o.metric in self.owns]
        foreign = len(norm.observations) - len(obs)
        vt = [Transform(step="version", field="schema_version", from_=version, to="1.0", reason="gateway upcast")] \
            if version and version != reply.schema_version and not version.startswith("1.") else []
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for o in obs:
            groups[(o.metric, o.entity_id)].append(o)
        rnd = int(req.payload.get("round", 0)) if req.message_type == "evidence_request" else 0
        n = ROUND_ID_STRIDE * rnd + 1
        findings: list[Finding] = []
        for (metric, eid), group in sorted(groups.items()):
            fs = findings_for(cfg, agent_id=self.agent_id, start_n=n, metric=metric, entity_id=eid,
                              obs=tuple(sorted(group, key=lambda o: (o.ts, o.source_ref))), window=ctx.window)
            n += len(fs)
            findings.extend(f.model_copy(update={"transforms": (vt + list(f.transforms))[:25]}) for f in fs)
        limitations = [lim for lim in lims if lim.impact != "none"]
        limitations += [lim for lim in norm.limitations if lim.impact in ("medium", "high")]
        if foreign:
            limitations.append(Limitation(code="FOREIGN_METRICS",
                                          detail=f"{foreign} observation(s) for metrics {self.agent_id} does not own were ignored",
                                          impact="low"))
        if version and not version.startswith("1."):
            limitations.append(Limitation(code="DIALECT_TRANSLATED",
                                          detail=f"{self.agent_id} speaks NMP {version}; translated to 1.0 by the gateway",
                                          impact="none"))
        if req.message_type == "task_request":
            anomalous = sorted([f for f in findings if f.anomalous], key=lambda f: f.finding_id)
            coverage = sorted({(f.metric, f.entity.type, f.entity.id) for f in findings})
            return [
                make_message("finding_report", sender=self.agent_id, recipient="orchestrator", incident_id=req.incident_id,
                             in_reply_to=req.message_id, status="completed" if findings else "insufficient_data",
                             limitations=limitations,
                             payload={"round": 0, "findings": [f.model_dump(mode="json", by_alias=True) for f in anomalous]}),
                make_message("coverage_manifest", sender=self.agent_id, recipient="orchestrator",
                             incident_id=req.incident_id, in_reply_to=req.message_id,
                             payload={"signals": [{"metric": m, "entity": {"type": t, "id": e}} for m, t, e in coverage]}),
            ]
        # evidence: exactly what was asked
        asked = [SignalRef.model_validate(r) for r in req.payload.get("requests", [])]
        asked_keys = {(s.metric, s.entity.id) for s in asked}
        answered = [f for f in findings if (f.metric, f.entity.id) in asked_keys]
        got = {(f.metric, f.entity.id) for f in answered}
        unavailable = [s.model_dump(mode="json") for s in asked if (s.metric, s.entity.id) not in got]
        return [make_message("evidence_response", sender=self.agent_id, recipient="orchestrator",
                             incident_id=req.incident_id, in_reply_to=req.message_id, limitations=limitations,
                             status="completed" if answered else "insufficient_data",
                             payload={"round": rnd, "findings": [f.model_dump(mode="json", by_alias=True) for f in answered],
                                      "unavailable": unavailable})]


@dataclass
class DiscoveryResult:
    agents: list[RemoteAgent]
    status: dict[str, str]
    details: dict[str, dict[str, Any]]


def discover(cfg: Config, transport: Transport | None = None) -> DiscoveryResult:
    """Discover external agents ONLY from the allowlist in config/agents.yaml."""
    transport = transport or HttpTransport()
    disc = cfg.agents.get("discovery", {})
    card_path = disc.get("card_path", "/.well-known/agent-card.json")
    probe_timeout = float(disc.get("probe_timeout_s", 1.5))
    agents: list[RemoteAgent] = []
    status: dict[str, str] = {}
    details: dict[str, dict[str, Any]] = {}
    for spec in cfg.agents.get("external", ()):
        aid = spec["agent_id"]
        base = str(spec["base_url"]).rstrip("/")
        max_bytes = int(spec.get("max_message_bytes", 262144))
        try:
            raw = transport.get(base + card_path, probe_timeout, max_bytes, "agent-card")
        except TransportError as exc:
            status[aid] = "unreachable"
            details[aid] = {"base_url": base, "error": exc.code}
            continue
        card, err = parse_card(raw)
        if card is None:
            status[aid] = "rejected"
            details[aid] = {"base_url": base, "error": err}
            continue
        if not same_origin(card.url, base):
            status[aid] = "rejected"
            details[aid] = {"base_url": base, "error": "card url outside allowlisted origin"}
            continue
        caps = map_capabilities(card, dict(spec.get("skill_map", {})))
        if not caps:
            status[aid] = "rejected"
            details[aid] = {"base_url": base, "error": "no card skill maps to an NMP capability"}
            continue
        owns = tuple(m for m in spec.get("owns", ()) if f"metric:{m}" in caps)
        agents.append(RemoteAgent(agent_id=aid, base_url=base, rpc_url=card.url, card=card, capabilities=caps, owns=owns,
                                  timeout_s=float(spec.get("timeout_s", 10)), max_bytes=max_bytes, transport=transport,
                                  limiter=RateLimiter(float(spec.get("rate_limit_per_s", 20))), cfg=cfg))
        status[aid] = "joined"
        details[aid] = {"base_url": base, "card_name": card.name[:60], "card_version": card.version[:20],
                        "capabilities": caps}
    return DiscoveryResult(agents=agents, status=status, details=details)
