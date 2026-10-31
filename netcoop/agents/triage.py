"""triage_agent: the LLM-backed agent (M1). Reads the free-text complaint and publishes an NMP `hint`.

Guardrails (CLAUDE.md D1/D9, §10, §11):
* advisory only: a hint can ADD a hypothesis for the analysis agents to test (PI5); it never sets cause,
  confidence, status or actions, and it never skips an agent;
* the complaint is the only untrusted text it sees, sanitized and wrapped (PI1); its output is allowlisted to the
  fault enum (PI4); the rationale is validated or replaced by a deterministic sentence;
* its only tool is `llm` (agents.yaml); with NETCOOP_LLM=off it is never tasked and sends nothing.
"""

from __future__ import annotations

from typing import Any

from netcoop.agents.base import ReadOnlyContext
from netcoop.protocol.envelope import Message, error_message, make_message


class TriageAgent:
    agent_id = "triage_agent"
    capabilities = ["triage:complaint", "hint"]

    def __init__(self, cfg: Any = None):
        pass

    def handle(self, msg: Message, ctx: ReadOnlyContext) -> list[Message]:
        if msg.message_type != "task_request" or msg.payload.get("task") != "triage":
            return [error_message(sender=self.agent_id, recipient=msg.sender, incident_id=msg.incident_id,
                                  code="MALFORMED", detail="triage_agent handles task_request triage",
                                  offending_message_id=msg.message_id)]
        complaint = str(msg.payload.get("params", {}).get("complaint", ""))[:1000]
        result = ctx.tool("llm").triage(complaint)
        if result.label is None or result.label not in ctx.config.signatures:
            return []  # nothing to add: off, unknown, or an invalid label
        return [make_message("hint", sender=self.agent_id, recipient="orchestrator", incident_id=msg.incident_id,
                             in_reply_to=msg.message_id,
                             payload={"fault_type": result.label, "rationale": result.rationale[:200],
                                      "model": result.model[:60]})]
