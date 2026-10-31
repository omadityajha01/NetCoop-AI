"""Entity canonicalization (step 7). Unknown entity -> quarantine. Never invent topology."""

from __future__ import annotations

import re

from netcoop.topology import Topology

RAW_ID = re.compile(r"^[A-Za-z0-9_.:\-]{1,64}$")  # PI6


def canonicalize(raw: object, expected_type: str | None, topo: Topology) -> tuple[str | None, str | None, str | None]:
    """Return (entity_type, entity_id, problem)."""
    if not isinstance(raw, str | int):
        return None, None, "entity id is not a string"
    s = str(raw).strip()
    if not RAW_ID.match(s):
        return None, None, "entity id fails ID regex (PI6)"
    eid = topo.resolve(s)
    if eid is None:
        return None, None, f"unknown entity {s!r}"
    etype = topo.type_of(eid)
    if expected_type and etype != expected_type:
        return None, None, f"{s!r} resolves to {etype} {eid}, record says {expected_type}"
    return etype, eid, None
