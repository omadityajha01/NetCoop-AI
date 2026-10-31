"""pytest entry point: AGENT_URL=http://127.0.0.1:8765 pytest conformance/ -v"""

from __future__ import annotations

import os

import pytest

from conformance.kit import Kit

URL = os.environ.get("AGENT_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set AGENT_URL to run the conformance kit")


@pytest.fixture(scope="module")
def results():
    return {c.name: c for c in Kit(URL).run()}


@pytest.mark.parametrize("name", [
    "serves a valid agent card",
    "answers task_request with valid NMP",
    "answers evidence_request with valid NMP",
    "returns error on malformed input",
    "idempotent on duplicate message_id",
    "declares schema_version",
    "tolerates unknown fields / newer MINOR",
])
def test_check(results, name):
    c = results[name]
    assert c.passed, c.detail
