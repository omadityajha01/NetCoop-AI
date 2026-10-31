"""Cross-platform task runner mirroring the Makefile (Windows has no make).

    python tasks.py setup | test | demo | eval | fuzz | tune | sweep | organizer | conformance [URL] | schemas | docs
                    | fixtures | lint | agent | preflight | present [--port N] [--auto] | snapshots
"""

from __future__ import annotations

import os
import subprocess
import sys

PY = sys.executable


def sh(*cmd: str) -> int:
    print("+", " ".join(cmd))
    return subprocess.call(list(cmd))


def main() -> int:
    t = sys.argv[1] if len(sys.argv) > 1 else "help"
    args = sys.argv[2:]
    n = os.environ.get("N", "280")
    if t == "setup":
        return sh(PY, "-m", "pip", "install", "-e", ".[dev]")
    if t == "test":
        return sh(PY, "-m", "pytest", "tests", "-q", "-p", "no:warnings")
    if t == "demo":
        return sh(PY, "-m", "netcoop", "demo")
    if t == "eval":
        return sh(PY, "-m", "eval.run_eval", "eval", "--n", n, "--seed-a", os.environ.get("SEED_A", "1000"),
                  "--seed-b", os.environ.get("SEED_B", "5000"))
    if t == "fuzz":
        return sh(PY, "-m", "eval.run_eval", "fuzz", "--n", os.environ.get("FUZZ_N", "70"))
    if t == "tune":
        return sh(PY, "-m", "eval.run_eval", "tune", "--n", n)
    if t == "sweep":
        return sh(PY, "-m", "eval.run_eval", "sweep", "--n", n)
    if t == "organizer":
        return sh(PY, "-m", "eval.organizer_check", "--seeds", os.environ.get("SEEDS", "500"))
    if t == "conformance":
        return sh(PY, "-m", "conformance.kit", args[0] if args else os.environ.get("AGENT_URL", "http://127.0.0.1:8765"))
    if t == "schemas":
        return sh(PY, "-m", "netcoop", "schemas")
    if t == "docs":
        return sh(PY, "-m", "netcoop", "docs")
    if t == "fixtures":
        return sh(PY, "-m", "eval.generate", "--fixtures")
    if t == "lint":
        return sh(PY, "-m", "ruff", "check", "netcoop", "eval", "conformance", "tests", "tasks.py")
    if t in ("preflight", "present", "snapshots"):
        from netcoop.present import main as present_main

        return present_main([t, *args])
    if t == "agent":
        return sh("node", "external_agents/wireless_agent/server.js")
    print(__doc__)
    return 0 if t == "help" else 2


if __name__ == "__main__":
    raise SystemExit(main())
