// NetCoop dashboard preview (design from the first template, restyled). Real API + SSE; text-only rendering; CSP-safe.
"use strict";

const INTERNAL = new Set(["normalizer", "orchestrator", "performance_agent", "infrastructure_agent", "connectivity_agent",
  "correlation_agent", "reporting_agent", "triage_agent", "human_operator", "remediation_planner"]);
const AGENT_INFO = [["performance_agent", "latency · loss · utilization"], ["infrastructure_agent", "CPU · memory · errors · drops"],
  ["connectivity_agent", "scope · upstream · DNS/DHCP"], ["correlation_agent", "hypotheses · predictions · scoring"],
  ["reporting_agent", "playbook · policy · report"]];
const SPEED_MS = { 1: 240, 2: 120 };
const SVGNS = "http://www.w3.org/2000/svg";
const $ = id => document.getElementById(id);
const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

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

const S = { incident: null, report: null, events: [], fseq: new Map(), buf: new ReorderBuffer(), es: null, speed: 1, topo: null,
            predRows: new Map(), policy: new Map(), shownPlans: new Set() };

function el(tag, cls, text) { const n = document.createElement(tag); if (cls) n.className = cls; if (text != null) n.textContent = String(text); return n; }
function svg(tag, attrs, text) { const n = document.createElementNS(SVGNS, tag); for (const [k, v] of Object.entries(attrs)) n.setAttribute(k, String(v)); if (text != null) n.textContent = String(text); return n; }
function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
function frame(fn) { requestAnimationFrame(() => requestAnimationFrame(fn)); }
function toast(t) { const n = $("toast"); n.textContent = t; n.classList.add("on"); clearTimeout(toast.h); toast.h = setTimeout(() => n.classList.remove("on"), 3200); }
async function api(path, opts) {
  const r = await fetch(path, opts);
  const b = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((b.detail && b.detail.detail) || "HTTP " + r.status);
  return b;
}
const fmt = v => typeof v === "number" ? (Number.isInteger(v) ? String(v) : String(+v.toFixed(2))) : String(v);

// ---------- feed ----------
function describe(ev) {
  const p = ev.payload || {};
  switch (ev.message_type) {
    case "normalization_summary": return `${p.summary.records_in} records in · ${p.summary.records_used} used · ${p.summary.records_quarantined} quarantined`;
    case "task_request": return `${p.task} (round ${p.round})`;
    case "finding_report": return `${(p.findings || []).length} anomalous finding(s)`;
    case "coverage_manifest": return "signals this agent can provide";
    case "prediction": { const x = p.prediction; return `${x.fault_type}: ${x.signal.metric}@${x.signal.entity.id} ${x.expected.op} ${x.expected.ref}`; }
    case "evidence_request": return (p.requests || p.items || []).map(r => (r.metric || "") + "@" + ((r.entity || {}).id || "")).join(", ") || "evidence requested";
    case "evidence_response": return `${(p.findings || []).length} finding(s), incl. non-anomalous`;
    case "diagnosis": return `${p.phase} · ${p.status} · ${Number(p.confidence).toFixed(2)}`;
    case "report": return `${p.report.status} · ${p.report.fault_type || "-"} · ${Number(p.report.confidence).toFixed(2)}`;
    case "hint": return `LLM hint (advisory): ${p.fault_type}`;
    case "human_decision": return `${p.decision} ${p.action_id} · not executed`;
    case "remediation_plan": return `dry-run plan for ${p.action_id} · ${p.label}`;
    case "error": return `${p.code}: ${p.detail}`;
    default: return "";
  }
}

function addEvent(ev) {
  S.events.push(ev);
  const p = ev.payload || {};
  for (const f of (p.findings || [])) if (f.finding_id && !S.fseq.has(f.finding_id)) S.fseq.set(f.finding_id, ev.seq);
  const feed = $("feed");
  const empty = feed.querySelector(".empty"); if (empty) empty.remove();
  const card = el("div", "ev t-" + ev.message_type);
  card.id = "ev-" + ev.seq;
  card.tabIndex = 0;
  const who = el("div", "who", ev.sender);
  who.appendChild(el("span", "tag", ev.message_type));
  if (!INTERNAL.has(ev.sender)) who.appendChild(el("span", "tag a2a", "via A2A"));
  const body = el("div");
  body.append(who, el("div", "what", "→ " + ev.recipient + " · " + describe(ev)));
  card.append(el("span", "seq", "#" + ev.seq), body);
  feed.appendChild(card);
  feed.scrollTop = feed.scrollHeight;
  $("msgcount").textContent = S.events.length + " messages";

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
  for (const [id, what] of AGENT_INFO) { const a = el("div", "agent"); a.append(el("b", null, id), el("span", null, what)); box.appendChild(a); }
  for (const [id, st] of Object.entries(external)) {
    const a = el("div", "agent ext" + (st === "joined" ? " joined" : "")); a.id = "agent-" + id;
    const b = el("b", null, id);
    if (st === "joined") { b.append(" "); b.appendChild(el("span", "tag a2a", "joined via A2A")); }
    a.append(b, el("span", null, st === "joined" ? "external · dialect translated" : "external · " + st));
    box.appendChild(a);
  }
  const pill = $("agent-pill");
  const joined = Object.entries(external).filter(([, s]) => s === "joined").map(([k]) => k);
  pill.classList.toggle("joined", joined.length > 0);
  pill.lastElementChild.textContent = joined.length ? joined.join(", ") + " joined via A2A" : "no external agent online";
}
function markJoined(id) { if (external[id] !== "joined") { external[id] = "joined"; loadAgents(); } }

// ---------- predictions / hypotheses ----------
function addPrediction(ev) {
  const x = ev.payload.prediction;
  const f = el("span", "flip");
  f.append(el("span", "face front", "pending"), el("span", "face back", ""));
  const left = el("div");
  left.append(el("div", "sig", x.signal.metric + "@" + x.signal.entity.id),
              el("div", "exp", x.fault_type + " expects " + x.expected.op + " " + x.expected.ref + " · logged #" + ev.seq));
  const row = el("div", "pred"); row.append(left, f);
  S.predRows.set(x.prediction_id, row);
  $("preds").appendChild(row);
}

function settle(p) {
  const row = S.predRows.get(p.prediction_id); if (!row) return;
  const f = row.querySelector(".flip"); if (f.classList.contains("flipped")) return;
  row.querySelector(".back").textContent = p.outcome + (p.observed != null ? " · " + fmt(p.observed) : "");
  f.classList.add("flipped", p.outcome === "hit" ? "hit" : p.outcome === "miss" ? "miss" : "unk");
}

function flip(seq) {   // a card flips when the message carrying its evidence finding lands
  for (const p of (S.report && S.report.predictions) || []) if (p.evidence_finding_id && S.fseq.get(p.evidence_finding_id) === seq) settle(p);
}

function renderHypotheses(d) {
  const box = $("hyps"); clear(box);
  const hs = [...(d.hypotheses || [])].sort((a, b) => b.score - a.score).slice(0, 4);
  if (!hs.length) { box.appendChild(el("p", "empty", "No hypothesis above the noise floor.")); return; }
  for (const h of hs) {
    const c = el("div", "hyp" + (h.hypothesis_id === d.top_hypothesis_id ? " top" : ""));
    const r = el("div", "row"); r.append(el("span", null, h.fault_type.replace(/_/g, " ")), el("span", null, Number(h.score).toFixed(2)));
    const bar = el("div", "bar"); const fill = el("i"); bar.appendChild(fill);
    c.append(r, el("div", "ent", h.entity.id + " · coverage " + Number(h.coverage).toFixed(2)), bar);
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
    const line = svg("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y }); line.appendChild(svg("title", {}, l.id)); g.appendChild(line);
    if (evidence.has(l.id)) later.push([line, "ev-link"]); if (root === l.id) later.push([line, "root"]);
  }
  for (const n of t.nodes) {
    if (!pos.has(n.id)) continue;
    const p = P(n.id);
    if (root === n.id) { const ring = svg("circle", { cx: p.x, cy: p.y, r: 12, class: "ring" }); g.appendChild(ring); later.push([ring, "on"]); }
    const c = svg("circle", { cx: p.x, cy: p.y, r: n.type === "device" ? 6.5 : 5, class: "node" });
    c.appendChild(svg("title", {}, `${n.id} (${n.type}${n.segment ? ", " + n.segment : ""})`)); g.appendChild(c);
    if (affected.has(n.id)) later.push([c, "affected"]); else if (evidence.has(n.id)) later.push([c, "evid"]);
    const hot = affected.has(n.id) || root === n.id;
    g.appendChild(svg("text", { x: p.x, y: p.y + 16, "text-anchor": "middle", class: hot ? "hot" : "",
      transform: `rotate(28 ${p.x} ${p.y + 16})` }, n.id));
  }
  frame(() => later.forEach(([n, c]) => n.classList.add(c)));
}

// ---------- report + actions ----------
function renderReport(rep) {
  const box = $("report"); clear(box); box.classList.remove("in"); void box.offsetWidth; box.classList.add("in");
  box.appendChild(el("span", "status " + rep.status, rep.status.replace(/_/g, " ")));
  box.appendChild(el("div", "root", rep.suspected_root_cause));
  const conf = Math.max(0, Math.min(1, Number(rep.confidence) || 0));
  const cl = el("div", "conf"); const b = el("b", null, conf.toFixed(2) + " · " + rep.confidence_category);
  cl.append(el("span", null, "Confidence"), b); box.appendChild(cl);
  const bar = el("div", "bar confbar"); const fill = el("i"); bar.appendChild(fill); box.appendChild(bar);
  frame(() => { fill.style.transform = "scaleX(" + conf + ")"; });
  const kv = el("dl", "kv");
  const add = (k, v) => { kv.append(el("dt", null, k), el("dd", null, v)); };
  add("Affected", (rep.affected_devices || []).join(", ") || "-");
  add("Decided by", rep.decision_source || "deterministic_scoring");
  add("Sources", (rep.evidence_sources || []).join(", ") || "-");
  if ((rep.alternative_causes || []).length) add("Alternatives", rep.alternative_causes.slice(0, 2).join("; "));
  if (rep.llm && rep.llm.hints && rep.llm.hints.length) add("LLM hint", rep.llm.hints.map(h => h.fault_type).join(", ") + " (advisory)");
  if (rep.status === "insufficient_evidence" && (rep.missing_signals || []).length) add("Missing", rep.missing_signals.slice(0, 4).join(", "));
  box.appendChild(kv);
  const ev = el("div", "evid");
  for (const e of (rep.supporting_evidence || []).slice(0, 6)) {
    const btn = el("button"); btn.type = "button"; btn.title = "Show the message that carried " + e.finding_id;
    btn.append(el("span", null, e.metric + " · " + (e.entity || "")), el("span", "v", fmt(e.value) + " " + (e.unit || "")));
    btn.addEventListener("click", () => { const s = S.fseq.get(e.finding_id); if (s) highlight(s); });
    ev.appendChild(btn);
  }
  if (ev.childNodes.length) box.appendChild(ev);
}

function decisions() { const m = new Map(); for (const e of S.events) if (e.message_type === "human_decision") m.set(e.payload.action_id, e); return m; }
function plans() { const m = new Map(); for (const e of S.events) if (e.message_type === "remediation_plan") m.set(e.payload.action_id, e); return m; }

function renderActions() {
  const rep = S.report; if (!rep || !$("report").classList.contains("in")) return;
  const box = $("actions"); clear(box);
  const dec = decisions(), pl = plans();
  const details = rep.action_details || [];
  if (!details.length) { box.appendChild(el("p", "empty", "No actions proposed.")); return; }
  for (const a of details) {
    const card = el("div", "act" + (a.allowed ? "" : " blocked"));
    const top = el("div", "top"); const txt = el("div");
    txt.append(el("span", "id", a.id + " · " + a.action), el("span", "txt", a.text));
    const btns = el("div", "btns");
    for (const [d, cls, label] of [["approve", "ok", "Approve"], ["reject", "no", "Reject"]]) {
      const b = el("button", "mini " + cls, label); b.type = "button"; b.addEventListener("click", () => decide(a.id, d, b)); btns.appendChild(b);
    }
    top.append(txt, btns); card.appendChild(top);
    if (!a.allowed) {
      const r = el("div", "rule"); r.textContent = "Blocked by " + a.rule_id + " · approval produces no plan"; card.appendChild(r);
    }
    if (dec.has(a.id)) {
      const e = dec.get(a.id); const pol = S.policy.get(a.id);
      card.appendChild(el("div", "decision", `${e.payload.decision} recorded as event #${e.seq}` +
        (pol && pol.rule_id ? ` · blocked by ${pol.rule_id}, no plan` : "") + " · nothing executed"));
    }
    if (pl.has(a.id)) {
      const e = pl.get(a.id), p = e.payload;
      const plan = el("div", "plan");
      plan.appendChild(el("div", "lbl", p.label + " · dry-run #" + e.seq));
      const ol = el("ol"); for (const s of p.steps) ol.appendChild(el("li", null, s)); plan.appendChild(ol);
      for (const s of p.rollback) plan.appendChild(el("div", "rb", "Rollback: " + s));
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
    toast(r.plan_seq ? `Dry-run plan #${r.plan_seq} ready: simulated, not executed`
      : r.policy && r.policy.rule_id ? `Blocked by ${r.policy.rule_id}: no plan` : `${decision} recorded`);
  } catch (err) { toast("Failed: " + err.message); }
  finally { btn.disabled = false; }
}

// ---------- run / replay ----------
async function stream(incident) {
  if (S.es) S.es.close();
  Object.assign(S, { incident, events: [], fseq: new Map(), buf: new ReorderBuffer(), predRows: new Map(), shownPlans: new Set() });
  clear($("feed")); clear($("hyps")); clear($("preds")); clear($("actions"));
  const r = $("report"); clear(r); r.classList.remove("in"); r.appendChild(el("p", "empty", "Agents are working…"));
  $("msgcount").textContent = "";
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
    renderReport(S.report); renderActions();
    drawTopology(new Set(S.report.affected_devices || []), new Set((S.report.supporting_evidence || []).map(e => e.entity)), localizedRoot());
  });
  es.onerror = () => { es.close(); S.es = null; };
}

async function run() {
  const btn = $("run"); btn.disabled = true;
  try {
    const r = await api("/scenarios/" + encodeURIComponent($("scenario").value) + "/run?external=true", { method: "POST" });
    await stream(r.incident_id);
    loadHistory(); loadAgents();
  } catch (err) { toast("Run failed: " + err.message); }
  finally { btn.disabled = false; }
}

async function loadHistory() {
  try {
    const rows = await api("/incidents?limit=25");
    const sel = $("history"); clear(sel); sel.appendChild(el("option", null, "Past runs")).value = "";
    for (const r of rows) { const o = el("option", null, r.incident_id + " · " + r.status.replace(/_/g, " ")); o.value = r.incident_id; sel.appendChild(o); }
  } catch { /* optional */ }
}

document.addEventListener("DOMContentLoaded", async () => {
  try {
    const [sc, topo] = await Promise.all([api("/scenarios"), api("/topology")]);
    for (const s of sc.scenarios) { const o = el("option", null, s.name.replace(/_/g, " ")); o.value = s.name; $("scenario").appendChild(o); }
    S.topo = topo; drawTopology();
  } catch (err) { toast("Backend not reachable: " + err.message); }
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
