"""W4: time `python tasks.py present --auto [--delay N]` end to end and record when each step starts.

    python -m eval.time_present [--delay N]      -> eval/reports/present_timing.json
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time

from netcoop.config import ROOT

STEP = re.compile(r"^\[(\d)/(\d)\]")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=None)
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    cmd = [sys.executable, "tasks.py", "present", "--auto", "--no-color", "--port", str(a.port)]
    if a.delay is not None:
        cmd += ["--delay", str(a.delay)]
    t0 = time.monotonic()
    starts: dict[int, float] = {}
    ok = False
    with subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                          env={**__import__("os").environ, "PYTHONUNBUFFERED": "1"}) as p:
        for line in p.stdout:  # type: ignore[union-attr]
            m = STEP.match(line.strip())
            if m:
                starts[int(m.group(1))] = round(time.monotonic() - t0, 2)
            if "steps matched the script" in line:
                ok = True
    total = round(time.monotonic() - t0, 2)
    res = {"delay": a.delay, "total_s": total, "step_start_s": starts, "all_matched": ok and p.returncode == 0}
    out = ROOT / "eval" / "reports" / "present_timing.json"
    out.write_text(json.dumps(res, indent=2), encoding="utf-8")
    print(json.dumps(res))


if __name__ == "__main__":
    main()
