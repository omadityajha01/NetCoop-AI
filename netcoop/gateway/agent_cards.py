"""A2A Agent Card validation and skill -> capability mapping.

Shapes follow the A2A AgentCard (name, description, url, version, protocolVersion, capabilities,
defaultInputModes, defaultOutputModes, skills[id,name,description,tags]). Unknown fields are tolerated.
"""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class AgentSkill(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    tags: list[str] = Field(default_factory=list)


class AgentCard(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    url: str = Field(min_length=1, max_length=300)
    version: str = Field(min_length=1, max_length=40)
    protocolVersion: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)
    defaultInputModes: list[str] = Field(default_factory=list)
    defaultOutputModes: list[str] = Field(default_factory=list)
    skills: list[AgentSkill] = Field(min_length=1)


def parse_card(raw: bytes) -> tuple[AgentCard | None, str | None]:
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None, "agent card is not valid UTF-8 JSON"
    try:
        card = AgentCard.model_validate(data)
    except ValidationError as exc:
        e = exc.errors()[0]
        return None, f"invalid agent card: {'.'.join(str(x) for x in e['loc'])}: {e['msg']}"
    if "application/json" not in card.defaultInputModes and "data" not in card.defaultInputModes:
        return None, "agent card does not accept application/json data parts"
    return card, None


def same_origin(a: str, b: str) -> bool:
    pa, pb = urlparse(a), urlparse(b)
    return (pa.scheme, pa.hostname, pa.port) == (pb.scheme, pb.hostname, pb.port)


def map_capabilities(card: AgentCard, skill_map: dict[str, Any]) -> list[str]:
    caps: list[str] = []
    for s in card.skills:
        for c in skill_map.get(s.id, ()):
            if c not in caps:
                caps.append(c)
    return caps
