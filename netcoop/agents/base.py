"""Agent contract, read-only context, tools and the shared finding builder.

Agents are pure: messages in, messages out. No global state, no direct calls to other agents,
no I/O except through the tools in `ctx` (granted per agent in agents.yaml).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Any, Protocol

from netcoop.config import Config
from netcoop.normalize.pipeline import Observation
from netcoop.protocol.envelope import Message, error_message, make_message
from netcoop.protocol.findings import (
    DataQuality,
    EntityRef,
    Finding,
    SignalRef,
    Transform,
    Window,
)
from netcoop.scoring.thresholds import severity

ROUND_ID_STRIDE = 10000  # finding n = round * stride + i  (unique per run without shared state)


class Agent(Protocol):
    agent_id: str
    capabilities: list[str]

    def handle(self, msg: Message, ctx: ReadOnlyContext) -> list[Message]: ...


# ---------------------------------------------------------------------------- tools

class TelemetryTool:
    """Read-only access to normalized observations."""

    def __init__(self, observations: list[Observation]):
        idx: dict[tuple[str, str], list[Observation]] = defaultdict(list)
        for o in observations:
            idx[(o.metric, o.entity_id)].append(o)
        self._idx = {k: tuple(sorted(v, key=lambda o: (o.ts, o.source, o.source_ref))) for k, v in idx.items()}

    def query(self, metric: str, entity_id: str, window: Window | None = None) -> tuple[Observation, ...]:
        obs = self._idx.get((metric, entity_id), ())
        if window is None:
            return obs
        return tuple(o for o in obs if window.start <= o.ts <= window.end)

    def cadence(self, window: Window) -> int:
        """Most samples any (metric, entity) has inside `window`: the collection cadence this input delivers."""
        return max((sum(1 for o in obs if window.start <= o.ts <= window.end) for obs in self._idx.values()), default=0)

    def entities_with(self, metric: str) -> list[str]:
        return sorted(e for (m, e) in self._idx if m == metric)

    def pairs(self) -> list[tuple[str, str]]:
        return sorted(self._idx)


class FindingsTool:
    """Read-only view of the event log (correlation/reporting)."""

    def __init__(self, log: Any):
        self._log = log

    def messages(self, *types: str) -> list[Message]:
        return [m.model_copy(deep=True) for m in self._log.by_type(*types)]

    def all(self) -> list[Message]:
        return [m.model_copy(deep=True) for m in self._log.all()]


@dataclass(frozen=True)
class ReadOnlyContext:
    incident_id: str
    incident_time: datetime
    window: Window
    config: Config
    tools: Mapping[str, Any]
    round: int = 0

    def tool(self, name: str) -> Any:
        if name not in self.tools:
            raise PermissionError(f"tool {name!r} not granted to this agent")
        return self.tools[name]


def make_context(cfg: Config, agent_id: str, available: Mapping[str, Any], **kw: Any) -> ReadOnlyContext:
    spec = cfg.agents["internal"].get(agent_id, {})
    granted = {t: available[t] for t in spec.get("tools", ()) if t in available}
    return ReadOnlyContext(config=cfg, tools=MappingProxyType(granted), **kw)


# ---------------------------------------------------------------------------- finding builder

def aggregate(kind: str, values: list[float], window_s: float) -> float:
    if not values:
        raise ValueError("no values")
    if kind == "p95":
        s = sorted(values)
        return s[max(0, math.ceil(0.95 * len(s)) - 1)]
    if kind == "mean":
        return sum(values) / len(values)
    if kind == "max":
        return max(values)
    if kind == "count":
        return float(len(values))
    if kind == "rate":
        return len(values) / max(window_s, 1.0)
    raise ValueError(kind)


def build_finding(cfg: Config, *, agent_id: str, n: int, metric: str, entity_type: str, entity_id: str,
                  obs: tuple[Observation, ...] | list[Observation], window: Window, source: str | None = None,
                  cadence: int | None = None) -> Finding:
    spec = cfg.metrics[metric]
    data_cfg = cfg.agents["data"]
    window_s = (window.end - window.start).total_seconds()
    vals = [o.value for o in obs]
    value = round(aggregate(spec["aggregation"], vals, window_s), 3)
    sev, ref = severity(cfg, metric, entity_id, value)
    # completeness is measured against the cadence the input actually delivers (a one-record snapshot is complete;
    # a signal with 2 samples while its peers have 6 is not), capped by the configured window/interval
    expected = max(1.0, window_s / float(data_cfg["expected_sample_interval_s"]))
    if cadence:
        expected = max(1.0, min(expected, float(cadence)))
    completeness = min(1.0, len(obs) / expected)
    last = max(o.ts for o in obs)
    staleness = max(0.0, (window.end - last).total_seconds())
    if staleness > float(data_cfg["staleness_threshold_s"]):
        completeness = min(completeness, float(cfg.scoring["stale_quality"]))
    seen: set[tuple[str, str, str, str]] = set()
    transforms: list[Transform] = []
    for o in obs:
        for t in o.transforms:
            k = (t.step, t.field, str(t.from_), str(t.to))
            if k not in seen:
                seen.add(k)
                transforms.append(t)
    transforms.sort(key=lambda t: (t.step, t.field, str(t.from_), str(t.to)))
    return Finding(
        finding_id=f"F-{agent_id}-{n}",
        metric=metric,
        entity=EntityRef(type=entity_type, id=entity_id),
        value=value,
        unit=str(spec["unit"]),
        window=Window(start=min(o.ts for o in obs), end=last),
        aggregation=spec["aggregation"],
        sample_count=len(obs),
        threshold_ref=ref,
        severity=sev,
        data_quality=DataQuality(completeness=round(completeness, 3), staleness_s=round(staleness, 1),
                                 coerced=any(o.coerced for o in obs)),
        transforms=transforms[:25],
        source_refs=sorted({o.source_ref for o in obs})[:50],
        source=source,
        placed=bool(getattr(cfg.topology.get(entity_id), "placed", True)),
    )


def findings_for(cfg: Config, *, agent_id: str, start_n: int, metric: str, entity_id: str,
                 obs: tuple[Observation, ...], window: Window, cadence: int | None = None) -> list[Finding]:
    """One finding per source (multiple sources -> C1 conflict detection downstream)."""
    if not obs:
        return []
    by_src: dict[str, list[Observation]] = defaultdict(list)
    for o in obs:
        by_src[o.source].append(o)
    etype = cfg.topology.type_of(entity_id) or obs[0].entity_type
    out = []
    for i, src in enumerate(sorted(by_src)):
        out.append(build_finding(cfg, agent_id=agent_id, n=start_n + i, metric=metric, entity_type=etype,
                                 entity_id=entity_id, obs=by_src[src], window=window, source=src, cadence=cadence))
    return out


# ---------------------------------------------------------------------------- analysis agent base

class AnalysisAgent:
    """Owns a set of metrics. Round 0: anomalous findings + coverage manifest. Later: evidence on request."""

    agent_id: str = "analysis_agent"

    def __init__(self, cfg: Config):
        self.owns: tuple[str, ...] = tuple(cfg.agents["internal"][self.agent_id]["owns"])
        self.capabilities = [f"metric:{m}" for m in self.owns] + [f"evidence:{m}" for m in self.owns]

    def handle(self, msg: Message, ctx: ReadOnlyContext) -> list[Message]:
        if msg.message_type == "task_request":
            task = msg.payload.get("task")
            if task == "analyze":
                return self.analyze(msg, ctx)
            return self.other_task(msg, ctx)
        if msg.message_type == "evidence_request":
            return self.evidence(msg, ctx)
        return [error_message(sender=self.agent_id, recipient=msg.sender, incident_id=msg.incident_id,
                              code="MALFORMED", detail=f"{self.agent_id} does not handle {msg.message_type}",
                              offending_message_id=msg.message_id)]

    def other_task(self, msg: Message, ctx: ReadOnlyContext) -> list[Message]:
        return [error_message(sender=self.agent_id, recipient=msg.sender, incident_id=msg.incident_id,
                              code="MALFORMED", detail=f"unsupported task {msg.payload.get('task')!r}",
                              offending_message_id=msg.message_id)]

    def analyze(self, msg: Message, ctx: ReadOnlyContext) -> list[Message]:
        tel: TelemetryTool = ctx.tool("telemetry")
        cfg = ctx.config
        anomalous: list[Finding] = []
        coverage: list[dict[str, Any]] = []
        n = ROUND_ID_STRIDE * 0 + 1
        for metric in sorted(self.owns):
            for eid in tel.entities_with(metric):
                obs = tel.query(metric, eid, ctx.window)
                if not obs:
                    continue
                etype = cfg.topology.type_of(eid) or obs[0].entity_type
                coverage.append({"metric": metric, "entity": {"type": etype, "id": eid}})
                fs = findings_for(cfg, agent_id=self.agent_id, start_n=n, metric=metric, entity_id=eid, obs=obs,
                                  window=ctx.window, cadence=tel.cadence(ctx.window))
                n += len(fs)
                # Round-0 rule: publish only anomalous signals. If any source of a signal is anomalous, all of
                # its sources are published so value conflicts (C1) stay visible.
                if any(f.anomalous for f in fs):
                    anomalous.extend(fs)
        anomalous.sort(key=lambda f: f.finding_id)
        status = "completed" if coverage else "insufficient_data"
        return [
            make_message("finding_report", sender=self.agent_id, recipient="orchestrator", incident_id=msg.incident_id,
                         in_reply_to=msg.message_id, status=status,
                         payload={"round": 0, "findings": [f.model_dump(mode="json", by_alias=True) for f in anomalous]}),
            make_message("coverage_manifest", sender=self.agent_id, recipient="orchestrator", incident_id=msg.incident_id,
                         in_reply_to=msg.message_id, payload={"signals": coverage}),
        ]

    def evidence(self, msg: Message, ctx: ReadOnlyContext) -> list[Message]:
        tel: TelemetryTool = ctx.tool("telemetry")
        cfg = ctx.config
        rnd = int(msg.payload.get("round", ctx.round))
        n = ROUND_ID_STRIDE * rnd + 1
        found: list[Finding] = []
        unavailable: list[dict[str, Any]] = []
        for req in msg.payload.get("requests", []):
            sig = SignalRef.model_validate(req)
            window = sig.window or ctx.window
            if sig.metric not in self.owns:
                unavailable.append(sig.model_dump(mode="json"))
                continue
            obs = tel.query(sig.metric, sig.entity.id, window)
            if not obs:
                unavailable.append(sig.model_dump(mode="json"))
                continue
            fs = findings_for(cfg, agent_id=self.agent_id, start_n=n, metric=sig.metric, entity_id=sig.entity.id,
                              obs=obs, window=window, cadence=tel.cadence(window))
            n += len(fs)
            found.extend(fs)
        found.sort(key=lambda f: f.finding_id)
        return [make_message("evidence_response", sender=self.agent_id, recipient="orchestrator",
                             incident_id=msg.incident_id, in_reply_to=msg.message_id,
                             status="completed" if found else "insufficient_data",
                             payload={"round": rnd, "findings": [f.model_dump(mode="json", by_alias=True) for f in found],
                                      "unavailable": unavailable})]
