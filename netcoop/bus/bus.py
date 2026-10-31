"""In-process message bus (D3). Every message goes through the event log before delivery.

Agents never call each other: the bus delivers a message to its recipient's `handle`, validates
what comes back, appends it to the log, and returns it to the orchestrator for routing.
"""

from __future__ import annotations

import concurrent.futures as cf
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from netcoop.bus.eventlog import EventLog
from netcoop.protocol.envelope import Message, error_message


class BusBoundExceeded(RuntimeError):
    pass


@dataclass
class Delivery:
    agent_id: str
    request: Message
    outputs: list[Message] = field(default_factory=list)
    failed: bool = False
    reason: str | None = None


class Bus:
    def __init__(self, log: EventLog, *, max_messages: int, retries: int = 1):
        self.log = log
        self.max_messages = max_messages
        self.retries = retries
        self._pool = cf.ThreadPoolExecutor(max_workers=8, thread_name_prefix="agent")

    def close(self) -> None:
        self._pool.shutdown(wait=False, cancel_futures=True)

    def publish(self, msg: Message) -> Message | None:
        if len(self.log) >= self.max_messages:
            raise BusBoundExceeded(f"bus bound of {self.max_messages} messages exceeded")
        return self.log.append(msg)

    # ---------- delivery ----------
    @staticmethod
    def _collect(fut: cf.Future, timeout_s: float) -> tuple[list[Message] | None, str | None]:
        try:
            out = fut.result(timeout=timeout_s)
        except cf.TimeoutError:
            fut.cancel()
            return None, f"TIMEOUT after {timeout_s:g}s"
        except Exception as exc:  # noqa: BLE001 - agent crash is data, not a run failure
            return None, f"crashed: {type(exc).__name__}: {str(exc)[:200]}"
        if not isinstance(out, list) or not all(isinstance(m, Message) for m in out):
            return None, "INVALID_OUTPUT: handler must return list[Message]"
        return out, None

    def _validate_outputs(self, agent_id: str, request: Message, outs: list[Message]) -> str | None:
        for m in outs:
            if m.sender != agent_id:
                return f"INVALID_OUTPUT: sender {m.sender!r} != {agent_id!r}"
            if m.incident_id != request.incident_id:
                return "INVALID_OUTPUT: incident_id mismatch"
            if m.seq is not None:
                return "INVALID_OUTPUT: agents must not set seq"
            try:
                Message.model_validate(m.model_dump())
            except ValidationError as exc:
                return f"INVALID_OUTPUT: {exc.errors()[0].get('msg', '')}"[:200]
        return None

    def deliver_many(self, items: Sequence[tuple[str, Callable[[Message, Any], list[Message]], Message, Any, float]]
                     ) -> list[Delivery]:
        """Deliver requests in parallel; append requests first, then outputs in agent_id order (deterministic)."""
        for _aid, _h, req, _ctx, _t in items:
            self.publish(req)
        attempts: dict[int, tuple[list[Message] | None, str | None]] = {}
        pending = list(range(len(items)))
        for _attempt in range(self.retries + 1):
            futs = {i: self._pool.submit(items[i][1], items[i][2], items[i][3]) for i in pending}
            nxt = []
            for i, f in futs.items():
                outs, err = self._collect(f, items[i][4])
                if err is None and outs is not None:
                    err = self._validate_outputs(items[i][0], items[i][2], outs)
                attempts[i] = (outs if err is None else None, err)
                if err is not None:
                    nxt.append(i)
            pending = nxt
            if not pending:
                break
        deliveries: list[Delivery] = []
        for i in sorted(range(len(items)), key=lambda k: (items[k][0], k)):
            aid, _h, req, _ctx, _t = items[i]
            outs, err = attempts[i]
            d = Delivery(agent_id=aid, request=req)
            if err is not None:
                d.failed, d.reason = True, err
                code = "TIMEOUT" if err.startswith("TIMEOUT") else ("INVALID_OUTPUT" if err.startswith("INVALID") else "AGENT_FAILED")
                emsg = error_message(sender="orchestrator", recipient="orchestrator", incident_id=req.incident_id,
                                     code=code, detail=f"{aid} failed after {self.retries} retry: {err}",
                                     offending_message_id=req.message_id, agent_id=aid)
                stamped = self.publish(emsg)
                if stamped:
                    d.outputs.append(stamped)
            else:
                for m in outs or []:
                    stamped = self.publish(m)
                    if stamped is not None:
                        d.outputs.append(stamped)
            deliveries.append(d)
        return deliveries

    def deliver(self, agent_id: str, handler: Callable[[Message, Any], list[Message]], msg: Message, ctx: Any,
                timeout_s: float) -> Delivery:
        return self.deliver_many([(agent_id, handler, msg, ctx, timeout_s)])[0]
