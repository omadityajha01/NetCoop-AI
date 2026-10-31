"""Field-name aliasing from metrics.yaml (step 3)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

# Keys that identify the entity a record is about -> entity type (None = infer from topology)
ENTITY_KEYS: dict[str, str | None] = {
    "device_id": "device", "device": "device", "hostname": "device", "host": "device", "switch": "device",
    "router": "device", "node": "device", "device_name": "device",
    "link_id": "link", "link": "link", "interface_link": "link",
    "ap_id": "ap", "ap": "ap", "access_point": "ap", "ap_name": "ap",
    "service": "service", "service_id": "service", "service_name": "service",
    "entity_id": None, "target": None,
}
TIME_KEYS = ("timestamp", "ts", "time", "@timestamp", "collected_at", "event_time", "datetime")
META_KEYS = {"source", "units", "unit", "metric", "value", "entity", "entity_type", "metrics", "schema_version",
             "ver", "sample_id", "record_id"}
# Generator fields that are labels, not measurements (kept in extras, never evidence: G7)
LABEL_FIELDS = {"status": "generator health label (Healthy/Warning/Critical) is not a measurement"}


@dataclass(frozen=True)
class AliasHit:
    metric: str
    unit_implied: bool


def build_alias_index(metrics: Mapping[str, Any]) -> dict[str, AliasHit]:
    idx: dict[str, AliasHit] = {}
    for name, spec in metrics.items():
        idx[name.lower()] = AliasHit(name, True)
        for a in spec.get("aliases", ()):
            idx[str(a).lower()] = AliasHit(name, True)
        for a in spec.get("ambiguous_aliases", ()):
            idx[str(a).lower()] = AliasHit(name, False)
    return idx


def resolve_field(name: str, idx: Mapping[str, AliasHit]) -> AliasHit | None:
    return idx.get(name.strip().lower())
