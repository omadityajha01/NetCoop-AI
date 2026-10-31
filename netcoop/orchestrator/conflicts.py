"""Conflict detection and resolution (CLAUDE.md §7.2). Pure functions over findings."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from netcoop.config import Config
from netcoop.protocol.findings import Finding


@dataclass
class ConflictSet:
    conflicts: list[dict] = field(default_factory=list)
    losers: set[str] = field(default_factory=set)
    stale: set[str] = field(default_factory=set)
    refetch: list[tuple[str, str]] = field(default_factory=list)  # (metric, entity_id)
    unresolved_c2: bool = False


def _overlap(a: Finding, b: Finding) -> bool:
    return a.window.start <= b.window.end and b.window.start <= a.window.end


def _rank_key(cfg: Config, f: Finding, agent_of: dict[str, str]) -> tuple:
    prio = list(cfg.agents.get("source_priority", ()))

    def p(name: str | None) -> int:
        return prio.index(name) if name in prio else len(prio)

    return (-f.window.end.timestamp(), -f.sample_count, p(f.source), p(agent_of.get(f.finding_id)), f.finding_id)


def detect_c1(cfg: Config, findings: list[Finding], agent_of: dict[str, str], cs: ConflictSet) -> None:
    thr = float(cfg.scoring["conflicts"]["c1_relative_diff"])
    groups: dict[tuple[str, str], list[Finding]] = defaultdict(list)
    for f in findings:
        groups[(f.metric, f.entity.id)].append(f)
    n = 0
    for (metric, eid), fs in sorted(groups.items()):
        srcs = {(f.source, agent_of.get(f.finding_id)) for f in fs}
        if len(srcs) < 2:
            continue
        fs = sorted(fs, key=lambda f: _rank_key(cfg, f, agent_of))
        winner = fs[0]
        losers = []
        for other in fs[1:]:
            if (other.source, agent_of.get(other.finding_id)) == (winner.source, agent_of.get(winner.finding_id)):
                continue
            if not _overlap(winner, other):
                continue
            denom = max(abs(winner.value), abs(other.value), 1e-9)
            if abs(winner.value - other.value) / denom > thr:
                losers.append(other)
        if not losers:
            continue
        n += 1
        cs.losers.update(f.finding_id for f in losers)
        cs.conflicts.append({
            "conflict_id": f"C1-{n}",
            "type": "C1",
            "detail": (f"{metric}@{eid}: {winner.value:g} ({winner.source}) vs "
                       + ", ".join(f"{f.value:g} ({f.source})" for f in losers)),
            "finding_ids": sorted([winner.finding_id] + [f.finding_id for f in losers]),
            "resolution": "kept fresher value (then higher sample_count, then source_priority)",
            "resolved": True,
            "winner_finding_id": winner.finding_id,
            "loser_finding_ids": sorted(f.finding_id for f in losers),
        })


def detect_c2(cfg: Config, findings: list[Finding], quarantined: list[dict], refetched: set[tuple[str, str]],
              cs: ConflictSet) -> None:
    n = 0
    by_entity: dict[str, list[Finding]] = defaultdict(list)
    for f in findings:
        by_entity[f.entity.id].append(f)
    for f in sorted(findings, key=lambda x: x.finding_id):
        if f.metric != "device_up" or f.severity not in ("high", "critical"):
            continue
        newer = [o for o in by_entity[f.entity.id] if o.metric != "device_up" and o.window.end > f.window.end]
        if not newer:
            continue
        n += 1
        ups = sorted([o for o in by_entity[f.entity.id] if o.metric == "device_up" and o.finding_id != f.finding_id
                      and o.window.end > f.window.end], key=lambda o: o.finding_id)
        resolved = bool(ups) and ups[-1].severity == "normal"
        cs.stale.add(f.finding_id)
        if resolved:
            cs.losers.add(f.finding_id)
        key = ("device_up", f.entity.id)
        if key not in refetched:
            cs.refetch.append(key)
        elif not resolved:
            cs.unresolved_c2 = True
        cs.conflicts.append({
            "conflict_id": f"C2-{n}",
            "type": "C2",
            "detail": f"{f.entity.id} reported down ({f.finding_id}) but has newer telemetry ({newer[0].finding_id})",
            "finding_ids": sorted([f.finding_id] + [o.finding_id for o in newer][:5]),
            "resolution": ("re-fetch showed device up; stale status discarded" if resolved
                           else "status source marked stale (quality 0.5); re-fetch requested" if key not in refetched
                           else "unresolved after re-fetch; confidence capped"),
            "resolved": resolved,
            "stale_finding_ids": [f.finding_id],
        })
    unknown_links = [q for q in quarantined if q.get("code") == "UNKNOWN_ENTITY" and q.get("field") in ("link_id", "link")]
    if unknown_links:
        n += 1
        cs.conflicts.append({
            "conflict_id": f"C2-{n}",
            "type": "C2",
            "detail": f"{len(unknown_links)} record(s) carry metrics for links absent from topology "
                      f"(e.g. {unknown_links[0]['source_ref']})",
            "finding_ids": [],
            "resolution": "records quarantined; topology is never invented",
            "resolved": True,
        })
