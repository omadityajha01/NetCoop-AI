"""NetCoop CLI (the required interface, D7).

    netcoop diagnose data/scenarios/congestion/incident.json [--no-external] [--json] [--timeline]
    netcoop demo [--no-external]
    netcoop replay <incident_id>
    netcoop agents refresh
    netcoop report <incident_id> | events <incident_id>
    netcoop timeline <incident_id> --html out.html
    netcoop feedback <incident_id> <action_id> approve|reject [--note ...]
    netcoop conformance <agent_url>
    netcoop schemas | docs | serve
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from netcoop.config import ROOT, load_config
from netcoop.orchestrator.run import RUNS_DIR, RunOptions, run_incident, safe_run_dir

SCENARIOS = ["normal", "congestion", "weak_wifi", "interface_fault", "dns_failure", "dhcp_failure", "interop"]


def _c(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if sys.stdout.isatty() else s


STATUS_COLOR = {"diagnosed": "32", "probable": "33", "insufficient_evidence": "35", "no_fault_detected": "36", "failed": "31"}


def print_report(rep: dict[str, Any], *, timeline: list[dict[str, Any]] | None = None) -> None:
    st = rep["status"]
    print(f"\n{_c(rep['incident_id'], '1')}  status: {_c(st, STATUS_COLOR.get(st, '0'))}  "
          f"confidence: {rep['confidence']:.2f} ({rep.get('confidence_category', '?')})")
    print(f"  root cause : {rep['suspected_root_cause']}")
    if rep["affected_devices"]:
        print(f"  affected   : {', '.join(rep['affected_devices'])}")
    sc = rep.get("scoring")
    if sc:
        print(f"  scoring    : support {sc['support']:.2f}  coverage {sc['coverage']:.2f}  contra {sc['contra']:.2f}  "
              f"quality {sc['quality']:.2f}  margin {sc['margin']:.2f}")
    if rep["supporting_evidence"]:
        print("  evidence:")
        for e in rep["supporting_evidence"]:
            print(f"    - {e['metric']:<24} {e['value']:>10g} {e.get('unit', ''):<6} {e.get('entity', ''):<18} "
                  f"{e['interpretation']}  [{e['finding_id']}]")
    if rep.get("predictions"):
        print("  predictions (logged before evidence was requested):")
        for p in rep["predictions"]:
            mark = {"hit": _c("HIT ", "32"), "miss": _c("MISS", "31")}.get(p["outcome"], p["outcome"].upper())
            obs = "" if p["observed"] is None else f" observed {p['observed']:g}"
            print(f"    - {p['prediction_id']} [{p['hypothesis']}] {p['signal']} expected {p['expected']}: {mark}{obs}")
    if rep["alternative_causes"]:
        print("  alternatives: " + "; ".join(rep["alternative_causes"]))
    for r in rep.get("rejected_alternatives", [])[:4]:
        print(f"    rejected {r['fault_type']} ({r['score']:.2f}): {r['reason']}")
    if rep.get("missing_signals"):
        print("  missing signals: " + ", ".join(rep["missing_signals"]))
    print("  recommended actions:")
    for a in rep["recommended_actions"]:
        print(f"    - {a}")
    for b in rep.get("blocked_actions", []):
        print(f"    {_c('BLOCKED', '31')} {b['reason']}")
    print("  evidence sources: " + ", ".join(rep["evidence_sources"]))
    if rep.get("agents"):
        print("  agents: " + ", ".join(f"{k}={v}" for k, v in rep["agents"].items()))
    ns = rep.get("normalization_summary")
    if ns:
        print("  normalization: " + ", ".join(f"{k} {v}" for k, v in ns.items() if v))
    print("  limitations:")
    for lim in rep["limitations"]:
        print(f"    - {lim}")
    if rep.get("narrative"):
        print(f"  narrative: {rep['narrative']}")
    if timeline:
        print("  message timeline:")
        for e in timeline:
            p = e["payload"]
            info = ""
            if e["message_type"] in ("finding_report", "evidence_response"):
                info = f"{len(p.get('findings', []))} finding(s)" + (" + scope" if p.get("scope") else "")
            elif e["message_type"] == "task_request":
                info = p.get("task", "")
            elif e["message_type"] == "prediction":
                pr = p["prediction"]
                info = f"{pr['prediction_id']} {pr['signal']['metric']}@{pr['signal']['entity']['id']} {pr['expected']['op']} {pr['expected']['ref']}"
            elif e["message_type"] == "evidence_request":
                info = ", ".join(f"{r['metric']}@{r['entity']['id']}" for r in p.get("requests", []))
            elif e["message_type"] == "diagnosis":
                info = f"{p['phase']} {p['status']} margin {p['margin']:.2f}"
            elif e["message_type"] == "error":
                info = f"{p['code']}: {p['detail'][:60]}"
            elif e["message_type"] == "coverage_manifest":
                info = f"{len(p.get('signals', []))} signal(s)"
            print(f"    {e['seq']:>3} {e['sender']:>20} -> {e['recipient']:<20} {e['message_type']:<21} {info}")


def cmd_diagnose(a: argparse.Namespace) -> int:
    path = Path(a.path)
    data = path.read_bytes()
    res = run_incident(data, opts=RunOptions(incident_id=a.incident_id, runs_dir=Path(a.runs_dir), external=not a.no_external,
                                             filename=path.name))
    if a.json:
        print(json.dumps(res.report, indent=2))
    else:
        tl = [m.to_json_dict() for m in res.log.all()] if a.timeline else None
        print_report(res.report, timeline=tl)
        if res.run_dir:
            print(f"\n  saved: {res.run_dir / 'report.json'}  events: {res.run_dir / 'events.jsonl'}")
    return 0 if res.report["status"] != "failed" else 3


def cmd_demo(a: argparse.Namespace) -> int:
    rows = []
    for name in SCENARIOS:
        p = ROOT / "data" / "scenarios" / name / "incident.json"
        res = run_incident(p.read_bytes(), opts=RunOptions(runs_dir=Path(a.runs_dir), external=not a.no_external, filename=p.name))
        if not a.quiet:
            print(f"\n=== scenario: {name} " + "=" * 50)
            print_report(res.report)
        r = res.report
        rows.append((name, r["incident_id"], r["status"], f"{r['confidence']:.2f}", r.get("fault_type") or "-",
                     res.external_status.get("wireless_agent", "-")))
    print("\n" + "=" * 100)
    print(f"{'scenario':<16} {'incident':<14} {'status':<22} {'conf':<5} {'fault_type':<16} wireless_agent")
    for row in rows:
        print(f"{row[0]:<16} {row[1]:<14} {row[2]:<22} {row[3]:<5} {row[4]:<16} {row[5]}")
    return 0


def cmd_replay(a: argparse.Namespace) -> int:
    from netcoop.orchestrator.replay import replay

    r = replay(a.incident_id, Path(a.runs_dir))
    print(f"replay {r.incident_id}: {r.detail}")
    return 0 if r.report_identical else 1


def cmd_resume(a: argparse.Namespace) -> int:
    from netcoop.orchestrator.resume import resume

    r = resume(a.incident_id, Path(a.runs_dir))
    print(f"resume {r.incident_id}: {r.state}: {r.detail}")
    return 1 if r.state == "refused" else 0


def cmd_agents(a: argparse.Namespace) -> int:
    from netcoop.gateway.a2a_gateway import discover

    cfg = load_config()
    print("internal agents:")
    for aid, spec in cfg.agents["internal"].items():
        print(f"  {aid:<22} tools={list(spec['tools'])} owns={list(spec['owns'])}")
    disc = discover(cfg)
    print("external agents (allowlist: config/agents.yaml):")
    for aid, st in disc.status.items():
        d = disc.details.get(aid, {})
        extra = d.get("error") or f"{d.get('card_name')} v{d.get('card_version')} caps={d.get('capabilities')}"
        print(f"  {aid:<22} {st:<12} {d.get('base_url')}  {extra}")
    print("A newly reachable agent joins the next run with no restart.")
    return 0


def _run_dir(a: argparse.Namespace) -> Path:
    return safe_run_dir(Path(a.runs_dir), a.incident_id)


def cmd_report(a: argparse.Namespace) -> int:
    rep = json.loads((_run_dir(a) / "report.json").read_text(encoding="utf-8"))
    if a.json:
        print(json.dumps(rep, indent=2))
    else:
        print_report(rep)
    return 0


def cmd_events(a: argparse.Namespace) -> int:
    from netcoop.bus.eventlog import EventLog

    rep = json.loads((_run_dir(a) / "report.json").read_text(encoding="utf-8"))
    print_report(rep, timeline=EventLog.read(_run_dir(a) / "events.jsonl"))
    return 0


def cmd_timeline(a: argparse.Namespace) -> int:
    from netcoop.timeline import write_timeline

    out = Path(a.html) if a.html else _run_dir(a) / "timeline.html"
    print(f"wrote {write_timeline(_run_dir(a), out)}")
    return 0


def cmd_feedback(a: argparse.Namespace) -> int:
    from netcoop.hitl import UnknownAction, record_human_decision
    from netcoop.storage import Store

    d = _run_dir(a)
    try:
        r = record_human_decision(d, Store(Path(a.runs_dir) / "netcoop.db"), a.incident_id, a.action_id, a.decision, a.note)
    except UnknownAction as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"recorded feedback #{r['id']}: {a.decision} {a.action_id} for {a.incident_id} as event #{r['event_seq']} "
          "(non-blocking; nothing is executed; the diagnosis is unchanged)")
    return 0


def cmd_conformance(a: argparse.Namespace) -> int:
    from conformance.kit import main as kit_main

    return kit_main([a.url])


def cmd_schemas(a: argparse.Namespace) -> int:
    from netcoop.docs import export_schemas

    for p in export_schemas():
        print(f"wrote {p}")
    return 0


def cmd_docs(a: argparse.Namespace) -> int:
    from netcoop.docs import update_readme

    update_readme()
    print("README.md tables regenerated from config/*.yaml")
    return 0


def cmd_mcp(a: argparse.Namespace) -> int:
    from netcoop.mcp_server import main as mcp_main

    mcp_main()
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("netcoop.api.main:app", host="127.0.0.1", port=a.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="netcoop", description="NetCoop AI: multi-agent network fault diagnosis")
    ap.add_argument("--runs-dir", default=str(RUNS_DIR))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("diagnose", help="diagnose an incident bundle (.json/.csv)")
    p.add_argument("path")
    p.add_argument("--incident-id")
    p.add_argument("--no-external", action="store_true", help="do not discover external agents")
    p.add_argument("--json", action="store_true")
    p.add_argument("--timeline", action="store_true", help="print the inter-agent message timeline")
    p.set_defaults(fn=cmd_diagnose)
    p = sub.add_parser("demo", help="run all scenarios end-to-end")
    p.add_argument("--no-external", action="store_true")
    p.add_argument("--quiet", action="store_true")
    p.set_defaults(fn=cmd_demo)
    p = sub.add_parser("replay", help="re-run a stored incident and compare report.json byte-for-byte")
    p.add_argument("incident_id")
    p.set_defaults(fn=cmd_replay)
    p = sub.add_parser("resume", help="finish an interrupted run from its event log (idempotent)")
    p.add_argument("incident_id")
    p.set_defaults(fn=cmd_resume)
    p = sub.add_parser("agents", help="list agents; re-check the external allowlist")
    p.add_argument("action", nargs="?", default="refresh", choices=["refresh", "list"])
    p.set_defaults(fn=cmd_agents)
    for name, fn in (("report", cmd_report), ("events", cmd_events)):
        p = sub.add_parser(name)
        p.add_argument("incident_id")
        if name == "report":
            p.add_argument("--json", action="store_true")
        p.set_defaults(fn=fn)
    p = sub.add_parser("timeline", help="static HTML timeline of a run (no JS, no network)")
    p.add_argument("incident_id")
    p.add_argument("--html", help="output file (default runs/<id>/timeline.html)")
    p.set_defaults(fn=cmd_timeline)
    p = sub.add_parser("feedback", help="non-blocking approve/reject of a recommended action")
    p.add_argument("incident_id")
    p.add_argument("action_id")
    p.add_argument("decision", choices=["approve", "reject"])
    p.add_argument("--note")
    p.set_defaults(fn=cmd_feedback)
    p = sub.add_parser("conformance", help="run the conformance kit against an agent URL")
    p.add_argument("url")
    p.set_defaults(fn=cmd_conformance)
    sub.add_parser("schemas", help="export JSON Schemas to docs/schemas/").set_defaults(fn=cmd_schemas)
    sub.add_parser("docs", help="regenerate README tables from config").set_defaults(fn=cmd_docs)
    sub.add_parser("mcp", help="run NetCoop as an MCP server over stdio (tools: list_scenarios, list_agents, "
                               "diagnose, get_report, explain)").set_defaults(fn=cmd_mcp)
    p = sub.add_parser("serve", help="run the read-only API")
    p.add_argument("--port", type=int, default=8000)
    p.set_defaults(fn=cmd_serve)
    a = ap.parse_args(argv)
    try:
        return int(a.fn(a))
    except (ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
