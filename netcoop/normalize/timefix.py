"""Timestamp parsing (step 8). Everything to UTC."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any


def parse_ts(raw: Any) -> tuple[datetime | None, str | None, str | None]:
    """Return (utc_datetime, transform_reason, problem)."""
    if raw is None or raw == "":
        return None, None, "missing timestamp"
    if isinstance(raw, bool):
        return None, None, "timestamp is a boolean"
    if isinstance(raw, int | float):
        v = float(raw)
        if v > 1e12:  # epoch milliseconds
            return datetime.fromtimestamp(v / 1000, UTC), "epoch ms -> UTC", None
        if v > 1e8:
            return datetime.fromtimestamp(v, UTC), "epoch s -> UTC", None
        return None, None, f"implausible epoch {raw!r}"
    if isinstance(raw, str):
        s = raw.strip()
        if s.replace(".", "", 1).isdigit():
            return parse_ts(float(s))
        try:
            dt = datetime.fromisoformat(s.replace("Z", "+00:00").replace(" UTC", "+00:00"))
        except ValueError:
            return None, None, f"unparseable timestamp {s[:40]!r}"
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC), "naive timestamp assumed UTC", None
        if dt.utcoffset() != timedelta(0):
            return dt.astimezone(UTC), "offset -> UTC", None
        return dt.astimezone(UTC), None, None
    return None, None, f"unsupported timestamp type {type(raw).__name__}"


def rfc3339(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")
