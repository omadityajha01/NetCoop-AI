# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Primary: campus network operators (IT / network-operations staff at IIT Bhubaneswar) troubleshooting a live connectivity
complaint (slow hostel internet, Wi-Fi drops, websites not opening, devices without an IP address). Their job: find
the likely cause quickly, see the evidence behind it, and decide what to do next without risking the production
network. Hackathon judges use the same product during the demo; they are not the design target.

## Product Purpose

NetCoop AI diagnoses network faults from telemetry. Specialized agents (performance, device health, connectivity,
reasoning, reporting; plus an external Wi-Fi agent that joins over A2A, and an optional LLM triage agent) exchange
structured messages and produce one report: probable root cause, affected devices, supporting evidence, alternative
causes, a documented confidence score, limitations and policy-checked recommended actions. Success means an operator
reaches a correct next step faster and is never misled by a confident wrong answer.

## Positioning

Honest about uncertainty. NetCoop says "not enough data" instead of guessing and names the missing measurements;
shows how sure it is and why (documented scoring, predictions logged before evidence, hits and misses both shown);
states limitations on every report; and never executes changes: approvals only produce a simulated plan.

## Operating Context

- Operators start from a symptom, then choose the data: a recorded example, a new incident from the organizer's
  generator (random seed shown), or their own telemetry upload (JSON/CSV). The raw data is shown before any diagnosis
  and can be edited and re-run.
- The investigation is visible as it happens (agent messages, predictions, evidence), then a plain-English answer and
  "what to do next".
- Runs locally (`netcoop serve`, loopback only); a CLI and an MCP server expose the same diagnosis.
- Demo context: a 3–5 minute recorded video and a live stage run (docs/SHOTLIST.md, docs/RUNBOOK.md).

## Capabilities and Constraints

- Decisions (cause, confidence, status, actions) come from deterministic scoring; an LLM may only suggest a candidate
  and write narrative text. Every analysis agent runs on every incident.
- Remediation is never executed; actions come from a playbook and pass hard policy rules (e.g. R1: no reboots during
  class hours).
- Web UI constraints: static files, no build step, no CDN or remote fonts, strict Content-Security-Policy (no inline
  script or style attributes), all data rendered as text.
- Terminology in the UI: plain language first ("Faulty cable or port", "came true / didn't happen"), technical names
  available on demand.
- Undecided: real campus telemetry integration (live SNMP/NetFlow collection) and authentication are not built.

## Evidence on Hand

- Measured accuracy on held-out generated incidents (eval/reports/, README "Evaluation"): 0.904 overall, 98.2% right
  when it commits, 0% false alarms on healthy networks; organizer generator 100% on its three labels; 0.943 → 0.886
  under 60% corrupted input.
- Recorded runs for every scenario (docs/frontend_fixtures/), demo snapshots (demo_snapshots/), smoke-test results
  (TODO.md).
- All data is synthetic. There are no real-campus results, users, customers, testimonials or deployments; do not
  invent any.

## Product Principles

1. Never overstate: uncertainty, limitations and misses are part of the answer, not hidden.
2. Show the evidence: every conclusion links back to the measurement and the agent message that produced it.
3. The input comes first: operators see (and can change) the data before trusting the diagnosis.
4. Recommend, never act: humans approve; nothing touches the network.
5. Plain language for operators, technical detail one click away.

## Accessibility & Inclusion

No formal standard was set. Current practice to preserve: keyboard access, visible focus, text contrast suitable for a
dark dashboard, and `prefers-reduced-motion` honoured.
