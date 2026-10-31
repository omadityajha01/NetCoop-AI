"""Generate docs/VIDEO_SCRIPT.md (4:30 voiceover) from the real reports, the demo snapshots and the MEASURED
`present --auto` timing (eval/reports/present_timing.json, written by `python -m eval.time_present`).

    python tasks.py video
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REP = ROOT / "eval" / "reports"
SNAP = ROOT / "demo_snapshots"
VIDEO_END = 270  # 4:30


def load(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def mmss(t: int) -> str:
    return f"{t // 60}:{t % 60:02d}"


def main() -> None:
    b = load(REP / "eval_B.json")
    org = load(REP / "organizer.json")["B"]
    fz = load(REP / "fuzz.json")
    cong = load(SNAP / "01_congestion" / "report.json")
    wifi_off = load(SNAP / "02_wifi_insufficient" / "report.json")
    wifi = load(SNAP / "05_wifi_diagnosed" / "report.json")
    chaos = load(SNAP / "06_chaos_input" / "report.json")
    conf_lines = (SNAP / "04_conformance" / "output.txt").read_text(encoding="utf-8").splitlines()
    timing = load(REP / "present_timing.json")
    starts = [float(timing["step_start_s"][str(k)]) for k in range(1, 9)]
    run_end = float(timing["total_s"])
    ev = {e["metric"]: e["value"] for e in wifi["supporting_evidence"]}
    preds = cong["predictions"]
    hits = sum(p["outcome"] == "hit" for p in preds)
    ns = chaos["normalization_summary"]
    blocked = cong["blocked_actions"][0]["reason"] if cong["blocked_actions"] else "-"

    intro = ("Title card for ~3 s, then cut to `docs/architecture.svg` for ~10 s and back. *Campus networks fail in "
             "ways no single monitor explains. NetCoop lets specialized agents argue it out over a documented protocol "
             "and produce one honest report; the core is deterministic: same input, same report.* ")
    steps = [
        ("Congestion", intro + f"Five internal agents exchange typed NMP messages on one bus, and every message lands in "
                       f"an append-only log. Before asking for evidence, the correlation agent writes down what it expects: "
                       f"{hits} of {len(preds)} predictions come back as hits, and the miss is shown too. Result: "
                       f"*{cong['suspected_root_cause']}*, confidence {cong['confidence']:.2f}."),
        ("Wi-Fi without the agent", "Same campus, a Wi-Fi complaint. Packet loss at AP_H3 is real, but nobody can see the "
                                    "radio. So NetCoop says `insufficient_evidence` and names the missing signals: "
                                    f"{', '.join(s for s in wifi_off['missing_signals'] if 'AP_H3' in s and 'L_' not in s)}. "
                                    "No guessing."),
        ("Start the external agent", "Now we start a separate agent, written in Node.js, that speaks an older dialect: version "
                                     "0.9, with its own field names. It joins mid-session, discovered from an allowlist, with "
                                     "no restart."),
        ("Conformance", f"Before we trust it, our conformance kit checks it: {sum(1 for x in conf_lines if x.startswith('PASS'))} "
                        f"of {len(conf_lines)} checks pass. That covers a valid card, valid replies, an error on malformed input, "
                        "idempotency, and tolerance of newer versions."),
        ("Wi-Fi again", f"Same incident file. The only difference is the new agent. Now: *{wifi['suspected_root_cause']}*. "
                        f"RSSI {ev.get('rssi_dbm', 0):g} dBm, SNR {ev.get('snr_db', 0):g} dB, retransmissions "
                        f"{ev.get('retransmission_pct', 0):g}%. The gateway translated `signal`, `noise_margin` and `ap-h3` on the way in."),
        ("Chaos input", f"Real data is messy. This bundle mixes a legacy v0.9 block, seconds instead of milliseconds, fractions, "
                        f"mangled IDs, a ghost switch and an injection attempt. {ns['records_in']} records in, {ns['records_used']} "
                        f"used, {ns['records_quarantined']} quarantined, none silently dropped. Diagnosis: device overload on DEPT_CORE_SW_01."),
        ("Policy", f"Recommendations come only from a playbook and pass hard rules in code. Here: *{blocked}*. Nothing is ever "
                   "executed automatically."),
        ("Normal network", "And a healthy network is reported as healthy: `no_fault_detected`. "
                           f"Measured, not claimed. On the organizer's own generator: "
                           f"{org['per_label']['latency_spike']['accuracy']:.0%} / {org['per_label']['hardware_failure']['accuracy']:.0%} "
                           f"correct, {org['per_label']['normal']['accuracy']:.0%} healthy. On our harder generator: "
                           f"{b['precision_when_diagnosed']:.0%} right when it commits, {b['wrong_diagnosis_rate']:.1%} wrong; 60% "
                           f"corrupted input: {fz[-1]['accuracy']}. Weak spots, published: device overload "
                           f"{b['per_fault']['device_overload']['accuracy']}, and weakened hardware failure stays at medium confidence."),
    ]
    L = ["# Video script (4:30)", "",
         "Generated by `python tasks.py video` from `eval/reports/` (including the **measured** run timing in "
         "`eval/reports/present_timing.json`) and `demo_snapshots/`, so every number and timestamp below is real.", "",
         "**Recording setup:** terminal ≥ 100 columns, font ≥ 16 pt, `NETCOOP_LLM` unset. Run `python tasks.py preflight` "
         "first. Start recording and immediately run `python tasks.py present --auto` (default 34 s between steps; the "
         f"measured run took **{run_end:.0f} s ({mmss(int(round(run_end)))})**). After the run ends, hold the final frame until 4:30.", "",
         "| Time | On screen | Voiceover |", "|---|---|---|"]
    for k, (title, vo) in enumerate(steps):
        a = int(starts[k]) if k else 0
        z = int(starts[k + 1]) if k + 1 < len(starts) else VIDEO_END
        if k == len(steps) - 1:
            title += f" (run ends at {mmss(int(round(run_end)))}; hold the final frame)"
        L.append(f"| {mmss(a)}–{mmss(z)} | `present` step {k + 1}: {title} | {vo} |")
    L += ["", f"Runtime check: measured run {run_end:.1f} s (target 4:00–4:45). Step starts (s): "
          + ", ".join(f"{k}: {v:g}" for k, v in timing["step_start_s"].items()) + ". The video ends at 4:30.", "",
          "**If a live step misbehaves while recording:** stop and re-record that segment from `demo_snapshots/<step>/timeline.html`."]
    out = ROOT / "docs" / "VIDEO_SCRIPT.md"
    out.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {out} (run {run_end:.0f} s)")


if __name__ == "__main__":
    main()
