"""`netcoop resume <incident_id>`: finish an interrupted run from its directory (M4).

A run persists its input and meta.json before any agent runs, and every message is appended to events.jsonl before
delivery (§7.4). If the process dies part-way (no report.json), resume:

1. reads the surviving log (a torn final line from the crash is dropped and noted);
2. re-derives the run deterministically from the stored input with the same incident_id. Agents are pure and the
   orchestrator's state is derived from the log, so the same input gives the same messages. External exchanges
   already recorded in external.jsonl are served from the recording; only exchanges never made are sent live;
3. checks that the surviving log is an exact prefix of the re-derived one (ignoring wall-clock `created_at`). If
   it is not, it refuses and changes nothing;
4. keeps the surviving lines verbatim, appends the missing messages, then writes report.json and meta.json.

Idempotent: if report.json exists, resume changes nothing. With NETCOOP_LLM != off the run is not reproducible,
so resume refuses.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from netcoop.config import Config, load_config
from netcoop.gateway.transport import (
    HttpTransport,
    RecordingTransport,
    ReplayTransport,
    Transport,
    TransportError,
)
from netcoop.orchestrator.run import RUNS_DIR, Orchestrator, RunOptions, dump_report, safe_run_dir
from netcoop.storage import Store


@dataclass
class ResumeResult:
    incident_id: str
    state: str  # already_complete | resumed | refused
    kept: int = 0
    appended: int = 0
    detail: str = ""


class _RecordedThenLive:
    """Serve what the interrupted run already exchanged; go live (and record) only for exchanges never made."""

    def __init__(self, path: Path, live: Transport):
        self._replay = ReplayTransport(path)
        self._path, self._inner = path, live
        self._recorder: RecordingTransport | None = None  # created on first live exchange (never touches disk before)

    @property
    def _live(self) -> RecordingTransport:
        if self._recorder is None:
            self._recorder = RecordingTransport(self._inner, self._path, append=True)
        return self._recorder

    def get(self, url: str, timeout: float, max_bytes: int, key: str) -> bytes:
        try:
            return self._replay.get(url, timeout, max_bytes, key)
        except TransportError as exc:
            if exc.detail != "not in recording":
                raise
            return self._live.get(url, timeout, max_bytes, key)

    def post(self, url: str, body: bytes, timeout: float, max_bytes: int, key: str) -> bytes:
        try:
            return self._replay.post(url, body, timeout, max_bytes, key)
        except TransportError as exc:
            if exc.detail != "not in recording":
                raise
            return self._live.post(url, body, timeout, max_bytes, key)


def _read_log(path: Path) -> tuple[list[str], bool]:
    """Complete JSON lines of the log, plus whether a torn final line was dropped."""
    if not path.exists():
        return [], False
    text = path.read_text(encoding="utf-8")
    lines = text.split("\n")
    kept, torn = [], False
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        try:
            json.loads(line)
        except ValueError:
            if i == len(lines) - 1 or all(not x.strip() for x in lines[i + 1:]):
                torn = True  # the crash cut the last append short
                break
            raise
        kept.append(line)
    return kept, torn


def _cmp(e: dict) -> dict:
    return {k: v for k, v in e.items() if k != "created_at"}


def resume(incident_id: str, runs_dir: Path = RUNS_DIR, cfg: Config | None = None,
           live: Transport | None = None) -> ResumeResult:
    run_dir = safe_run_dir(runs_dir, incident_id)
    if (run_dir / "report.json").is_file():
        return ResumeResult(incident_id, "already_complete", detail="report.json exists; nothing to do")
    meta_p = run_dir / "meta.json"
    if not meta_p.is_file():
        return ResumeResult(incident_id, "refused", detail="no meta.json: this run never started or is not a NetCoop run")
    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    if meta.get("llm", "off") != "off":
        return ResumeResult(incident_id, "refused", detail="run used an LLM; deterministic resume requires NETCOOP_LLM=off")
    raw = (run_dir / meta["input_file"]).read_bytes()
    old_lines, torn = _read_log(run_dir / "events.jsonl")
    old = [json.loads(x) for x in old_lines]

    cfg = cfg or load_config()
    with tempfile.TemporaryDirectory() as tmp:
        opts = RunOptions(incident_id=incident_id, runs_dir=Path(tmp), external=bool(meta.get("external", True)),
                          transport=_RecordedThenLive(run_dir / "external.jsonl", live or HttpTransport()),
                          record_external=False, store=False, filename=meta.get("filename"))
        res = Orchestrator(cfg, opts).run(raw)
        new_dir = Path(tmp) / incident_id
        new_lines = [x for x in (new_dir / "events.jsonl").read_text(encoding="utf-8").split("\n") if x.strip()]
        new_meta = (new_dir / "meta.json").read_bytes()

    new = [json.loads(x) for x in new_lines]
    if len(old) > len(new) or [_cmp(e) for e in old] != [_cmp(e) for e in new[:len(old)]]:
        first = next((i for i, (a, b) in enumerate(zip(old, new, strict=False)) if _cmp(a) != _cmp(b)), min(len(old), len(new)))
        return ResumeResult(incident_id, "refused", kept=len(old),
                            detail=f"surviving log diverges from the deterministic re-run at seq {first + 1}; nothing changed")

    with (run_dir / "events.jsonl").open("w", encoding="utf-8", newline="\n") as fh:
        for line in old_lines + new_lines[len(old):]:
            fh.write(line + "\n")
    (run_dir / "report.json").write_bytes(dump_report(res.report))
    (run_dir / "meta.json").write_bytes(new_meta)
    try:
        Store(runs_dir / "netcoop.db").save_report(res.report)
    except Exception:  # noqa: BLE001 - storage must never fail a diagnosis
        pass
    detail = f"kept {len(old)} logged message(s), appended {len(new) - len(old)}"
    if torn:
        detail += "; dropped a torn final line left by the crash"
    return ResumeResult(incident_id, "resumed", kept=len(old), appended=len(new) - len(old), detail=detail)
