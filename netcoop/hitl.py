"""Non-blocking human-in-the-loop (D5): approve/reject a recommended action.

The decision is stored in SQLite (with the optional free-text note) and appended to the run's event log as an NMP
`human_decision` message, after the report. On approve, the policy checker runs again. If the action is allowed, an
NMP `remediation_plan` dry-run follows, labelled "SIMULATED – NOT EXECUTED" (S1). Nothing is ever executed (D8/G2),
and the diagnosis never changes: report.json is not touched, and `netcoop replay` ignores both message types.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netcoop.config import Config, load_config
from netcoop.protocol.envelope import Message, make_message
from netcoop.remediation import load_events, plan_for
from netcoop.storage import Store

POST_RUN_TYPES = ("human_decision", "remediation_plan")  # appended after the report; never part of the diagnosis


class UnknownAction(ValueError):
    pass


def report_action_ids(report: dict[str, Any]) -> set[str]:
    ids = {a["id"] for a in report.get("action_details", []) if a.get("id")}
    ids |= {b["action_id"] for b in report.get("blocked_actions", []) if b.get("action_id")}
    return ids


def _append(log: Path, msg: Message, seq: int) -> Message:
    stamped = msg.model_copy(update={"seq": seq, "created_at": datetime.now(UTC)})
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(stamped.to_json_dict(), sort_keys=True, ensure_ascii=True) + "\n")
    return stamped


def record_human_decision(run_dir: Path, store: Store, incident_id: str, action_id: str, decision: str,
                          note: str | None, cfg: Config | None = None) -> dict[str, Any]:
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    if action_id not in report_action_ids(report):
        raise UnknownAction(f"{action_id} is not an action of {incident_id}")
    fid = store.add_feedback(incident_id, action_id, decision, note)
    log = run_dir / "events.jsonl"
    events = load_events(log)
    seq = events[-1]["seq"] + 1 if events else 1
    hd = _append(log, make_message("human_decision", sender="human_operator", recipient="orchestrator",
                                   incident_id=incident_id, salt=fid,
                                   payload={"action_id": action_id, "decision": decision, "feedback_id": fid,
                                            "note_stored": bool(note)}), seq)
    out: dict[str, Any] = {"id": fid, "executed": False, "event_seq": seq, "message_id": hd.message_id,
                           "policy": None, "plan_seq": None, "plan": None}
    if decision != "approve":
        return out
    plan, policy = plan_for(cfg or load_config(), report, events, action_id)
    out["policy"] = policy
    if plan is None:
        return out  # blocked (rule id in `policy`) or not plannable: no plan is ever emitted
    msg = make_message("remediation_plan", sender="remediation_planner", recipient="human_operator",
                       incident_id=incident_id, in_reply_to=hd.message_id, salt=fid,
                       payload={**plan, "human_decision_seq": seq})
    stamped = _append(log, msg, seq + 1)
    out["plan_seq"] = seq + 1
    out["plan"] = stamped.payload
    return out
