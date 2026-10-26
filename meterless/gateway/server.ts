// Meterless gateway for ClinAssist AI: runs the vendored Meterless engines for the Python app.
//
//   World Model : one event-sourced store per request (run). The supervisor records the request, Scout's decision,
//                 and for every action (script run, Zetaris query, Nightshift call) the request, the approval and the
//                 result, each with provenance. Stored in data/derived/world/runs/<run_id>/.world/run.json
//   H-MEM       : the catalog of single-action scripts (rebuilt when the app starts) and lessons from finished runs
//                 (persisted in data/derived/hmem). Retrieval ranks them for the question; the text is injected into
//                 Nemotron's prompt.
//
// Start from the project folder:   npx.cmd tsx meterless/gateway/server.ts        (listens on 127.0.0.1:8090)
// Local only; no secrets pass through it.

import http from "node:http";
import { existsSync, mkdirSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { WorldModel } from "../vendor/world-model/index.ts";
import { HMEM } from "../vendor/hmem/index.ts";

const PORT = Number(process.env.METERLESS_GATEWAY_PORT ?? 8090);
const ROOT = process.cwd();
const RUNS_DIR = path.join(ROOT, "data", "derived", "world", "runs");
const HMEM_DIR = path.join(ROOT, "data", "derived", "hmem");
const SAFE = /^[A-Za-z0-9_.:-]{1,120}$/;

mkdirSync(RUNS_DIR, { recursive: true });
mkdirSync(HMEM_DIR, { recursive: true });

// ---------------------------------------------------------------- World Model: one store per run
const runs = new Map<string, WorldModel>();
function runModel(runId: string): WorldModel {
  if (!SAFE.test(runId)) throw new Error("invalid run id");
  let w = runs.get(runId);
  if (!w) {
    const dir = path.join(RUNS_DIR, runId);
    mkdirSync(dir, { recursive: true });
    w = new WorldModel({ namespace: "run", storage: "local", directory: dir });
    runs.set(runId, w);
  }
  return w;
}
const prov = (kind: string, by: string, runId: string, at?: string) => ({ kind, by, at: at ?? new Date().toISOString(), runId });
const requestId = (runId: string) => `request:clinassist:${runId}`;
const actionId = (runId: string, id: string) => `action:${runId}:${id}`;

// ---------------------------------------------------------------- H-MEM: script catalog + lessons
let catalog = new HMEM({ actor: "clinassist-catalog" });
let catalogSize = 0;
const lessons = new HMEM({ actor: "clinassist-lessons", persistDir: HMEM_DIR });

// ---------------------------------------------------------------- HTTP plumbing
function send(res: http.ServerResponse, code: number, body: unknown) {
  const text = JSON.stringify(body);
  res.writeHead(code, { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(text) });
  res.end(text);
}
function readBody(req: http.IncomingMessage): Promise<any> {
  return new Promise((resolve, reject) => {
    let raw = "";
    req.on("data", (c) => { raw += c; if (raw.length > 2_000_000) reject(new Error("body too large")); });
    req.on("end", () => { try { resolve(raw ? JSON.parse(raw) : {}); } catch (e) { reject(e); } });
    req.on("error", reject);
  });
}

type Handler = (body: any, m: RegExpMatchArray) => Promise<unknown> | unknown;
const routes: [string, RegExp, Handler][] = [
  ["GET", /^\/health$/, () => ({ ok: true, engines: ["world-model", "hmem"], runs_open: runs.size, catalog: catalogSize,
    lessons: lessons.store.all().length })],

  // --- World Model: request / decision / actions / close
  ["POST", /^\/world\/runs\/([^/]+)\/request$/, async (b, m) => {
    const w = runModel(m[1]);
    const id = (await w.upsertEntity({ type: "request", externalKey: { system: "clinassist", id: m[1] }, name: `request ${m[1]}`,
      attrs: { prompt: b.prompt, user: b.user, role: b.role, patient: b.patient, ai: b.ai, data_path: b.data_path },
      source: prov("ui", String(b.user ?? "unknown"), m[1]) })).id;
    return { entity: id };
  }],
  ["POST", /^\/world\/runs\/([^/]+)\/decision$/, async (b, m) => {
    const w = runModel(m[1]);
    await w.assertFact({ about: requestId(m[1]), predicate: "scout_decision", confidence: 1,
      value: { status: b.status, intent: b.intent, source: b.source, flags: b.flags, contract_id: b.contract_id, tools: b.tools, lanes: b.lanes },
      source: prov("meterless:scout", "scout", m[1]) });
    return { ok: true };
  }],
  ["POST", /^\/world\/runs\/([^/]+)\/actions$/, async (b, m) => {
    if (!SAFE.test(String(b.id))) throw new Error("invalid action id");
    const w = runModel(m[1]);
    const id = (await w.upsertEntity({ type: "action", externalKey: { system: m[1], id: String(b.id) }, name: `${b.kind} ${b.target}`,
      attrs: { kind: b.kind, target: b.target, args: b.args, actor: b.actor, seq: b.seq },
      source: prov(`agent:${b.actor}`, String(b.actor), m[1]) })).id;
    await w.relate({ from: id, type: "part_of", to: requestId(m[1]), source: prov("meterless:supervisor", "supervisor", m[1]) });
    await w.assertFact({ about: id, predicate: "status", value: "requested", confidence: 1, source: prov("meterless:supervisor", "supervisor", m[1]) });
    return { entity: id };
  }],
  ["POST", /^\/world\/runs\/([^/]+)\/actions\/([^/]+)\/decision$/, async (b, m) => {
    const w = runModel(m[1]);
    await w.assertFact({ about: actionId(m[1], m[2]), predicate: "authorization", confidence: 1,
      value: { allowed: !!b.allowed, reason: b.reason, policy: b.policy }, source: prov("meterless:supervisor", "scout-contract", m[1]) });
    await w.assertFact({ about: actionId(m[1], m[2]), predicate: "status", value: b.allowed ? "approved" : "denied", confidence: 1,
      source: prov("meterless:supervisor", "supervisor", m[1]) });
    return { ok: true };
  }],
  ["POST", /^\/world\/runs\/([^/]+)\/actions\/([^/]+)\/result$/, async (b, m) => {
    const w = runModel(m[1]);
    await w.assertFact({ about: actionId(m[1], m[2]), predicate: "result", confidence: 1,
      value: { status: b.status, seconds: b.seconds, summary: b.summary, error: b.error }, source: prov(`executor:${b.executor ?? "app"}`, String(b.executor ?? "app"), m[1]) });
    await w.assertFact({ about: actionId(m[1], m[2]), predicate: "status", value: b.status === "ok" ? "done" : "failed", confidence: 1,
      source: prov("meterless:supervisor", "supervisor", m[1]) });
    return { ok: true };
  }],
  ["POST", /^\/world\/runs\/([^/]+)\/close$/, async (b, m) => {
    const w = runModel(m[1]);
    await w.assertFact({ about: requestId(m[1]), predicate: "outcome", value: { status: b.status, rounds: b.rounds }, confidence: 1,
      source: prov("meterless:supervisor", "supervisor", m[1]) });
    runs.delete(m[1]);
    return { ok: true, events: w.events().length };
  }],
  ["GET", /^\/world\/runs\/([^/]+)$/, (_b, m) => {
    if (!SAFE.test(m[1])) throw new Error("invalid run id");
    const w = runs.get(m[1]);
    if (w) return { run_id: m[1], events: w.events(), audit: w.audit() };
    const file = path.join(RUNS_DIR, m[1], ".world", "run.json");
    if (!existsSync(file)) throw new Error("unknown run");
    const saved = JSON.parse(readFileSync(file, "utf-8"));
    return { run_id: m[1], events: saved.events ?? [], audit: saved.audit ?? [] };
  }],
  ["GET", /^\/world\/runs$/, () => ({
    runs: existsSync(RUNS_DIR) ? readdirSync(RUNS_DIR).filter((d) => existsSync(path.join(RUNS_DIR, d, ".world", "run.json"))).sort().reverse() : [],
  })],

  // --- H-MEM: catalog, retrieval, lessons
  ["POST", /^\/hmem\/catalog$/, (b) => {
    catalog = new HMEM({ actor: "clinassist-catalog" });
    for (const s of b.scripts ?? []) {
      catalog.add({ content: `Script ${s.name} (${s.kind}): ${s.does} Arguments: ${JSON.stringify(s.args ?? {})}. Returns: ${s.returns}.`,
        type: "factual", layer: "long_term", tags: [`script:${s.name}`, ...(s.tags ?? [])], confidence: 1, source: "clinassist:script-registry" });
    }
    catalogSize = catalog.store.all().length;
    return { loaded: catalogSize };
  }],
  ["POST", /^\/hmem\/query$/, (b) => {
    const q = String(b.query ?? "").slice(0, 2000);
    const scripts = catalog.query(q, { topN: Number(b.topN ?? 40), threshold: Number(b.threshold ?? 0) });
    const learned = lessons.query(q, { topN: Number(b.lessonsTopN ?? 3), threshold: Number(b.lessonsThreshold ?? 0.2) });
    const pick = (r: any) => ({ id: r.memory.id, content: r.memory.content, tags: r.memory.tags, relevance: Number(r.relevance.toFixed(4)) });
    return { scripts: scripts.memories.map(pick), lessons: learned.memories.map(pick), trace: scripts.trace };
  }],
  ["POST", /^\/hmem\/lessons$/, (b) => {
    const r = lessons.add({ content: String(b.content ?? "").slice(0, 1500), type: "general", layer: "working",
      tags: (b.tags ?? []).map(String).slice(0, 12), confidence: Number(b.confidence ?? 0.8), source: `clinassist:run:${b.run_id ?? "unknown"}` });
    return { id: r.id };
  }],
];

const server = http.createServer(async (req, res) => {
  const url = new URL(req.url ?? "/", "http://localhost");
  for (const [method, rx, fn] of routes) {
    const m = url.pathname.match(rx);
    if (m && req.method === method) {
      try {
        const body = method === "POST" ? await readBody(req) : {};
        return send(res, 200, await fn(body, m));
      } catch (e) {
        return send(res, 400, { error: (e as Error).message });
      }
    }
  }
  send(res, 404, { error: "not found" });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`Meterless gateway on http://127.0.0.1:${PORT}  (World Model run traces + H-MEM script catalog)`);
  console.log(`  run traces: ${RUNS_DIR}`);
  console.log(`  lessons:    ${HMEM_DIR}`);
});
