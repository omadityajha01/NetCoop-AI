// NetCoop dashboard: vanilla JS, no build, no CDN.
// PI8: every data field is rendered with textContent / createTextNode / setAttribute. Never innerHTML.
"use strict";

const SVGNS = "http://www.w3.org/2000/svg";
const state = { incident: null, events: [], findingSeq: new Map(), report: null, source: null, topo: null };

function $(id) { return document.getElementById(id); }

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

async function getJSON(url, opts) {
  const r = await fetch(url, opts);
  const body = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error((body.detail && body.detail.detail) || body.detail || ("HTTP " + r.status));
  return body;
}

// ---------- lanes ----------
function laneFor(sender) {
  const id = "lane-" + sender.replace(/[^a-z0-9_]/gi, "_");
  let lane = document.getElementById(id);
  if (!lane) {
    lane = el("div", { class: "lane", id }, el("div", { class: "lane-head" }, sender));
    $("lanes").appendChild(lane);
  }
  return lane;
}

function resetLanes() {
  clear($("lanes"));
  const old = document.getElementById("detail");
  if (old) old.remove();
  state.events = []; state.findingSeq = new Map();
  $("msgcount").textContent = "";
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

function addEvent(ev) {
  state.events.push(ev);
  const p = ev.payload || {};
  for (const f of (p.findings || [])) if (f && f.finding_id && !state.findingSeq.has(f.finding_id)) state.findingSeq.set(f.finding_id, ev.seq);
  const label = ev.message_type + (ev.recipient ? " → " + ev.recipient : "");
  const chip = el("div", { class: "msg t-" + ev.message_type, id: "msg-" + ev.seq, title: ev.message_id,
                           on: { click: () => selectSeq(ev.seq) } },
                  el("span", { class: "seq" }, "#" + ev.seq + " "), label);
  laneFor(ev.sender).appendChild(chip);
  $("msgcount").textContent = "(" + state.events.length + " messages, event-log order)";
}

function stream(incident, delay) {
  if (state.source) state.source.close();
  resetLanes();
  status("streaming " + incident + " from its event log…");
  const es = new EventSource("/incidents/" + encodeURIComponent(incident) + "/stream?delay_ms=" + encodeURIComponent(delay));
  state.source = es;
  es.addEventListener("message", e => addEvent(JSON.parse(e.data)));
  es.addEventListener("end", async () => {
    es.close(); state.source = null;
    await loadReport(incident);
    status("done: " + incident + " (" + state.events.length + " messages)");
  });
  es.onerror = () => { es.close(); state.source = null; status("stream closed"); };
}

// ---------- topology ----------
async function loadTopology() {
  state.topo = await getJSON("/topology");
  drawTopology(new Set(), new Set());
}

function drawTopology(affected, evidence) {
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
  for (const l of t.links) {
    if (!pos.has(l.a) || !pos.has(l.b)) continue;
    const a = P(l.a), b = P(l.b);
    const line = svg("line", { x1: a.x, y1: a.y, x2: b.x, y2: b.y, class: evidence.has(l.id) ? "evidence" : "" });
    line.appendChild(svg("title", {}, l.id));
    g.appendChild(line);
  }
  for (const n of t.nodes) {
    if (!pos.has(n.id)) continue;
    const p = P(n.id);
    const cls = affected.has(n.id) ? "affected" : (evidence.has(n.id) ? "evidence" : "");
    const c = svg("circle", { cx: p.x, cy: p.y, r: n.type === "device" ? 8 : 6, class: cls });
    c.appendChild(svg("title", {}, n.id + " (" + n.type + (n.segment ? ", " + n.segment : "") + ")"));
    g.appendChild(c);
    g.appendChild(svg("text", { x: p.x, y: p.y + 18, "text-anchor": "middle", transform: "rotate(25 " + p.x + " " + (p.y + 18) + ")" }, n.id));
  }
}

// ---------- report ----------
function fidLink(fid) {
  if (!fid) return document.createTextNode("");
  return el("button", { class: "fid", type: "button", title: "show the message that carried this finding", on: { click: () => {
    const seq = state.findingSeq.get(fid);
    const ev = state.events.find(e => e.seq === seq);
    const f = ev && (ev.payload.findings || []).find(x => x.finding_id === fid);
    if (seq) { $("lanes-panel").scrollIntoView({ block: "start", behavior: "smooth" }); selectSeq(seq, f || null); }
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

async function decide(actionId, decision) {
  try {
    const r = await getJSON("/incidents/" + encodeURIComponent(state.incident) + "/feedback", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action_id: actionId, decision }) });
    const evs = await getJSON("/incidents/" + encodeURIComponent(state.incident) + "/events");
    for (const e of evs) if (!state.events.find(x => x.seq === e.seq)) addEvent(e);
    renderActions();
    status("recorded " + decision + " for " + actionId + " as event #" + r.event_seq + " (nothing executed; diagnosis unchanged)");
  } catch (err) { status("feedback failed: " + err.message); }
}

function renderActions() {
  const rep = state.report; if (!rep) return;
  const dec = decisionsFor();
  const blockedIds = new Set((rep.blocked_actions || []).map(b => b.action_id));
  const recs = (rep.action_details || []).filter(a => !blockedIds.has(a.id));
  rows($("actions").tBodies[0], recs, a => el("tr", {}, el("td", {}, a.id), el("td", {}, a.text),
    el("td", {}, dec.has(a.id) ? dec.get(a.id) : "",
      el("button", { class: "ghost", type: "button", on: { click: () => decide(a.id, "approve") } }, "approve"), " ",
      el("button", { class: "ghost", type: "button", on: { click: () => decide(a.id, "reject") } }, "reject"))));
  rows($("blocked").tBodies[0], rep.blocked_actions || [], b => el("tr", {}, el("td", {}, b.action_id), el("td", {}, b.action),
    el("td", {}, b.rule_id), el("td", {}, b.reason)));
}

async function loadReport(incident) {
  const rep = await getJSON("/incidents/" + encodeURIComponent(incident) + "/report");
  state.report = rep; state.incident = incident;
  const box = $("report"); clear(box); box.className = "";
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
  if (rep.narrative) kv("narrative", rep.narrative);
  box.appendChild(dl);

  rows($("evidence").tBodies[0], rep.supporting_evidence || [], e => el("tr", {},
    el("td", {}, e.metric), el("td", {}, e.entity || ""), el("td", { class: "num" }, String(e.value) + " " + (e.unit || "")),
    el("td", {}, e.interpretation), el("td", {}, fidLink(e.finding_id))));

  const predSeq = new Map();
  for (const e of state.events) if (e.message_type === "prediction") predSeq.set(e.payload.prediction.prediction_id, e.seq);
  rows($("predictions").tBodies[0], rep.predictions || [], p => el("tr", {},
    el("td", {}, p.hypothesis), el("td", {}, p.signal), el("td", {}, p.expected),
    el("td", { class: p.outcome === "hit" ? "hit" : (p.outcome === "miss" ? "miss" : "") }, p.outcome),
    el("td", { class: "num" }, predSeq.has(p.prediction_id) ? "#" + predSeq.get(p.prediction_id) : "")));

  renderActions();

  const ns = state.events.find(e => e.message_type === "normalization_summary");
  const nbox = $("normsummary"); clear(nbox);
  const q = ns ? (ns.payload.quarantined || []) : [];
  if (ns) nbox.appendChild(el("p", {}, Object.entries(ns.payload.summary || {}).map(([k, v]) => k + ": " + v).join(" · ")));
  rows($("quarantine").tBodies[0], q.slice(0, 200), r => el("tr", {}, el("td", {}, r.code), el("td", {}, r.field),
    el("td", {}, r.reason), el("td", {}, r.source_ref)));

  const ul = $("limitations"); clear(ul);
  for (const l of (rep.limitations || [])) ul.appendChild(el("li", {}, l));

  const affected = new Set(rep.affected_devices || []);
  const evid = new Set((rep.supporting_evidence || []).map(e => e.entity).filter(Boolean));
  drawTopology(affected, evid);
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
    state.incident = r.incident_id;
    stream(r.incident_id, $("speed").value);
    loadHistory();
  } catch (err) { status("run failed: " + err.message); }
  finally { btn.disabled = false; }
}

document.addEventListener("DOMContentLoaded", async () => {
  $("run").addEventListener("click", runScenario);
  $("history").addEventListener("change", e => { if (e.target.value) { state.incident = e.target.value; stream(e.target.value, 0); } });
  try { await Promise.all([loadScenarios(), loadTopology(), loadHistory()]); status("ready"); }
  catch (err) { status("failed to load: " + err.message); }
});
