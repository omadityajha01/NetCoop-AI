"""V2: Windows demo safety: loopback-only binds, snapshot freshness, presentation flags."""

from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from netcoop import present
from tests.conftest import ROOT, free_port

NODE = shutil.which("node")
AGENT = str(ROOT / "external_agents" / "wireless_agent" / "server.js")


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_agent_refuses_non_loopback_bind():
    r = subprocess.run([NODE, AGENT, "--host", "0.0.0.0", "--port", str(free_port())], capture_output=True,
                       text=True, timeout=20)
    assert r.returncode == 2 and "loopback only" in r.stderr


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_agent_is_not_reachable_on_lan_address():
    port = free_port()
    agent = present.Agent(port)
    try:
        assert agent.start()
        ok, detail = present.loopback_only(port)
        assert ok, detail
    finally:
        agent.stop()


def test_api_server_binds_loopback():
    src = (ROOT / "netcoop" / "cli.py").read_text(encoding="utf-8")
    assert 'host="127.0.0.1"' in src and "0.0.0.0" not in src


def test_fingerprint_detects_changes(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    f = tmp_path / "config" / "x.yaml"
    f.write_text("a: 1\n", encoding="utf-8")
    monkeypatch.setattr(present, "ROOT", tmp_path)
    monkeypatch.setattr(present, "_tracked_files", lambda dirs: sorted((tmp_path / "config").rglob("*")))
    h1 = present.content_hash(("config",))
    f.write_bytes(b"a: 1\r\n")  # CRLF checkout -> same hash
    assert present.content_hash(("config",)) == h1
    f.write_text("a: 2\n", encoding="utf-8")
    assert present.content_hash(("config",)) != h1


def test_committed_snapshots_are_fresh():
    meta = json.loads((ROOT / "demo_snapshots" / "meta.json").read_text(encoding="utf-8"))
    cur = present.fingerprint()
    assert meta["source_hash"] == cur["source_hash"], "run `python tasks.py snapshots` and commit demo_snapshots/"
    assert meta["config_hash"] == cur["config_hash"]


def test_no_color_has_no_ansi(capsys):
    present.set_color(False)
    try:
        print(present.ok("PASS"), present.bad("FAIL"), present.c("x", "1"))
    finally:
        present.set_color(present.TTY)
    assert "\033[" not in capsys.readouterr().out


@pytest.mark.skipif(not NODE, reason="node not installed")
def test_auto_delay_runs_hands_free(tmp_path, monkeypatch):
    sleeps = []
    real_sleep = present.time.sleep

    def fake_sleep(s):  # record the between-step pause; keep real sleeps elsewhere (agent start-up polling)
        if s == 2.5:
            sleeps.append(s)
        else:
            real_sleep(s)

    monkeypatch.setattr(present.time, "sleep", fake_sleep)
    assert present.present(free_port(), auto=True, out=tmp_path / "snap", delay=2.5) == 0
    assert sleeps.count(2.5) == len(present.STEPS) - 1  # one pause between consecutive steps
