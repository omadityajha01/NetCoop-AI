# Shot list: edited demo video (target 4:30, hard max 5:00)

Recorded as **separate clips** and cut together: no `--auto` waits, dead time trimmed. Covers the PS requirements:
**end-to-end diagnosis** and **inter-agent communication** (chapter 3), **final report** (3.3). The voiceover
for all shots, timed per chapter, is in [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md).

Every value named under "On screen" was checked by running these exact commands on the stage code
(`demo-final-2`, docs at `main`). Numbers come from `eval/reports/*` (held-out seed range B).

**Before the first take** (terminal at the repo root):

```powershell
.\.venv\Scripts\activate
python tasks.py preflight          # must end: PREFLIGHT OK (15/15)
```

**Order matters:** record chapter 3 **before** starting the Wi-Fi agent (chapter 4). With the agent running, the
congestion run gains extra `wireless_agent` messages and the sequence numbers below shift.
Timelines are written outside the repo (`$HOME\Videos\netcoop\`).

## Shots

| # | Chapter title (on screen) | Command | On screen | Voiceover (summary; full text in VIDEO_SCRIPT.md) | Target |
|---|---|---|---|---|---|
| 1.1 | **The problem** | none (title card) | Title card: "NetCoop AI: multi-agent network fault diagnosis" | Faults hide across systems; agents cooperate over a protocol; one honest diagnosis | 15 s |
| 2.1 | **Architecture** | open `docs/architecture.svg` in the browser | Full diagram; slow zoom from bus + 5 agents to the A2A gateway and `wireless_agent` | 5 agents, one logged bus, replay byte-identical, A2A gateway, knowledge in config | 25 s |
| 3.1 | **End-to-end diagnosis** | `netcoop diagnose data/scenarios/congestion/incident.json --incident-id INC-VID0001 --timeline` | Terminal, top of output: `status: diagnosed  confidence: 1.00 (high)`, `root cause : Likely link congestion causing egress queue drops on L_HOSTEL_UPLINK` | One command: normalization, five agents, final report | 15 s |
| 3.2 | **Inter-agent communication** | `netcoop timeline INC-VID0001 --html $HOME\Videos\netcoop\congestion.html`, then open the file | Timeline HTML: *Message timeline* lanes (scroll seq 1 → 27), then the *Predictions → evidence* table: `P-1-1 … 15 → 18 → 20 … hit`, P-1-2 miss, P-1-3 hit | Predictions logged at seq 15–17, evidence request at 18, answer at 20; 2 of 3 hit, the miss is shown | 25 s |
| 3.3 | **Final report** | `netcoop report INC-VID0001 --json` (or scroll the 3.1 output) | Highlight the PS fields one by one: `incident_id`, `status`, `suspected_root_cause`, `confidence`, `affected_devices` (HOSTEL_CORE_SW_01), `supporting_evidence` (with `finding_id`), `alternative_causes`, `recommended_actions`, `evidence_sources` (performance_agent, infrastructure_agent), `limitations` | Every PS field present, evidence traceable to findings | 20 s |
| 4.1 | **Interoperability** | `netcoop diagnose data/scenarios/weak_wifi/incident.json --incident-id INC-VID0002` | `status: insufficient_evidence  confidence: 0.33 (low)`; `missing signals: … retransmission_pct@AP_H3, rssi_dbm@AP_H3, snr_db@AP_H3` | No radio data → refuses to guess, names the missing signals | 12 s |
| 4.2 | **Interoperability** | second terminal: `node external_agents/wireless_agent/server.js` | Ready line: `[wifi-probe] dialect 0.9 agent on http://127.0.0.1:8765` | External Node.js agent, older dialect v0.9 | 10 s |
| 4.3 | **Interoperability** | `python tasks.py conformance http://127.0.0.1:8765` | 7 PASS lines; `conformance: 7/7 checks passed` | Checked before it is trusted: 7 of 7 | 12 s |
| 4.4 | **Interoperability** | `netcoop diagnose data/scenarios/weak_wifi/incident.json --incident-id INC-VID0003` | `status: diagnosed  confidence: 1.00 (high)`, `Likely weak Wi-Fi … on AP_H3`; evidence rows `rssi_dbm -78`, `snr_db 13`, `retransmission_pct 28.3` from `wireless_agent` | Same file, agent joined → diagnosed | 14 s |
| 4.5 | **Interoperability** | `netcoop timeline INC-VID0003 --html $HOME\Videos\netcoop\wifi.html`, then open the file | *Transforms applied to evidence*: `signal → rssi_dbm`, `noise_margin → snr_db`, `ap-h3 → AP_H3`, `0.208 fraction → 20.8 pct`, version `0.9 → 1.0` | The v0.9 dialect being normalized | 12 s |
| 5.1 | **Robustness** | `netcoop diagnose data/scenarios/interop/incident.json --incident-id INC-VID0004` | `status: diagnosed  confidence: 0.85`; the `normalization:` line `records_in 48, records_used 36, records_quarantined 12 …`; limitations lines (`converted from s`, `unit inferred`, `quarantined`) | Messy input recovered or quarantined, never silently dropped | 15 s |
| 5.2 | **Robustness** | none (chart) | `2_degradation_curve.png` | 60% corruption: 0.94 → 0.89 (ours), 1.0 → 0.98 (organizer); registry off 0.51 | 15 s |
| 6.1 | **Organizer data** | `python tasks.py judge --fault hardware_failure --seed 4242` | `Judge mode: organizer generator, label=hardware_failure, seed=4242`, the raw record, `diagnosed … SW_CAMPUS_5`, `MATCHES the documented mapping` (seed visible) | Raw organizer generator, judge-chosen seed, correct | 15 s |
| 6.2 | **Organizer data** | none (chart) | `1_accuracy_per_fault.png` | 500 seeds/label: 100% each; ours: 98.2% right when it commits | 15 s |
| 7.1 | **Safety** | reuse 3.1 footage (zoom) | `BLOCKED Reboot HOSTEL_CORE_SW_01: blocked by R1 (Class hours)` | Playbook-only actions, hard policy rules | 8 s |
| 7.2 | **Honesty** | reuse 4.1 footage (zoom) | `status: insufficient_evidence` | Says so instead of guessing | 7 s |
| 7.3 | **Known weaknesses** | none (text card) | Card: "Device overload 0.80 (32/40) · Weakened hardware failure: medium confidence, named in 100% of reports · One organizer confidence band: said 0.60, right 0.567" | Weak spots published with numbers | 15 s |
| 8.1 | **Close** | none (end card) | `github.com/omadityajha01/NetCoop-AI` · "Measured, not claimed." | Open, reproducible, CI-tested | 10 s |

**Timing:** chapters 15 + 25 + 60 + 60 + 30 + 30 + 30 + 10 = **260 s (4:20)** of content, plus ~10 s of chapter
title cards = **~4:30**. Even with every shot +10%, the total stays under the 5:00 hard max.

After chapter 4, stop the agent with **Ctrl+C** in its terminal (only the process you started).

## Charts (on branch `slides`, exported outside the repo; `slides` is not merged)

PowerShell, from the repo root:

```powershell
git fetch origin slides
git archive --format=zip -o "$HOME\Videos\netcoop-charts.zip" origin/slides docs/slides
Expand-Archive "$HOME\Videos\netcoop-charts.zip" "$HOME\Videos\netcoop-charts" -Force
# -> $HOME\Videos\netcoop-charts\docs\slides\{1_accuracy_per_fault,2_degradation_curve,3_severity_sweep,4_operating_point,5_confidence_vs_accuracy}.png
```

Git Bash equivalent: `git archive --format=zip -o ~/Videos/netcoop-charts.zip origin/slides docs/slides && unzip -o ~/Videos/netcoop-charts.zip -d ~/Videos/netcoop-charts`.
This leaves the working tree untouched (verified). Used in the video: `2_degradation_curve.png` (5.2) and `1_accuracy_per_fault.png` (6.2).

## Recording checklist

- [ ] Screen recording at **1920×1080**
- [ ] Terminal font **≥ 18 pt**, **dark theme**, window ≥ 100 columns
- [ ] Prompt shows **no username or full path** (PowerShell: `function prompt { "> " }` for the session)
- [ ] OS **notifications off** (Windows: Focus / Do not disturb), **other apps closed**, browser tabs hidden
- [ ] Browser zoom so the timeline tables are readable at 1080p (≈ 125–150%)
- [ ] **Mic test**: 10 s sample and play back; no clipping; quiet room
- [ ] `python tasks.py preflight` → 15/15 before recording
- [ ] Chapter 3 recorded before starting the Wi-Fi agent; agent stopped with Ctrl+C afterwards
- [ ] **Export MP4 (H.264)**, 1920×1080, 30 fps, AAC audio; final length 3:00–5:00 (target 4:30)
