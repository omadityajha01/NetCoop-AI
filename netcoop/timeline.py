"""`netcoop timeline <incident_id> --html <out>`: one static HTML file from events.jsonl + report.json.

No JavaScript, no CDN, no network. Every data value is HTML-escaped (PI8): device names, field names and
agent strings render as text, never as markup.
"""

from __future__ import annotations

import html
import json
from collections import Counter
from pathlib import Path
from typing import Any

from netcoop.bus.eventlog import EventLog

LANE_ORDER = ["normalizer", "orchestrator", "triage_agent", "performance_agent", "infrastructure_agent", "connectivity_agent",
              "wireless_agent", "correlation_agent", "reporting_agent"]
TYPE_CLASS = {"task_request": "t-task", "finding_report": "t-find", "coverage_manifest": "t-cov", "prediction": "t-pred",
              "evidence_request": "t-req", "evidence_response": "t-resp", "diagnosis": "t-diag", "report": "t-rep",
              "error": "t-err", "normalization_summary": "t-norm", "hint": "t-hint"}

CSS = """
*{box-sizing:border-box} body{font:14px/1.45 system-ui,-apple-system,Segoe UI,Roboto,sans-serif;margin:0;background:#fcfcfb;color:#0b0b0b}
header{padding:20px 28px;border-bottom:1px solid #e1e0d9;background:#fff} h1{font-size:20px;margin:0 0 6px} h2{font-size:16px;margin:28px 0 10px}
main{padding:0 28px 40px} .muted{color:#52514e} .pill{display:inline-block;padding:2px 10px;border-radius:999px;font-weight:600;font-size:12px}
.s-diagnosed{background:#d9f2d9;color:#004d00} .s-probable{background:#fff1c7;color:#5c4300} .s-insufficient_evidence{background:#f1e4f7;color:#4d1a66}
.s-no_fault_detected{background:#dcecfb;color:#0b3d75} .s-failed{background:#fde0e0;color:#7a0b0b}
table{border-collapse:collapse;width:100%;background:#fff} th,td{border-bottom:1px solid #e1e0d9;padding:6px 8px;text-align:left;vertical-align:top;font-size:13px}
th{color:#52514e;font-weight:600;background:#f6f6f3} code{font:12px ui-monospace,Consolas,monospace;background:#f1f1ee;padding:1px 4px;border-radius:4px;word-break:break-all}
.lanes{display:grid;gap:0;border:1px solid #e1e0d9;background:#fff;overflow-x:auto}
.lh{position:sticky;top:0;background:#f6f6f3;font-weight:600;font-size:12px;padding:6px;border-bottom:1px solid #e1e0d9;border-left:1px solid #eeede8}
.cell{border-left:1px solid #eeede8;border-bottom:1px solid #f3f2ee;padding:4px 6px;min-height:28px;font-size:12px}
.seq{color:#52514e;font-variant-numeric:tabular-nums;border-bottom:1px solid #f3f2ee;padding:4px 6px;font-size:12px}
.msg{border-radius:6px;padding:3px 6px;border-left:4px solid #888;background:#f6f6f3}
.t-task{border-color:#52514e}.t-find{border-color:#2a78d6}.t-cov{border-color:#9bbbe6}.t-pred{border-color:#6250d6}
.t-req{border-color:#eb6834}.t-resp{border-color:#1baf7a}.t-diag{border-color:#eda100}.t-rep{border-color:#008300}
.t-err{border-color:#e34948;background:#fdecec}.t-norm{border-color:#e87ba4}.t-hint{border-color:#6250d6;border-left-style:dashed}
.hit{background:#d9f2d9;color:#004d00}.miss{background:#fde0e0;color:#7a0b0b}.unknown,.pending{background:#eeede8;color:#52514e}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:24px} @media (max-width:1000px){.grid2{grid-template-columns:1fr}}
.blocked{color:#7a0b0b;font-weight:600} ul{margin:6px 0;padding-left:20px}
"""


def e(v: Any) -> str:
    """Escape any data value for HTML text or attribute context."""
    return html.escape("" if v is None else str(v), quote=True)


def _info(m: dict[str, Any]) -> str:
    p = m.get("payload", {})
    t = m["message_type"]
    if t == "task_request":
        return f"task: {p.get('task')}"
    if t in ("finding_report", "evidence_response"):
        s = f"{len(p.get('findings', []))} finding(s)"
        if p.get("unavailable"):
            s += f", {len(p['unavailable'])} unavailable"
        return s + (" + scope" if p.get("scope") else "")
    if t == "coverage_manifest":
        return f"{len(p.get('signals', []))} signal(s)"
    if t == "prediction":
        pr = p["prediction"]
        return (f"{pr['prediction_id']} [{pr['fault_type']}] {pr['signal']['metric']}@{pr['signal']['entity']['id']} "
                f"{pr['expected']['op']} {pr['expected']['ref']}")
    if t == "evidence_request":
        return ", ".join(f"{r['metric']}@{r['entity']['id']}" for r in p.get("requests", []))
    if t == "diagnosis":
        return f"{p['phase']}: {p['status']} (margin {p['margin']:.2f})"
    if t == "error":
        return f"{p.get('code')}: {p.get('detail', '')[:120]}"
    if t == "normalization_summary":
        s = p.get("summary", {})
        return f"{s.get('records_used', 0)}/{s.get('records_in', 0)} records used, {s.get('records_quarantined', 0)} quarantined"
    if t == "report":
        return f"status {p['report'].get('status')}"
    if t == "hint":
        return f"LLM hint (advisory): {p.get('fault_type')}: {p.get('rationale', '')}"
    return ""


def render(events: list[dict[str, Any]], report: dict[str, Any]) -> str:
    agents = sorted({m["sender"] for m in events}, key=lambda a: (LANE_ORDER.index(a) if a in LANE_ORDER else 99, a))
    cols = len(agents)
    out: list[str] = ["<!DOCTYPE html><html lang='en'><head><meta charset='utf-8'>",
                      "<meta name='viewport' content='width=device-width,initial-scale=1'>",
                      f"<title>NetCoop timeline {e(report.get('incident_id'))}</title><style>{CSS}</style></head><body>"]
    st = report.get("status", "")
    out.append(f"<header><h1>{e(report.get('incident_id'))} <span class='pill s-{e(st)}'>{e(st)}</span></h1>"
               f"<div>{e(report.get('suspected_root_cause'))}</div>"
               f"<div class='muted'>confidence {e(report.get('confidence'))} ({e(report.get('confidence_category'))}) · "
               f"{len(events)} messages · NMP {e(report.get('schema_version'))}</div></header><main>")

    # ---- lanes
    out.append("<h2>Message timeline (one lane per agent, in seq order)</h2>")
    out.append(f"<div class='lanes' style='grid-template-columns:44px repeat({cols}, minmax(150px,1fr))'>")
    out.append("<div class='lh'>seq</div>" + "".join(f"<div class='lh'>{e(a)}</div>" for a in agents))
    for m in events:
        out.append(f"<div class='seq'>{e(m.get('seq'))}</div>")
        for a in agents:
            if a == m["sender"]:
                cls = TYPE_CLASS.get(m["message_type"], "")
                out.append(f"<div class='cell'><div class='msg {cls}'><b>{e(m['message_type'])}</b> → {e(m['recipient'])}"
                           f"<br><span class='muted'>{e(_info(m))}</span></div></div>")
            else:
                out.append("<div class='cell'></div>")
    out.append("</div>")

    # ---- predictions -> evidence
    seq_of_pred = {m["payload"]["prediction"]["prediction_id"]: m["seq"] for m in events if m["message_type"] == "prediction"}
    req_of_pred: dict[str, dict] = {}
    for m in events:
        if m["message_type"] == "evidence_request":
            for pid in m["payload"].get("prediction_ids", []):
                req_of_pred[pid] = m
    resp_of_req = {m.get("in_reply_to"): m for m in events if m["message_type"] == "evidence_response"}
    out.append("<h2>Predictions → evidence (logged before looking)</h2><table><tr><th>prediction</th><th>hypothesis</th>"
               "<th>signal</th><th>expected</th><th>seq: predicted → requested → answered</th><th>observed</th><th>outcome</th></tr>")
    preds = report.get("predictions", [])
    if not preds:
        out.append("<tr><td colspan='7' class='muted'>no predictions in this run</td></tr>")
    for p in preds:
        req = req_of_pred.get(p["prediction_id"])
        resp = resp_of_req.get(req["message_id"]) if req else None
        seqs = f"{seq_of_pred.get(p['prediction_id'], '?')} → {req['seq'] if req else '?'} → {resp['seq'] if resp else '?'}"
        out.append(f"<tr><td><code>{e(p['prediction_id'])}</code></td><td>{e(p['hypothesis'])}</td><td><code>{e(p['signal'])}</code></td>"
                   f"<td>{e(p['expected'])}</td><td>{e(seqs)}</td><td>{e(p.get('observed'))}</td>"
                   f"<td><span class='pill {e(p['outcome'])}'>{e(p['outcome'])}</span></td></tr>")
    out.append("</table>")

    # ---- normalization
    norm = next((m["payload"] for m in events if m["message_type"] == "normalization_summary"), {})
    out.append("<h2>Normalization</h2><div class='grid2'><div>")
    summ = norm.get("summary", {})
    out.append("<table><tr><th>counter</th><th>value</th></tr>" +
               "".join(f"<tr><td>{e(k)}</td><td>{e(v)}</td></tr>" for k, v in summ.items() if v) + "</table>")
    steps: Counter = Counter()
    examples: dict[tuple, dict] = {}
    for m in events:
        if m["message_type"] in ("finding_report", "evidence_response"):
            for f in m["payload"].get("findings", []):
                for t in f.get("transforms", []):
                    key = (t["step"], t["field"], str(t.get("to"))[:30] if t["step"] in ("alias", "entity") else "")
                    steps[key] += 1
                    examples.setdefault(key, t)
    out.append("<h3>Transforms applied to evidence</h3><table><tr><th>step</th><th>field</th><th>example</th><th>findings</th></tr>")
    for key, n in steps.most_common(40):
        t = examples[key]
        out.append(f"<tr><td>{e(t['step'])}</td><td><code>{e(t['field'])}</code></td>"
                   f"<td><code>{e(t.get('from'))}</code> → <code>{e(t.get('to'))}</code> <span class='muted'>{e(t['reason'])}</span></td>"
                   f"<td>{n}</td></tr>")
    out.append("</table></div><div>")
    out.append("<h3>Quarantined (never silently dropped)</h3><table><tr><th>where</th><th>code</th><th>reason</th></tr>")
    q = norm.get("quarantined", [])
    if not q:
        out.append("<tr><td colspan='3' class='muted'>nothing quarantined</td></tr>")
    for item in q[:60]:
        out.append(f"<tr><td><code>{e(item.get('source_ref'))}</code></td><td>{e(item.get('code'))}</td><td>{e(item.get('reason'))}</td></tr>")
    out.append("</table>")
    ex = norm.get("extras", [])
    if ex:
        out.append("<h3>Kept in extras (not evidence)</h3><table><tr><th>where</th><th>field</th><th>value</th><th>note</th></tr>")
        for item in ex[:40]:
            out.append(f"<tr><td><code>{e(item.get('source_ref'))}</code></td><td><code>{e(item.get('field'))}</code></td>"
                       f"<td>{e(item.get('value'))}</td><td>{e(item.get('note'))}</td></tr>")
        out.append("</table>")
    out.append("</div></div>")

    # ---- final report
    out.append("<h2>Final report</h2><div class='grid2'><div>")
    out.append("<table><tr><th>metric</th><th>value</th><th>entity</th><th>interpretation</th><th>finding</th></tr>")
    for ev in report.get("supporting_evidence", []):
        out.append(f"<tr><td><code>{e(ev['metric'])}</code></td><td>{e(ev['value'])} {e(ev.get('unit'))}</td>"
                   f"<td>{e(ev.get('entity'))}</td><td>{e(ev['interpretation'])}</td><td><code>{e(ev['finding_id'])}</code></td></tr>")
    if not report.get("supporting_evidence"):
        out.append("<tr><td colspan='5' class='muted'>no supporting evidence</td></tr>")
    out.append("</table>")
    if report.get("observations"):
        out.append("<h3>Observations (context, not evidence)</h3><ul>" +
                   "".join(f"<li>{e(o['interpretation'])}: {e(o['value'])} {e(o.get('unit'))} on {e(o['entity'])}</li>"
                           for o in report["observations"]) + "</ul>")
    if report.get("missing_signals"):
        out.append("<h3>Missing signals</h3><ul>" + "".join(f"<li><code>{e(s)}</code></li>" for s in report["missing_signals"]) + "</ul>")
    out.append("</div><div><h3>Recommended actions</h3><ul>" +
               "".join(f"<li>{e(a)}</li>" for a in report.get("recommended_actions", [])) + "</ul>")
    if report.get("blocked_actions"):
        out.append("<h3>Blocked by policy</h3><ul>" +
                   "".join(f"<li class='blocked'>{e(b['reason'])}</li>" for b in report["blocked_actions"]) + "</ul>")
    out.append("<h3>Alternatives</h3><ul>" + "".join(f"<li>{e(a)}</li>" for a in report.get("alternative_causes", [])) + "</ul>")
    out.append("<h3>Limitations</h3><ul>" + "".join(f"<li>{e(lim)}</li>" for lim in report.get("limitations", [])) + "</ul>")
    out.append("</div></div></main></body></html>")
    return "\n".join(out)


def write_timeline(run_dir: Path, out: Path) -> Path:
    events = EventLog.read(run_dir / "events.jsonl")
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(events, report), encoding="utf-8")
    return out
