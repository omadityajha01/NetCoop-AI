"""T5: interoperability check with the OFFICIAL a2a-sdk client (optional; skipped if a2a-sdk is not installed).

    pip install -e .[a2a]   then   pytest tests/a2a_sdk -m a2a_sdk

The SDK fetches the Node wireless_agent's card and sends one task_request. The reply must come back as an A2A
agent Message with a data part that our parser accepts (dialect 0.9 -> NMP via the registered upcaster).
"""

from __future__ import annotations

import asyncio
import uuid

import pytest

a2a_client = pytest.importorskip("a2a.client")
a2a_types = pytest.importorskip("a2a.types")
httpx = pytest.importorskip("httpx")
from google.protobuf import json_format, struct_pb2  # noqa: E402

from netcoop.protocol.envelope import SCHEMA_VERSION  # noqa: E402
from netcoop.protocol.versions import parse_message  # noqa: E402

pytestmark = pytest.mark.a2a_sdk


async def _roundtrip(url: str) -> tuple[object, list]:
    env = {"schema_version": SCHEMA_VERSION, "message_id": str(uuid.uuid4()), "message_type": "task_request",
           "incident_id": "INC-SDK00001", "sender": "orchestrator", "recipient": "wireless_agent",
           "payload": {"task": "analyze", "window": {"start": "2026-10-29T14:30:00Z", "end": "2026-10-29T15:00:00Z"},
                       "round": 0, "params": {}}}
    value = struct_pb2.Value()
    json_format.ParseDict(env, value)
    msg = a2a_types.Message(message_id=env["message_id"], role=a2a_types.Role.Value("ROLE_USER"),
                            parts=[a2a_types.Part(data=value)])
    async with httpx.AsyncClient() as h:
        card = await a2a_client.A2ACardResolver(h, url).get_agent_card()
        client = await a2a_client.create_client(card, a2a_client.ClientConfig(streaming=False, httpx_client=h))
        events = [ev async for ev in client.send_message(a2a_types.SendMessageRequest(message=msg))]
    return card, events


def test_official_sdk_client_talks_to_node_agent(wireless_agent):
    card, events = asyncio.run(_roundtrip(wireless_agent))
    assert card.name == "wifi-probe"
    assert events, "no response event"
    reply = events[0].message
    assert reply.role == a2a_types.Role.Value("ROLE_AGENT")
    data = json_format.MessageToDict(reply.parts[0].data)
    assert data["ver"] == "0.9"  # the agent keeps its own dialect
    pr = parse_message(data)
    assert pr.message is not None and pr.message.message_type == "finding_report"
    assert pr.message.payload["observations"], "Wi-Fi observations expected for the weak_wifi window"
