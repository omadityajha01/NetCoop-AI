"""infrastructure_agent: device status, CPU, memory, interface/CRC errors, link flaps, egress queue drops."""

from __future__ import annotations

from netcoop.agents.base import AnalysisAgent


class InfrastructureAgent(AnalysisAgent):
    agent_id = "infrastructure_agent"
