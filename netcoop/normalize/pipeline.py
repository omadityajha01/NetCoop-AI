"""Normalization pipeline (CLAUDE.md §5). Recover what's recoverable, quarantine what isn't.
Never silently drop, never invent. Every step records a Transform.

Accounting invariant (tested): records_in == records_used + records_quarantined, and every
candidate observation is exactly one of: used, quarantined, missing.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from netcoop.config import Config
from netcoop.normalize.aliases import (
    ENTITY_KEYS,
    LABEL_FIELDS,
    META_KEYS,
    TIME_KEYS,
    build_alias_index,
    resolve_field,
)
from netcoop.normalize.entities import canonicalize
from netcoop.normalize.plausibility import check_range
from netcoop.normalize.timefix import parse_ts, rfc3339
from netcoop.normalize.units import MISSING, coerce_value, infer_batch_multiplier, unit_multiplier
from netcoop.protocol.findings import Limitation, Transform, Window
from netcoop.protocol.upcasters import UPCASTERS
from netcoop.protocol.versions import parse_version

_SOURCE_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,40}$")


class NormalizationError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(f"{code}: {detail}")
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class Observation:
    entity_type: str
    entity_id: str
    metric: str
    value: float
    unit: str
    ts: datetime
    source: str
    source_ref: str
    coerced: bool = False
    transforms: tuple[Transform, ...] = ()


@dataclass
class Quarantined:
    source_ref: str
    code: str
    reason: str
    field: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"source_ref": self.source_ref, "code": self.code, "reason": self.reason, "field": self.field}


@dataclass
class NormalizationResult:
    observations: list[Observation] = field(default_factory=list)
    quarantined: list[Quarantined] = field(default_factory=list)
    missing: list[tuple[str, str]] = field(default_factory=list)
    extras: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[Limitation] = field(default_factory=list)
    transforms: list[Transform] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)
    incident_time: datetime | None = None
    incident_time_inferred: bool = False
    window: Window | None = None
    complaint: str | None = None
    input_sha256: str = ""
    records_in: int = 0
    records_used: int = 0
    records_quarantined: int = 0
    title: str | None = None
    unplaced: dict[str, str] = field(default_factory=dict)  # device ids seen in telemetry but absent from topology


@dataclass
class _Cand:
    rec_idx: int
    ref: str
    entity_type: str
    entity_id: str
    metric: str
    field_name: str
    value: float
    unit_mult: float | None  # None = pending batch inference
    ts: datetime
    source: str
    coerced: bool
    transforms: list[Transform]


# ---------------------------------------------------------------------------- parsing (step 1-2)

def _decode(data: bytes, max_bytes: int) -> str:
    if len(data) > max_bytes:
        raise NormalizationError("TOO_LARGE", f"input is {len(data)} bytes; limit {max_bytes}")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise NormalizationError("MALFORMED", f"input is not UTF-8 ({exc.reason} at byte {exc.start})") from exc


def _parse_csv(text: str) -> list[dict[str, Any]]:
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""))
        if not reader.fieldnames:
            raise NormalizationError("MALFORMED", "CSV has no header row")
        return [{(k or "").strip(): v for k, v in row.items() if k is not None} for row in reader]
    except csv.Error as exc:
        raise NormalizationError("MALFORMED", f"invalid CSV: {exc}") from exc


def parse_input(data: bytes | str | dict | list, cfg: Config, filename: str | None = None) -> tuple[Any, str]:
    max_bytes = int(cfg.agents["data"]["max_upload_bytes"])
    if isinstance(data, dict | list):
        raw_bytes = json.dumps(data, sort_keys=True).encode()
        return data, hashlib.sha256(raw_bytes).hexdigest()
    if isinstance(data, str):
        data = data.encode("utf-8")
    sha = hashlib.sha256(data).hexdigest()
    text = _decode(data, max_bytes)
    is_csv = (filename or "").lower().endswith(".csv") or (text.lstrip()[:1] not in ("{", "["))
    if is_csv:
        return _parse_csv(text), sha
    try:
        return json.loads(text), sha
    except json.JSONDecodeError as exc:
        raise NormalizationError("MALFORMED", f"invalid JSON: {exc.msg} at line {exc.lineno}") from exc
    except RecursionError as exc:
        raise NormalizationError("MALFORMED", "JSON nested too deeply") from exc


def _expand_v09(obj: dict[str, Any], ref: str, res: NormalizationResult) -> list[tuple[str, Any]]:
    upcaster = UPCASTERS.get(str(obj.get("ver")))
    if upcaster is None:
        res.quarantined.append(Quarantined(ref, "SCHEMA_VERSION_UNSUPPORTED", f"no upcaster from {obj.get('ver')!r}"))
        return []
    up, transforms = upcaster[1](obj)
    res.transforms.extend(transforms)
    res.summary["version_upcast"] = res.summary.get("version_upcast", 0) + 1
    obs = (up.get("payload") or {}).get("observations") or []
    return [(f"{ref}.obs[{j}]", o) for j, o in enumerate(obs)]


def _unwrap(parsed: Any, res: NormalizationResult) -> list[tuple[str, Any]]:
    """Bundle -> list of (ref, record)."""
    if isinstance(parsed, list):
        res.limitations.append(Limitation(code="VERSION_INFERRED", detail="bare record list; bundle schema 1.0 inferred",
                                          impact="none"))
        items = list(enumerate(parsed))
    elif isinstance(parsed, dict):
        if "ver" in parsed and "obs" in parsed:
            return _expand_v09(parsed, "input", res)
        if "metrics" in parsed and "records" not in parsed:
            res.limitations.append(Limitation(code="VERSION_INFERRED",
                                              detail="single organizer-generator record; bundle shape inferred",
                                              impact="none"))
            items = [(0, parsed)]
        else:
            ver = parsed.get("schema_version")
            if ver is None:
                res.limitations.append(Limitation(code="VERSION_INFERRED", detail="bundle schema_version missing; 1.0 inferred",
                                                  impact="none"))
            elif (pv := parse_version(str(ver))) is None or pv[0] != 1:
                raise NormalizationError("SCHEMA_VERSION_UNSUPPORTED", f"bundle schema_version {ver!r} not supported")
            inc = parsed.get("incident") if isinstance(parsed.get("incident"), dict) else {}
            if isinstance(inc.get("complaint"), str):
                res.complaint = inc["complaint"]
            if isinstance(inc.get("title"), str):
                res.title = inc["title"][:120]
            if inc.get("time") is not None:
                ts, _, prob = parse_ts(inc.get("time"))
                if prob:
                    raise NormalizationError("BAD_TYPE", f"incident.time: {prob}")
                res.incident_time = ts
            recs = parsed.get("records")
            if not isinstance(recs, list):
                raise NormalizationError("MISSING_FIELD", "bundle has no `records` list")
            items = list(enumerate(recs))
    else:
        raise NormalizationError("MALFORMED", "input must be a JSON object, array or CSV")
    out: list[tuple[str, Any]] = []
    for i, rec in items:
        ref = f"records[{i}]"
        if isinstance(rec, dict) and "ver" in rec and "obs" in rec:
            out.extend(_expand_v09(rec, ref, res))
        else:
            out.append((ref, rec))
    return out


# ---------------------------------------------------------------------------- per-record (steps 3-7)

def _record_fields(rec: dict[str, Any]) -> list[tuple[str, Any, Any]]:
    units = rec.get("units") if isinstance(rec.get("units"), dict) else {}
    fields: list[tuple[str, Any, Any]] = []
    if "metric" in rec and "value" in rec:
        fields.append((str(rec["metric"]), rec["value"], rec.get("unit")))
    metrics = rec.get("metrics")
    if isinstance(metrics, dict):
        fields.extend((str(k), v, units.get(k)) for k, v in metrics.items())
    reserved = set(ENTITY_KEYS) | set(TIME_KEYS) | META_KEYS | set(LABEL_FIELDS)
    for k, v in rec.items():
        if k not in reserved and not str(k).startswith("_"):
            fields.append((str(k), v, units.get(k)))
    return fields


def _entity_of(rec: dict[str, Any]) -> tuple[Any, str | None, str | None]:
    ent = rec.get("entity")
    if isinstance(ent, dict) and "id" in ent:
        return ent.get("id"), ent.get("type") if ent.get("type") in ("device", "link", "ap", "service") else None, "entity"
    for k, etype in ENTITY_KEYS.items():
        if k in rec and rec[k] not in (None, ""):
            return rec[k], etype, k
    return None, None, None


def _process_record(ref: str, idx: int, rec: Any, cfg: Config, alias_idx: Any, res: NormalizationResult,
                    source_default: str, cands: list[_Cand], rec_problems: dict[int, list[Quarantined]]) -> None:
    probs = rec_problems.setdefault(idx, [])
    if not isinstance(rec, dict):
        probs.append(Quarantined(ref, "MALFORMED", "record is not an object"))
        return
    ts_key = next((k for k in TIME_KEYS if k in rec), None)
    ts, treason, tprob = parse_ts(rec.get(ts_key) if ts_key else None)
    if tprob:
        probs.append(Quarantined(ref, "MISSING_FIELD" if ts_key is None else "BAD_TYPE", tprob, ts_key or "timestamp"))
        return
    base_t: list[Transform] = []
    if treason:
        base_t.append(Transform(step="time", field=ts_key or "timestamp", from_=rec.get(ts_key), to=rfc3339(ts),
                                reason=treason))
    raw_id, etype_hint, ekey = _entity_of(rec)
    if raw_id is None:
        probs.append(Quarantined(ref, "MISSING_FIELD", "no entity identifier", "device_id"))
        return
    etype, eid, eprob = canonicalize(raw_id, etype_hint, cfg.topology)
    if eprob and eprob.startswith("unknown entity") and etype_hint in ("device", None):
        # U2: an unknown DEVICE is never quarantined just for being unknown; it is kept unplaced (no localization)
        uid = unplaced_id(str(raw_id))
        if not cfg.topology.exists(uid) or uid in res.unplaced:
            res.unplaced[uid] = "device"
            etype, eid, eprob = "device", uid, None
            base_t.append(Transform(step="entity", field=ekey or "entity", from_=str(raw_id), to=uid,
                                    reason="device not in topology: kept unplaced"))
    if eprob:
        code = "MALFORMED" if eprob.startswith(("entity id fails ID regex", "entity id is not a string")) else "UNKNOWN_ENTITY"
        probs.append(Quarantined(ref, code, eprob, ekey))
        return
    if str(raw_id) != eid and eid not in res.unplaced:
        base_t.append(Transform(step="entity", field=ekey or "entity", from_=str(raw_id), to=eid,
                                reason="topology alias (case/separator-insensitive)"))
    src_raw = rec.get("source")
    source = src_raw if isinstance(src_raw, str) and _SOURCE_RE.match(src_raw) else source_default
    for label, note in LABEL_FIELDS.items():
        if label in rec:
            res.extras.append({"source_ref": ref, "field": label, "value": str(rec[label])[:40], "note": note})
    fields = _record_fields(rec)
    if not fields:
        probs.append(Quarantined(ref, "MISSING_FIELD", "record has no metric fields"))
        return
    for fname, raw_val, raw_unit in fields:
        fref = f"{ref}.{fname}"
        hit = resolve_field(fname, alias_idx)
        if hit is None:
            res.extras.append({"source_ref": ref, "field": fname[:64], "value": str(raw_val)[:40],
                               "note": "unknown field (not in metrics.yaml)"})
            res.summary["unknown_fields"] = res.summary.get("unknown_fields", 0) + 1
            continue
        spec = cfg.metrics[hit.metric]
        t = list(base_t)
        if fname != hit.metric:
            t.append(Transform(step="alias", field=fname, from_=fname, to=hit.metric, reason="metrics.yaml alias"))
        if etype not in spec.get("entity_types", ()):
            res.quarantined.append(Quarantined(fref, "BAD_TYPE", f"{hit.metric} is not reported for {etype}", fname))
            continue
        value, utoken, coerced, vprob = coerce_value(raw_val, spec.get("value_map"))
        if value is MISSING:
            res.missing.append((fref, hit.metric))
            continue
        if vprob or value is None:
            res.quarantined.append(Quarantined(fref, "BAD_TYPE", vprob or "bad value", fname))
            continue
        if coerced:
            t.append(Transform(step="coerce", field=fname, from_=str(raw_val)[:40], to=value, reason="string/bool -> number"))
        explicit = utoken or (raw_unit if isinstance(raw_unit, str) and raw_unit.strip() else None)
        mult: float | None
        if explicit:
            mult = unit_multiplier(spec, explicit)
            if mult is None:
                res.quarantined.append(Quarantined(fref, "BAD_UNIT", f"unknown unit {explicit!r} for {hit.metric}", fname))
                continue
            if explicit.lower() != str(spec["unit"]).lower():
                t.append(Transform(step="unit", field=fname, from_=f"{value:g} {explicit}", to=f"{value * mult:g} {spec['unit']}",
                                   reason="explicit unit via unit_aliases"))
        elif hit.unit_implied:
            mult = 1.0
        else:
            mult = None
        cands.append(_Cand(idx, fref, etype, eid, hit.metric, fname, value, mult, ts, source,
                           coerced or bool(utoken), t))


# ---------------------------------------------------------------------------- driver

def unplaced_id(raw: str) -> str:
    """Stable id for a device absent from topology: upper-case, separators -> '_' (IPv4 kept dotted)."""
    s = raw.strip()
    if re.fullmatch(r"\d{1,3}(\.\d{1,3}){3}", s):
        return s
    return re.sub(r"[\s\-.:/]+", "_", s.upper()).strip("_")[:64] or "UNKNOWN"


def input_topology(data: bytes | str | dict | list, cfg: Config, filename: str | None = None) -> Any:
    """The bundle's `topology` object, if any (None on parse problems: normalize_bundle reports those)."""
    try:
        parsed, _ = parse_input(data, cfg, filename)
    except NormalizationError:
        return None
    return parsed.get("topology") if isinstance(parsed, dict) else None


def _infer_pending(cands: list[_Cand], cfg: Config, res: NormalizationResult) -> list[_Cand]:
    groups: dict[tuple[str, str], list[_Cand]] = defaultdict(list)
    for c in cands:
        if c.unit_mult is None:
            groups[(c.metric, c.field_name)].append(c)
    out = [c for c in cands if c.unit_mult is not None]
    for (metric, fname), items in sorted(groups.items()):
        spec = cfg.metrics[metric]
        mult, why = infer_batch_multiplier(spec, [c.value for c in items])
        if mult is None:
            for c in items:
                res.quarantined.append(Quarantined(c.ref, "BAD_UNIT", f"unit not stated for {fname!r}; {why}", fname))
            continue
        res.summary["unit_inferred"] = res.summary.get("unit_inferred", 0) + len(items)
        res.limitations.append(Limitation(code="UNIT_INFERRED",
                                          detail=f"{len(items)} {metric} value(s) from field {fname!r}: unit inferred ({why})",
                                          impact="medium"))
        for c in items:
            c.unit_mult = mult
            c.coerced = True
            c.transforms.append(Transform(step="unit", field=fname, from_=c.value, to=c.value * mult,
                                          reason=f"inferred from batch: {why}"))
            out.append(c)
    return out


def _infer_incident_time(cands: list[_Cand], window_s: int) -> datetime | None:
    if not cands:
        return None
    ts = sorted(c.ts for c in cands)
    med = ts[len(ts) // 2]
    bound = med + timedelta(seconds=window_s)
    return max(t for t in ts if t <= bound)


def normalize_records(
    items: list[tuple[str, Any]],
    cfg: Config,
    *,
    res: NormalizationResult | None = None,
    source_default: str = "input",
    incident_time: datetime | None = None,
) -> NormalizationResult:
    res = res or NormalizationResult()
    if incident_time is not None:
        res.incident_time = incident_time
    alias_idx = build_alias_index(cfg.metrics)
    max_records = int(cfg.agents["data"]["max_records"])
    if len(items) > max_records:
        raise NormalizationError("TOO_LARGE", f"{len(items)} records; limit {max_records}")
    cands: list[_Cand] = []
    rec_problems: dict[int, list[Quarantined]] = {}
    for idx, (ref, rec) in enumerate(items):
        _process_record(ref, idx, rec, cfg, alias_idx, res, source_default, cands, rec_problems)
    cands = _infer_pending(cands, cfg, res)

    data_cfg = cfg.agents["data"]
    window_s = int(data_cfg["incident_window_s"])
    if res.incident_time is None:
        res.incident_time = _infer_incident_time(cands, window_s)
        res.incident_time_inferred = True
        if res.incident_time is not None:
            res.limitations.append(Limitation(code="INCIDENT_TIME_INFERRED",
                                              detail=f"incident time not given; using latest sample {rfc3339(res.incident_time)}",
                                              impact="low"))
    it = res.incident_time
    future_limit = it + timedelta(seconds=int(data_cfg["future_tolerance_s"])) if it else None
    win_start = it - timedelta(seconds=window_s) if it else None
    if it is not None:
        res.window = Window(start=win_start, end=it)

    # plausibility -> record-level quarantine (step 6)
    implausible: dict[int, str] = {}
    for c in cands:
        v = c.value * (c.unit_mult or 1.0)
        prob = check_range(cfg.metrics[c.metric], v)
        if prob and c.rec_idx not in implausible:
            implausible[c.rec_idx] = f"{c.metric}: {prob}"
    used: list[Observation] = []
    used_recs: set[int] = set()
    seen: set[tuple[str, str, datetime, str]] = set()
    for c in cands:
        if c.rec_idx in implausible:
            res.quarantined.append(Quarantined(c.ref, "IMPLAUSIBLE", f"record quarantined: {implausible[c.rec_idx]}", c.field_name))
            continue
        if future_limit is not None and c.ts > future_limit:
            res.quarantined.append(Quarantined(c.ref, "FUTURE_TIMESTAMP", f"timestamp {rfc3339(c.ts)} is > tolerance after incident time"))
            continue
        if win_start is not None and c.ts < win_start:
            res.quarantined.append(Quarantined(c.ref, "OUT_OF_WINDOW", f"sample {rfc3339(c.ts)} precedes analysis window"))
            continue
        key = (c.entity_id, c.metric, c.ts, c.source)
        if key in seen:
            res.quarantined.append(Quarantined(c.ref, "DUPLICATE", "duplicate (entity, metric, timestamp, source)"))
            continue
        seen.add(key)
        used_recs.add(c.rec_idx)
        value = c.value * (c.unit_mult or 1.0)
        used.append(Observation(c.entity_type, c.entity_id, c.metric, float(f"{value:.12g}"), str(cfg.metrics[c.metric]["unit"]),
                                c.ts, c.source, c.ref, c.coerced, tuple(c.transforms)))
    used.sort(key=lambda o: (o.entity_id, o.metric, o.ts, o.source, o.source_ref))
    res.observations.extend(used)

    # record-level accounting
    for idx, (ref, _rec) in enumerate(items):
        if idx in used_recs:
            res.records_used += 1
        else:
            res.records_quarantined += 1
            if not rec_problems.get(idx):
                reasons = sorted({q.code for q in res.quarantined if q.source_ref.startswith(ref + ".") or q.source_ref == ref})
                if not reasons and any(m[0].startswith(ref + ".") for m in res.missing):
                    reasons = ["MISSING_VALUE"]
                rec_problems[idx] = [Quarantined(ref, "NO_USABLE_VALUES", f"no usable observations ({', '.join(reasons) or 'unknown fields only'})")]
    for idx in sorted(rec_problems):
        res.quarantined.extend(rec_problems[idx])
    res.records_in += len(items)
    _summarize(res, cfg)
    return res


def single_snapshot_limitation(res: NormalizationResult) -> Limitation | None:
    """Reporting only (V1): if every device has exactly one sample time, persistence over time is not verified.
    It adds a limitation and nothing else: status, confidence and scoring are unchanged (tested)."""
    times: dict[str, set] = {}
    for o in res.observations:
        if o.entity_type == "device":
            times.setdefault(o.entity_id, set()).add(o.ts)
    if times and all(len(t) == 1 for t in times.values()):
        return Limitation(code="SINGLE_SNAPSHOT", impact="low",
                          detail=f"single snapshot: persistence not verified ({len(times)} device(s), one sample each)")
    return None


def _summarize(res: NormalizationResult, cfg: Config) -> None:
    s = res.summary
    renamed = sum(1 for o in res.observations for t in o.transforms if t.step == "alias")
    converted = sum(1 for o in res.observations for t in o.transforms if t.step == "unit")
    s.update({
        "records_in": res.records_in,
        "records_used": res.records_used,
        "records_quarantined": res.records_quarantined,
        "observations_used": len(res.observations),
        "renamed": renamed,
        "unit_converted": converted,
        "entity_canonicalized": sum(1 for o in res.observations if any(t.step == "entity" for t in o.transforms)),
        "coerced": sum(1 for o in res.observations if o.coerced),
        "quarantined": len([q for q in res.quarantined if q.code not in ("OUT_OF_WINDOW", "DUPLICATE")]),
        "out_of_window": len([q for q in res.quarantined if q.code == "OUT_OF_WINDOW"]),
        "deduped": len([q for q in res.quarantined if q.code == "DUPLICATE"]),
        "missing_values": len(res.missing),
        "extras": len(res.extras),
    })
    s.setdefault("unit_inferred", 0)
    s.setdefault("version_upcast", 0)
    s.setdefault("unknown_fields", 0)
    # human limitations (aggregated, deterministic order)
    conv = Counter()
    for o in res.observations:
        for t in o.transforms:
            if t.step == "unit" and "explicit" in t.reason:
                unit = str(t.from_).split(" ", 1)[-1] if isinstance(t.from_, str) else "?"
                conv[(o.metric, unit)] += 1
    for (metric, unit), n in sorted(conv.items()):
        res.limitations.append(Limitation(code="UNIT_CONVERTED", detail=f"{n} {metric} value(s) converted from {unit}",
                                          impact="low"))
    snap = single_snapshot_limitation(res)
    if snap is not None:
        res.limitations.append(snap)
    if s["renamed"]:
        res.limitations.append(Limitation(code="FIELDS_RENAMED", detail=f"{s['renamed']} field(s) mapped from aliases to canonical names",
                                          impact="none"))
    if s["entity_canonicalized"]:
        res.limitations.append(Limitation(code="ENTITY_CANONICALIZED",
                                          detail=f"{s['entity_canonicalized']} observation(s) had entity IDs canonicalized via topology aliases",
                                          impact="none"))
    if res.unplaced:
        ids = sorted(res.unplaced)
        res.limitations.append(Limitation(
            code="UNPLACED_DEVICE",
            detail=(f"device not in topology: {', '.join(ids[:6])}{' …' if len(ids) > 6 else ''} (findings kept with "
                    "placed=false; topology localization skipped; confidence capped at medium if the diagnosis involves it)"),
            impact="medium"))
    if s["version_upcast"]:
        res.limitations.append(Limitation(code="VERSION_UPCAST", detail=f"{s['version_upcast']} legacy v0.9 block(s) upcast to 1.0",
                                          impact="low"))
    if res.missing:
        res.limitations.append(Limitation(code="MISSING_VALUES",
                                          detail=f"{len(res.missing)} value(s) were missing (N/A/null/empty) and treated as missing, never 0",
                                          impact="low"))
    by_code = Counter(q.code for q in res.quarantined if q.code not in ("OUT_OF_WINDOW", "DUPLICATE", "NO_USABLE_VALUES"))
    for code, n in sorted(by_code.items()):
        example = next(q for q in res.quarantined if q.code == code)
        res.limitations.append(Limitation(code=f"QUARANTINED_{code}",
                                          detail=f"{n} item(s) quarantined ({code}), e.g. {example.source_ref}: {example.reason}"[:300],
                                          impact="medium"))
    if s["out_of_window"]:
        res.limitations.append(Limitation(code="OUT_OF_WINDOW", detail=f"{s['out_of_window']} sample(s) older than the analysis window not used",
                                          impact="low"))
    if s["deduped"]:
        res.limitations.append(Limitation(code="DEDUPED", detail=f"{s['deduped']} duplicate sample(s) removed", impact="none"))
    labels = [e for e in res.extras if e["field"] in LABEL_FIELDS]
    if labels:
        res.limitations.append(Limitation(code="LABEL_NOT_EVIDENCE",
                                          detail=f"{len(labels)} generator `status` label(s) kept in extras; labels are not used as evidence",
                                          impact="none"))
    unknown = sorted({e["field"] for e in res.extras if e["field"] not in LABEL_FIELDS})
    if unknown:
        res.limitations.append(Limitation(code="UNKNOWN_FIELDS",
                                          detail=f"unknown field(s) kept in extras: {', '.join(unknown)[:200]}", impact="none"))


def normalize_bundle(data: bytes | str | dict | list, cfg: Config, *, filename: str | None = None) -> NormalizationResult:
    parsed, sha = parse_input(data, cfg, filename)
    res = NormalizationResult(input_sha256=sha)
    items = _unwrap(parsed, res)
    normalize_records(items, cfg, res=res, incident_time=res.incident_time)
    if res.incident_time is None:
        raise NormalizationError("MISSING_FIELD", "no usable timestamps and no incident.time; cannot place the incident")
    return res
