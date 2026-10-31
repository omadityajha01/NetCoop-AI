from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import urllib.request
from pathlib import Path

import pytest

from netcoop.config import ROOT, load_config, thaw
from netcoop.orchestrator.run import RunOptions, run_incident

SCEN = ROOT / "data" / "scenarios"
NODE = shutil.which("node")


@pytest.fixture(scope="session")
def cfg():
    return load_config()


def scenario_bytes(name: str) -> bytes:
    return (SCEN / name / "incident.json").read_bytes()


def scenario_json(name: str) -> dict:
    return json.loads(scenario_bytes(name))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def cfg_with_external_url(cfg, url: str):
    agents = thaw(cfg.agents)
    agents["external"][0]["base_url"] = url
    return cfg.with_overrides(agents=agents)


def cfg_without_external(cfg):
    agents = thaw(cfg.agents)
    agents["external"][0]["base_url"] = f"http://127.0.0.1:{free_port()}"  # nothing listens here
    return cfg.with_overrides(agents=agents)


@pytest.fixture
def run(tmp_path, cfg):
    def _run(data, *, config=None, external=False, incident_id=None, persist=True, transport=None):
        if isinstance(data, str) and (SCEN / data).exists():
            data = scenario_bytes(data)
        return run_incident(data, config or cfg, RunOptions(runs_dir=tmp_path / "runs", external=external,
                                                            incident_id=incident_id, persist=persist, transport=transport))
    return _run


@pytest.fixture(scope="session")
def wireless_agent():
    """Start the real Node.js wireless_agent (dialect 0.9) on a free port."""
    if not NODE:
        pytest.skip("node not installed")
    port = free_port()
    proc = subprocess.Popen([NODE, str(ROOT / "external_agents" / "wireless_agent" / "server.js"), "--port", str(port)],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(url + "/healthz", timeout=0.2)
            break
        except OSError:
            time.sleep(0.05)
    else:
        proc.kill()
        pytest.skip("wireless_agent did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=5)
