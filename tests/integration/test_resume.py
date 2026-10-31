"""M4: `netcoop resume` after a hard kill (os._exit, no cleanup) right after round 0 -> byte-identical report."""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap

import pytest

from netcoop.orchestrator.replay import replay
from netcoop.orchestrator.resume import resume
from netcoop.orchestrator.run import RunOptions, run_incident
from tests.conftest import ROOT, scenario_bytes

IID = "INC-RESUME01"

KILL = textwrap.dedent("""
    import os, sys
    from pathlib import Path
    import netcoop.agents.correlation as corr
    from netcoop.orchestrator.run import RunOptions, run_incident

    def die(self, msg, ctx):  # round 0 is logged; the first correlation task kills the process, no cleanup
        os._exit(137)

    corr.CorrelationAgent.handle = die
    run_incident(Path(sys.argv[1]).read_bytes(), opts=RunOptions(incident_id=sys.argv[3], runs_dir=Path(sys.argv[2]),
                 external=False, filename="incident.json"))
""")


@pytest.mark.parametrize("scenario", ["congestion", "interop"])
def test_kill_after_round0_then_resume_is_byte_identical(tmp_path, cfg, scenario):
    ref = run_incident(scenario_bytes(scenario), cfg, RunOptions(incident_id=IID, runs_dir=tmp_path / "ref",
                                                                 external=False, filename="incident.json"))
    ref_dir = tmp_path / "ref" / IID

    (tmp_path / "kill.py").write_text(KILL, encoding="utf-8")
    (tmp_path / "in.json").write_bytes(scenario_bytes(scenario))
    runs = tmp_path / "runs"
    p = subprocess.run([sys.executable, str(tmp_path / "kill.py"), str(tmp_path / "in.json"), str(runs), IID],
                       cwd=ROOT, capture_output=True, timeout=120)
    assert p.returncode == 137, p.stderr.decode()[-2000:]
    d = runs / IID
    assert not (d / "report.json").exists() and (d / "meta.json").exists() and (d / "input.json").exists()
    logged = [json.loads(x) for x in (d / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    assert logged and logged[-1]["recipient"] == "correlation_agent"  # died at the first correlation task
    assert {m["sender"] for m in logged} >= {"performance_agent", "infrastructure_agent", "connectivity_agent"}

    r = resume(IID, runs, cfg)
    assert r.state == "resumed" and r.kept == len(logged) and r.appended > 0, r.detail
    assert (d / "report.json").read_bytes() == (ref_dir / "report.json").read_bytes()
    strip = lambda p: [{k: v for k, v in json.loads(x).items() if k != "created_at"}  # noqa: E731
                       for x in p.read_text(encoding="utf-8").splitlines()]
    assert strip(d / "events.jsonl") == strip(ref_dir / "events.jsonl")
    assert replay(IID, runs, cfg).report_identical
    assert ref.report["incident_id"] == IID

    # idempotent: a second resume changes nothing
    before = {f.name: f.read_bytes() for f in d.iterdir()}
    assert resume(IID, runs, cfg).state == "already_complete"
    assert {f.name: f.read_bytes() for f in d.iterdir()} == before


def test_torn_final_line_is_dropped_and_rederived(tmp_path, cfg):
    runs = tmp_path / "runs"
    run_incident(scenario_bytes("congestion"), cfg, RunOptions(incident_id=IID, runs_dir=runs, external=False))
    d = runs / IID
    full = (d / "report.json").read_bytes()
    lines = (d / "events.jsonl").read_text(encoding="utf-8").splitlines()
    (d / "report.json").unlink()
    (d / "events.jsonl").write_text("\n".join(lines[:12]) + "\n" + lines[12][:40], encoding="utf-8")  # crash mid-append
    r = resume(IID, runs, cfg)
    assert r.state == "resumed" and r.kept == 12 and "torn" in r.detail
    assert (d / "report.json").read_bytes() == full


def test_divergent_log_is_refused_and_nothing_changes(tmp_path, cfg):
    runs = tmp_path / "runs"
    run_incident(scenario_bytes("congestion"), cfg, RunOptions(incident_id=IID, runs_dir=runs, external=False))
    d = runs / IID
    (d / "report.json").unlink()
    lines = (d / "events.jsonl").read_text(encoding="utf-8").splitlines()[:10]
    e = json.loads(lines[4])
    e["status"] = "failed"  # the stored log no longer matches what the input deterministically produces
    lines[4] = json.dumps(e, sort_keys=True)
    (d / "events.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    before = {f.name: f.read_bytes() for f in d.iterdir()}
    r = resume(IID, runs, cfg)
    assert r.state == "refused" and "seq 5" in r.detail
    assert {f.name: f.read_bytes() for f in d.iterdir()} == before


@pytest.mark.parametrize("bad", ["../x", "INC-../../etc", "inc-0001"])
def test_resume_rejects_bad_ids(tmp_path, bad):
    with pytest.raises(ValueError):
        resume(bad, tmp_path)


def test_resume_refuses_llm_runs(tmp_path, cfg):
    d = tmp_path / IID
    d.mkdir()
    (d / "meta.json").write_text(json.dumps({"llm": "local", "input_file": "input.json"}), encoding="utf-8")
    assert resume(IID, tmp_path, cfg).state == "refused"
