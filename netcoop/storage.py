"""SQLite store for reports + non-blocking HITL feedback (D4, D5). Parameterized queries only."""

from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netcoop.protocol.envelope import INCIDENT_ID_PATTERN

_ID = re.compile(INCIDENT_ID_PATTERN)
SCHEMA = """
CREATE TABLE IF NOT EXISTS reports (
  incident_id TEXT PRIMARY KEY, status TEXT NOT NULL, root_cause TEXT NOT NULL, confidence REAL NOT NULL,
  created_at TEXT NOT NULL, report_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback (
  id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT NOT NULL, action_id TEXT NOT NULL,
  decision TEXT NOT NULL CHECK (decision IN ('approve','reject')), note TEXT, created_at TEXT NOT NULL);
"""


def valid_incident_id(incident_id: str) -> bool:
    return isinstance(incident_id, str) and bool(_ID.fullmatch(incident_id))


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with self._conn() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        try:
            with conn:  # commit / rollback
                yield conn
        finally:
            conn.close()  # always close (Windows keeps the file locked otherwise)

    def save_report(self, report: dict[str, Any]) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT OR REPLACE INTO reports (incident_id, status, root_cause, confidence, created_at, report_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (report["incident_id"], report["status"], report["suspected_root_cause"], float(report["confidence"]),
                 datetime.now(UTC).isoformat(), json.dumps(report, sort_keys=True)),
            )

    def get_report(self, incident_id: str) -> dict[str, Any] | None:
        if not valid_incident_id(incident_id):
            return None
        with self._conn() as c:
            row = c.execute("SELECT report_json FROM reports WHERE incident_id = ?", (incident_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def list_reports(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT incident_id, status, root_cause, confidence, created_at FROM reports "
                             "ORDER BY created_at DESC LIMIT ?", (int(limit),)).fetchall()
        return [dict(zip(("incident_id", "status", "suspected_root_cause", "confidence", "created_at"), r, strict=True))
                for r in rows]

    def add_feedback(self, incident_id: str, action_id: str, decision: str, note: str | None) -> int:
        if not valid_incident_id(incident_id):
            raise ValueError("bad incident_id")
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve|reject")
        if not re.fullmatch(r"[A-Z]{2,6}-[0-9]{1,3}", action_id or ""):
            raise ValueError("bad action_id")
        with self._conn() as c:
            cur = c.execute("INSERT INTO feedback (incident_id, action_id, decision, note, created_at) VALUES (?, ?, ?, ?, ?)",
                            (incident_id, action_id, decision, (note or "")[:500], datetime.now(UTC).isoformat()))
            return int(cur.lastrowid or 0)

    def feedback(self, incident_id: str) -> list[dict[str, Any]]:
        with self._conn() as c:
            rows = c.execute("SELECT action_id, decision, note, created_at FROM feedback WHERE incident_id = ? ORDER BY id",
                             (incident_id,)).fetchall()
        return [dict(zip(("action_id", "decision", "note", "created_at"), r, strict=True)) for r in rows]
