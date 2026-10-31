"""Append-only JSONL event log. Assigns monotonic `seq` on append, before delivery (§7.4)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from netcoop.protocol.envelope import Message


class EventLog:
    def __init__(self, path: Path | None, *, clock: Any = None):
        self.path = path
        self._messages: list[Message] = []
        self._ids: set[str] = set()
        self._clock = clock or (lambda: datetime.now(UTC))
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("", encoding="utf-8")

    def append(self, msg: Message) -> Message | None:
        """Append and return the stamped message. Duplicate message_id -> ignored (idempotent), returns None."""
        if msg.message_id in self._ids:
            return None
        stamped = msg.model_copy(update={"seq": len(self._messages) + 1, "created_at": msg.created_at or self._clock()})
        self._messages.append(stamped)
        self._ids.add(stamped.message_id)
        if self.path is not None:
            with self.path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(stamped.to_json_dict(), sort_keys=True, ensure_ascii=True) + "\n")
        return stamped

    # ---------- read-only views ----------
    def __len__(self) -> int:
        return len(self._messages)

    def all(self) -> tuple[Message, ...]:
        return tuple(self._messages)

    def by_type(self, *types: str) -> list[Message]:
        return [m for m in self._messages if m.message_type in types]

    def get(self, message_id: str) -> Message | None:
        for m in self._messages:
            if m.message_id == message_id:
                return m
        return None

    @staticmethod
    def read(path: Path) -> list[dict[str, Any]]:
        out = []
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out
