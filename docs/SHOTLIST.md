# Shot list: edited demo video (target ~4:40, hard max 5:00)

Recorded as **separate clips** and cut together. The **new web UI** (`netcoop serve`: landing page at `/`, dashboard
at `/ui/dashboard.html`) is the main visual. Covers the PS requirements: **end-to-end diagnosis** and **inter-agent
communication** (chapter 3) and the **final report** (3.3). The voiceover, timed per chapter, is in
[`VIDEO_SCRIPT.md`](VIDEO_SCRIPT.md).

Every value under "On screen" was checked by running these flows through the UI on a fresh clone of main (TODO.md,
final smoke). Numbers come from `eval/reports/*` (held-out seed range B). Incident IDs are generated, so they differ
per take.

**Before the first take** (terminal at the repo root):

```powershell
.\.venv\Scripts\activate
python tasks.py preflight          # must end: PREFLIGHT OK (15/15)
netcoop serve                      # terminal A: web UI at http://127.0.0.1:8000/ (LLM off); data is chosen in *Input data*
```

**Order matters:** record chapter 3 **before** starting the Wi-Fi agent (chapter 4). With the agent running, the
congestion run gains `Wi-Fi agent` messages and the message numbers below shift. Dashboard speed: **Normal**. Hide the
3-step guide (×) after shot 3.1 if you want more room; it remembers.

## Shots

| # | Chapter title (on screen) | Action | On screen | Target |
|---|---|---|---|---|
| 1.1 | **The problem** | open http://127.0.0.1:8000/ | Landing hero "Ask your network **what broke.**"; the chat preview streams its opening answer word by word, with evidence cards (`98.31 pct`, `528 count`, `CONG-4 reboot blocked · R1`) | 12 s |
| 2.1 | **Architecture** | open `docs/architecture.svg` | Slow zoom: bus + agents → A2A gateway → `wireless_agent` | 15 s |
| 3.1 | **End-to-end diagnosis** | landing **Try Now** → dashboard | *Input data* shows the example's 108 raw records **before** the diagnosis; feed opens with **Problem received**, then **Hand-off** "Coordinator hands the investigation to Connectivity agent, Device-health agent, Performance agent"; progress bar phases | 18 s |
| 3.2 | **Inter-agent communication** | watch *Predictions*; click one feed card | Cards written at messages #15–#17, then flip: **came true** / **didn't happen** / **came true**; the clicked card expands to show what it contains | 13 s |
| 3.3 | **Final report** | *The answer* card; feed end | "Network congestion (link overloaded) at HOSTEL_CORE_SW_01", **High (100%)**, **2 of 3 predictions came true**; feed ends with **Coordinator's recommendation** "Inspect upstream and egress link utilization on L_HOSTEL_UPLINK."; map: switch red, uplink pulses | 14 s |
| 4.1 | **Interoperability** | *Input data* → Examples → "Wi-Fi keeps dropping" → **Diagnose this data** | **INSUFFICIENT EVIDENCE**, "Not enough data to be sure, so we won't guess."; Missing: "link load on L_AP_H3, link flaps on L_AP_H3, retransmissions on AP_H3, Wi-Fi signal strength on AP_H3"; next step "Connect the Wi-Fi agent (it measures signal strength), then press Diagnose again." | 9 s |
| 4.2 | **Interoperability** | terminal B: `node external_agents/wireless_agent/server.js` | `[wifi-probe] dialect 0.9 agent on http://127.0.0.1:8765` | 7 s |
| 4.3 | **Interoperability** | terminal C: `python tasks.py conformance http://127.0.0.1:8765` | `conformance: 7/7 checks passed` | 9 s |
| 4.4 | **Interoperability** | **Diagnose this data** again | Pill "Wi-Fi agent connected"; feed cards tagged **joined via A2A**; answer "Weak Wi-Fi signal at AP_H3", High (100%) | 12 s |
| 4.5 | **Interoperability** | technical details → note the Incident; `netcoop timeline <id> --html $HOME\Videos\netcoop\wifi.html`, open it | *Transforms*: `signal → rssi_dbm`, `noise_margin → snr_db`, `ap-h3 → AP_H3`, `0.208 fraction → 20.8 pct` | 8 s |
| 5.1 | **Robustness** | Examples → "Messy data from many sources" → **Diagnose this data** | Raw table shows the mixed input (text cells like units are read-only); feed #1 "Data cleaner · Read 48 records, used 36, set aside 12 unreadable"; answer "Overloaded device at DEPT_CORE_SW_01", High (85%) | 13 s |
| 5.2 | **Robustness** | none (chart) | `2_degradation_curve.png` (0.94 → 0.89 at 60%) | 12 s |
| 6.1 | **Organizer data** | `python tasks.py judge --fault hardware_failure --seed 4242`, then chart `1_accuracy_per_fault.png` | `MATCHES the documented mapping`; 100% per label | 20 s |
| 6.2 | **Not hard-coded** | (a) *Generate new incident*, Fault "Random", **Generate with a random seed** → **Diagnose this data**. (b) Examples → "Slow internet at peak hours" → **Diagnose**; in row 5 (HOSTEL_CORE_SW_01) set `interface_errors` to `200` → **Diagnose this data** | (a) **SEED nnnnnn** shown big, the raw record, then the answer for that seed (fault hidden until diagnosed). (b) the edited cell turns amber; **Before / After**: "Network congestion · diagnosed · High (100%)" → "Faulty cable or port · probable · Medium (56%)" | 20 s |
| 7.1 | **Safety: policy + dry-run remediation** | open the congestion run from *Previous diagnoses*; *What you can do*: **Approve (simulate)** on CONG-1, then **Approve** on CONG-4 | CONG-1: "Plan (simulation only, not executed)", 3 steps + "If it goes wrong: …"; toast "Plan ready below…". CONG-4: "Not allowed right now: safety rule R1 (Class hours)", then "still blocked by rule R1, so no plan". Answer unchanged | 25 s |
| 8.1 | **LLM explains, code decides** | stop terminal A (Ctrl+C); `$env:NETCOOP_LLM="local"; $env:NETCOOP_LOCAL_MODEL="llama3.2:3b"; netcoop serve` (Ollama running); Examples → "Messy data from many sources" → **Diagnose this data** (~20 s; cut the wait) | Feed "LLM triage · The language model suggests dns failure (name lookup) (advice only)"; answer still "Overloaded device at DEPT_CORE_SW_01", High (85%); technical details "Decided by deterministic_scoring", "LLM hint dns_failure (advice only)" | 25 s |
| 9.1 | **Chat via MCP** | Claude Desktop with the config in [`MCP.md`](MCP.md); prompt 3 from MCP.md, then "explain it" | Tool calls `diagnose` → `explain`; answer cites `AP_H3`, the finding IDs and the predictions; `decision_source: deterministic_scoring` | 30 s |
| 10.1 | **Close** | none (end card) | `github.com/omadityajha01/NetCoop-AI` · "Measured, not claimed." | 10 s |

**Timing:** 12 + 15 + 45 + 45 + 25 + 20 + 20 + 25 + 25 + 30 + 10 = **272 s (4:32)** of content, plus ~11 s of chapter
cards = **~4:43**. If a take runs long, trim 3.3 and 4.4 first; the hard max is 5:00.

After chapter 4, stop the agent with **Ctrl+C** in its terminal (only the process you started). For 9.1 the Wi-Fi
agent may be running or not: MCP prompt 3 explains either outcome. The classic dashboard is still at `/dashboard` as a
fallback visual.

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
- [ ] Browser zoom so the dashboard text is readable at 1080p (≈ 110–125%); hide the bookmarks bar
- [ ] OS "reduce motion" **off** (with it on, the UI shows final states without animation)
- [ ] Ollama running with `llama3.2:3b` before chapter 8; Claude Desktop configured per `docs/MCP.md` before chapter 9
- [ ] **Mic test**: 10 s sample and play back; no clipping; quiet room
- [ ] `python tasks.py preflight` → 15/15 before recording
- [ ] Chapter 3 recorded before starting the Wi-Fi agent; agent stopped with Ctrl+C afterwards
- [ ] **Export MP4 (H.264)**, 1920×1080, 30 fps, AAC audio; final length 3:00–5:00 (target ~4:40)
