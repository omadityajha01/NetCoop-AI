"""Build frontend_handoff.zip at the repo root (F5; gitignored). `python tools/make_handoff.py`

Layout inside the zip (self-contained; the mock runs from it with the Python standard library only):
  frontend_handoff/README_HANDOFF.md      (from docs/handoff/README_HANDOFF.md)
  frontend_handoff/FRONTEND_API.md
  frontend_handoff/architecture.svg
  frontend_handoff/mock_api.py
  frontend_handoff/dry_run_templates.json (config/playbook.yaml `_dry_run`, so plans render like the server)
  frontend_handoff/frontend_fixtures/...
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "frontend_handoff.zip"
TOP = "frontend_handoff"


def build(out: Path = OUT) -> Path:
    import yaml

    files = {
        "README_HANDOFF.md": ROOT / "docs" / "handoff" / "README_HANDOFF.md",
        "FRONTEND_API.md": ROOT / "docs" / "FRONTEND_API.md",
        "architecture.svg": ROOT / "docs" / "architecture.svg",
        "mock_api.py": ROOT / "tools" / "mock_api.py",
    }
    fix = ROOT / "docs" / "frontend_fixtures"
    dry = (yaml.safe_load((ROOT / "config" / "playbook.yaml").read_text(encoding="utf-8")) or {}).get("_dry_run", {})
    with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name, src in files.items():
            z.write(src, f"{TOP}/{name}")
        z.writestr(f"{TOP}/dry_run_templates.json", json.dumps(dry, indent=2, ensure_ascii=False) + "\n")
        for p in sorted(fix.rglob("*")):
            if p.is_file():
                z.write(p, f"{TOP}/frontend_fixtures/{p.relative_to(fix).as_posix()}")
    return out


if __name__ == "__main__":
    p = build()
    with zipfile.ZipFile(p) as z:
        n = len(z.namelist())
    print(f"{p}  ({p.stat().st_size // 1024} KB, {n} files)")
    sys.exit(0)
