"""Corruption operators for robustness eval (`make fuzz`). Each record is corrupted with probability `rate`.

Operators (all seen in the wild; most are recoverable by the normalizer, some are not by design):
  rename      canonical field -> registry alias (e.g. latency_ms -> rtt_ms, queue_drops -> egress_drops)
  units       value rewritten in another unit with an explicit suffix ("0.21s", "0.93 fraction")
  fraction    *_pct value -> bare fraction under an ambiguous name (needs batch inference)
  old_version device record -> legacy v0.9 probe block (dev/rtt/loss/cpu, epoch ts)
  missing     metric value -> "N/A" / null / ""  (must become missing, never 0)
  mangle_id   entity id -> lowercase-hyphen / mixed case / IP address
  drop_field  a metric field deleted
"""

from __future__ import annotations

import copy
import random
from datetime import datetime
from typing import Any

from netcoop.config import load_config

OPS = ("rename", "units", "fraction", "old_version", "missing", "mangle_id", "drop_field")
_ALIAS = {"latency_ms": "rtt_ms", "queue_drops": "egress_drops", "interface_errors": "if_errors", "cpu_utilization_pct": "cpu_util_pct",
          "packet_loss_pct": "loss_pct", "link_utilization_pct": "util_pct", "jitter_ms": "jitter_msec", "memory_pct": "mem_pct",
          "crc_errors": "fcs_errors", "link_flaps": "flap_count", "dns_failure_pct": "dns_fail_pct", "dhcp_failure_pct": "dhcp_fail_pct"}
_FRACTION = {"cpu_utilization_pct": "cpu", "link_utilization_pct": "utilization", "memory_pct": "mem"}


def _mangle(eid: str, rng: random.Random) -> str:
    topo = load_config().topology
    choice = rng.randrange(3)
    if choice == 0:
        return eid.lower().replace("_", "-")
    if choice == 1:
        return "".join(c.lower() if rng.random() < 0.5 else c for c in eid)
    ent = topo.get(eid)
    return ent.ip if ent and ent.ip else eid.lower()


def mutate_record(rec: dict[str, Any], op: str, rng: random.Random) -> Any:
    rec = copy.deepcopy(rec)
    m = rec.get("metrics")
    if not isinstance(m, dict) or not m:
        return rec
    key = rng.choice(sorted(m))
    if op == "rename" and key in _ALIAS:
        m[_ALIAS[key]] = m.pop(key)
    elif op == "units":
        if key.endswith("_ms"):
            m[key] = f"{float(m[key]) / 1000:.5f}s"
        elif key.endswith("_pct"):
            m[key] = f"{float(m[key]) / 100:.5f} fraction"
        elif key in ("queue_drops", "interface_errors", "crc_errors"):
            m[key] = f"{m[key]} pkts" if key == "queue_drops" else f"{m[key]} count"
    elif op == "fraction":
        for k, alias in _FRACTION.items():
            if k in m:
                m[alias] = round(float(m.pop(k)) / 100, 5)
    elif op == "old_version" and "device_id" in rec:
        ts = int(datetime.fromisoformat(rec["timestamp"].replace("Z", "+00:00")).timestamp())
        o: dict[str, Any] = {"dev": rec["device_id"].lower().replace("_", "-"), "ts": ts}
        if "latency_ms" in m:
            o["rtt"] = round(float(m.pop("latency_ms")) / 1000, 5)
        if "packet_loss_pct" in m:
            o["loss"] = round(float(m.pop("packet_loss_pct")) / 100, 5)
        if "cpu_utilization_pct" in m:
            o["cpu"] = round(float(m.pop("cpu_utilization_pct")) / 100, 5)
        legacy = {"ver": "0.9", "inc": "INC-LEGACY", "from": "legacy-probe", "obs": [o]}
        return [rec, legacy] if m else [legacy]
    elif op == "missing":
        m[key] = rng.choice(["N/A", None, "", "null"])
    elif op == "mangle_id":
        for k in ("device_id", "link_id", "ap", "service"):
            if k in rec:
                rec[k] = _mangle(rec[k], rng)
    elif op == "drop_field":
        m.pop(key)
        if not m:
            m["zz_note"] = "empty"
    return rec


def mutate_bundle(bundle: dict[str, Any], rate: float, rng: random.Random, ops: tuple[str, ...] = OPS,
                  drop_version: bool = True) -> dict[str, Any]:
    b = copy.deepcopy(bundle)
    out: list[Any] = []
    for r in b["records"]:
        if rng.random() < rate:
            mr = mutate_record(r, rng.choice(ops), rng)
            out.extend(mr if isinstance(mr, list) else [mr])
        else:
            out.append(r)
    b["records"] = out
    if drop_version and rate > 0 and rng.random() < rate:
        b.pop("schema_version", None)  # missing version: detected by shape
    return b
