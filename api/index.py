"""Vercel entry point: serves the NetCoop FastAPI app (API + web UI) as one Python function.

The function's disk is read-only except /tmp, so run logs and the SQLite report index go to /tmp.
They are temporary: they disappear when the instance is recycled.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("NETCOOP_RUNS_DIR", "/tmp/netcoop-runs")
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from netcoop.api.main import app  # noqa: E402

__all__ = ["app"]
