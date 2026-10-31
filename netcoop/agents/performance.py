"""performance_agent: latency, jitter, packet loss, throughput, link utilization."""

from __future__ import annotations

from netcoop.agents.base import AnalysisAgent


class PerformanceAgent(AnalysisAgent):
    agent_id = "performance_agent"
