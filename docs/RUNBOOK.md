# Stage runbook (one page)

**Stage version: `demo-final-5`** (`git checkout demo-final-5`). Previous known-good: `demo-final-4`, the same code
without the dashboard animation. The stage flow below is the same in both.

Everything runs offline on `127.0.0.1`. Work from the repo root in a terminal at least 100 columns wide.

## Stage commands, in order

```powershell
cd C:\Projects\new
.\.venv\Scripts\activate                     # macOS/Linux: source .venv/bin/activate
python tasks.py preflight                    # must end: PREFLIGHT OK (15/15). Fix any red line before going on
python tasks.py present                      # 8 steps, press Enter between them
python tasks.py present --judge              # same, plus step 9: a judge picks an organizer label + seed
netcoop serve                                # optional visual: dashboard at http://127.0.0.1:8000/ (Ctrl+C to stop)
```

Useful flags (combine freely):

| Flag | Use |
|---|---|
| `--port 8790` | the default port 8765 is busy |
| `--no-color` | projector washes out colors |
| `--open` | open each step's timeline in the browser |
| `--auto` | hands-free: 34 s between steps by default, the run lasts ~4:05 (screen recording, see `docs/VIDEO_SCRIPT.md`); `--delay N` overrides |

A judge can also run the organizer's raw generator directly: `python tasks.py judge --fault hardware_failure --seed 42`.

## Fallback (if the live run fails)

1. **Snapshots:** open `demo_snapshots/<step>/timeline.html` (and `report.json`) in any browser. They are static
   files that work offline, one folder per step, and are kept fresh: preflight checks the code + config hash.
2. **Known-good code:** `git stash` (if you changed anything), then `git checkout demo-final-5` (or the previous `demo-final-4`), then rerun preflight.
3. **Another machine:** `git clone https://github.com/omadityajha01/NetCoop-AI`, then
   `python -m venv .venv`, then `.venv\Scripts\pip install -e .[dev]`, then `python tasks.py preflight`.

## When something goes wrong

| Symptom | Do this |
|---|---|
| **Dashboard won't start** (port 8000 busy, or Windows "access … forbidden" on a reserved port) | `netcoop serve --port 8080` and open http://127.0.0.1:8080/. If the dashboard misbehaves, use `present` and the snapshots: the dashboard is optional |
| **Port busy** (preflight: "Port … free" FAIL, or present says the port is busy with something that is not our agent) | `python tasks.py present --port 8790`. Preflight already kills a stale *wireless_agent* on that port, matched by its command line; it never kills other programs. |
| **Agent won't start** ("wireless_agent starts" FAIL) | `node --version` must be ≥ 18 and on PATH. Try another port. If Node is unusable, present steps 1, 2, 6, 7, 8 live and show 3–5 from `demo_snapshots/`. |
| **Browser won't open** (`--open` prints "could not open a browser") | Ignore it: the run continues. Copy the printed `timeline:` path into the browser's address bar, or open `demo_snapshots/<step>/timeline.html`. |
| **Firewall prompt** | It should not appear: the agent binds 127.0.0.1 only (preflight checks it). If it appears anyway, choose *Cancel / don't allow*; localhost still works. |
| **Snapshots stale** (preflight FAIL) | `python tasks.py snapshots` (~10 s), then preflight again. |
| **Text wraps / unreadable** | Widen the window to ≥ 100 columns, use `--no-color`, or zoom out (Ctrl+-). |
| **A step prints a different result** | The run names the step; switch to its snapshot timeline and narrate from there. |

Numbers, talking points and judge Q&A: [`docs/DEMO.md`](DEMO.md).
