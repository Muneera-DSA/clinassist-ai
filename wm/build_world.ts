// ClinAssist AI: record patient identities in the Meterless World Model.
//
// Input : data/derived/identity/identity_links.json   (from run_matching.py)
//         data/derived/identity/review_decisions.json (optional, from wm/review.ts)
// Output: data/derived/world/.world/clinassist.json   (event-sourced World Model store)
//         data/derived/world/patient_identity.json    (one entry per hospital patient)
//
// Run from the project folder:
//   npx.cmd tsx wm/build_world.ts
//
// The world is rebuilt from scratch on every run: the source systems and the
// recorded reviewer decisions are the truth; the World Model is the shared,
// provenance-carrying view of them. Every write carries provenance (who, when,
// which run), so any link can be traced back to the matcher run or the person
// who confirmed it.

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import { WorldModel } from "../vendor/meterless-world-model/index.ts";

type Link = {
  system: "laboratory" | "pharmacy";
  record_id: string;
  record_label: string;
  decision: "auto-link" | "review" | "no-match";
  mrn: string | null;
  hospital_label: string | null;
  score: number | null;
  runner_up_mrn: string | null;
  runner_up_score: number | null;
  reasons: string[];
};
type Decision = { system: string; record_id: string; mrn: string; action: "approve" | "reject"; by: string; at: string; note?: string };

const MAX_SCORE = 12.5;
const SYSTEM_KEY = { laboratory: "lab_lis", pharmacy: "pharmacy_rx" } as const;
const RECORD_TYPE = { laboratory: "lab_patient", pharmacy: "pharmacy_patient" } as const;

const identityDir = process.argv[2] ?? path.join("data", "derived", "identity");
const worldDir = process.argv[3] ?? path.join("data", "derived", "world");

const input = JSON.parse(readFileSync(path.join(identityDir, "identity_links.json"), "utf-8")) as {
  generated_at: string; run_id: string; source: string; hospital: { mrn: string; label: string }[]; links: Link[];
};
const decisionsFile = path.join(identityDir, "review_decisions.json");
const decisions: Decision[] = existsSync(decisionsFile) ? JSON.parse(readFileSync(decisionsFile, "utf-8")) : [];

rmSync(path.join(worldDir, ".world"), { recursive: true, force: true });
mkdirSync(worldDir, { recursive: true });
// highest-confidence-wins: a reviewer's decision (confidence 1) always beats the
// matcher's (capped at 0.99), whatever order the events were recorded in.
// Built in memory, then saved once at the end in the World Model's own store
// format (.world/<namespace>.json). Saving after every event was slow on Windows.
const world = new WorldModel({ namespace: "clinassist", storage: "memory", conflictPolicy: "highest-confidence-wins" });

const at = input.generated_at;
const matcher = { kind: "agent", by: "clinassist-matcher", at, runId: input.run_id };
const origin = (system: string) => ({ kind: `${input.source}:${system}`, by: "clinassist-loader", at, runId: input.run_id });

async function main() {
  // 1. Hospital patients are the master index (one entity per MRN).
  const patientId = new Map<string, string>();
  for (const h of input.hospital) {
    const e = await world.upsertEntity({
      type: "patient", externalKey: { system: "hospital_ehr", id: h.mrn },
      name: h.label, attrs: { mrn: h.mrn, label: h.label }, source: origin("hospital_ehr"),
    });
    patientId.set(h.mrn, e.id);
  }

  // 2. Each lab / pharmacy patient record, and what the matcher concluded.
  const recordId = new Map<string, string>();
  for (const l of input.links) {
    const r = await world.upsertEntity({
      type: RECORD_TYPE[l.system], externalKey: { system: SYSTEM_KEY[l.system], id: l.record_id },
      name: l.record_label, attrs: { system: l.system, record_id: l.record_id, label: l.record_label },
      source: origin(SYSTEM_KEY[l.system]),
    });
    recordId.set(`${l.system}:${l.record_id}`, r.id);
    const confidence = l.score == null ? 0 : Math.max(0, Math.min(0.99, l.score / MAX_SCORE));
    if (l.decision === "no-match" || !l.mrn) {
      await world.assertFact({ about: r.id, predicate: "identity_status", value: "unmatched", confidence, source: matcher });
      continue;
    }
    const target = patientId.get(l.mrn)!;
    const attrs = { score: l.score, runner_up_mrn: l.runner_up_mrn, runner_up_score: l.runner_up_score, evidence: l.reasons };
    if (l.decision === "auto-link") {
      await world.relate({ from: r.id, type: "same_person_as", to: target, attrs, source: matcher });
      await world.assertFact({ about: r.id, predicate: "identity_status", value: "linked", confidence, source: matcher });
    } else {
      await world.relate({ from: r.id, type: "possible_same_person", to: target, attrs, source: matcher });
      await world.assertFact({ about: r.id, predicate: "identity_status", value: "pending-review", confidence, source: matcher });
    }
  }

  // 3. Replay reviewer decisions, each with the reviewer as provenance.
  for (const d of decisions) {
    const rid = recordId.get(`${d.system}:${d.record_id}`);
    const pid = patientId.get(d.mrn);
    if (!rid || !pid) { console.warn(`skipped decision for unknown record ${d.system}:${d.record_id} -> ${d.mrn}`); continue; }
    const reviewer = { kind: "manual", by: d.by, at: d.at, runId: input.run_id };
    if (d.action === "approve") {
      await world.relate({ from: rid, type: "same_person_as", to: pid, attrs: { confirmed_by: d.by, note: d.note ?? "" }, source: reviewer });
      await world.assertFact({ about: rid, predicate: "identity_status", value: "linked-by-reviewer", confidence: 1, source: reviewer });
    } else {
      await world.assertFact({ about: rid, predicate: "identity_status", value: "rejected-by-reviewer", confidence: 1, source: reviewer });
    }
  }

  // 4. Patient-level view for the agent: which records belong to whom.
  const graph = world.view("graph");
  const statusOf = (id: string) => String(graph.entity(id)?.attrs.identity_status ?? "");
  const out = input.hospital.map((h) => {
    const pid = patientId.get(h.mrn)!;
    const linked = graph.incoming(pid, { via: "same_person_as" })
      .filter((e) => ["linked", "linked-by-reviewer"].includes(statusOf(e.id)))
      .map((e) => ({ system: e.attrs.system, record_id: e.attrs.record_id, status: statusOf(e.id) }));
    const pending = graph.incoming(pid, { via: "possible_same_person" })
      .filter((e) => statusOf(e.id) === "pending-review")
      .map((e) => ({ system: e.attrs.system, record_id: e.attrs.record_id, status: "pending-review" }));
    return { mrn: h.mrn, label: h.label, entity_id: pid, linked_records: linked, pending_review: pending };
  });
  mkdirSync(path.join(worldDir, ".world"), { recursive: true });
  writeFileSync(path.join(worldDir, ".world", "clinassist.json"),
    JSON.stringify({ events: world.events(), audit: world.audit(), mergeQueue: world.mergeQueue() }, null, 2) + "\n", "utf-8");
  writeFileSync(path.join(worldDir, "patient_identity.json"), JSON.stringify({ built_from: input.run_id, patients: out }, null, 2), "utf-8");

  const count = (s: string) => input.links.filter((l) => statusOf(recordId.get(`${l.system}:${l.record_id}`)!) === s).length;
  console.log(`World Model built: ${world.events().length} events, ${world.audit().length} audit entries`);
  console.log(`  patients ${input.hospital.length} | records linked ${count("linked")} | confirmed by reviewer ${count("linked-by-reviewer")}`
    + ` | pending review ${count("pending-review")} | rejected ${count("rejected-by-reviewer")} | unmatched ${count("unmatched")}`);
  console.log(`  store: ${path.join(worldDir, ".world", "clinassist.json")}`);
  console.log(`  view : ${path.join(worldDir, "patient_identity.json")}`);
}

main().catch((e) => { console.error(e); process.exit(1); });
