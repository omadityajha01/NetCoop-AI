# Video script: edited demo video (~4:30)

Continuous voiceover for the shots in [`SHOTLIST.md`](SHOTLIST.md): separate clips, cut together, no waiting on
`--auto`. All numbers come from `eval/reports/*` (held-out seed range B) or from the exact runs listed in the
shot list. Content is 4:20, plus ~10 s of chapter cards, for ~4:30; the hard max is 5:00.

> This file is hand-written for the edited video. Do **not** run `python tasks.py video`: that regenerates the older
> single-take `present --auto` script over this file.

---

### 0:00–0:15 · Chapter 1: The problem (shot 1.1)

Campus network faults hide across switches, Wi-Fi and services, each monitored in its own format. NetCoop AI lets
specialized agents cooperate over a documented protocol, and produces one honest, explainable diagnosis.

### 0:15–0:40 · Chapter 2: Architecture (shot 2.1)

Five internal agents (performance, infrastructure, connectivity, correlation and reporting) exchange typed messages
on one bus. Every message is written to an append-only event log, so any report can be replayed byte for byte. An A2A
gateway lets outside agents join. All knowledge lives in configuration, not code.

### 0:40–1:40 · Chapter 3: End-to-end diagnosis, inter-agent communication, final report (shots 3.1–3.3)

Here is an end-to-end diagnosis of a congested hostel uplink. One command: normalization, five agents, and a final
report with confidence 1.00.

The timeline shows the inter-agent conversation, one lane per agent. Before asking for evidence, the correlation agent
logs its predictions at sequence 15 to 17; the evidence request follows at 18, the answer at 20. Two of three
predictions hit, and the miss is reported too.

The final report keeps every field the problem statement asks for: root cause, affected device, supporting evidence
with finding IDs, alternative causes, recommended actions, evidence sources, confidence and limitations.

### 1:40–2:40 · Chapter 4: Interoperability (shots 4.1–4.5)

Now a Wi-Fi complaint at access point AP_H3. Without radio data, NetCoop refuses to guess: insufficient evidence, and
it names the missing signals: RSSI, SNR and retransmissions.

We start an external agent written in Node.js. It speaks an older dialect, version 0.9, with its own field names.

Our conformance kit checks it before we trust it: valid agent card, valid replies, errors on bad input, idempotency.
Seven of seven pass.

Same incident file, re-run. Now it is diagnosed: weak Wi-Fi at AP_H3, RSSI minus 78 dBm, SNR 13 dB, and 28.3 percent
retransmissions.

The timeline shows the translation: signal becomes rssi_dbm, noise_margin becomes snr_db, ap-h3 becomes AP_H3, and
retransmission fractions become percentages.

### 2:40–3:10 · Chapter 5: Robustness (shots 5.1–5.2)

Real data is messy. This bundle mixes a legacy 0.9 block, seconds, fractions, mangled IDs and an injection attempt:
48 records in, 36 used, 12 quarantined, none silently dropped.

Across hundreds of generated incidents, corrupting 60 percent of records drops accuracy only from 0.94 to 0.89 on our
data, and from 1.0 to 0.98 on the organizer's. Without our alias and unit registry it would be 0.51.

### 3:10–3:40 · Chapter 6: Organizer data (shots 6.1–6.2)

Now the organizer's own generator, unmodified. A judge picks the fault and the seed; here, hardware failure with seed
4242. Raw record in, correct diagnosis out.

On 500 held-out seeds per label, normal, latency spike and hardware failure are all 100 percent correct. On our harder
generator, committed diagnoses are right 98.2 percent of the time.

### 3:40–4:10 · Chapter 7: Safety and honesty (shots 7.1–7.3)

Actions come only from a playbook and pass hard policy rules: rebooting a core switch during class hours is blocked by
rule R1.

And when evidence is missing, NetCoop says insufficient evidence instead of guessing.

We publish our weak spots: device overload is 0.80 on our generator, a weakened hardware failure is reported at
medium confidence, and one organizer confidence band says 0.60 but scores 0.567.

### 4:10–4:20 · Chapter 8: Close (shot 8.1)

Everything is open, reproducible and tested in CI. Measured, not claimed.

---

Number sources:
* congestion run INC-VID0001: confidence 1.00; predictions at seq 15–17, request 18, response 20; 2 hits, 1 miss
* Wi-Fi INC-VID0002 / 0003: insufficient → diagnosed; RSSI −78, SNR 13, retransmissions 28.3; conformance 7/7
* chaos INC-VID0004: 48 / 36 / 12
* `fuzz.json`: 0.943 → 0.886; registry off 0.514
* `organizer_robustness.json`: 1.0 → 0.982
* `organizer.json` B: 100% × 3, 500 per label
* `eval_B.json`: precision 0.982, device_overload 0.80
* `weak_hw_after.json`: weakened hardware failure all medium
* organizer calibration 0.60 vs 0.567
