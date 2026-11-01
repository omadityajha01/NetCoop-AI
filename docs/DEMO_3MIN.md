# NetCoop AI: 3-minute demo script (target 2:50)

Recorded locally (`netcoop serve`), because the Wi-Fi hot-plug needs the Node agent on your machine. The live site
(https://netcoop-ai-six.vercel.app) works for every other shot.

**Before recording** (PowerShell, repo root):

```powershell
.\.venv\Scripts\activate
python tasks.py preflight      # must end: PREFLIGHT OK (15/15)
netcoop serve                  # terminal A -> http://127.0.0.1:8000/
```

Keep terminal B and C open for the Wi-Fi agent. Dashboard speed **Normal**; hide the 3-step guide. Record shot 3
before starting the Wi-Fi agent.

| # | Time | On screen (do this) | Say this (voiceover) |
|---|---|---|---|
| 1 | 0:00–0:12 | Landing page `http://127.0.0.1:8000/` | "When students say the hostel internet is slow, the cause could be congestion, a bad cable, weak Wi-Fi or DNS. NetCoop AI finds out which one, and says how sure it is." |
| 2 | 0:12–0:27 | Deck slide 4 (architecture) | "Seven agents share one message bus. Each one checks one thing: performance, device health, connectivity, Wi-Fi. They are plain deterministic code, not LLM wrappers. The same input always gives the same report." |
| 3 | 0:27–1:00 | **Try Now** → Examples → "Slow internet at peak hours" → **Diagnose this data**. Point at the raw data, the feed, the predictions flipping, then *The answer* | "First, the raw data, before any diagnosis. Press Diagnose and the agents report what they see. The reasoning agent writes its predictions down before it asks for the evidence. Two came true, one didn't, and both are shown. Answer: congestion at the hostel core switch, high confidence, with the exact measurements behind it." |
| 4 | 1:00–1:35 | Examples → "Wi-Fi keeps dropping" → **Diagnose** (INSUFFICIENT EVIDENCE). Terminal B: `node external_agents/wireless_agent/server.js`. Terminal C: `python tasks.py conformance http://127.0.0.1:8765` (7/7). **Diagnose** again | "Now a Wi-Fi complaint. Our agents can't measure Wi-Fi, so NetCoop says 'not enough data' instead of guessing, and lists what's missing. We start a Wi-Fi agent written in Node.js that speaks an older message format. It passes our conformance checks live, joins over A2A, and now the answer is weak Wi-Fi at access point H3." |
| 5 | 1:35–2:00 | Examples → "Slow internet at peak hours". Row 5 (HOSTEL_CORE_SW_01): set `interface_errors` to `200` → **Diagnose this data**. Show *Before / After* | "Nothing is hard-coded. Change one number: two hundred interface errors on the same switch. Now it points to a faulty cable or port, and since the evidence is mixed, it says 'probable' with lower confidence." |
| 6 | 2:00–2:22 | *Previous diagnoses* → the congestion run. *What you can do*: **Approve (simulate)** on CONG-1, then **Approve** on CONG-4 | "It recommends, never acts. A human approves each step, and approval only produces a simulated plan. A core-switch reboot during class hours is blocked by a safety rule, even after approval." |
| 7 | 2:22–2:40 | Deck slide 12 (accuracy numbers), then slide 13 (corruption chart) | "We measured it on held-out test incidents: about ninety percent accurate overall, ninety-eight percent right when it commits, zero false alarms on healthy networks. With sixty percent of the input corrupted, it still doesn't crash." |
| 8 | 2:40–2:50 | Deck slide 17 (live demo + GitHub links) | "It also runs as an MCP server and as a live web app. NetCoop AI: measured, not claimed." |

**About 310 words of voiceover (~2:05 spoken), leaving ~45 s for clicks and loading.** If a take runs long, shorten shot 3 first (skip clicking a feed
card), then shot 7 (show only slide 12).

After shot 4, stop the Wi-Fi agent with **Ctrl+C** in terminal B.

## Recording checklist

- [ ] 1920×1080, browser zoom 110–125%, bookmarks bar hidden
- [ ] Terminal font ≥ 18 pt, dark theme, short prompt (`function prompt { "> " }`)
- [ ] Notifications off, other apps closed
- [ ] OS "reduce motion" off (otherwise the UI skips its animations)
- [ ] 10-second mic test played back
- [ ] Preflight 15/15 before the first take
- [ ] Export MP4 (H.264, 30 fps, AAC); final length under 3:00
