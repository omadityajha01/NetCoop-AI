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

if (typeof module !== "undefined" && module.exports) module.exports = { ReorderBuffer, describe, INTERNAL, SPEED_MS, PROBLEMS, sureWord, expectText };

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
  card.title = "Technical: " + ev.message_type + " from " + ev.sender + " to " + ev.recipient + " (seq " + ev.seq + ")";
  const who = el("div", "who", nice(AGENTS, ev.sender));
  who.appendChild(el("span", "tag", ev.message_type.replace(/_/g, " ")));
  if (!INTERNAL.has(ev.sender)) who.appendChild(el("span", "tag a2a", "joined via A2A"));
  const body = el("div"); body.append(who, el("div", "what", describe(ev)));
  card.append(el("span", "seq", "#" + ev.seq), body);
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
function receive(ev) { for (const e of S.buf.push(ev)) addEvent(e); }
function highlight(seq) {
  document.querySelectorAll(".ev.sel").forEach(n => n.classList.remove("sel"));
  const c = $("ev-" + seq);
  if (c) { c.classList.add("sel"); c.scrollIntoView({ block: "center", behavior: reduced() ? "auto" : "smooth" }); }
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

// ---------- run / replay ----------
async function stream(incident) {
  if (S.es) S.es.close();
  Object.assign(S, { incident, events: [], fseq: new Map(), buf: new ReorderBuffer(), predRows: new Map(), shownPlans: new Set(), phase: -1 });
  clear($("feed")); clear($("hyps")); clear($("preds")); clear($("actions")); clear($("report")); $("report").classList.remove("in");
  $("tech").hidden = true; $("tech").open = false;
  const ans = $("answer"); clear(ans); ans.appendChild(empty("The agents are investigating. The answer appears here when they finish.", "Working on it…"));
  $("msgcount").textContent = "";
  setGuide(2); setPhase(0);
  drawTopology();
  S.report = await api("/incidents/" + encodeURIComponent(incident) + "/report");   // revealed only at the end
  $("replay").disabled = false;
  const delay = reduced() ? 0 : SPEED_MS[S.speed];
  const es = new EventSource("/incidents/" + encodeURIComponent(incident) + "/stream?delay_ms=" + delay);
  S.es = es;
  es.addEventListener("message", e => receive(JSON.parse(e.data)));
  es.addEventListener("end", () => {
    es.close(); S.es = null;
    for (const p of S.report.predictions || []) settle(p);
    setPhase(3); $("progress-fill").style.transform = "scaleX(1)";
    renderAnswer(S.report); renderReport(S.report); renderActions(); setGuide(4);
    drawTopology(new Set(S.report.affected_devices || []), new Set((S.report.supporting_evidence || []).map(e => e.entity)), localizedRoot());
  });
  es.onerror = () => { es.close(); S.es = null; toast("Lost the connection to the server. Press Replay to try again."); };
}

async function run() {
  const btn = $("run"); btn.disabled = true; btn.lastChild.textContent = "Diagnosing…";
  try {
    const r = await api("/scenarios/" + encodeURIComponent($("scenario").value) + "/run?external=true", { method: "POST" });
    await stream(r.incident_id);
    loadHistory(); loadAgents();
  } catch (err) { toast("Couldn't start the diagnosis: " + err.message + ". Is the server running?"); setGuide(1); }
  finally { btn.disabled = false; btn.lastChild.textContent = "Diagnose"; }
}

async function loadHistory() {
  try {
    const rows = await api("/incidents?limit=25");
    const sel = $("history"); clear(sel); sel.appendChild(el("option", null, "Previous diagnoses")).value = "";
    for (const r of rows) { const o = el("option", null, r.incident_id + " · " + r.status.replace(/_/g, " ")); o.value = r.incident_id; sel.appendChild(o); }
  } catch { /* optional */ }
}

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
  $("scenario").addEventListener("change", () => setGuide(2));
  loadAgents(); loadHistory();
  $("run").addEventListener("click", run);
  $("replay").addEventListener("click", () => { if (S.incident) stream(S.incident); });
  $("history").addEventListener("change", e => { if (e.target.value) stream(e.target.value); });
  document.querySelectorAll(".seg-btn").forEach(b => b.addEventListener("click", () => {
    S.speed = Number(b.dataset.speed);
    document.querySelectorAll(".seg-btn").forEach(x => { const on = x === b; x.classList.toggle("on", on); x.setAttribute("aria-pressed", String(on)); });
  }));
  const q = new URLSearchParams(location.search).get("run");
  if (q && /^[a-z_]{1,40}$/.test(q)) { $("scenario").value = q; run(); }
});
