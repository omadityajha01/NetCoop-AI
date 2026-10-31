# NetCoop AI: frontend handoff

You are building a new dashboard for **NetCoop AI**, a multi-agent network fault diagnosis system. Specialized agents
exchange structured messages (the NetCoop Message Protocol, NMP), and deterministic scoring produces one diagnostic
report. Your UI visualises a run as it replays and lets a human approve or reject recommended actions. The backend
already exists. Build against the mock in this zip; it then runs unchanged against the real server.

## What's in this zip

| File | What it is |
|---|---|
| `FRONTEND_API.md` | The contract, generated from the backend code: every endpoint (params, request/response schema, real examples, errors), the SSE stream, the payload of each message type with a real example, the flows, CSP/CORS headers verbatim, and a glossary |
| `frontend_fixtures/` | Real recorded runs: `events.jsonl` (exactly what `/events` and `/stream` serve), `report.json`, `api.json` (every HTTP exchange of the flow); `index.json` lists them; `api_examples.json` has the other endpoints and real error bodies |
| `mock_api.py` | The same endpoints, serving the fixtures, with SSE replay. Python 3.11+ standard library only, no backend |
| `dry_run_templates.json` | Remediation dry-run templates, so the mock renders plans like the server |
| `architecture.svg` | One-picture architecture: bus, agents, A2A gateway, external agent |

## Run the mock

```
python mock_api.py --ui path/to/your_ui        # http://127.0.0.1:8000/  (your index.html at /, your files at /ui/<path>)
python mock_api.py --ui path/to/your_ui --port 8080 --agent joined
```

* Start a run: `POST /scenarios/{name}/run` → `{incident_id, status}`; then `GET /incidents/{id}/stream?delay_ms=240`
  (SSE, `event: message` per NMP message, then `event: end`), then `GET /incidents/{id}/report`.
* External agent: `weak_wifi` returns *insufficient evidence* until `POST /mock/agent/join`, then *diagnosed*, with a
  new `wireless_agent` lane (joined via A2A). `GET /agents` shows the state.
* HITL: `POST /incidents/{id}/feedback {action_id, decision}`. Approving an allowed action appends `human_decision` and
  `remediation_plan` ("SIMULATED – NOT EXECUTED"); approving CONG-4 (reboot) comes back blocked by rule R1 with no plan.
* `&timing=recorded` on the stream replays the recorded gaps between messages.

Against the real backend later: `netcoop serve --ui dashboard_v2` (put your UI in the repo's `dashboard_v2/` folder).
Same URLs, same headers.

## Hard rules (the server enforces the first one with headers)

* **CSP**: `default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self';
  base-uri 'none'; form-action 'none'; frame-ancestors 'none'`. So: no CDN, no npm runtime from the internet, no inline
  `<script>`, no `style="…"` attributes (set styles via CSSOM or classes), no remote fonts, and every request goes to
  the same origin. A build step is fine if its output is static files that obey this.
* **Text only (PI8)**: render every data field with `textContent` / `setAttribute`, never `innerHTML`. Device names,
  limitations and LLM text are untrusted.
* **Read-only + two actions**: run a scenario, approve/reject an action. Nothing in the UI may imply something was
  executed or fixed: plans are "SIMULATED – NOT EXECUTED" and the diagnosis never changes after a decision.
* **Order by `seq`**: the stream is already ordered; keep it that way and drop duplicates.
* `prefers-reduced-motion` → no animation.

## Brief

> The brief line in the request was an unfilled placeholder ("paste the dashboard brief from earlier here"). Below are
> the two dashboard briefs given earlier in this project, **verbatim**. Replace this section if a newer brief exists.

### Brief 1: dashboard (M3)

```
M3 Dashboard (3 h)
- FastAPI serves ONE static page: vanilla JS, no build step, no CDN. Read-only over the API + one action: Run scenario.
- Panels:
  - scenario picker
  - live message lanes per agent (SSE from the event log)
  - SVG topology with affected devices + localization highlighted
  - report with evidence → finding_id links
  - predictions hit/miss, normalization log, blocked actions
- HITL, non-blocking: approve/reject per recommendation → `human_decision` event in the log; never changes the diagnosis.
- All data rendered as text (PI8); CORS localhost only.
- Tests: escaping, human_decision events, SSE ordering. Headless browser smoke test if playwright installs in .venv; else a manual checklist in TODO.md.
```

### Brief 2: dashboard animation (S2)

```
S2 Dashboard animation (branch ui-anim off the latest green tag, 2 h)
- Touch only dashboard static files + their tests. Keep the strict CSP: no CDN, no new libraries; CSS transitions + vanilla JS. All data rendered as text.
- Animate:
  - messages entering lanes in seq order, with a sender→recipient pulse
  - Replay button at 1×/2×
  - prediction card flips hit (green) / miss (red) when its evidence arrives
  - topology: affected devices fade red, the localized root pulses
  - normalization row animates raw → canonical (retx 0.208 → 20.8 %)
  - external agent lane appears with a "joined via A2A" badge
  - remediation plan reveals after approve
  - report slides in last; confidence bar fills
- prefers-reduced-motion = no animation; no layout shift; smooth on a mid laptop.
- Tests: replay ordering, reduced-motion; CSP headers unchanged.
```

## Useful facts

* The run is complete before you stream it; the stream is a replay of its event log. `delay_ms` 240 ≈ 1×, 120 ≈ 2×.
* For a prediction flip, `report.predictions[].evidence_finding_id` names the finding. The message that carries that
  finding (in `payload.findings[]`) is the moment its evidence arrives.
* The localized root is the entity of the top hypothesis in the last `diagnosis` message
  (`payload.top_hypothesis_id` → `payload.hypotheses[].entity.id`).
* Raw → canonical comes from `finding.transforms[]` (`step` ∈ version/alias/unit/entity, `from`, `to`).
* An external agent is a `sender` that is not internal (see FRONTEND_API.md → Flows → Agent list); its messages carry
  the limitation `DIALECT_TRANSLATED`.
