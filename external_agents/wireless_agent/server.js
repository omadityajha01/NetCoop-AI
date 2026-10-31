#!/usr/bin/env node
// wireless_agent ("wifi-probe"): an EXTERNAL Wi-Fi telemetry agent written in Node.js.
//
// It deliberately speaks NetCoop dialect v0.9 with its own field names (signal, noise_margin, retx,
// clients, epoch-seconds ts, ap-h3 style ids). Do NOT "fix" it to speak NMP 1.0: the mismatch is the
// demo. NetCoop's A2A gateway + 0.9->1.0 upcaster + metric registry translate it.
//
// Transport: A2A shapes over plain HTTP: Agent Card at /.well-known/agent-card.json, JSON-RPC 2.0
// `message/send` with the NMP envelope in a `data` part. No dependencies (node >= 18).
//
//   node server.js [--port 8765] [--host 127.0.0.1] [--data data/demo.json]
"use strict";

const http = require("http");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");

function arg(name, dflt) {
  const i = process.argv.indexOf(`--${name}`);
  return i > 0 && process.argv[i + 1] ? process.argv[i + 1] : dflt;
}

// Loopback only: never listen on a LAN interface (no firewall prompt on stage, nothing exposed to the network).
const HOST = arg("host", "127.0.0.1");
if (!["127.0.0.1", "localhost", "::1"].includes(HOST)) {
  console.error(`[wifi-probe] refusing to bind ${HOST}: loopback only (127.0.0.1)`);
  process.exit(2);
}
const PORT = parseInt(arg("port", "8765"), 10);
const DATA = path.resolve(arg("data", path.join(__dirname, "data", "demo.json")));
const MAX_BODY = 256 * 1024;
const FROM = "wifi-probe";

// metric names NetCoop asks for -> our own field names
const FIELD_OF = { rssi_dbm: "signal", snr_db: "noise_margin", retransmission_pct: "retx", client_count: "clients" };

function loadObs() {
  try {
    const raw = JSON.parse(fs.readFileSync(DATA, "utf8"));
    return Array.isArray(raw) ? raw : raw.observations || [];
  } catch (e) {
    console.error(`[wifi-probe] cannot read ${DATA}: ${e.message}`);
    return [];
  }
}

const OBS = loadObs();
const cache = new Map(); // idempotency: same message_id -> same response

function card() {
  return {
    name: "wifi-probe",
    description: "Campus Wi-Fi RF probe. Reports RSSI, noise margin, retransmissions and clients per AP (NetCoop dialect 0.9).",
    url: `http://${HOST}:${PORT}/`,
    version: "0.9.3",
    protocolVersion: "0.3.0",
    capabilities: { streaming: false, pushNotifications: false },
    defaultInputModes: ["application/json"],
    defaultOutputModes: ["application/json"],
    skills: [
      { id: "wifi-rf-telemetry", name: "Wi-Fi RF telemetry",
        description: "Per-AP RF quality samples for a time window", tags: ["wifi", "rf", "nmp-0.9"] },
    ],
  };
}

const myId = (canonical) => String(canonical).toLowerCase().replace(/_/g, "-");

function inWindow(o, w) {
  if (!w || !w.start || !w.end) return true;
  const t = Number(o.ts) * 1000;
  return t >= Date.parse(w.start) && t <= Date.parse(w.end);
}

function err(env, code, detail) {
  return { ver: "0.9", inc: env && env.incident_id, from: FROM, re: env && env.message_id, kind: "err",
           err: { code, detail } };
}

function answer(env) {
  if (!env || typeof env !== "object" || Array.isArray(env)) return err(null, "MALFORMED", "data part is not an object");
  if (!env.message_type) return err(env, "MISSING_FIELD", "message_type missing");
  if (!env.incident_id) return err(env, "MISSING_FIELD", "incident_id missing");
  if (!env.message_id) return err(env, "MISSING_FIELD", "message_id missing");
  const major = String(env.schema_version || "").split(".")[0];
  if (major !== "1" && major !== "0") return err(env, "SCHEMA_VERSION_UNSUPPORTED", `cannot read ${env.schema_version}`);
  const p = env.payload && typeof env.payload === "object" ? env.payload : {};
  // unknown fields are tolerated: we only read what we understand
  if (env.message_type === "task_request") {
    const w = p.window;
    const obs = OBS.filter((o) => inWindow(o, w));
    return { ver: "0.9", inc: env.incident_id, from: FROM, re: env.message_id, q: "task", kind: "obs", obs };
  }
  if (env.message_type === "evidence_request") {
    const reqs = Array.isArray(p.requests) ? p.requests : null;
    if (!reqs) return err(env, "MALFORMED", "requests must be a list");
    const obs = [];
    const na = [];
    for (const r of reqs) {
      const field = FIELD_OF[r && r.metric];
      const ap = r && r.entity && myId(r.entity.id);
      const w = (r && r.window) || p.window;
      if (!field || !ap) { na.push({ ap: ap || "?", sig: String((r && r.metric) || "?") }); continue; }
      const rows = OBS.filter((o) => o.ap === ap && inWindow(o, w) && o[field] !== undefined);
      if (!rows.length) { na.push({ ap, sig: field }); continue; }
      for (const o of rows) obs.push({ ap: o.ap, [field]: o[field], ts: o.ts });
    }
    return { ver: "0.9", inc: env.incident_id, from: FROM, re: env.message_id, q: "evidence",
             round: p.round || 0, kind: "obs", obs, na };
  }
  return err(env, "MALFORMED", `unsupported message_type ${env.message_type}`);
}

function rpcReply(id, data, contextId) {
  const messageId = crypto.createHash("sha256").update(JSON.stringify(data)).digest("hex").slice(0, 32);
  return { jsonrpc: "2.0", id, result: { kind: "message", role: "agent", messageId, contextId,
                                         parts: [{ kind: "data", data }] } };
}

function send(res, code, obj) {
  const body = JSON.stringify(obj);
  res.writeHead(code, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) });
  res.end(body);
}

const server = http.createServer((req, res) => {
  if (req.method === "GET" && req.url === "/.well-known/agent-card.json") return send(res, 200, card());
  if (req.method === "GET" && req.url === "/healthz") return send(res, 200, { ok: true, observations: OBS.length });
  if (req.method !== "POST") return send(res, 404, { error: "not found" });
  let size = 0;
  const chunks = [];
  req.on("data", (c) => {
    size += c.length;
    if (size > MAX_BODY) { send(res, 413, { jsonrpc: "2.0", id: null, error: { code: -32600, message: "too large" } }); req.destroy(); return; }
    chunks.push(c);
  });
  req.on("end", () => {
    if (res.writableEnded) return;
    let rpc;
    try { rpc = JSON.parse(Buffer.concat(chunks).toString("utf8")); }
    catch (e) { return send(res, 200, { jsonrpc: "2.0", id: null, error: { code: -32700, message: "parse error" } }); }
    if (!rpc || rpc.jsonrpc !== "2.0" || rpc.method !== "message/send") {
      return send(res, 200, { jsonrpc: "2.0", id: (rpc && rpc.id) || null, error: { code: -32601, message: "method not found" } });
    }
    const msg = (rpc.params && rpc.params.message) || {};
    const parts = Array.isArray(msg.parts) ? msg.parts : [];
    const part = parts.find((x) => x && x.kind === "data");
    const env = part ? part.data : undefined;
    const key = (env && typeof env === "object" && env.message_id) || msg.messageId;
    if (key && cache.has(key)) return send(res, 200, rpcReply(rpc.id, cache.get(key), msg.contextId));
    const data = part ? answer(env) : err(null, "MALFORMED", "no data part");
    if (key) cache.set(key, data);
    if (cache.size > 5000) cache.delete(cache.keys().next().value);
    return send(res, 200, rpcReply(rpc.id, data, msg.contextId));
  });
});

server.listen(PORT, HOST, () => {
  console.log(`[wifi-probe] dialect 0.9 agent on http://${HOST}:${PORT}  (${OBS.length} observations from ${DATA})`);
});
