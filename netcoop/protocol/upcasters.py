"""Registered upcasters. Each maps an older dialect dict to the next version and records Transforms.

Dialect 0.9 (spoken by the external wireless_agent; it is deliberately NOT fixed):

    {"ver":"0.9","inc":"INC-001","from":"wifi-probe","re":"<request id>","q":"task|evidence",
     "kind":"obs|err","obs":[{"ap":"ap-h3","signal":-78,"noise_margin":9,"retx":0.22,"clients":31,"ts":1730370000}],
     "na":[{"ap":"ap-h3","sig":"signal"}], "err":{"code":"MALFORMED","detail":"..."}}

Mapping 0.9 -> 1.0 (structure here; names/units then go through the metric registry + topology):
    ver -> schema_version, inc -> incident_id, from -> sender, re -> in_reply_to,
    obs -> payload.observations, ts (epoch s) -> RFC3339 UTC, retx declared unit `fraction` (x100 via unit_aliases),
    wired probes: dev -> device_id, rtt (s) -> latency_ms, loss (fraction) -> packet_loss_pct, cpu (fraction) -> cpu_pct,
    signal -> rssi_dbm, noise_margin -> snr_db, retx -> retransmission_pct (aliases in metrics.yaml),
    ap-h3 -> AP_H3 (topology alias canonicalization).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from netcoop.protocol.envelope import deterministic_uuid4
from netcoop.protocol.findings import Transform

# 0.9 field -> unit declared by the 0.9 dialect (names are mapped by metrics.yaml aliases)
V09_OBS_UNITS = {"signal": "dbm", "noise_margin": "db", "retx": "fraction", "clients": "count",
                 # wired probe fields (legacy probes embed these in bundles)
                 "rtt": "s", "loss": "fraction", "cpu": "fraction"}
V09_FIELDS = set(V09_OBS_UNITS)


def _epoch_to_rfc3339(v: Any) -> Any:
    if isinstance(v, bool) or not isinstance(v, int | float):
        return v
    return datetime.fromtimestamp(float(v), UTC).isoformat().replace("+00:00", "Z")


def _agent_id(name: Any) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", str(name or "unknown").lower()).strip("_") or "unknown"
    if not s[0].isalpha():
        s = "a_" + s
    return s[:40]


def upcast_0_9_to_1_0(raw: dict[str, Any]) -> tuple[dict[str, Any], list[Transform]]:
    t: list[Transform] = []
    kind = raw.get("kind", "obs")
    q = raw.get("q", "task")
    incident = raw.get("inc")
    sender = _agent_id(raw.get("from"))
    t.append(Transform(step="version", field="from", from_=raw.get("from"), to=sender, reason="0.9 sender name"))
    known = {"ver", "inc", "from", "re", "q", "kind", "obs", "na", "err", "mid", "round"}
    extras = {k: v for k, v in raw.items() if k not in known}
    out: dict[str, Any] = {
        "schema_version": "1.0",
        "message_id": raw.get("mid") or deterministic_uuid4("upcast-0.9", raw.get("re"), raw.get("inc"), kind, q),
        "incident_id": incident,
        "sender": sender,
        "recipient": "orchestrator",
        "in_reply_to": raw.get("re"),
        "status": "completed",
        "limitations": [],
        "extras": extras,
    }
    if kind == "err":
        err = raw.get("err") if isinstance(raw.get("err"), dict) else {}
        if not isinstance(incident, str) or not incident:
            out["incident_id"] = "INC-UNKNOWN"  # error replies to unparseable input may not know the incident
        out["message_type"] = "error"
        out["status"] = "failed"
        out["payload"] = {
            "code": str(err.get("code", "MALFORMED"))[:40],
            "detail": str(err.get("detail", ""))[:500],
            "offending_message_id": raw.get("re"),
            "field": err.get("field"),
            "agent_id": sender,
        }
        return out, t
    observations: list[dict[str, Any]] = []
    obs = raw.get("obs")
    for i, o in enumerate(obs if isinstance(obs, list) else []):
        if not isinstance(o, dict):
            observations.append({"_malformed": o})
            continue
        ts = o.get("ts")
        new_ts = _epoch_to_rfc3339(ts)
        if new_ts != ts:
            t.append(Transform(step="time", field=f"obs[{i}].ts", from_=ts, to=new_ts, reason="epoch seconds -> RFC3339 UTC"))
        metrics = {k: v for k, v in o.items() if k in V09_FIELDS}
        units = {k: V09_OBS_UNITS[k] for k in metrics}
        rest = {k: v for k, v in o.items() if k not in V09_FIELDS and k not in ("ap", "dev", "ts")}
        ent_key, ent_val = ("dev", o.get("dev")) if "dev" in o and "ap" not in o else ("ap", o.get("ap"))
        rec: dict[str, Any] = {"timestamp": new_ts, ("device_id" if ent_key == "dev" else "ap"): ent_val,
                               "metrics": metrics, "units": units, "source": raw.get("from") or "external"}
        rec.update({k: v for k, v in rest.items() if k not in rec})
        observations.append(rec)
    unavailable = []
    na = raw.get("na")
    for n in na if isinstance(na, list) else []:
        if isinstance(n, dict) and isinstance(n.get("ap"), str) and isinstance(n.get("sig"), str):
            unavailable.append({"metric": n["sig"], "entity": {"type": "ap", "id": n["ap"]}})
    payload: dict[str, Any] = {"round": int(raw.get("round") or 0) if str(raw.get("round") or 0).isdigit() else 0,
                               "findings": [], "observations": observations}
    if q == "evidence":
        out["message_type"] = "evidence_response"
        payload["unavailable"] = unavailable
    else:
        out["message_type"] = "finding_report"
    out["payload"] = payload
    return out, t


# from_version -> (to_version, fn)
UPCASTERS: dict[str, tuple[str, Callable[[dict[str, Any]], tuple[dict[str, Any], list[Transform]]]]] = {
    "0.9": ("1.0", upcast_0_9_to_1_0),
}


def detect_version_by_shape(raw: dict[str, Any]) -> str | None:
    """Registered detectors for messages that omit their version."""
    if "message_type" in raw and "payload" in raw:
        return "1.0"
    if "from" in raw and ("obs" in raw or "err" in raw):
        return "0.9"
    return None
