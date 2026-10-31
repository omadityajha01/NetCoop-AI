// NetCoop dashboard: vanilla JS, no build, no CDN, no libraries.
// PI8: every data field is rendered with textContent / createTextNode / setAttribute. Never innerHTML.
// Motion (S2): CSS transitions/keyframes on transform + opacity only, so nothing reflows; all of it is disabled by
// prefers-reduced-motion (CSS media query + delayFor() returns 0, i.e. no paced replay).
"use strict";

// ---------- pure helpers (unit-tested with Node: tests/security/test_dashboard_anim.py) ----------
const INTERNAL = new Set(["normalizer", "orchestrator", "performance_agent", "infrastructure_agent", "connectivity_agent",
  "correlation_agent", "reporting_agent", "triage_agent", "human_operator", "remediation_planner"]);
const SPEED_MS = { "1": 240, "2": 120, "0": 0 };

/** Releases events strictly in seq order (1, 2, 3, ...), whatever order they arrive in; duplicates are dropped. */
class ReorderBuffer {
  constructor(next = 1) { this.next = next; this.pending = new Map(); }
  push(ev) {
    if (typeof ev.seq !== "number" || ev.seq < this.next || this.pending.has(ev.seq)) return [];
    this.pending.set(ev.seq, ev);
    const out = [];
    while (this.pending.has(this.next)) { out.push(this.pending.get(this.next)); this.pending.delete(this.next); this.next += 1; }
    return out;
  }
}

/** Replay pacing per message: 1× = 240 ms, 2× = 120 ms, instant = 0; reduced motion is always 0 (no animation). */
function delayFor(speed, reducedMotion) { return reducedMotion ? 0 : (SPEED_MS[String(speed)] ?? SPEED_MS["1"]); }

function isExternal(sender) { return !INTERNAL.has(sender); }

/** prediction_id -> seq of the message that carried its evidence (when the card may flip). */
function flipSeqs(report, findingSeq) {
  const out = new Map();
  for (const p of (report && report.predictions) || []) {
    if (p.evidence_finding_id && findingSeq.has(p.evidence_finding_id)) out.set(p.prediction_id, findingSeq.get(p.evidence_finding_id));
  }
  return out;
}

/** Entity the top hypothesis is attached to (the localized root), from the last diagnosis message. */
function localizedRoot(events) {
  const d = [...events].reverse().find(e => e.message_type === "diagnosis");
  if (!d) return null;
  const top = (d.payload.hypotheses || []).find(h => h.hypothesis_id === d.payload.top_hypothesis_id);
  return top ? top.entity.id : null;
}

/** raw -> canonical rows from a message's findings: renamed fields, unit conversions, entity ids. Deduplicated. */
function transformRows(findings, seen) {
  const rows = [];
  for (const f of findings || []) {
    for (const t of f.transforms || []) {
      let raw, canon;
      if (t.step === "unit") { raw = t.field + " " + t.from; canon = f.metric + " " + t.to; }
      else if (t.step === "alias") { raw = t.from; canon = t.to; }
      else if (t.step === "entity") { raw = t.from; canon = t.to; }
      else continue;
      const key = t.step + "|" + raw;
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push({ step: t.step, raw: String(raw), canon: String(canon), reason: String(t.reason || "") });
    }
  }
  return rows;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { ReorderBuffer, delayFor, isExternal, flipSeqs, localizedRoot, transformRows };
}

// ---------- DOM ----------
const SVGNS = "http://www.w3.org/2000/svg";
const state = { incident: null, events: [], findingSeq: new Map(), report: null, source: null, topo: null,
                buffer: new ReorderBuffer(), flips: new Map(), seenTransforms: new Set(), predRows: new Map() };

function $(id) { return document.getElementById(id); }
function reducedMotion() { return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches; }

function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (k === "class") n.className = v;
    else if (k === "on") for (const [ev, fn] of Object.entries(v)) n.addEventListener(ev, fn);
    else n.setAttribute(k, String(v));
  }
  for (const k of kids) n.appendChild(k instanceof Node ? k : document.createTextNode(k == null ? "" : String(k)));
  return n;
}

function svg(tag, attrs, text) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, String(v));
  if (text != null) n.textContent = String(text);
  return n;
}

function clear(n) { while (n.firstChild) n.removeChild(n.firstChild); }
function status(t) { $("status").textContent = t; }
function nextFrame(fn) { requestAnimationFrame(() => requestAnimationFrame(fn)); }
function flash(node, cls) {
  if (!node || reducedMotion()) return;
  node.classList.remove(cls); void node.getBoundingClientRect(); node.classList.add(cls);
}

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body.detail && body.detail.detail) || body.detail || ("HTTP " + r.status));
  return body;
}

// ---------- lanes ----------
function laneId(sender) { return "lane-" + sender.replace(/[^a-z0-9_]/gi, "_"); }

function laneFor(sender) {
  let lane = document.getElementById(laneId(sender));
  if (!lane) {
    const head = el("div", { class: "lane-head" }, sender);
    if (isExternal(sender)) head.appendChild(el("span", { class: "badge a2a", title: "external agent discovered from the allowlist" }, "joined via A2A"));
    lane = el("div", { class: "lane" + (isExternal(sender) ? " external" : ""), id: laneId(sender) }, head);
    $("lanes").appendChild(lane);
  }
  return lane;
}

function resetView() {
  clear($("lanes"));
  const old = document.getElementById("detail");
  if (old) old.remove();
  Object.assign(state, { events: [], findingSeq: new Map(), buffer: new ReorderBuffer(), flips: new Map(),
                         seenTransforms: new Set(), predRows: new Map() });
  $("msgcount").textContent = "";
  for (const id of ["evidence", "predictions", "actions", "blocked", "quarantine", "transforms"]) clear($(id).tBodies[0]);
  for (const id of ["normsummary", "limitations"]) clear($(id));
  const box = $("report"); clear(box); box.className = "muted"; box.textContent = "the report appears when the last message lands";
  $("confbar").classList.remove("on"); $("conffill").style.transform = "scaleX(0)";
  drawTopology(new Set(), new Set(), null);
}

function showDetail(obj) {
  let d = document.getElementById("detail");
  if (!d) { d = el("pre", { id: "detail" }); $("lanes-panel").appendChild(d); }
  d.textContent = JSON.stringify(obj, null, 2);
}

function selectSeq(seq, focus) {
  document.querySelectorAll(".msg.sel").forEach(m => m.classList.remove("sel"));
  const chip = document.getElementById("msg-" + seq);
  if (chip) { chip.classList.add("sel"); chip.scrollIntoView({ block: "nearest", inline: "nearest" }); }
  const ev = state.events.find(e => e.seq === seq);
  if (focus) showDetail(focus);
  else if (ev) showDetail(ev);
}

function receive(ev) { for (const e of state.buffer.push(ev)) addEvent(e); }

function addEvent(ev) {
  state.events.push(ev);
  const p = ev.payload || {};
  for (const f of (p.findings || [])) if (f && f.finding_id && !state.findingSeq.has(f.finding_id)) state.findingSeq.set(f.finding_id, ev.seq);
  const label = ev.message_type + (ev.recipient ? " → " + ev.recipient : "");
  const chip = el("div", { class: "msg enter t-" + ev.message_type, id: "msg-" + ev.seq, title: ev.message_id,
                           on: { click: () => selectSeq(ev.seq) } },
                  el("span", { class: "seq" }, "#" + ev.seq + " "), label);
  const lane = laneFor(ev.sender);
  lane.appendChild(chip);
  lane.scrollTop = lane.scrollHeight;
  flash(lane.querySelector(".lane-head"), "pulse-out");
  const to = document.getElementById(laneId(ev.recipient || ""));
  if (to && to !== lane) flash(to.querySelector(".lane-head"), "pulse-in");
  $("msgcount").textContent = "(" + state.events.length + " messages, event-log order)";

  if (ev.message_type === "prediction") addPredictionCard(ev);
  if (p.findings) { addTransformRows(p.findings); flipPredictions(ev.seq); }
  if (ev.message_type === "normalization_summary") renderNormalization(ev);
  if (ev.message_type === "remediation_plan" || ev.message_type === "human_decision") renderActions();
}

// ---------- predictions: a card per prediction, flipped when its evidence lands ----------
function addPredictionCard(ev) {
  const pr = ev.payload.prediction;
  const sig = pr.signal.metric + "@" + pr.signal.entity.id;
  const flip = el("span", { class: "flip" }, el("span", { class: "face front" }, "pending"),
                  el("span", { class: "face back" }, ""));
  const row = el("tr", { id: "pred-" + pr.prediction_id }, el("td", {}, pr.fault_type || ""), el("td", {}, sig),
                 el("td", {}, pr.expected.op + " " + pr.expected.ref), el("td", {}, flip), el("td", { class: "num" }, "#" + ev.seq));
  state.predRows.set(pr.prediction_id, row);
  $("predictions").tBodies[0].appendChild(row);
  if (state.report) state.flips = flipSeqs(state.report, state.findingSeq);
}

function flipPredictions(seq) {
  if (!state.report) return;
  state.flips = flipSeqs(state.report, state.findingSeq);
  for (const p of state.report.predictions || []) {
    if (state.flips.get(p.prediction_id) !== seq) continue;
    const row = state.predRows.get(p.prediction_id);
    if (!row) continue;
    const back = row.querySelector(".back");
    back.textContent = p.outcome + (p.observed != null ? " (" + p.observed + ")" : "");
    row.querySelector(".flip").classList.add("flipped", p.outcome === "hit" ? "hit" : (p.outcome === "miss" ? "miss" : "unk"));
  }
}

function settlePredictions(rep) {  // final state, e.g. after an instant replay or for outcomes with no evidence message
  for (const p of rep.predictions || []) {
    const row = state.predRows.get(p.prediction_id);
    if (!row) continue;
    const f = row.querySelector(".flip");
    if (!f.classList.contains("flipped")) {
      row.querySelector(".back").textContent = p.outcome + (p.observed != null ? " (" + p.observed + ")" : "");
      f.classList.add("flipped", p.outcome === "hit" ? "hit" : (p.outcome === "miss" ? "miss" : "unk"));
    }
  }
}

// ---------- normalization: raw -> canonical rows ----------
function addTransformRows(findings) {
  const body = $("transforms").tBodies[0];
  for (const r of transformRows(findings, state.seenTransforms)) {
    if (body.children.length >= 40) return;
    const morph = el("span", { class: "morph" }, el("span", { class: "raw" }, r.raw), el("span", { class: "canon" }, r.canon));
    const row = el("tr", { class: "enter" }, el("td", {}, r.step), el("td", {}, morph), el("td", { class: "muted" }, r.reason));
    body.appendChild(row);
    if (reducedMotion()) morph.classList.add("done"); else setTimeout(() => morph.classList.add("done"), 450);
  }
}

function renderNormalization(ns) {
  const nbox = $("normsummary"); clear(nbox);
  nbox.appendChild(el("p", {}, Object.entries(ns.payload.summary || {}).map(([k, v]) => k + ": " + v).join(" · ")));
  rows($("quarantine").tBodies[0], (ns.payload.quarantined || []).slice(0, 200), r => el("tr", {}, el("td", {}, r.code),
    el("td", {}, r.field), el("td", {}, r.reason), el("td", {}, r.source_ref)));
}

// ---------- stream / replay ----------
async function stream(incident, speed) {
  if (state.source) state.source.close();
  resetView();
  state.incident = incident;
  try { state.report = await getJSON("/incidents/" + encodeURIComponent(incident) + "/report"); }  // revealed only at the end
  catch (err) { status("failed to load report: " + err.message); return; }
  const delay = delayFor(speed, reducedMotion());
  status("replaying " + incident + " from its event log" + (delay ? " at " + (speed === "2" ? "2×" : "1×") : "") + "…");
  const es = new EventSource("/incidents/" + encodeURIComponent(incident) + "/stream?delay_ms=" + encodeURIComponent(delay));
  state.source = es;
  es.addEventListener("message", e => receive(JSON.parse(e.data)));
  es.addEventListener("end", () => {
    es.close(); state.source = null;
    revealReport(state.report);
    status("done: " + incident + " (" + state.events.length + " messages)");
  });
  es.onerror = () => { es.close(); state.source = null; status("stream closed"); };
}

// ---------- topology ----------
async function loadTopology() {
  state.topo = await getJSON("/topology");
  drawTopology(new Set(), new Set(), null);
}

function drawTopology(affected, evidence, root) {
  const t = state.topo, g = $("topo");
  if (!t) return;
  clear(g);
  const kids = new Map(), byId = new Map(t.nodes.map(n => [n.id, n]));
  for (const n of t.nodes) {
    if (n.parent && byId.has(n.parent)) { if (!kids.has(n.parent)) kids.set(n.parent, []); kids.get(n.parent).push(n.id); }
  }
  const roots = t.nodes.filter(n => !n.parent || !byId.has(n.parent)).map(n => n.id);
  const pos = new Map(); let leaf = 0, maxDepth = 0;
  (function place(ids, depth) {
    for (const id of ids) {
      const c = kids.get(id) || [];
      maxDepth = Math.max(maxDepth, depth);
      if (c.length === 0) pos.set(id, { x: leaf++, y: depth });
      else { place(c, depth + 1); const xs = c.map(k => pos.get(k).x); pos.set(id, { x: (Math.min(...xs) + Math.max(...xs)) / 2, y: depth }); }
    }
  })(roots, 0);
  const W = Math.max(leaf * 46, 400), H = (maxDepth + 1) * 70 + 20;
  g.setAttribute("viewBox", "0 0 " + W + " " + H);
  const P = id => { const p = pos.get(id); return { x: 23 + p.x * 46, y: 20 + p.y * 70 }; };
  const later = [];
  for (const l of t.links) {
    if (!pos.has(l.a) || !pos.has(l.b)) continue;
    const a = P(l.a), b = P(l.b);
    const line = svg("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y });
    line.appendChild(svg("title", {}, l.id));
    g.appendChild(line);
    if (evidence.has(l.id)) later.push([line, "evidence"]);
    if (root === l.id) later.push([line, "root"]);
  }
  for (const n of t.nodes) {
    if (!pos.has(n.id)) continue;
    const p = P(n.id);
    const c = svg("circle", { cx: p.x, cy: p.y, r: n.type === "device" ? 8 : 6 });
    c.appendChild(svg("title", {}, n.id + " (" + n.type + (n.segment ? ", " + n.segment : "") + ")"));
    g.appendChild(c);
    if (affected.has(n.id)) later.push([c, "affected"]); else if (evidence.has(n.id)) later.push([c, "evidence"]);
    if (root === n.id) {
      const ring = svg("circle", { cx: p.x, cy: p.y, r: 14, class: "root-ring" });
      g.insertBefore(ring, c);
      later.push([ring, "on"]);
    }
    g.appendChild(svg("text", { x: p.x, y: p.y + 18, "text-anchor": "middle", transform: "rotate(25 " + p.x + " " + (p.y + 18) + ")" }, n.id));
  }
  nextFrame(() => { for (const [node, cls] of later) node.classList.add(cls); });  // fade in via CSS transitions
}

// ---------- report ----------
function fidLink(fid) {
  if (!fid) return document.createTextNode("");
  return el("button", { class: "fid", type: "button", title: "show the message that carried this finding", on: { click: () => {
    const seq = state.findingSeq.get(fid);
    const ev = state.events.find(e => e.seq === seq);
    const f = ev && (ev.payload.findings || []).find(x => x.finding_id === fid);
    if (seq) { $("lanes-panel").scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" }); selectSeq(seq, f || null); }
  } } }, fid);
}

function rows(tbody, items, make) {
  clear(tbody);
  if (!items.length) tbody.appendChild(el("tr", {}, el("td", { colspan: 6, class: "muted" }, "none")));
  for (const it of items) tbody.appendChild(make(it));
}

function decisionsFor() {
  const m = new Map();
  for (const e of state.events) if (e.message_type === "human_decision") m.set(e.payload.action_id, e.payload.decision + " (#" + e.seq + ")");
  return m;
}

function plansFor() {
  const m = new Map();
  for (const e of state.events) if (e.message_type === "remediation_plan") m.set(e.payload.action_id, e);
  return m;
}

const lastPolicy = new Map();  // action_id -> policy result of the latest approve in this session (blocked -> rule id)
const revealedPlans = new Set();  // plan seqs already shown (reveal animation plays once)

async function decide(actionId, decision) {
  try {
    const r = await getJSON("/incidents/" + encodeURIComponent(state.incident) + "/feedback", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_id: actionId, decision }) });
    if (r.policy) lastPolicy.set(actionId, r.policy);
    const evs = await getJSON("/incidents/" + encodeURIComponent(state.incident) + "/events");
    for (const e of evs) receive(e);  // human_decision / remediation_plan events re-render the actions (plan reveals once)
    let msg = "recorded " + decision + " for " + actionId + " as event #" + r.event_seq;
    if (r.plan_seq) msg += "; dry-run plan #" + r.plan_seq + " (SIMULATED, NOT EXECUTED)";
    else if (r.policy && r.policy.rule_id) msg += "; blocked by " + r.policy.rule_id + ", no plan";
    status(msg + " (nothing executed; diagnosis unchanged)");
  } catch (err) { status("feedback failed: " + err.message); }
}

function decisionButtons(id) {
  return [el("button", { class: "ghost", type: "button", on: { click: () => decide(id, "approve") } }, "approve"), " ",
          el("button", { class: "ghost", type: "button", on: { click: () => decide(id, "reject") } }, "reject")];
}

function planBox(ev) {
  const p = ev.payload;
  const fresh = !revealedPlans.has(ev.seq);
  revealedPlans.add(ev.seq);
  const box = el("div", { class: "plan" + (fresh ? " reveal" : ""), id: "plan-" + p.action_id },
    el("div", { class: "plan-label" }, p.label + " · dry-run #" + ev.seq + " · policy checked" +
                                       (p.policy && p.policy.checked_at ? " at " + p.policy.checked_at : "")));
  const ol = el("ol", {});
  for (const s of p.steps) ol.appendChild(el("li", {}, s));
  box.appendChild(ol);
  for (const s of p.rollback) box.appendChild(el("div", { class: "rollback" }, "Rollback: " + s));
  return box;
}

function renderActions() {
  const rep = state.report; if (!rep || !$("report").classList.contains("shown")) return;
  const dec = decisionsFor(), plans = plansFor();
  const blockedIds = new Set((rep.blocked_actions || []).map(b => b.action_id));
  const recs = (rep.action_details || []).filter(a => !blockedIds.has(a.id));
  rows($("actions").tBodies[0], recs, a => {
    const cell = el("td", {}, dec.has(a.id) ? dec.get(a.id) + " " : "", ...decisionButtons(a.id));
    const text = el("td", {}, a.text);
    if (plans.has(a.id)) text.appendChild(planBox(plans.get(a.id)));
    return el("tr", {}, el("td", {}, a.id), text, cell);
  });
  rows($("blocked").tBodies[0], rep.blocked_actions || [], b => {
    const pol = lastPolicy.get(b.action_id);
    const note = dec.has(b.action_id) ? dec.get(b.action_id) + (pol && pol.rule_id ? " · blocked by " + pol.rule_id + ", no plan" : "") + " " : "";
    return el("tr", {}, el("td", {}, b.action_id), el("td", {}, b.action), el("td", {}, b.rule_id), el("td", {}, b.reason),
              el("td", {}, note, ...decisionButtons(b.action_id)));
  });
}

function revealReport(rep) {
  const box = $("report"); clear(box); box.className = "slide-in shown";
  const dl = el("dl", { class: "kv" });
  const kv = (k, v, cls) => { dl.appendChild(el("dt", {}, k)); dl.appendChild(el("dd", cls ? { class: cls } : {}, v)); };
  kv("incident", rep.incident_id);
  kv("status", rep.status, "status-" + rep.status);
  kv("root cause", rep.suspected_root_cause);
  kv("confidence", Number(rep.confidence).toFixed(2) + " (" + rep.confidence_category + ")");
  kv("affected", (rep.affected_devices || []).join(", "));
  kv("alternatives", (rep.alternative_causes || []).join("; ") || "none");
  kv("decided by", rep.decision_source || "deterministic_scoring");
  kv("sources", (rep.evidence_sources || []).join(", "));
  if (rep.scoring) kv("scoring", Object.entries(rep.scoring).map(([k, v]) => k + "=" + v).join("  "));
  const llmInfo = rep.llm || { mode: "off", hints: [] };
  kv("LLM", llmInfo.mode === "off" ? "off" : llmInfo.mode + " · " + llmInfo.model + " · narrative from " + llmInfo.narrative_source);
  if ((llmInfo.hints || []).length)
    kv("LLM hints (advisory)", llmInfo.hints.map(h => h.fault_type + ": " + h.rationale).join("; "));
  if (rep.narrative) kv("narrative", rep.narrative);
  box.appendChild(dl);
  const conf = Math.max(0, Math.min(1, Number(rep.confidence) || 0));
  $("confbar").classList.add("on");
  $("conflabel").textContent = "confidence " + conf.toFixed(2) + " (" + rep.confidence_category + ")";
  nextFrame(() => { $("conffill").style.transform = "scaleX(" + conf + ")"; });  // CSSOM, allowed by the CSP

  rows($("evidence").tBodies[0], rep.supporting_evidence || [], e => el("tr", {},
    el("td", {}, e.metric), el("td", {}, e.entity || ""), el("td", { class: "num" }, String(e.value) + " " + (e.unit || "")),
    el("td", {}, e.interpretation), el("td", {}, fidLink(e.finding_id))));
  settlePredictions(rep);
  renderActions();
  const ul = $("limitations"); clear(ul);
  for (const l of (rep.limitations || [])) ul.appendChild(el("li", {}, l));
  const affected = new Set(rep.affected_devices || []);
  const evid = new Set((rep.supporting_evidence || []).map(e => e.entity).filter(Boolean));
  drawTopology(affected, evid, localizedRoot(state.events));
}

// ---------- controls ----------
async function loadScenarios() {
  const s = await getJSON("/scenarios");
  const sel = $("scenario"); clear(sel);
  for (const x of s.scenarios) sel.appendChild(el("option", { value: x.name }, x.name));
}

async function loadHistory() {
  const h = await getJSON("/incidents?limit=30");
  const sel = $("history"); clear(sel);
  sel.appendChild(el("option", { value: "" }, "(choose)"));
  for (const r of h) sel.appendChild(el("option", { value: r.incident_id }, r.incident_id + " · " + r.status));
}

async function runScenario() {
  const btn = $("run"); btn.disabled = true;
  try {
    status("running " + $("scenario").value + " (all agents run; deterministic scoring)…");
    const r = await getJSON("/scenarios/" + encodeURIComponent($("scenario").value) + "/run?external=" + $("external").checked,
                            { method: "POST" });
    await stream(r.incident_id, $("speed").value);
    loadHistory();
  } catch (err) { status("run failed: " + err.message); }
  finally { btn.disabled = false; }
}

if (typeof document !== "undefined") {
  document.addEventListener("DOMContentLoaded", async () => {
    $("run").addEventListener("click", runScenario);
    $("replay").addEventListener("click", () => { if (state.incident) stream(state.incident, $("speed").value); });
    $("history").addEventListener("change", e => { if (e.target.value) stream(e.target.value, "0"); });
    try { await Promise.all([loadScenarios(), loadTopology(), loadHistory()]); status("ready"); }
    catch (err) { status("failed to load: " + err.message); }
  });
}
