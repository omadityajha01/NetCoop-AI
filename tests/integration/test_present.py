"""T10: the scripted presentation runs end-to-end non-interactively and writes per-step fallbacks."""

from __future__ import annotations

import json
import shutil

import pytest

from netcoop import present
from tests.conftest import free_port


@pytest.mark.skipif(not shutil.which("node"), reason="node not installed")
def test_present_auto_writes_all_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(present, "ROOT", tmp_path)  # keep runs/ out of the repo
    port = free_port()
    assert present.present(port, auto=True, out=tmp_path / "snap") == 0
    for step, _ in present.STEPS:
        d = tmp_path / "snap" / step
        assert d.is_dir() and any(d.iterdir()), step
    wifi = json.loads((tmp_path / "snap" / "05_wifi_diagnosed" / "report.json").read_text())
    assert wifi["status"] == "diagnosed" and wifi["affected_devices"] == ["AP_H3"]
    assert present.port_free(port)  # agent stopped


def test_stale_agent_matcher_ignores_unrelated_processes(monkeypatch):
    monkeypatch.setattr(present.os, "name", "posix")
    monkeypatch.setattr(present.subprocess, "run", lambda *a, **k: type("X", (), {"stdout": (
        "101 node /x/external_agents/wireless_agent/server.js --port 9001\n"
        "102 node /x/other_app/server.js --port 9001\n"
        "103 node /x/external_agents/wireless_agent/server.js --port 9002\n"
        "104 node /x/external_agents/wireless_agent/server.js\n")})())
    assert present._agent_pids(9001) == [101]
    assert present._agent_pids(8765) == [104]  # default port when --port is absent
