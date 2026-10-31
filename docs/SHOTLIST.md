# Shot list: edited demo video (target ~4:40, hard max 5:00)

Recorded as **separate clips** and cut together. The **dashboard** is the main visual for chapters 3, 4 and 7.
Covers the PS requirements: **end-to-end diagnosis** and **inter-agent communication** (chapter 3) and the **final
report** (3.3). The voiceover for all shots, timed per chapter, is in [`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md).

Every value named under "On screen" was checked by running these exact flows on `demo-final-5` (smoke test S3). Numbers
come from `eval/reports/*` (held-out seed range B). Dashboard incident IDs are generated, so they differ per take.

**Before the first take** (terminal at the repo root):

```powershell
.\.venv\Scripts\activate
python tasks.py preflight          # must end: PREFLIGHT OK (15/15)
netcoop serve                      # terminal A: dashboard at http://127.0.0.1:8000/ (LLM off)
```

**Order matters:** record chapter 3 **before** starting the Wi-Fi agent (chapter 4). With the agent running, the
congestion run gains `wireless_agent` messages and the sequence numbers below shift. Speed **1×** (2× for re-takes); with the OS "reduce motion" setting on, the dashboard shows the final state without animation.

## Shots

| # | Chapter title (on screen) | Action | On screen | Target |
|---|---|---|---|---|
| 1.1 | **The problem** | none (title card) | "NetCoop AI: multi-agent network fault diagnosis" | 12 s |
| 2.1 | **Architecture** | open `docs/architecture.svg` | Slow zoom: bus + agents → A2A gateway → `wireless_agent` | 15 s |
| 3.1 | **End-to-end diagnosis** | dashboard: scenario `congestion`, speed **1×**, **Run scenario** | Messages slide into their lanes in seq order (#1 → #27); each one pulses its sender and recipient lane headers | 20 s |
| 3.2 | **Inter-agent communication** | watch *Predictions* during the run (or press **Replay**, 2×) | Cards appear at `#15 #16 #17` as "pending" and flip when their evidence lands (`#20 evidence_response`): hit (green) / miss (red) / hit | 15 s |
| 3.3 | **Final report** | after the last message; click one `F-…` link | Report slides in last, confidence bar fills to `1.00 (high)`; root cause on `L_HOSTEL_UPLINK`; topology: `HOSTEL_CORE_SW_01` fades red, the uplink pulses (localized root); the link outlines the carrying message | 15 s |
| 4.1 | **Interoperability** | dashboard: scenario `weak_wifi`, Run | `insufficient_evidence`; limitations / missing signals `rssi_dbm`, `snr_db`, `retransmission_pct` at `AP_H3` | 10 s |
| 4.2 | **Interoperability** | terminal B: `node external_agents/wireless_agent/server.js` | `[wifi-probe] dialect 0.9 agent on http://127.0.0.1:8765` | 8 s |
| 4.3 | **Interoperability** | terminal C: `python tasks.py conformance http://127.0.0.1:8765` | `conformance: 7/7 checks passed` | 10 s |
| 4.4 | **Interoperability** | dashboard: `weak_wifi`, Run again; scroll to *Raw → canonical* | New `wireless_agent` lane with a **joined via A2A** badge; `diagnosed`, `1.00`; rows morph `retx 0.208 fraction → retransmission_pct 20.8 pct`, `signal → rssi_dbm`, `ap-h3 → AP_H3`; evidence `rssi_dbm -78`, `snr_db 13` | 22 s |
| 5.1 | **Robustness** | dashboard: `interop`, Run; *Normalization log* | `records_in: 48 · records_used: 36 · records_quarantined: 12`; raw → canonical rows (seconds → ms, fractions → pct); quarantine table | 13 s |
| 5.2 | **Robustness** | none (chart) | `2_degradation_curve.png` (0.94 → 0.89 at 60%) | 12 s |
| 6.1 | **Organizer data** | `python tasks.py judge --fault hardware_failure --seed 4242`, then chart `1_accuracy_per_fault.png` | `MATCHES the documented mapping`; 100% per label | 20 s |
| 7.1 | **Safety: policy + dry-run remediation** | dashboard: congestion run (*Past runs*); *Actions*: **approve** CONG-1, then **approve** CONG-4 | CONG-1: a plan reveals under the action, `SIMULATED – NOT EXECUTED`, steps + rollback, `human_decision #28`, `remediation_plan #29`. CONG-4 (reboot): `blocked by R1, no plan`. Report unchanged | 25 s |
| 8.1 | **LLM explains, code decides** | stop terminal A (Ctrl+C); restart: `$env:NETCOOP_LLM="local"; $env:NETCOOP_LOCAL_MODEL="llama3.2:3b"; netcoop serve` (Ollama running); dashboard: `interop`, Run (~20 s; cut the wait) | `triage_agent` lane `#12 hint`; Report: `LLM: local · llama3.2:3b · narrative from llm`, `LLM hints (advisory): dns_failure …`, still `device overload … DEPT_CORE_SW_01`, `0.85 (high)`; `decided by deterministic_scoring` | 30 s |
| 9.1 | **Chat via MCP** | Claude Desktop with the config in [`MCP.md`](MCP.md); prompt 3 from MCP.md, then "explain it" | Tool calls `diagnose` → `explain`; answer cites `AP_H3`, the finding IDs and the predictions; `decision_source: deterministic_scoring` | 30 s |
| 10.1 | **Close** | none (end card) | `github.com/omadityajha01/NetCoop-AI` · "Measured, not claimed." | 10 s |

**Timing:** 12 + 15 + 50 + 50 + 25 + 20 + 25 + 30 + 30 + 10 = **267 s (4:27)** of content, plus ~10 s of chapter cards
= **~4:40**. Chapter 6 is 20 s, chapter 7 is 25 s. If a take runs long, trim 3.3 and 4.4 first; the hard max is 5:00.

After chapter 4, stop the agent with **Ctrl+C** in its terminal (only the process you started). For 9.1 the Wi-Fi
agent may be running or not: MCP prompt 3 explains either outcome.

## Charts (on branch `slides`, exported outside the repo; `slides` is not merged)

PowerShell, from the repo root:

```powershell
git fetch origin slides
git archive --format=zip -o "$HOME\Videos\netcoop-charts.zip" origin/slides docs/slides
Expand-Archive "$HOME\Videos\netcoop-charts.zip" "$HOME\Videos\netcoop-charts" -Force
# -> $HOME\Videos\netcoop-charts\docs\slides\{1_accuracy_per_fault,2_degradation_curve,3_severity_sweep,4_operating_point,5_confidence_vs_accuracy}.png
```

Git Bash equivalent: `git archive --format=zip -o ~/Videos/netcoop-charts.zip origin/slides docs/slides && unzip -o ~/Videos/netcoop-charts.zip -d ~/Videos/netcoop-charts`.
This leaves the working tree untouched (verified). Used in the video: `2_degradation_curve.png` (5.2) and `1_accuracy_per_fault.png` (6.1).

## Recording checklist

- [ ] Screen recording at **1920×1080**
- [ ] Terminal font **≥ 18 pt**, **dark theme**, window ≥ 100 columns
- [ ] Prompt shows **no username or full path** (PowerShell: `function prompt { "> " }` for the session)
- [ ] OS **notifications off** (Windows: Focus / Do not disturb), **other apps closed**, browser tabs hidden
- [ ] Browser zoom so the dashboard tables are readable at 1080p (≈ 125%); hide bookmarks bar
- [ ] Ollama running with `llama3.2:3b` before chapter 8; Claude Desktop configured per `docs/MCP.md` before chapter 9
- [ ] **Mic test**: 10 s sample and play back; no clipping; quiet room
- [ ] `python tasks.py preflight` → 15/15 before recording
- [ ] Chapter 3 recorded before starting the Wi-Fi agent; agent stopped with Ctrl+C afterwards
- [ ] **Export MP4 (H.264)**, 1920×1080, 30 fps, AAC audio; final length 3:00–5:00 (target ~4:40)
