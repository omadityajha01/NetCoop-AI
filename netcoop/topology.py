"""Topology: entity registry, alias resolution and graph helpers. Never invents entities."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

ENTITY_TYPES = ("device", "link", "ap", "service")
_SEP = re.compile(r"[\s_\-.:/]+")


def alias_key(raw: str) -> str:
    """Case- and separator-insensitive key ("hostel-core-sw-01" == "HOSTEL_CORE_SW_01").

    IPv4 addresses keep their dots so 10.0.1.1 and 10.0.11 never collide.
    """
    s = raw.strip()
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", s):
        return "IP:" + s
    return _SEP.sub("", s.upper())


@dataclass(frozen=True)
class Entity:
    id: str
    type: str
    segment: str | None = None
    role: str | None = None
    upstream: str | None = None
    uplink: str | None = None
    kind: str | None = None
    attached_to: str | None = None
    ip: str | None = None
    endpoints: tuple[str, ...] = ()
    placed: bool = True  # False = seen in telemetry but absent from topology (no links, no upstream, no localization)


@dataclass
class Topology:
    entities: dict[str, Entity] = field(default_factory=dict)
    aliases: dict[str, str] = field(default_factory=dict)
    segments: tuple[str, ...] = ()
    raw: dict[str, Any] = field(default_factory=dict)

    # ---------- construction ----------
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Topology:
        topo = cls(segments=tuple(data.get("segments", ())), raw=copy.deepcopy(data))
        for did, spec in (data.get("devices") or {}).items():
            topo._add(Entity(id=did, type="device", segment=spec.get("segment"), role=spec.get("role"),
                             upstream=spec.get("upstream"), uplink=spec.get("uplink"), ip=spec.get("ip")),
                      spec.get("aliases", []))
        for aid, spec in (data.get("aps") or {}).items():
            topo._add(Entity(id=aid, type="ap", segment=spec.get("segment"), role="access_point",
                             upstream=spec.get("upstream"), uplink=spec.get("uplink"), ip=spec.get("ip")),
                      spec.get("aliases", []))
        for sid, spec in (data.get("services") or {}).items():
            topo._add(Entity(id=sid, type="service", segment=spec.get("segment"), role="service",
                             kind=spec.get("kind"), attached_to=spec.get("attached_to"), ip=spec.get("ip")),
                      spec.get("aliases", []))
        # derive links from uplink declarations
        for ent in list(topo.entities.values()):
            if ent.uplink and ent.upstream:
                topo._add(Entity(id=ent.uplink, type="link", segment=ent.segment, role="link",
                                 endpoints=(ent.id, ent.upstream)),
                          [f"{ent.id}-{ent.upstream}", f"{ent.upstream}-{ent.id}"])
        for lid, extra in (data.get("link_aliases") or {}).items():
            if lid not in topo.entities:
                raise ValueError(f"topology: link_aliases references unknown link {lid}")
            for a in extra:
                topo.aliases[alias_key(a)] = lid
        topo._check()
        return topo

    def _add(self, ent: Entity, aliases: list[str]) -> None:
        if ent.id in self.entities:
            raise ValueError(f"topology: duplicate id {ent.id}")
        self.entities[ent.id] = ent
        for a in [ent.id, *aliases, *([ent.ip] if ent.ip else [])]:
            k = alias_key(str(a))
            if k in self.aliases and self.aliases[k] != ent.id:
                raise ValueError(f"topology: alias {a} is ambiguous")
            self.aliases[k] = ent.id

    def _check(self) -> None:
        for e in self.entities.values():
            for ref in (e.upstream, e.attached_to, *e.endpoints):
                if ref and ref not in self.entities:
                    raise ValueError(f"topology: {e.id} references unknown {ref}")

    # ---------- per-run extensions ----------
    def with_unplaced(self, ids: dict[str, str]) -> Topology:
        """Copy with devices seen in telemetry but absent from topology (placed=False). Never adds links."""
        if not ids:
            return self
        t = Topology(entities=dict(self.entities), aliases=dict(self.aliases), segments=self.segments, raw=self.raw)
        for eid, etype in sorted(ids.items()):
            if eid not in t.entities:
                t.entities[eid] = Entity(id=eid, type=etype, placed=False)
                t.aliases.setdefault(alias_key(eid), eid)
        return t

    def merge_input(self, data: Any) -> tuple[Topology, list[str], list[str], str | None]:
        """Merge an input-supplied topology additively over this one.

        Returns (topology, added_ids, conflicts, error). New entities and aliases are added; an attribute that
        conflicts with config keeps the CONFIG value (roles drive policy, so incident data cannot override them).
        Any validation error rejects the whole input topology (config unchanged)."""
        if not isinstance(data, dict):
            return self, [], [], "input topology is not an object"
        merged = copy.deepcopy(self.raw)
        added: list[str] = []
        conflicts: list[str] = []
        id_re = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")
        for section in ("devices", "aps", "services"):
            sec = data.get(section)
            if sec is None:
                continue
            if not isinstance(sec, dict):
                return self, [], [], f"input topology `{section}` is not an object"
            base = merged.setdefault(section, {}) or {}
            merged[section] = base
            for eid, spec in sec.items():
                if not isinstance(eid, str) or not id_re.match(eid) or not isinstance(spec, dict):
                    return self, [], [], f"input topology entry {str(eid)[:40]!r} is invalid"
                clean = {k: v for k, v in spec.items() if k in ("role", "segment", "upstream", "uplink", "ip", "kind",
                                                                "attached_to", "aliases")}
                for k, v in clean.items():
                    if k == "aliases":
                        if not isinstance(v, list) or not all(isinstance(a, str) and id_re.match(a) for a in v):
                            return self, [], [], f"input topology aliases for {eid} are invalid"
                    elif not isinstance(v, str) or not id_re.match(v):
                        return self, [], [], f"input topology {eid}.{k} is invalid"
                existing = self.get(eid)
                if eid in base or existing is not None:
                    cur = base.setdefault(eid, {})
                    for k, v in clean.items():
                        if k == "aliases":
                            cur["aliases"] = sorted(set(cur.get("aliases", [])) | set(v))
                        elif k in cur and cur[k] != v:
                            conflicts.append(f"{eid}.{k}: config {cur[k]!r} kept, input {v!r} ignored")
                        elif k not in cur:
                            cur[k] = v
                else:
                    base[eid] = clean
                    added.append(eid)
        try:
            topo = Topology.from_dict(merged)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            return self, [], [], f"input topology rejected: {str(exc)[:160]}"
        return topo, sorted(added), conflicts, None

    # ---------- lookups ----------
    def resolve(self, raw: str) -> str | None:
        return self.aliases.get(alias_key(raw))

    def get(self, eid: str) -> Entity | None:
        return self.entities.get(eid)

    def exists(self, eid: str) -> bool:
        return eid in self.entities

    def type_of(self, eid: str) -> str | None:
        e = self.entities.get(eid)
        return e.type if e else None

    def ids_of_type(self, etype: str) -> list[str]:
        return sorted(e.id for e in self.entities.values() if e.type == etype)

    def links_of(self, eid: str) -> list[str]:
        return sorted(e.id for e in self.entities.values() if e.type == "link" and eid in e.endpoints)

    def related(self, eid: str) -> set[str]:
        """Entities whose signals count as evidence for a hypothesis attached to `eid`."""
        e = self.entities.get(eid)
        if e is None:
            return set()
        out = {eid}
        if e.type == "link":
            out.update(e.endpoints)
        elif e.type == "device":
            out.update(self.links_of(eid))
        elif e.type == "ap":
            if e.uplink:
                out.add(e.uplink)
        elif e.type == "service":
            if e.attached_to:
                out.add(e.attached_to)
        return out

    def related_ordered(self, eid: str) -> list[str]:
        """`related` in localization order: entity, then link endpoints (downstream first) / uplink, then the rest."""
        e = self.entities.get(eid)
        if e is None:
            return []
        first = [eid]
        if e.type == "link":
            first += list(e.endpoints)
        elif e.uplink:
            first.append(e.uplink)
        elif e.attached_to:
            first.append(e.attached_to)
        return first + sorted(self.related(eid) - set(first))

    def devices_of(self, eid: str) -> list[str]:
        e = self.entities.get(eid)
        if e is None:
            return []
        if e.type == "link":
            return list(e.endpoints)
        return [eid]

    def tree_node(self, eid: str) -> str | None:
        """Map an entity onto the device/AP tree (a link maps to its downstream endpoint)."""
        e = self.entities.get(eid)
        if e is None:
            return None
        if e.type == "link":
            return e.endpoints[0]
        if e.type == "service":
            return e.attached_to
        return eid

    def ancestors(self, eid: str) -> list[str]:
        chain: list[str] = []
        cur = self.tree_node(eid)
        guard = 0
        while cur and guard < 64:
            chain.append(cur)
            cur = self.entities[cur].upstream
            guard += 1
        return chain

    def nearest_common_upstream(self, ids: list[str]) -> str | None:
        chains = [self.ancestors(i) for i in sorted(set(ids)) if self.exists(i)]
        chains = [c for c in chains if c]
        if not chains:
            return None
        common = set(chains[0])
        for c in chains[1:]:
            common &= set(c)
        for node in chains[0]:
            if node in common:
                return node
        return None

    def segment_of(self, eid: str) -> str | None:
        e = self.entities.get(eid)
        return e.segment if e else None

    def role_of(self, eid: str) -> str | None:
        e = self.entities.get(eid)
        return e.role if e else None
