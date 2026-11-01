// NetCoop dashboard. Real API + SSE; plain-language layer on top of the technical stream; text-only; CSP-safe.
"use strict";

const INTERNAL = new Set(["normalizer", "orchestrator", "performance_agent", "infrastructure_agent", "connectivity_agent",
  "correlation_agent", "reporting_agent", "triage_agent", "human_operator", "remediation_planner"]);
const SPEED_MS = { 1: 240, 2: 120 };
const SVGNS = "http://www.w3.org/2000/svg";

// ---------- plain-language vocabulary ----------
const PROBLEMS = {
  congestion: "Slow internet at peak hours", weak_wifi: "Wi-Fi keeps dropping", dns_failure: "Websites won't open (ping works)",
  dhcp_failure: "New devices get no IP address", interface_fault: "Connection keeps cutting out", normal: "Routine health check",
  interop: "Messy data from many sources",
};
const AGENTS = {
  normalizer: "Data cleaner", orchestrator: "Coordinator", performance_agent: "Performance agent",
  infrastructure_agent: "Device-health agent", connectivity_agent: "Connectivity agent", correlation_agent: "Reasoning agent",
  reporting_agent: "Report writer", triage_agent: "LLM triage", human_operator: "You", remediation_planner: "Plan writer",
  wireless_agent: "Wi-Fi agent",
};
const AGENT_INFO = [["performance_agent", "speed, delay, packet loss, link load"], ["infrastructure_agent", "CPU, memory, errors, dropped packets"],
  ["connectivity_agent", "which devices are affected, DNS/DHCP"], ["correlation_agent", "weighs the evidence, tests causes"],
  ["reporting_agent", "writes the answer and checks the rules"]];
const FAULTS = {
  congestion: "Network congestion (link overloaded)", interface_fault: "Faulty cable or port", device_overload: "Overloaded device",
  weak_wifi: "Weak Wi-Fi signal", dns_failure: "DNS failure (name lookup)", dhcp_failure: "DHCP failure (IP addresses)",
  latency_spike: "Latency spike", hardware_failure: "Hardware failure",
};
const METRICS = {
  latency_ms: "delay", jitter_ms: "jitter", packet_loss_pct: "packet loss", throughput_mbps: "throughput",
  link_utilization_pct: "link load", cpu_pct: "CPU", memory_pct: "memory", queue_drops_count: "dropped packets",
  interface_errors_count: "interface errors", crc_errors_count: "CRC errors", link_flaps_count: "link flaps",
  rssi_dbm: "Wi-Fi signal strength", snr_db: "signal-to-noise", retransmission_pct: "retransmissions",
  client_count: "connected clients", dns_failure_pct: "DNS failures", dhcp_failure_pct: "DHCP failures",
};
const STATUS_TEXT = {
  diagnosed: ["We found the likely cause.", "ok"],
  probable: ["Two causes fit about equally well; both are shown.", "warn"],
  insufficient_evidence: ["Not enough data to be sure, so we won't guess.", "warn"],
  no_fault_detected: ["Your network looks healthy.", "calm"],
  failed: ["The input couldn't be read.", "bad"],
};
const PHASE_OF = { normalization_summary: 0, task_request: 1, finding_report: 1, coverage_manifest: 1, prediction: 2,
  evidence_request: 2, evidence_response: 2, diagnosis: 2, report: 3 };

const OPS = { ">=": "at or above", ">": "above", "<=": "at or below", "<": "below" };
const expectText = x => `${OPS[x.op] || x.op} the ${x.ref} level`;   // ">= high" -> "at or above the high level"
const nice = (map, k) => map[k] || String(k || "").replace(/_/g, " ");
const metric = m => nice(METRICS, m);
const sureWord = c => (c >= 0.75 ? "High" : c >= 0.5 ? "Medium" : "Low");

class ReorderBuffer {
  constructor() { this.next = 1; this.pending = new Map(); }
  push(ev) {
    if (typeof ev.seq !== "number" || ev.seq < this.next || this.pending.has(ev.seq)) return [];
    this.pending.set(ev.seq, ev);
    const out = [];
    while (this.pending.has(this.next)) { out.push(this.pending.get(this.next)); this.pending.delete(this.next); this.next += 1; }
    return out;
  }
}

/** One plain-English line per message (the technical type stays visible as a small tag). */
function describe(ev) {
  const p = ev.payload || {};
  switch (ev.message_type) {
    case "normalization_summary": return `Read ${p.summary.records_in} records, used ${p.summary.records_used}, set aside ${p.summary.records_quarantined} unreadable`;
    case "task_request": return p.task === "analyze" ? `Asked ${nice(AGENTS, ev.recipient)} to check the network`
      : p.task === "scope" ? "Asked which devices are affected" : p.task === "report" ? "Asked for the final report"
      : `Asked ${nice(AGENTS, ev.recipient)} to ${p.task}`;
    case "finding_report": { const n = (p.findings || []).length; return n ? `Found ${n} problem${n > 1 ? "s" : ""}` : "Found nothing unusual"; }
    case "coverage_manifest": return "Listed what it can measure";
    case "prediction": { const x = p.prediction; return `Predicts ${metric(x.signal.metric)} on ${x.signal.entity.id} will be ${expectText(x.expected)} if it's ${nice(FAULTS, x.fault_type).toLowerCase()}`; }
    case "evidence_request": return `Asked for evidence: ${(p.requests || []).map(r => metric(r.metric) + " on " + ((r.entity || {}).id || "?")).join(", ")}`;
    case "evidence_response": return `Sent ${(p.findings || []).length} measurement(s) as evidence`;
    case "diagnosis": return p.phase === "final" ? `Final verdict: ${p.status.replace(/_/g, " ")} (${Number(p.confidence).toFixed(2)})`
      : `Working verdict: ${p.status.replace(/_/g, " ")} (${Number(p.confidence).toFixed(2)})`;
    case "report": return `Wrote the answer: ${nice(FAULTS, p.report.fault_type) || p.report.status}`;
    case "hint": return `The language model suggests ${nice(FAULTS, p.fault_type).toLowerCase()} (advice only)`;
    case "human_decision": return `You chose to ${p.decision} ${p.action_id}; nothing was executed`;
    case "remediation_plan": return `Wrote a step-by-step plan for ${p.action_id} (simulation only)`;
    case "error": return `Problem: ${p.detail}`;
    default: return ev.message_type;
  }
}

/** What a message contains, as plain [label, value] rows for the click-to-expand details in the feed. */
function detailRows(ev) {
  const p = ev.payload || {};
  const rows = [["From → to", nice(AGENTS, ev.sender) + " → " + nice(AGENTS, ev.recipient)], ["Message", "#" + ev.seq + " · " + ev.message_type]];
  const finding = f => [`${metric(f.metric)} · ${f.entity.id}`, `${fmtv(f.value)} ${f.unit || ""} · ${f.severity}`.trim()];
  switch (ev.message_type) {
    case "normalization_summary": {
      const s = p.summary || {};
      rows.push(["Records", `${s.records_in} in · ${s.records_used} used · ${s.records_quarantined} set aside`],
                ["Repairs", `${s.renamed || 0} fields renamed · ${s.unit_converted || 0} units converted · ${s.coerced || 0} values fixed`],
                ["Time window", `${(p.window || {}).start} → ${(p.window || {}).end}`]);
      for (const q of (p.quarantined || []).slice(0, 3)) rows.push(["Set aside", `${q.field}: ${q.reason}`]);
      break;
    }
    case "task_request":
      rows.push(["Task", `${p.task} (round ${p.round})`]);
      if (p.window) rows.push(["Time window", `${p.window.start} → ${p.window.end}`]);
      if (p.params && p.params.entities) rows.push(["Devices to check", p.params.entities.join(", ") || "none"]);
      break;
    case "finding_report": case "evidence_response": {
      const fs = p.findings || [];
      if (!fs.length) rows.push(["Findings", ev.message_type === "finding_report" ? "nothing unusual" : "none"]);
      for (const f of fs.slice(0, 8)) rows.push(finding(f));
      if (fs.length > 8) rows.push(["…", `${fs.length - 8} more`]);
      for (const u of (p.unavailable || []).slice(0, 3)) rows.push(["Could not measure", `${metric(u.metric)} · ${(u.entity || {}).id}`]);
      if (p.scope && p.scope.affected_devices) rows.push(["Affected devices", p.scope.affected_devices.join(", ")],
                                                          ["Nearest common upstream", p.scope.nearest_common_upstream || "-"]);
      break;
    }
    case "coverage_manifest":
      rows.push(["Can measure", (p.signals || []).slice(0, 6).map(x => `${metric(x.metric)} · ${x.entity.id}`).join("; ") +
                ((p.signals || []).length > 6 ? ` … (${p.signals.length} in total)` : "")]);
      break;
    case "prediction": {
      const x = p.prediction;
      rows.push(["Possible cause", nice(FAULTS, x.fault_type)],
                ["Expects", `${metric(x.signal.metric)} on ${x.signal.entity.id} ${expectText(x.expected)}`],
                ["Logged", "before the evidence was requested"]);
      break;
    }
    case "evidence_request":
      for (const r of p.requests || []) rows.push(["Asks for", `${metric(r.metric)} on ${(r.entity || {}).id}`]);
      if (p.reason) rows.push(["Why", p.reason]);
      break;
    case "diagnosis":
      rows.push(["Verdict", `${p.status.replace(/_/g, " ")} · confidence ${Number(p.confidence).toFixed(2)} (${p.confidence_category})`]);
      for (const h of [...(p.hypotheses || [])].sort((a, b) => b.score - a.score).slice(0, 3))
        rows.push(["Cause considered", `${nice(FAULTS, h.fault_type)} at ${h.entity.id} · score ${Math.round(h.score * 100)}%`]);
      if ((p.missing_signals || []).length) rows.push(["Still missing", p.missing_signals.slice(0, 4).join(", ")]);
      break;
    case "report": {
      const r = p.report || {};
      rows.push(["Answer", r.suspected_root_cause], ["Confidence", `${Number(r.confidence).toFixed(2)} (${r.confidence_category})`],
                ["Actions", `${(r.recommended_actions || []).length} suggested · ${(r.blocked_actions || []).length} blocked by rules`]);
      break;
    }
    case "hint": rows.push(["Suggests", nice(FAULTS, p.fault_type) + " (advice only)"], ["Why", p.rationale]); break;
    case "human_decision": rows.push(["Decision", `${p.decision} ${p.action_id}`], ["Executed", "no (never)"]); break;
    case "remediation_plan":
      rows.push(["Plan for", `${p.action_id} on ${p.target || "-"}`], ["Label", p.label]);
      (p.steps || []).forEach((x, i) => rows.push(["Step " + (i + 1), x]));
      break;
    case "error": rows.push(["Error", `${p.code}: ${p.detail}`]); break;
    default: break;
  }
  return rows;
}
function fmtv(v) { return typeof v === "number" ? (Number.isInteger(v) ? String(v) : String(+v.toFixed(2))) : String(v); }

if (typeof module !== "undefined" && module.exports) module.exports = { ReorderBuffer, describe, detailRows, INTERNAL, SPEED_MS, PROBLEMS, sureWord, expectText };

// ---------- DOM ----------
const $ = id => document.getElementById(id);
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const S = { incident: null, report: null, events: [], fseq: new Map(), buf: new ReorderBuffer(), es: null, speed: 1, topo: null,
            predRows: new Map(), policy: new Map(), shownPlans: new Set(), phase: -1 };

function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = String(text); return n; }
function svg(tag, attrs, text) { const n = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v)); if (text != null) n.textContent = String(text); return n; }
function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
function frame(fn) { requestAnimationFrame(() => requestAnimationFrame(fn)); }
function toast(t) { const n = $("toast"); n.textContent = t; n.classList.add("on"); clearTimeout(toast.h); toast.h = setTimeout(() => n.classList.remove("on"), 3600); }
function empty(text, title, small) { const d = el("div", "empty-state" + (small ? " small" : "")); if (title) d.appendChild(el("b", null, title)); d.appendChild(el("span", null, text)); return d; }
async function api(path, opts) {
  const r = await fetch(path, opts);
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((b.detail && b.detail.detail) || "HTTP " + r.status);
  return b;
}
const fmt = v => typeof v === "number" ? (Number.isInteger(v) ? String(v) : String(+v.toFixed(2))) : String(v);

// ---------- guide + progress ----------
function setGuide(step) {
  document.querySelectorAll(".guide-steps li").forEach(li => {
    const g = Number(li.dataset.g);
    li.classList.toggle("on", g === step); li.classList.toggle("done", g < step);
  });
}
function showGuide(show) {
  $("guide").hidden = !show; $("guide-show").hidden = show;
  try { localStorage.setItem("netcoop.guide", show ? "show" : "hide"); } catch { /* private mode */ }
}
function setPhase(i) {
  if (i < S.phase) return;          // only advance: task_requests recur later in a run
  S.phase = i;
  $("progress").hidden = false;
  $("progress-fill").style.transform = "scaleX(" + ((i + 1) / 4) + ")";
  document.querySelectorAll(".phases li").forEach(li => {
    const p = Number(li.dataset.p); li.classList.toggle("on", p === i); li.classList.toggle("done", p < i);
  });
}

// ---------- feed ----------
function addEvent(ev) {
  S.events.push(ev);
  const p = ev.payload || {};
  for (const f of (p.findings || [])) if (f.finding_id && !S.fseq.has(f.finding_id)) S.fseq.set(f.finding_id, ev.seq);
  const feed = $("feed");
  const es = feed.querySelector(".empty-state"); if (es) es.remove();
  const card = el("div", "ev t-" + ev.message_type);
  card.id = "ev-" + ev.seq; card.tabIndex = 0;
  card.title = "Click to see what this message contains";
  const who = el("div", "who", nice(AGENTS, ev.sender));
  who.appendChild(el("span", "tag", ev.message_type.replace(/_/g, " ")));
  if (!INTERNAL.has(ev.sender)) who.appendChild(el("span", "tag a2a", "joined via A2A"));
  const body = el("div"); body.append(who, el("div", "what", describe(ev)));
  card.append(el("span", "seq", "#" + ev.seq), body);
  card.setAttribute("role", "button");
  card.setAttribute("aria-expanded", "false");
  card.addEventListener("click", () => toggleDetails(card, ev));
  card.addEventListener("keydown", k => { if (k.key === "Enter" || k.key === " ") { k.preventDefault(); toggleDetails(card, ev); } });
  feed.appendChild(card);
  feed.scrollTop = feed.scrollHeight;
  $("msgcount").textContent = S.events.length + " messages";

  if (ev.message_type in PHASE_OF) setPhase(PHASE_OF[ev.message_type]);
  if (!INTERNAL.has(ev.sender)) markJoined(ev.sender);
  if (ev.message_type === "prediction") addPrediction(ev);
  if (p.findings) flip(ev.seq);
  if (ev.message_type === "diagnosis") renderHypotheses(p);
  if (ev.message_type === "human_decision" || ev.message_type === "remediation_plan") renderActions();
}
function toggleDetails(card, ev, forceOpen) {
  let box = card.querySelector(".details");
  if (box && !forceOpen) { box.remove(); card.setAttribute("aria-expanded", "false"); card.classList.remove("open"); return; }
  if (box) return;
  box = el("dl", "details");
  for (const [k, v] of detailRows(ev)) box.append(el("dt", null, k), el("dd", null, v));
  card.lastElementChild.appendChild(box);
  card.setAttribute("aria-expanded", "true");
  card.classList.add("open");
}
function receive(ev) { for (const e of S.buf.push(ev)) addEvent(e); }
function highlight(seq) {
  document.querySelectorAll(".ev.sel").forEach(n => n.classList.remove("sel"));
  const c = $("ev-" + seq);
  if (c) {
    c.classList.add("sel");
    const ev = S.events.find(e => e.seq === seq); if (ev) toggleDetails(c, ev, true);   // evidence link opens the details
    c.scrollIntoView({ block: "center", behavior: reduced() ? "auto" : "smooth" });
  }
}

// ---------- agents ----------
let external = {};
async function loadAgents() {
  try { external = (await api("/agents")).external || {}; } catch { external = {}; }
  const box = $("agents"); clear(box);
  for (const [id, what] of AGENT_INFO) { const a = el("div", "agent"); a.title = id; a.append(el("b", null, nice(AGENTS, id)), el("span", null, what)); box.appendChild(a); }
  for (const [id, st] of Object.entries(external)) {
    const a = el("div", "agent ext" + (st === "joined" ? " joined" : "")); a.title = id;
    const b = el("b", null, nice(AGENTS, id));
    if (st === "joined") { b.append(" "); b.appendChild(el("span", "tag a2a", "joined via A2A")); }
    a.append(b, el("span", null, st === "joined" ? "connected from outside; its data is translated automatically"
      : "not connected; start it to add Wi-Fi measurements"));
    box.appendChild(a);
  }
  const pill = $("agent-pill");
  const joined = Object.entries(external).filter(([, s]) => s === "joined").map(([k]) => nice(AGENTS, k));
  pill.classList.toggle("joined", joined.length > 0);
  pill.lastElementChild.textContent = joined.length ? joined.join(", ") + " connected" : "No external agent connected";
}
function markJoined(id) { if (external[id] !== "joined") { external[id] = "joined"; loadAgents(); } }

// ---------- predictions / possible causes ----------
function addPrediction(ev) {
  const x = ev.payload.prediction;
  const f = el("span", "flip");
  f.append(el("span", "face front", "checking…"), el("span", "face back", ""));
  const left = el("div");
  left.append(el("div", "said", `If it's ${nice(FAULTS, x.fault_type).toLowerCase()}, ${metric(x.signal.metric)} on ${x.signal.entity.id} should be ${expectText(x.expected)}`),
              el("div", "exp", "written down before checking · message #" + ev.seq));
  const row = el("div", "pred"); row.append(left, f);
  row.title = x.signal.metric + "@" + x.signal.entity.id + " " + x.expected.op + " " + x.expected.ref;
  S.predRows.set(x.prediction_id, row);
  $("preds").appendChild(row);
}
function settle(p) {
  const row = S.predRows.get(p.prediction_id); if (!row) return;
  const f = row.querySelector(".flip"); if (f.classList.contains("flipped")) return;
  const label = p.outcome === "hit" ? "came true" : p.outcome === "miss" ? "didn't happen" : "couldn't check";
  row.querySelector(".back").textContent = label + (p.observed != null ? " · " + fmt(p.observed) : "");
  f.classList.add("flipped", p.outcome === "hit" ? "hit" : p.outcome === "miss" ? "miss" : "unk");
}
function flip(seq) {
  for (const p of (S.report && S.report.predictions) || []) if (p.evidence_finding_id && S.fseq.get(p.evidence_finding_id) === seq) settle(p);
}
function renderHypotheses(d) {
  const box = $("hyps"); clear(box);
  const hs = [...(d.hypotheses || [])].sort((a, b) => b.score - a.score).slice(0, 4);
  if (!hs.length) { box.appendChild(empty("No cause fits the data well.", null, true)); return; }
  for (const h of hs) {
    const c = el("div", "hyp" + (h.hypothesis_id === d.top_hypothesis_id ? " top" : ""));
    const r = el("div", "row"); r.append(el("span", null, nice(FAULTS, h.fault_type)), el("span", null, Math.round(h.score * 100) + "%"));
    const bar = el("div", "bar"); const fill = el("i"); bar.appendChild(fill);
    c.append(r, el("div", "ent", "at " + h.entity.id + " · evidence coverage " + Math.round(h.coverage * 100) + "%"), bar);
    box.appendChild(c);
    frame(() => { fill.style.transform = "scaleX(" + Math.max(0.02, h.score) + ")"; });
  }
}
function localizedRoot() {
  const d = [...S.events].reverse().find(e => e.message_type === "diagnosis");
  if (!d) return null;
  const top = (d.payload.hypotheses || []).find(h => h.hypothesis_id === d.payload.top_hypothesis_id);
  return top ? top.entity.id : null;
}

// ---------- topology ----------
function drawTopology(affected = new Set(), evidence = new Set(), root = null) {
  const t = S.topo, g = $("topo"); if (!t) return; clear(g);
  const kids = new Map(), byId = new Map(t.nodes.map(n => [n.id, n]));
  for (const n of t.nodes) if (n.parent && byId.has(n.parent)) { if (!kids.has(n.parent)) kids.set(n.parent, []); kids.get(n.parent).push(n.id); }
  const pos = new Map(); let leaf = 0, depthMax = 0;
  (function place(ids, d) {
    for (const id of ids) {
      const c = kids.get(id) || []; depthMax = Math.max(depthMax, d);
      if (!c.length) pos.set(id, { x: leaf++, y: d });
      else { place(c, d + 1); const xs = c.map(k => pos.get(k).x); pos.set(id, { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: d }); }
    }
  })(t.nodes.filter(n => !n.parent || !byId.has(n.parent)).map(n => n.id), 0);
  const W = Math.max(leaf * 34, 300), H = (depthMax + 1) * 62 + 14;
  g.setAttribute("viewBox", `0 0 ${W} ${H}`);
  const P = id => { const p = pos.get(id); return { x: 17 + p.x * 34, y: 16 + p.y * 62 }; };
  const later = [];
  for (const l of t.links) {
    if (!pos.has(l.a) || !pos.has(l.b)) continue;
    const a = P(l.a), b = P(l.b);
    const line = svg("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y }); line.appendChild(svg("title", {}, "Link " + l.id)); g.appendChild(line);
    if (evidence.has(l.id)) later.push([line, "ev-link"]); if (root === l.id) later.push([line, "root"]);
  }
  for (const n of t.nodes) {
    if (!pos.has(n.id)) continue;
    const p = P(n.id);
    if (root === n.id) { const ring = svg("circle", { cx: p.x, cy: p.y, r: 12, class: "ring" }); g.appendChild(ring); later.push([ring, "on"]); }
    const c = svg("circle", { cx: p.x, cy: p.y, r: n.type === "device" ? 6.5 : 5, class: "node" });
    c.appendChild(svg("title", {}, `${n.id} (${(n.role || n.type).replace(/_/g, " ")}${n.segment ? ", " + n.segment : ""})`)); g.appendChild(c);
    if (affected.has(n.id)) later.push([c, "affected"]); else if (evidence.has(n.id)) later.push([c, "evid"]);
    const hot = affected.has(n.id) || root === n.id;
    g.appendChild(svg("text", { x: p.x, y: p.y + 16, "text-anchor": "middle", class: hot ? "hot" : "", transform: `rotate(28 ${p.x} ${p.y + 16})` }, n.id));
  }
  frame(() => later.forEach(([n, c]) => n.classList.add(c)));
}

// ---------- the answer (plain English) + technical details ----------
function renderAnswer(rep) {
  const box = $("answer"); clear(box);
  const [plain, tone] = STATUS_TEXT[rep.status] || [rep.status, "warn"];
  const card = el("div", "answer-card " + tone);
  card.appendChild(el("span", "status " + rep.status, rep.status.replace(/_/g, " ")));
  const headline = rep.status === "diagnosed" || rep.status === "probable"
    ? nice(FAULTS, rep.fault_type) + (rep.affected_devices && rep.affected_devices.length ? " at " + rep.affected_devices.join(", ") : "")
    : plain;
  card.appendChild(el("div", "headline", headline));
  card.appendChild(el("p", "plain", rep.status === "diagnosed" || rep.status === "probable" ? plain + " " + rep.suspected_root_cause + "." : rep.suspected_root_cause));
  const facts = el("dl", "facts");
  const add = (k, v) => { facts.append(el("dt", null, k), v instanceof Node ? (() => { const d = el("dd"); d.appendChild(v); return d; })() : el("dd", null, v)); };
  const conf = Math.max(0, Math.min(1, Number(rep.confidence) || 0));
  const sure = el("span", "sure"); const bar = el("div", "bar"); const fill = el("i"); bar.appendChild(fill);
  sure.append(el("b", null, sureWord(conf) + " (" + Math.round(conf * 100) + "%)"), bar);
  add("How sure", sure);
  frame(() => { fill.style.transform = "scaleX(" + conf + ")"; });
  const top3 = (rep.supporting_evidence || []).slice(0, 3).map(e => `${metric(e.metric)} ${fmt(e.value)} ${e.unit || ""} on ${e.entity || "?"}`.trim());
  if (top3.length) add("Because", top3.join(" · "));
  const hits = (rep.predictions || []).filter(p => p.outcome === "hit").length;
  if ((rep.predictions || []).length) add("Self-check", `${hits} of ${rep.predictions.length} predictions came true`);
  if (rep.status === "insufficient_evidence" && (rep.missing_signals || []).length) {
    add("Missing", rep.missing_signals.slice(0, 4).map(s => { const [m, e] = s.split("@"); return metric(m) + (e ? " on " + e : ""); }).join(", "));
  }
  card.appendChild(facts);
  const allowed = (rep.action_details || []).filter(a => a.allowed);
  const nextText = rep.status === "insufficient_evidence"
    ? ((rep.missing_signals || []).some(s => /rssi|snr|retransmission/.test(s))
      ? "Connect the Wi-Fi agent (it measures signal strength), then press Diagnose again."
      : "Collect the missing measurements listed above, then press Diagnose again.")
    : rep.status === "no_fault_detected" ? "Nothing to do. Keep monitoring."
    : allowed.length ? allowed[0].text + "." : "See the suggested actions below.";
  const next = el("div", "next"); next.append(el("b", null, "What to do next: "), nextText);
  card.appendChild(next);
  box.appendChild(card);
}

function renderReport(rep) {
  $("tech").hidden = false;
  const box = $("report"); clear(box); box.classList.remove("in"); void box.offsetWidth; box.classList.add("in");
  box.appendChild(el("div", "root", rep.suspected_root_cause));
  const kv = el("dl", "kv");
  const add = (k, v) => { kv.append(el("dt", null, k), el("dd", null, v)); };
  add("Incident", rep.incident_id);
  add("Status", rep.status + (rep.status_reason ? " (" + rep.status_reason + ")" : ""));
  add("Confidence", Number(rep.confidence).toFixed(2) + " · " + rep.confidence_category);
  add("Decided by", rep.decision_source || "deterministic_scoring");
  add("Sources", (rep.evidence_sources || []).join(", ") || "-");
  if ((rep.alternative_causes || []).length) add("Alternatives", rep.alternative_causes.slice(0, 3).join("; "));
  if (rep.scoring) add("Scoring", Object.entries(rep.scoring).map(([k, v]) => k + "=" + v).join("  "));
  if (rep.llm && rep.llm.hints && rep.llm.hints.length) add("LLM hint", rep.llm.hints.map(h => h.fault_type).join(", ") + " (advice only)");
  box.appendChild(kv);
  const ev = el("div", "evid");
  for (const e of (rep.supporting_evidence || []).slice(0, 8)) {
    const btn = el("button"); btn.type = "button"; btn.title = "Show the message that carried " + e.finding_id;
    btn.append(el("span", null, e.metric + " · " + (e.entity || "")), el("span", "v", fmt(e.value) + " " + (e.unit || "")));
    btn.addEventListener("click", () => { const s = S.fseq.get(e.finding_id); if (s) highlight(s); });
    ev.appendChild(btn);
  }
  if (ev.childNodes.length) { box.appendChild(el("p", "explain", "Evidence (click to see which message reported it):")); box.appendChild(ev); }
}

function decisions() { const m = new Map(); for (const e of S.events) if (e.message_type === "human_decision") m.set(e.payload.action_id, e); return m; }
function plans() { const m = new Map(); for (const e of S.events) if (e.message_type === "remediation_plan") m.set(e.payload.action_id, e); return m; }

function renderActions() {
  const rep = S.report; if (!rep || !$("report").classList.contains("in")) return;
  const box = $("actions"); clear(box);
  const dec = decisions(), pl = plans();
  const details = rep.action_details || [];
  if (!details.length) { box.appendChild(empty("No actions are needed.", null, true)); return; }
  for (const a of details) {
    const card = el("div", "act" + (a.allowed ? "" : " blocked"));
    const top = el("div", "top"); const txt = el("div");
    txt.append(el("span", "id", a.id), el("span", "txt", a.text));
    const btns = el("div", "btns");
    const approve = el("button", "mini ok", a.allowed ? "Approve (simulate)" : "Approve");
    approve.title = a.allowed ? "Records your approval and shows a step-by-step plan. Nothing is executed."
      : "Records your approval; the safety rule still blocks it, so no plan is made.";
    const reject = el("button", "mini no", "Reject"); reject.title = "Records that you don't want this action.";
    approve.type = reject.type = "button";
    approve.addEventListener("click", () => decide(a.id, "approve", approve));
    reject.addEventListener("click", () => decide(a.id, "reject", reject));
    btns.append(approve, reject);
    top.append(txt, btns); card.appendChild(top);
    if (!a.allowed) {
      const why = ((rep.blocked_actions || []).find(b => b.action_id === a.id) || {}).reason || "";
      const m = why.match(/\(([^)]*)\)\s*$/);  // "...: blocked by R1 (Class hours)" -> "Class hours"
      card.appendChild(el("div", "rule", "Not allowed right now: safety rule " + a.rule_id + (m ? " (" + m[1] + ")" : "")));
    }
    if (dec.has(a.id)) {
      const e = dec.get(a.id); const pol = S.policy.get(a.id);
      card.appendChild(el("div", "decision", `You chose: ${e.payload.decision} · ` +
        (pol && pol.rule_id ? `still blocked by rule ${pol.rule_id}, so no plan` : "nothing was executed")));
    }
    if (pl.has(a.id)) {
      const e = pl.get(a.id), p = e.payload;
      const plan = el("div", "plan");
      plan.appendChild(el("div", "lbl", "Plan (simulation only, not executed)"));
      const ol = el("ol"); for (const s of p.steps) ol.appendChild(el("li", null, s)); plan.appendChild(ol);
      for (const s of p.rollback) plan.appendChild(el("div", "rb", "If it goes wrong: " + s));
      if (S.shownPlans.has(e.seq)) plan.classList.add("seen"); S.shownPlans.add(e.seq);
      card.appendChild(plan);
    }
    box.appendChild(card);
  }
}

async function decide(actionId, decision, btn) {
  btn.disabled = true;
  try {
    const r = await api("/incidents/" + encodeURIComponent(S.incident) + "/feedback",
      { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action_id: actionId, decision }) });
    if (r.policy) S.policy.set(actionId, r.policy);
    for (const e of await api("/incidents/" + encodeURIComponent(S.incident) + "/events")) receive(e);
    toast(r.plan_seq ? "Plan ready below. It's a simulation; nothing was changed."
      : r.policy && r.policy.rule_id ? `Recorded. Safety rule ${r.policy.rule_id} still blocks this action.`
      : decision === "reject" ? "Recorded: you rejected this action." : "Recorded.");
  } catch (err) { toast("That didn't work: " + err.message + ". Try again."); }
  finally { btn.disabled = false; }
}

// ---------- input data: examples / generate / upload / edit & re-run ----------
const ID_KEYS = ["timestamp", "ts", "time", "device_id", "device", "ap", "link_id", "link", "entity", "service"];

/** Records of any bundle shape we accept: {records:[...]}, a bare list, a single flat record, or a v0.9 {obs:[...]}. */
function recordsOf(data) {
  if (Array.isArray(data)) return data;
  if (data && Array.isArray(data.records)) return data.records;
  if (data && Array.isArray(data.obs)) return data.obs;
  if (data && typeof data === "object") return [data];
  return [];
}

/** Table model of the raw input: id columns, then every top-level/metrics leaf; numbers are editable. */
function rawTable(data, maxCols = 16) {
  const recs = recordsOf(data);
  const cols = [], seen = new Set();
  const add = c => { if (!seen.has(c) && cols.length < maxCols) { seen.add(c); cols.push(c); } };
  for (const r of recs) {
    if (!r || typeof r !== "object") continue;
    for (const k of ID_KEYS) if (k in r && typeof r[k] !== "object") add(k);
  }
  for (const r of recs) {
    if (!r || typeof r !== "object") continue;
    for (const [k, v] of Object.entries(r)) if (!ID_KEYS.includes(k) && (v === null || typeof v !== "object")) add(k);
    if (r.metrics && typeof r.metrics === "object") for (const [k, v] of Object.entries(r.metrics)) if (v === null || typeof v !== "object") add("metrics." + k);
  }
  const rows = recs.map((r, i) => ({ index: i, cells: cols.map(c => {
    const v = r && typeof r === "object" ? (c.startsWith("metrics.") ? (r.metrics || {})[c.slice(8)] : r[c]) : undefined;
    return { path: c, value: v, editable: typeof v === "number" && Number.isFinite(v) };
  }) }));
  return { columns: cols, rows, total: recs.length };
}

/** Copy of the bundle with one numeric cell changed (record index + column path). */
function withEdit(data, index, path, value) {
  const copy = JSON.parse(JSON.stringify(data));
  const r = recordsOf(copy)[index];
  if (path.startsWith("metrics.")) r.metrics[path.slice(8)] = value; else r[path] = value;
  return copy;
}

const SRC = { mode: "example", label: "", detail: "", seed: null, original: null, data: null, csv: null, edits: 0, filename: "input.json",
              example: null };

function setCompact(on) {
  $("input").classList.toggle("compact", on);
  const b = $("toggle-input");
  b.hidden = false;
  b.textContent = on ? "Show the data" : "Hide the data";
  b.setAttribute("aria-expanded", String(!on));
}

function setMode(mode) {
  setCompact(false);
  SRC.mode = mode;
  document.querySelectorAll(".tab").forEach(t => { const on = t.dataset.mode === mode; t.classList.toggle("on", on); t.setAttribute("aria-selected", String(on)); });
  document.querySelectorAll(".src").forEach(s => { s.hidden = s.dataset.for !== mode; });
  $("seed-box").hidden = !(mode === "generate" && SRC.seed !== null);
  if (mode === "example") loadExample($("scenario").value);
}

function showInput({ data = null, csv = null, label, detail, seed = null, filename = "input.json", example = null }) {
  Object.assign(SRC, { data, original: data, csv, label, detail, seed, filename, example, edits: 0 });
  $("seed-box").hidden = seed === null;
  if (seed !== null) { $("seed-val").textContent = String(seed); $("seed-fault").textContent = detail; }
  renderRaw();
  setCompact(false);
  $("run").disabled = !(data || csv);
  $("compare").hidden = true;
  setGuide(2);
}

function renderRaw() {
  const head = $("raw").tHead, body = $("raw").tBodies[0]; clear(head); clear(body);
  const meta = $("input-meta"); clear(meta);
  if (SRC.csv !== null) {
    const lines = SRC.csv.split(/\r?\n/).filter(x => x.trim());
    meta.append(el("b", null, SRC.label), ` · ${Math.max(0, lines.length - 1)} CSV rows (shown as uploaded; edit JSON uploads to change values)`);
    const tr = el("tr"); for (const c of (lines[0] || "").split(",")) tr.appendChild(el("th", null, c)); head.appendChild(tr);
    for (const line of lines.slice(1, 201)) { const r = el("tr"); for (const c of line.split(",")) r.appendChild(el("td", "txt", c)); body.appendChild(r); }
    return;
  }
  if (!SRC.data) { meta.textContent = "No data loaded yet."; return; }
  const t = rawTable(SRC.data);
  meta.append(el("b", null, SRC.label), ` · ${t.total} record${t.total === 1 ? "" : "s"} · ${SRC.detail}` + (SRC.edits ? ` · ${SRC.edits} value(s) edited by you` : ""));
  const tr = el("tr"); tr.appendChild(el("th", null, "#")); for (const c of t.columns) tr.appendChild(el("th", null, c.replace("metrics.", ""))); head.appendChild(tr);
  const orig = rawTable(SRC.original);
  for (const row of t.rows.slice(0, 300)) {
    const r = el("tr"); r.appendChild(el("td", "txt", String(row.index + 1)));
    row.cells.forEach((cell, ci) => {
      const td = el("td");
      if (cell.editable) {
        const inp = el("input"); inp.type = "number"; inp.step = "any"; inp.value = String(cell.value);
        inp.setAttribute("aria-label", `${cell.path} in record ${row.index + 1}`);
        const was = orig.rows[row.index].cells[ci].value;
        if (cell.value !== was) inp.classList.add("changed");
        inp.addEventListener("change", () => {
          const v = Number(inp.value);
          if (inp.value.trim() === "" || !Number.isFinite(v)) { inp.classList.add("invalid"); $("run").disabled = true; toast("Numbers only, please."); return; }
          inp.classList.remove("invalid");
          SRC.data = withEdit(SRC.data, row.index, cell.path, v);
          SRC.edits = countEdits(); inp.classList.toggle("changed", v !== was);
          $("reset-edits").hidden = SRC.edits === 0; $("run").disabled = false;
          $("input-meta").lastChild.textContent = ` · ${t.total} record${t.total === 1 ? "" : "s"} · ${SRC.detail}` + (SRC.edits ? ` · ${SRC.edits} value(s) edited by you` : "");
        });
        td.appendChild(inp);
      } else { td.className = "txt"; td.textContent = cell.value === undefined ? "" : String(cell.value); }
      r.appendChild(td);
    });
    body.appendChild(r);
  }
  if (t.total > 300) body.appendChild(el("tr")).appendChild(el("td", "txt", `… ${t.total - 300} more records (all are sent)`));
  $("reset-edits").hidden = SRC.edits === 0;
}

function countEdits() {
  const a = rawTable(SRC.data), b = rawTable(SRC.original); let n = 0;
  a.rows.forEach((r, i) => r.cells.forEach((c, j) => { if (c.value !== b.rows[i].cells[j].value) n += 1; }));
  return n;
}

async function loadExample(name) {
  try {
    const data = await api("/scenarios/" + encodeURIComponent(name) + "/input");
    showInput({ data, label: "Example: " + nice(PROBLEMS, name), detail: "recorded scenario data/scenarios/" + name, example: name,
                filename: name + ".json" });
  } catch (err) { toast("Couldn't load the example: " + err.message); }
}

async function generateNew() {
  const btn = $("gen"); btn.disabled = true;
  try {
    const g = await api("/generate?fault=" + encodeURIComponent($("gen-fault").value) + "&seed=random");
    const hidden = $("gen-fault").value === "random";
    showInput({ data: g.record, seed: g.seed, filename: "generated.json",
                label: "Generated incident", detail: hidden ? "fault hidden until the diagnosis" : "fault: " + nice(FAULTS, g.fault).toLowerCase() });
    SRC.truth = g.fault;
  } catch (err) { toast("Couldn't generate: " + err.message); }
  finally { btn.disabled = false; }
}

function uploadFile(file) {
  if (!file) return;
  if (!/\.(json|csv)$/i.test(file.name)) { toast("Only .json or .csv files."); return; }
  if (file.size > 10 * 1024 * 1024) { toast("That file is over 10 MB."); return; }
  const rd = new FileReader();
  rd.onload = () => {
    const text = String(rd.result);
    if (/\.csv$/i.test(file.name)) { showInput({ csv: text, label: "Upload: " + file.name, detail: "", filename: file.name }); return; }
    try { showInput({ data: JSON.parse(text), label: "Upload: " + file.name, detail: Math.ceil(file.size / 1024) + " KB", filename: file.name }); }
    catch { showInput({ csv: null, data: null, label: "Upload: " + file.name, detail: "" }); SRC.badText = text;
            $("input-meta").textContent = "That file isn't valid JSON. Diagnose it anyway to see how the data cleaner rejects it.";
            $("run").disabled = false; }
  };
  rd.readAsText(file);
}

function summaryOf(rep) {
  return { v: rep.status === "diagnosed" || rep.status === "probable" ? nice(FAULTS, rep.fault_type) : (STATUS_TEXT[rep.status] || [rep.status])[0],
           s: `${rep.status.replace(/_/g, " ")} · ${sureWord(rep.confidence)} (${Math.round(rep.confidence * 100)}%) · ${(rep.affected_devices || []).join(", ") || "-"}` };
}

function showCompare(before, after) {
  const box = $("compare"); clear(box); box.hidden = false;
  const card = (k, rep, cls) => { const c = el("div", "cmp " + cls); const s = summaryOf(rep); c.append(el("div", "k", k), el("div", "v", s.v), el("div", "s", s.s)); return c; };
  box.append(card("Before your edit", before, "before"), el("div", "cmp-arrow", "→"), card("After your edit", after, "after"));
}

// ---------- flow cards (UI only: not NMP messages) ----------
function flowCard(title, text) {
  const card = el("div", "ev flow");
  const body = el("div"); body.append(el("div", "who", title), el("div", "what", text));
  card.append(el("span", "seq", "·"), body);
  $("feed").appendChild(card);
  return card;
}
let handoff = null;
function noteHandoff(ev) {
  if (ev.message_type !== "task_request" || (ev.payload || {}).task !== "analyze") return;
  const names = new Set((handoff && handoff.names) || []); names.add(nice(AGENTS, ev.recipient));
  const text = "Coordinator hands the investigation to " + [...names].join(", ");
  if (!handoff) { const c = flowCard("Hand-off", text); handoff = { card: c, names }; $("ev-" + ev.seq).before(c); }
  else { handoff.names = names; handoff.card.querySelector(".what").textContent = text; }
}

// ---------- run / replay ----------
async function stream(incident, source) {
  if (S.es) S.es.close();
  Object.assign(S, { incident, events: [], fseq: new Map(), buf: new ReorderBuffer(), predRows: new Map(), shownPlans: new Set(), phase: -1 });
  handoff = null;
  clear($("feed")); clear($("hyps")); clear($("preds")); clear($("actions")); clear($("report")); $("report").classList.remove("in");
  $("tech").hidden = true; $("tech").open = false;
  const ans = $("answer"); clear(ans); ans.appendChild(empty("The agents are investigating. The answer appears here when they finish.", "Working on it…"));
  $("msgcount").textContent = "";
  setGuide(2); setPhase(0);
  drawTopology();
  const src = source || { label: "Previous diagnosis " + incident, detail: "reopened from the event log" };
  flowCard("Problem received", `${src.label}${src.detail ? " · " + src.detail : ""}${src.seed != null ? " · seed " + src.seed : ""}`);
  S.report = await api("/incidents/" + encodeURIComponent(incident) + "/report");   // revealed only at the end
  $("replay").disabled = false;
  const delay = reduced() ? 0 : SPEED_MS[S.speed];
  const es = new EventSource("/incidents/" + encodeURIComponent(incident) + "/stream?delay_ms=" + delay);
  S.es = es;
  es.addEventListener("message", e => { const ev = JSON.parse(e.data); receive(ev); if ($("ev-" + ev.seq)) noteHandoff(ev); });
  es.addEventListener("end", () => {
    es.close(); S.es = null;
    for (const p of S.report.predictions || []) settle(p);
    setPhase(3); $("progress-fill").style.transform = "scaleX(1)";
    renderAnswer(S.report); renderReport(S.report); renderActions(); setGuide(4);
    const next = $("answer").querySelector(".next");
    flowCard("Coordinator's recommendation", next ? next.textContent.replace(/^What to do next:\s*/, "") : S.report.suspected_root_cause);
    $("feed").scrollTop = $("feed").scrollHeight;
    drawTopology(new Set(S.report.affected_devices || []), new Set((S.report.supporting_evidence || []).map(e => e.entity)), localizedRoot());
  });
  es.onerror = () => { es.close(); S.es = null; toast("Lost the connection to the server. Press Replay to try again."); };
}

async function run() {
  const btn = $("run"); btn.disabled = true; btn.lastChild.textContent = "Diagnosing…";
  setCompact(true);
  const before = SRC.edits && S.report && S.lastData === SRC.original ? S.report : null;
  try {
    let r;
    const source = { label: SRC.label, detail: SRC.edits ? `${SRC.edits} value(s) edited by you` : SRC.detail, seed: SRC.seed };
    if (SRC.mode === "example" && SRC.example && !SRC.edits) {
      r = await api("/scenarios/" + encodeURIComponent(SRC.example) + "/run?external=true", { method: "POST" });
    } else {
      const body = SRC.csv !== null ? SRC.csv : SRC.data ? JSON.stringify(SRC.data) : (SRC.badText || "");
      const external = SRC.mode === "generate" ? "false" : "true";   // organizer data has no Wi-Fi telemetry (as in judge mode)
      r = await api("/incidents?external=" + external + "&filename=" + encodeURIComponent(SRC.filename),
                    { method: "POST", headers: { "Content-Type": "application/octet-stream" }, body });
    }
    S.lastData = SRC.original;
    await stream(r.incident_id, source);
    if (before) showCompare(before, S.report);
    loadHistory(); loadAgents();
  } catch (err) { toast("Couldn't start the diagnosis: " + err.message + ". Is the server running?"); setGuide(1); }
  finally { btn.disabled = false; btn.lastChild.textContent = "Diagnose this data"; }
}

async function loadHistory() {
  try {
    const rows = await api("/incidents?limit=25");
    const sel = $("history"); clear(sel); sel.appendChild(el("option", null, "Previous diagnoses")).value = "";
    for (const r of rows) { const o = el("option", null, r.incident_id + " · " + r.status.replace(/_/g, " ")); o.value = r.incident_id; sel.appendChild(o); }
  } catch { /* optional */ }
}

async function reopen(incident) {
  try {
    const inp = await api("/incidents/" + encodeURIComponent(incident) + "/input");
    if (inp.json !== undefined) showInput({ data: inp.json, label: "Previous diagnosis " + incident, detail: "input hash " + String(inp.input_sha256 || "").slice(0, 12) });
    else if (inp.csv !== undefined) showInput({ csv: inp.csv, label: "Previous diagnosis " + incident, detail: "" });
    SRC.mode = "upload"; SRC.example = null;
  } catch { /* input display is optional */ }
  stream(incident, { label: "Previous diagnosis " + incident, detail: "reopened from the event log" });
}

if (typeof module !== "undefined" && module.exports) Object.assign(module.exports, { rawTable, withEdit, recordsOf });

if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", async () => {
  try {
    const [sc, topo] = await Promise.all([api("/scenarios"), api("/topology")]);
    for (const s of sc.scenarios) { const o = el("option", null, nice(PROBLEMS, s.name)); o.value = s.name; o.title = s.name; $("scenario").appendChild(o); }
    S.topo = topo; drawTopology();
  } catch (err) { toast("Can't reach the NetCoop server (" + err.message + "). Start it with `netcoop serve`."); }
  let guide = "show"; try { guide = localStorage.getItem("netcoop.guide") || "show"; } catch { /* private mode */ }
  showGuide(guide !== "hide");
  $("guide-hide").addEventListener("click", () => showGuide(false));
  $("guide-show").addEventListener("click", () => showGuide(true));
  document.querySelectorAll(".tab").forEach(t => t.addEventListener("click", () => setMode(t.dataset.mode)));
  $("scenario").addEventListener("change", () => loadExample($("scenario").value));
  $("gen").addEventListener("click", generateNew);
  $("file").addEventListener("change", e => uploadFile(e.target.files[0]));
  $("reset-edits").addEventListener("click", () => { SRC.data = SRC.original; SRC.edits = 0; renderRaw(); });
  $("toggle-input").addEventListener("click", () => setCompact(!$("input").classList.contains("compact")));
  loadAgents(); loadHistory();
  $("run").addEventListener("click", run);
  $("replay").addEventListener("click", () => { if (S.incident) stream(S.incident, { label: SRC.label, detail: "replayed from the event log", seed: SRC.seed }); });
  $("history").addEventListener("change", e => { if (e.target.value) reopen(e.target.value); });
  document.querySelectorAll(".seg-btn").forEach(b => b.addEventListener("click", () => {
    S.speed = Number(b.dataset.speed);
    document.querySelectorAll(".seg-btn").forEach(x => { const on = x === b; x.classList.toggle("on", on); x.setAttribute("aria-pressed", String(on)); });
  }));
  const q = new URLSearchParams(location.search).get("run");
  if (q && /^[a-z_]{1,40}$/.test(q)) { $("scenario").value = q; await loadExample(q); run(); }
  else await loadExample($("scenario").value);
});
