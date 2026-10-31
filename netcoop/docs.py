"""`make schemas` / `make docs`: JSON Schema export + README tables generated from config/*.yaml."""

from __future__ import annotations

import json
import re
from pathlib import Path

from netcoop.config import ROOT, load_config
from netcoop.protocol.envelope import Message
from netcoop.protocol.findings import Finding, Hypothesis, Prediction
from netcoop.protocol.messages import PAYLOAD_MODELS

SCHEMA_DIR = ROOT / "docs" / "schemas"
README = ROOT / "README.md"

ENVELOPE_MEANING = {
    "schema_version": ("\"MAJOR.MINOR\"", "Protocol version of this message (current 1.1; 1.0 accepted; 0.9 upcast)"),
    "message_id": ("uuid", "Unique; receivers are idempotent on duplicates (content-derived UUIDv4)"),
    "message_type": ("enum", ", ".join(f"`{t}`" for t in PAYLOAD_MODELS)),
    "incident_id": ("str", "Server-generated, `^INC-[0-9A-Z]{4,12}$`"),
    "sender / recipient": ("agent_id", "`recipient` may be `orchestrator`"),
    "in_reply_to": ("uuid | null", "`message_id` this responds to"),
    "seq": ("int", "Assigned by the event log on append (monotonic per run); agents never set it"),
    "created_at": ("RFC3339 UTC", "Stamped by the event log on append"),
    "status": ("enum", "`completed`, `partial`, `failed`, `insufficient_data`"),
    "payload": ("object", "Typed per `message_type` (see docs/schemas/)"),
    "limitations": ("list[Limitation]", "`{code, detail, impact}`"),
    "extras": ("object", "Unknown fields from newer MINOR versions, kept (never silently dropped)"),
}


def export_schemas() -> list[Path]:
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    items = {"envelope": Message, "finding": Finding, "hypothesis": Hypothesis, "prediction": Prediction}
    items.update({f"payload.{k}": v for k, v in PAYLOAD_MODELS.items()})
    for name, model in items.items():
        p = SCHEMA_DIR / f"{name}.schema.json"
        schema = model.model_json_schema(by_alias=True)
        schema["$id"] = f"https://netcoop.local/schemas/nmp-1.1/{name}.schema.json"
        p.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        out.append(p)
    return out


def _thr(t: dict) -> str:
    return " / ".join(f"{t[k]:g}" for k in ("warn", "high", "critical") if k in t)


def tables() -> dict[str, str]:
    cfg = load_config()
    rows = ["| Metric | Unit | Aggregation | Direction | Range | Thresholds warn/high/critical | Aliases | Meaning |",
            "|---|---|---|---|---|---|---|---|"]
    for name, s in cfg.metrics.items():
        th = s["thresholds"]
        thr = "; ".join(f"{ctx}: {_thr(v)}" for ctx, v in th.items())
        aliases = ", ".join(f"`{a}`" for a in [*s.get("aliases", ()), *s.get("ambiguous_aliases", ())])
        rows.append(f"| `{name}` | {s['unit']} | {s['aggregation']} | {s['direction'].replace('_', ' ')} | "
                    f"{s['range'][0]}–{s['range'][1]} | {thr} | {aliases} | {s['meaning']} |")
    metrics = "\n".join(rows)
    rows = ["| fault_type | Report label | Expects (op ref ×weight) | Contradicts | Entity |", "|---|---|---|---|---|"]
    for ft, s in cfg.signatures.items():
        e = ", ".join(f"`{m}` {v['op']} {v['ref']} ×{v['weight']}" for m, v in s["expects"].items())
        c = ", ".join(f"`{m}` {v['op']} {v['ref']} ×{v['weight']}" for m, v in s.get("contradicts", {}).items())
        rows.append(f"| `{ft}` | {s['label']} | {e} | {c} | {', '.join(s['entity'])} |")
    sigs = "\n".join(rows)
    rows = ["| Rule | Type | Applies to | When | Reason |", "|---|---|---|---|---|"]
    for r in cfg.policies["rules"]:
        if r["type"] == "forbidden_action":
            acts = r["action"] if isinstance(r["action"], tuple | list) else [r["action"]]
            what = f"{', '.join(acts)} on {r.get('target_role', 'any')}"
            when = " ".join(x for x in (r.get("window", ""), ",".join(r.get("weekdays", ())),
                                         "–".join(r.get("dates", ()))) if x) or "always"
        else:
            what = f"{r['metric']} in {r['segment']}"
            when = "warn " + str(r.get("warn")) + ", high " + str(r.get("high"))
        rows.append(f"| {r['id']} | {r['type']} | {what} | {when} | {r.get('reason', '')} |")
    pol = "\n".join(rows)
    rows = ["| Field | Type | Meaning |", "|---|---|---|"]
    rows += [f"| `{k}` | {t} | {m} |" for k, (t, m) in ENVELOPE_MEANING.items()]
    env = "\n".join(rows)
    rows = ["| Field | Type | Meaning |", "|---|---|---|"]
    for k, f in Finding.model_fields.items():
        ann = getattr(f.annotation, "__name__", str(f.annotation)).replace("typing.", "")
        rows.append(f"| `{k}` | {ann} | {FINDING_MEANING.get(k, '')} |")
    fnd = "\n".join(rows)
    out = {"metrics": metrics, "signatures": sigs, "policies": pol, "envelope": env, "finding": fnd}
    rep = ROOT / "eval" / "reports"
    if (rep / "eval.md").exists():
        text = (rep / "eval.md").read_text(encoding="utf-8")
        b = text.find("## Seed range B")
        out["eval"] = (text[b:] if b >= 0 else text).replace("## Seed range B", "#### Seed range B").strip()
    if (rep / "sweep.json").exists():
        sw = json.loads((rep / "sweep.json").read_text(encoding="utf-8"))
        rows = ["| min_top_score | A accuracy | A wrong-diagnosis | A normal FP | A fault→healthy | eligible | B accuracy | "
                "B wrong-diagnosis | B normal FP | B committed precision |", "|---|---|---|---|---|---|---|---|---|---|"]
        for a_, b_ in zip(sw["A"], sw["B"], strict=False):
            ok = (a_["wrong_diagnosis_rate"] <= 0.03 and a_["false_positive_rate_normal"] <= 0.05
                  and a_.get("fault_to_no_fault_rate", 0) <= 0.03)
            mark = "**chosen**" if a_["min_top_score"] == sw["chosen"] else ("✓" if ok else "✗")
            rows.append(f"| {a_['min_top_score']:.2f} | {a_['accuracy']} | {a_['wrong_diagnosis_rate']} | "
                        f"{a_['false_positive_rate_normal']} | {a_.get('fault_to_no_fault_rate', '-')} | {mark} | {b_['accuracy']} | "
                        f"{b_['wrong_diagnosis_rate']} | {b_['false_positive_rate_normal']} | {b_['precision_when_diagnosed']} |")
        out["sweep"] = "\n".join(rows)
    if (rep / "organizer_robustness.md").exists():
        out["organizer_robustness"] = (rep / "organizer_robustness.md").read_text(encoding="utf-8").strip()
    if (rep / "organizer.md").exists():
        out["organizer"] = (rep / "organizer.md").read_text(encoding="utf-8").strip()
    if (rep / "fuzz.md").exists():
        out["fuzz"] = (rep / "fuzz.md").read_text(encoding="utf-8").replace("## Degradation", "#### Degradation").strip()
    sc = cfg.scoring
    out["constants"] = "\n".join([
        "| Constant | Value |", "|---|---|",
        f"| contra_penalty | {sc['contra_penalty']} |", f"| quality_floor | {sc['quality_floor']} |",
        f"| coerced_penalty | {sc['coerced_penalty']} |", f"| stale_quality | {sc['stale_quality']} |",
        *[f"| status.{k} | {v} |" for k, v in sc["status"].items()],
        *[f"| confidence.{k} | {v} |" for k, v in sc["confidence"].items()],
        f"| conflicts.c1_relative_diff | {sc['conflicts']['c1_relative_diff']} |"])
    return out


FINDING_MEANING = {
    "finding_id": "`F-<agent>-<n>`, unique per run",
    "metric": "Canonical name; must exist in `metrics.yaml`",
    "entity": "`{type, id}`; type ∈ device, link, ap, service; id exists in topology",
    "value": "Aggregated value, canonical unit",
    "unit": "Canonical unit from `metrics.yaml`",
    "window": "`{start, end}` UTC span of the samples used",
    "aggregation": "p95, mean, max, count, rate (from `metrics.yaml`)",
    "sample_count": "Samples aggregated",
    "threshold_ref": "e.g. `metrics.yaml#latency_ms.wireless.high` or `policies.yaml#R2.high`",
    "severity": "normal, warn, high, critical: derived from thresholds only",
    "data_quality": "`{completeness 0–1, staleness_s, coerced}`",
    "transforms": "Every normalization step applied to the underlying data",
    "source_refs": "Raw record references (`records[i].field`)",
    "source": "Originating telemetry source (snmp, probe, wifi-probe…); used for C1 conflicts",
}


def update_readme() -> None:
    text = README.read_text(encoding="utf-8")
    for key, table in tables().items():
        pat = re.compile(rf"(<!-- BEGIN GENERATED: {key} -->\n)(?:.*?\n)?(<!-- END GENERATED: {key} -->)", re.S)
        text = pat.sub(lambda m, t=table: m.group(1) + t + "\n" + m.group(2), text)
    README.write_text(text, encoding="utf-8")
