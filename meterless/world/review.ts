// ClinAssist AI: record a reviewer's decision on a pending identity match.
//
//   npx.cmd tsx meterless/world/review.ts list
//   npx.cmd tsx meterless/world/review.ts approve laboratory LPB76ACC1 --by "Dr Reviewer" --note "DOB swap confirmed with patient"
//   npx.cmd tsx meterless/world/review.ts reject  pharmacy  RX298B1A2 --by "Dr Reviewer"
//
// Decisions are appended to data/derived/identity/review_decisions.json and
// replayed into the World Model by meterless/world/build_world.ts, with the reviewer as provenance.

import { existsSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";

const identityDir = path.join("data", "derived", "identity");
const links = JSON.parse(readFileSync(path.join(identityDir, "identity_links.json"), "utf-8")).links as
  { system: string; record_id: string; record_label: string; decision: string; mrn: string | null; hospital_label: string | null; reasons: string[] }[];
const file = path.join(identityDir, "review_decisions.json");
const decisions: { system: string; record_id: string; mrn: string; action: string; by: string; at: string; note?: string }[] =
  existsSync(file) ? JSON.parse(readFileSync(file, "utf-8")) : [];

const [cmd, system, recordId, ...rest] = process.argv.slice(2);
const flag = (name: string) => { const i = rest.indexOf(name); return i >= 0 ? rest[i + 1] : undefined; };

if (!cmd || cmd === "list") {
  const pending = links.filter((l) => l.decision === "review"
    && !decisions.some((d) => d.system === l.system && d.record_id === l.record_id));
  console.log(pending.length ? "Pending review:" : "Nothing pending.");
  for (const l of pending) {
    console.log(`\n  ${l.system} ${l.record_id}  ${l.record_label}`);
    console.log(`    suggested: ${l.mrn}  ${l.hospital_label}`);
    for (const r of l.reasons) console.log(`    - ${r}`);
  }
  process.exit(0);
}

if (cmd !== "approve" && cmd !== "reject") { console.error("usage: review.ts list | approve|reject <system> <record_id> --by <name> [--note <text>]"); process.exit(2); }
const link = links.find((l) => l.system === system && l.record_id === recordId);
if (!link || link.decision !== "review" || !link.mrn) { console.error(`${system} ${recordId} is not a pending review case`); process.exit(2); }
const by = flag("--by");
if (!by) { console.error("--by <reviewer name> is required: every decision needs a named person"); process.exit(2); }

decisions.push({ system, record_id: recordId, mrn: link.mrn, action: cmd, by, at: new Date().toISOString(), note: flag("--note") });
writeFileSync(file, JSON.stringify(decisions, null, 2), "utf-8");
console.log(`Recorded: ${cmd} ${system} ${recordId} -> ${link.mrn} by ${by}. Now run: npx.cmd tsx meterless/world/build_world.ts`);
