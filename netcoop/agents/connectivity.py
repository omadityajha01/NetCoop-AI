"""connectivity_agent: topology, scope of impact, nearest common upstream node, DNS/DHCP service health."""

from __future__ import annotations

from netcoop.agents.base import AnalysisAgent, ReadOnlyContext
from netcoop.protocol.envelope import Message, make_message
from netcoop.topology import Topology


class ConnectivityAgent(AnalysisAgent):
    agent_id = "connectivity_agent"

    def other_task(self, msg: Message, ctx: ReadOnlyContext) -> list[Message]:
        if msg.payload.get("task") != "scope":
            return super().other_task(msg, ctx)
        topo: Topology = ctx.tool("topology")
        raw = msg.payload.get("params", {}).get("entities", [])
        entities = sorted({e for e in raw if isinstance(e, str) and topo.exists(e)})
        devices = sorted({d for e in entities for d in topo.devices_of(e) if topo.type_of(d) in ("device", "ap")})
        ncu = topo.nearest_common_upstream(entities) if entities else None
        segments = sorted({s for e in entities if (s := topo.segment_of(e))})
        scope = {"affected_entities": entities, "affected_devices": devices, "nearest_common_upstream": ncu,
                 "segments": segments}
        return [make_message("finding_report", sender=self.agent_id, recipient="orchestrator",
                             incident_id=msg.incident_id, in_reply_to=msg.message_id,
                             status="completed" if entities else "insufficient_data",
                             payload={"round": 0, "findings": [], "scope": scope})]
