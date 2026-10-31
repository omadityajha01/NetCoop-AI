"""Config loading. All thresholds, aliases, weights and rules live in config/*.yaml (never in code)."""

from __future__ import annotations

import functools
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

from netcoop.topology import Topology

ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT / "config"


def freeze(obj: Any) -> Any:
    """Deep-freeze config so agents get a read-only view."""
    if isinstance(obj, Mapping):
        return MappingProxyType({k: freeze(v) for k, v in obj.items()})
    if isinstance(obj, list | tuple):
        return tuple(freeze(v) for v in obj)
    return obj


def thaw(obj: Any) -> Any:
    if isinstance(obj, Mapping):
        return {k: thaw(v) for k, v in obj.items()}
    if isinstance(obj, tuple):
        return [thaw(v) for v in obj]
    return obj


def _load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@dataclass(frozen=True)
class Config:
    metrics: Mapping[str, Any]
    signatures: Mapping[str, Any]
    playbook: Mapping[str, Any]
    policies: Mapping[str, Any]
    agents: Mapping[str, Any]
    scoring: Mapping[str, Any]
    topology: Topology
    config_dir: str

    @property
    def fault_types(self) -> tuple[str, ...]:
        return tuple(sorted(self.signatures))

    @property
    def analysis_agents(self) -> tuple[str, ...]:
        return tuple(self.agents["analysis_agents"])

    def owner_map(self) -> dict[str, str]:
        """metric -> agent_id (internal + allowlisted external)."""
        out: dict[str, str] = {}
        for aid, spec in self.agents["internal"].items():
            for m in spec.get("owns", ()):
                out[m] = aid
        for spec in self.agents.get("external", ()):
            for m in spec.get("owns", ()):
                out.setdefault(m, spec["agent_id"])
        return out

    def with_overrides(self, **sections: Any) -> Config:
        """Return a copy with whole sections replaced (used by eval/tests, never by agents)."""
        data = {
            "metrics": self.metrics,
            "signatures": self.signatures,
            "playbook": self.playbook,
            "policies": self.policies,
            "agents": self.agents,
            "scoring": self.scoring,
            "topology": self.topology,
            "config_dir": self.config_dir,
        }
        for k, v in sections.items():
            data[k] = freeze(v) if k != "topology" else v
        return Config(**data)


def _validate(cfg: Config) -> None:
    metric_names = set(cfg.metrics)
    for name, spec in cfg.metrics.items():
        for key in ("unit", "label", "meaning", "range", "aggregation", "direction", "thresholds"):
            if key not in spec:
                raise ValueError(f"metrics.yaml: {name} missing {key}")
        if spec["aggregation"] not in ("p95", "mean", "max", "count", "rate"):
            raise ValueError(f"metrics.yaml: {name} bad aggregation")
    for ft, sig in cfg.signatures.items():
        for section in ("expects", "contradicts"):
            for m, s in sig.get(section, {}).items():
                if m not in metric_names:
                    raise ValueError(f"signatures.yaml: {ft}.{section}.{m} not in metrics.yaml")
                if s["ref"] not in ("warn", "high", "critical"):
                    raise ValueError(f"signatures.yaml: {ft}.{m} bad ref")
        if sig.get("playbook") not in cfg.playbook:
            raise ValueError(f"signatures.yaml: {ft} playbook missing")
    seen_alias: dict[str, str] = {}
    for name, spec in cfg.metrics.items():
        for a in [name, *spec.get("aliases", ()), *spec.get("ambiguous_aliases", ())]:
            key = a.lower()
            if key in seen_alias and seen_alias[key] != name:
                raise ValueError(f"metrics.yaml: alias {a} used by {seen_alias[key]} and {name}")
            seen_alias[key] = name


@functools.lru_cache(maxsize=8)
def load_config(config_dir: str | None = None) -> Config:
    d = Path(config_dir) if config_dir else CONFIG_DIR
    cfg = Config(
        metrics=freeze(_load_yaml(d / "metrics.yaml")),
        signatures=freeze(_load_yaml(d / "signatures.yaml")),
        playbook=freeze(_load_yaml(d / "playbook.yaml")),
        policies=freeze(_load_yaml(d / "policies.yaml")),
        agents=freeze(_load_yaml(d / "agents.yaml")),
        scoring=freeze(_load_yaml(d / "scoring.yaml")),
        topology=Topology.from_dict(_load_yaml(d / "topology.yaml")),
        config_dir=str(d),
    )
    _validate(cfg)
    return cfg
