"""Non-blocking human-in-the-loop (D5): approve/reject a recommended action.

The decision is stored in SQLite (with the optional free-text note) and appended to the run's event log as an NMP
`human_decision` message, after the report. It never executes anything (D8/G2) and never changes the diagnosis:
report.json is not touched, and `netcoop replay` ignores human_decision events.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netcoop.protocol.envelope import make_message
from netcoop.storage import Store


class UnknownAction(ValueError):
    pass


def report_action_ids(report: dict[str, Any]) -> set[str]:
    ids = {a["id"] for a in report.get("action_details", []) if a.get("id")}
    ids |= {b["action_id"] for b in report.get("blocked_actions", []) if b.get("action_id")}
    return ids


def record_human_decision(run_dir: Path, store: Store, incident_id: str, action_id: str, decision: str,
                          note: str | None) -> dict[str, Any]:
    report = json.loads((run_dir / "report.json").read_text(encoding="utf-8"))
    if action_id not in report_action_ids(report):
        raise UnknownAction(f"{action_id} is not an action of {incident_id}")
    fid = store.add_feedback(incident_id, action_id, decision, note)
    log = run_dir / "events.jsonl"
    lines = [x for x in log.read_text(encoding="utf-8").splitlines() if x.strip()]
    seq = json.loads(lines[-1])["seq"] + 1 if lines else 1
    msg = make_message("human_decision", sender="human_operator", recipient="orchestrator", incident_id=incident_id,
                       payload={"action_id": action_id, "decision": decision, "feedback_id": fid,
                                "note_stored": bool(note)}, salt=fid)
    stamped = msg.model_copy(update={"seq": seq, "created_at": datetime.now(UTC)})
    with log.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(stamped.to_json_dict(), sort_keys=True, ensure_ascii=True) + "\n")
    return {"id": fid, "executed": False, "event_seq": seq, "message_id": stamped.message_id}
