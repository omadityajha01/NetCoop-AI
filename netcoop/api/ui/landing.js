// NetCoop landing preview. Text-only rendering (textContent), same-origin API, CSP-safe (no inline code).
"use strict";

const reduced = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const sleep = ms => new Promise(r => setTimeout(r, reduced() ? 0 : ms));
const $ = id => document.getElementById(id);

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text != null) n.textContent = String(text);
  return n;
}

async function api(path, method = "GET") {
  const r = await fetch(path, { method });
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

// ---------- chat ----------
const body = () => $("chat-body");
function scrollChat() { const b = body(); b.scrollTop = b.scrollHeight; }

function userMsg(text) { body().appendChild(el("div", "msg user", text)); scrollChat(); }

function typing() { const t = el("div", "typing"); t.setAttribute("aria-label", "NetCoop is thinking"); for (let i = 0; i < 3; i++) t.appendChild(el("span")); body().appendChild(t); scrollChat(); return t; }

async function streamAi(text, speed = 18) {
  const m = el("div", "msg ai");
  const who = el("div", "who", "NetCoop");
  const out = el("span");
  const caret = el("span", "caret");
  m.append(who, out, caret);
  body().appendChild(m);
  const tokens = text.split(/(\s+)/);
  for (const tok of tokens) {           // token-by-token streaming (typewriter), skill: AI Interaction / Streaming
    out.textContent += tok;
    if (tok.trim()) { scrollChat(); await sleep(speed + Math.random() * speed); }
  }
  caret.remove();
  return m;
}

function contextCards(rows) {
  const box = el("div", "ctx");
  for (const [k, v, cls] of rows) {
    const c = el("div", "ctx-card" + (cls ? " " + cls : ""));
    c.append(el("span", "k", k), el("span", "v", v));
    box.appendChild(c);
  }
  body().appendChild(box);
  scrollChat();
}

function fmt(v) { return typeof v === "number" ? (Number.isInteger(v) ? String(v) : v.toFixed(2)) : String(v); }

function summarize(rep) {
  const conf = Number(rep.confidence).toFixed(2) + " (" + rep.confidence_category + ")";
  const root = rep.suspected_root_cause || rep.status;
  if (rep.status === "insufficient_evidence") {
    const miss = (rep.missing_signals || []).slice(0, 3).join(", ");
    return `I won't guess: the evidence is insufficient. ${root}. Missing signals: ${miss || "see report"}. ` +
           "Connect an agent that can provide them and ask again.";
  }
  if (rep.status === "no_fault_detected") return "No fault detected. All measurements are within their thresholds.";
  return `${root}. Confidence ${conf}. ` + (rep.predictions && rep.predictions.length
    ? `${rep.predictions.filter(p => p.outcome === "hit").length} of ${rep.predictions.length} logged predictions were hits. `
    : "") + "Here is the evidence I used:";
}

async function ask(text, scenario) {
  const chips = document.querySelectorAll(".chip"); chips.forEach(c => { c.disabled = true; });
  userMsg(text);
  const t = typing();
  $("chat-status").textContent = "agents working…";
  try {
    const run = await api("/scenarios/" + encodeURIComponent(scenario) + "/run?external=true", "POST");
    const rep = await api("/incidents/" + encodeURIComponent(run.incident_id) + "/report");
    await sleep(400);
    t.remove();
    await streamAi(summarize(rep));
    const rows = (rep.supporting_evidence || []).slice(0, 3).map(e => [e.metric + " · " + (e.entity || ""), fmt(e.value) + " " + (e.unit || "")]);
    for (const b of (rep.blocked_actions || []).slice(0, 1)) rows.push([b.action_id + " blocked", b.rule_id, "blocked"]);
    if (rows.length) contextCards(rows);
    $("chat-status").textContent = "deterministic scoring · " + run.incident_id;
  } catch (err) {
    t.remove();
    await streamAi("The backend isn't reachable from this page. Serve it with `netcoop serve --ui templates/netcoop_ui` " +
                   "(or `python tools/mock_api.py --ui templates/netcoop_ui`).");
    $("chat-status").textContent = "offline";
  } finally {
    chips.forEach(c => { c.disabled = false; });
  }
}

const KEYWORDS = [[/wi-?fi|wireless|signal|ap\b|access point/i, "weak_wifi"], [/dns|website|sites?|domain|resolve/i, "dns_failure"],
  [/dhcp|ip address|lease|new laptop/i, "dhcp_failure"], [/lab|disconnect|flap|cable|port/i, "interface_fault"],
  [/slow|lag|video|evening|congest|bandwidth/i, "congestion"], [/fine|normal|check|healthy/i, "normal"]];

function pickScenario(text) { const hit = KEYWORDS.find(([re]) => re.test(text)); return hit ? hit[1] : "congestion"; }

async function intro() {
  // Scripted opening exchange (numbers from the recorded congestion fixture), then hand over to the live API.
  userMsg("Hostel students say video calls freeze every evening.");
  const t = typing(); await sleep(1100); t.remove();
  await streamAi("Likely link congestion causing egress queue drops on L_HOSTEL_UPLINK. Confidence 1.00 (high). " +
                 "2 of 3 predictions I logged before looking were hits. Evidence:");
  contextCards([["link_utilization_pct · L_HOSTEL_UPLINK", "98.31 pct"], ["queue_drops_count · HOSTEL_CORE_SW_01", "528 count"],
                ["latency_ms · HOSTEL_CORE_SW_01", "286.44 ms"], ["CONG-4 reboot blocked", "R1", "blocked"]]);
}

// ---------- live SSE stream panel ----------
const STEP_OF = { normalization_summary: "normalize", task_request: "analyze", finding_report: "analyze", coverage_manifest: "analyze",
  prediction: "predict", evidence_request: "predict", evidence_response: "predict", diagnosis: "predict", report: "decide" };
const ORDER = ["normalize", "analyze", "predict", "decide"];

let stepMax = -1;
function setStep(step) {
  stepMax = Math.max(stepMax, ORDER.indexOf(step));  // only advance: task_requests recur later in the run
  const idx = stepMax;
  document.querySelectorAll("#steps li").forEach(li => {
    const i = ORDER.indexOf(li.dataset.step);
    li.classList.toggle("on", i === idx);
    li.classList.toggle("done", i < idx);
  });
}

function line(ev) {
  const out = $("stream-out");
  const row = document.createDocumentFragment();
  row.append(el("span", "t-seq", "#" + String(ev.seq).padStart(2, "0") + " "), el("span", "t-type", ev.message_type.padEnd(22)));
  let tail = " " + ev.sender + " → " + ev.recipient;
  if (ev.message_type === "prediction") {
    const p = ev.payload.prediction; tail = ` ${p.fault_type}: ${p.signal.metric}@${p.signal.entity.id} ${p.expected.op} ${p.expected.ref}`;
  } else if (ev.message_type === "report") {
    const r = ev.payload.report; tail = ` ${r.status} · ${r.fault_type || ""} · ${Number(r.confidence).toFixed(2)}`;
  }
  row.append(el("span", ev.message_type === "report" ? "t-ok" : "", tail + "\n"));
  out.appendChild(row);
  out.scrollTop = out.scrollHeight;
}

let streamed = false;
async function startStream() {
  if (streamed) return; streamed = true;
  try {
    const run = await api("/scenarios/congestion/run?external=false", "POST");
    $("stream-id").textContent = run.incident_id;
    const es = new EventSource("/incidents/" + encodeURIComponent(run.incident_id) + "/stream?delay_ms=" + (reduced() ? 0 : 260));
    es.addEventListener("message", e => { const ev = JSON.parse(e.data); line(ev); if (STEP_OF[ev.message_type]) setStep(STEP_OF[ev.message_type]); });
    es.addEventListener("end", () => { es.close(); setStep("decide"); document.querySelector('#steps li[data-step="decide"]').classList.add("done"); });
    es.onerror = () => es.close();
  } catch {
    $("stream-id").textContent = "backend not reachable";
    $("stream-out").textContent = "Serve this folder with `netcoop serve --ui templates/netcoop_ui` to see a live stream.";
  }
}

if (typeof module !== "undefined" && module.exports) module.exports = { pickScenario, summarize, STEP_OF, ORDER };

if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", () => {
  intro();
  document.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => ask(c.textContent, c.dataset.scenario)));
  $("composer").addEventListener("submit", e => {
    e.preventDefault();
    const text = $("ask").value.trim().slice(0, 200);
    if (!text) return;
    $("ask").value = "";
    ask(text, pickScenario(text));
  });
  const io = new IntersectionObserver(es => { if (es.some(x => x.isIntersecting)) { startStream(); io.disconnect(); } }, { threshold: 0.3 });
  io.observe($("how"));
});
