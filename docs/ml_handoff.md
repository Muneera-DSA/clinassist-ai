# ClinAssist AI: ML handover for the backend and frontend

This document explains what the data-science side provides, how to call it, what it returns, and what the
demo must not claim. The full reasoning behind each choice is in the team doc
*ClinAssist AI: Data Science & ML Work Explained*.

All data is **synthetic** (Synthea). No real patient data is used anywhere.

---

## 1. What is ready

| Component | Code | What it does |
|---|---|---|
| Fragmented source systems | `clinassist_build_sources.py`, `sources/`, `zetaris/` | Splits 112 synthetic patients into a hospital EHR, a lab system and a pharmacy, each with its own IDs, formats and 39 logged data-entry errors. The three databases (SQL Server, MySQL, PostgreSQL) are queried together through **Zetaris**. |
| Patient matching | `clinassist/matching.py`, `run_matching.py` | Decides which lab and pharmacy records belong to which hospital patient. Auto-links only when every field agrees exactly (score ≥ 11.5); uncertain cases go to a person. |
| Identity store | `meterless/world/build_world.ts`, `meterless/world/review.ts` | Writes every link and every reviewer decision into the **Meterless World Model**, with provenance (an audit trail). |
| Patient record | `clinassist/patient_record.py` | Collects one patient's confirmed records from all three systems over a 3-year window. Every row gets an **evidence ID** such as `E-lab_result-RC30F74999E`. |
| Clinical analytics | `clinassist/analysis.py`, `config/clinical_rules.json` | Trends (Theil–Sen), guideline-sourced rules, monitoring gaps, medicine checks, allergy check, timeline. Every finding lists the evidence IDs it rests on. |
| Scout (front-door safety layer) | `meterless/scout/__init__.py`, `meterless/scout/intents.json` | Implements the **Meterless Scout Intent** spec: understands the request, blocks unsafe ones (diagnosis/prescribing, prompt injection, another patient, population-wide data, role not permitted), routes tools and a Nightshift lane per AI role, and issues an HMAC-signed execution contract. |
| Meterless supervisor | `meterless/supervisor/`, `meterless/gateway/server.ts` | Every action (script, Zetaris fetch, Nemotron call, H-MEM lookup) is checked against the signed Scout contract and recorded (request → approval → result) in the **Meterless World Model**. If the gateway is down nothing runs. |
| Single-action scripts | `clinassist/scripts/` | One script = one action (fetch, list, trend, check one criterion, rank). Scripts report facts such as "criterion met"; they never decide. Their catalog is loaded into **Meterless H-MEM** and given to Nemotron with each request. |
| AI agent (Nemotron is the boss) + fact-check | `clinassist/agent.py`, `clinassist/verifier.py`, `clinassist/llm.py` | Nemotron (via **Meterless Nightshift**) chooses which scripts to run, step by step, reads the results, decides and writes. Meterless always runs the deterministic fact-check (`verify_draft`) and a second Nemotron reviewer (judge); failures go back to Nemotron or are escalated. Unverified AI text is never returned. |
| Tests and experiments | `tests/`, `eval/` | Rule scenario tests, twins stress test, matching sweep, verifier red-team, Zetaris audit, AI benchmark. |

---

## 2. Setup

```powershell
cd C:\Hackathon\clinical-ai-assistant
& "<path to python 3.10 or newer>\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd install                       # tsx, for the Meterless gateway and World Model scripts
Copy-Item .env.example .env           # then fill in the values (never commit .env)
```

`.env` needs the Zetaris REST URL, org ID and API key, plus the Nightshift base URL and runtime token.
See `.env.example` and `docs/setup_log.md` sections 5 and 7. Python is always called as `.\.venv\Scripts\python.exe`.

---

## 3. Rebuilding the data and results from scratch

`data/derived/` is not in git: it is large and fully regenerated. Run these in order from the project folder.

| # | Command | Produces |
|---|---|---|
| 1 | Unzip the Synthea sample into `data\synthea_fhir\` (see `docs/setup_log.md` §4) | 112 patient files |
| 2 | `.\.venv\Scripts\python.exe .\clinassist_build_sources.py` | `data\derived\` (hospital, laboratory, pharmacy CSVs; `_truth` answer key) |
| 3 | `cd sources; docker compose up -d; cd ..` | The 3 databases: SQL Server, MySQL, PostgreSQL (load the CSVs on first start) |
| 4 | Register them in Zetaris: `zetaris\01_register_sources.sql`, one statement at a time | 12 tables visible to Zetaris |
| 5 | `.\.venv\Scripts\python.exe .\eval\audit_sources.py` | Must print `ALL MATCH` |
| 6 | `.\.venv\Scripts\python.exe .\run_matching.py --score` | `data\derived\identity\` (links, review queue, report) |
| 7 | `npx.cmd tsx meterless/world/build_world.ts` | `data\derived\world\patient_identity.json` |
| 8 | `.\.venv\Scripts\python.exe .\run_patient_review.py --mrn MRN91862E3E --as-of 2026-10-24` | `data\derived\reviews\MRN91862E3E.json` and `.md` |

Steps 6 and 8 also have an offline mode that reads the CSVs instead of Zetaris (`--source csv`), useful when
Zetaris is not running. **Use `--as-of 2026-10-24` for the demo** so results match the documented numbers;
without it, the review date is today.

For the experiments, the extra datasets come from step 2 with a different seed:
`clinassist_build_sources.py --seed 7 --out data\derived\holdout_seed7` (likewise 2026 and 99).

---

## 4. Calling it from the backend

**Always call Scout first, then the agent with the contract.** `require_contract=True` makes the agent refuse
anything that did not pass Scout.

```python
from datetime import date
from pathlib import Path
from clinassist import scripts as S
from clinassist.agent import Agent
from clinassist.analysis import load_rules
from clinassist.llm import NightshiftLLM
from clinassist.patient_record import ZetarisSource, CsvSource
from clinassist.zetaris_client import ZetarisClient
from meterless.scout import Scout, load_patients
from meterless.supervisor import Supervisor, GatewayRecorder, SupervisedSource, SupervisedLLM

DATA = Path("data/derived")
user = {"id": "<logged-in user id>", "role": "clinician"}
request, mrn = "Why is his eGFR flagged?", "MRN91862E3E"

# 1. Meterless opens a run: the request is recorded in the World Model before anything else happens
sup = Supervisor(GatewayRecorder())                    # fails closed (MeterlessUnavailable) if the gateway is down
sup.open(request, mrn, user, ai=True, data_path="zetaris")

# 2. Scout (inside Meterless) decides; the decision and the signed contract are recorded
llm = NightshiftLLM.from_env()
scout = Scout(patients=load_patients(DATA / "world"), llm=SupervisedLLM(llm, sup, "interpreter"))
decision = scout.decide(request, mrn, user)            # status: approved | clarify | blocked
sup.decided(decision.to_dict(), scope={mrn, "<linked lab / pharmacy record ids>"})

# 3. Nemotron is the boss: it picks single-action scripts; every script, Zetaris fetch and Nemotron call goes
#    through sup.act() (approved against the contract, then recorded with its result)
source = SupervisedSource(ZetarisSource(ZetarisClient.from_env()), sup, "zetaris")   # or CsvSource(DATA) offline
ctx = S.Ctx(mrn, date(2026, 10, 24), 3, source, DATA / "world", load_rules())
agent = Agent(llm, supervisor=sup)                     # Agent(None) = the contract's default plan + rule-based writer
out = agent.run(request, ctx, contract=decision.contract, require_contract=True)
sup.close(out.status, out.rounds)

out.status    # "verified-ai" | "verified-rules" | "escalated" | "refused" (no valid contract) | "error"
out.summary   # markdown; every sentence ends with [evidence IDs]
out.plan      # the scripts Nemotron chose, in order
out.trace     # every step: boss steps, script results, writer, fact-check, judge, Meterless approvals
```

The app does all of this in `server/services.py` (`run_agent`); the example only shows the order.

- `load_record` uses only records the World Model has **confirmed**. Pending matches are listed in
  `review["identity"]["pending_review"]` and are never used silently.
- If Nightshift is offline, `Agent.run` runs the contract's default plan and the verified rule-based summary (`status = "verified-rules"`).
  The UI should say so.
- Patient IDs are checked before they go into SQL (`SAFE_ID`); keep passing MRNs, not free text.
- Roles Scout knows: `clinician` (all review requests), `coordinator` (summary, findings, trends, gaps, linked records),
  `records_staff` (linked records only). Pass the logged-in user's real role; Scout has no login of its own.
- Set `SCOUT_SIGNING_KEY` in `.env` (see `.env.example`). Without it Scout signs with a temporary key that only
  works inside one running process; the decision message says so.
- Contracts expire after 15 minutes; the request text, intent, tools, lanes and user are inside the contract, so
  store it with the result as the audit record.

---

## 5. The review JSON (what the screens read)

`analyse()` returns, and `run_patient_review.py` writes, one object per patient:

| Key | Type | Use in the UI |
|---|---|---|
| `patient` | `{mrn, label, birth_date, sex, deceased_at}` | Header |
| `window` | `{as_of, since}` | "Records from … to …" |
| `identity` | `{linked_records: [{system, record_id, status}], pending_review: [...]}` | Which systems were joined; pending matches need a reviewer |
| `counts` | records per kind: `encounter, condition, procedure, observation, allergy, lab_result, prescription, administration` | Summary tiles |
| `allergies` | `[{substance, category, reaction, criticality, evidence}]` | Allergy banner |
| `active_conditions` | `[{display, onset, evidence}]` | Problem list |
| `trends` | `{egfr, creatinine, hba1c, glucose, potassium, sodium, ldl, hemoglobin, urine_protein, acr, sbp, dbp}` | Charts (below) |
| `medications` | `[{medication, ingredient, status, first_prescribed, last_prescribed, prescriptions, prescriptions_in_window, evidence}]` | Medicine list |
| `findings` | `[{rule, severity, title, detail, evidence, source}]` | Alert list, sorted by severity |
| `timeline` | `[{date, type, text, evidence}]`; `type` is one of `diagnosis, admission, emergency, medication started, flag` | Timeline view, already sorted |
| `rules_version` | e.g. `2026-10-25.2` | Footer / audit |
| `sources` | `{key: {title, url}}` | Turns each finding's `source` into a guideline link |

**Each trend** has `label, unit, n, first {date, value, eid}, latest {...}, min, max, slope_per_year,
change_pct, direction` (`rising | falling | stable | too few results`), `band` (reference range, marked
*illustrative* where it is), `above_band, below_band, evidence`, and `points` as `[[date, value], ...]` for
the chart. `series` names the lab panel used; `other_series` counts results from other panels that were
**not** mixed in (Synthea reports some tests from two panels with different values on the same day).

**Severity** is `high` (show first, red), `review` (needs a look) or `info`. Across the 112 patients there are
4 high, 124 review and 12 info findings.

**Evidence IDs** have the form `E-<kind>-<record id>`. To show the source row for a drill-down, use
`rec.by_eid()[eid]`: it returns the item with `.row` (the source row), `.system` (`hospital_ehr`, `lab_lis` or `pharmacy_rx`) and `.when`.

---

## 6. Numbers you can quote (synthetic data only)

| What | Result |
|---|---|
| Patients linked by simple exact matching | 99 of 112 lab patients (13 silently lost) |
| ClinAssist matcher, strict setting, main dataset | 99 lab + 91 pharmacy auto-links; 30 sent to a person, all with the right suggestion; **0 wrong merges** |
| Wrong merges in 4 stress scenarios × 4 datasets | **0** at the strict setting (79 at the old setting; the World Model's built-in name matcher made 112) |
| Clinical rule tests | 36 of 36 scenarios + 8 ingredient-parsing checks pass |
| Fact-checker, planted errors caught | 87–91% overall (3 runs); 100% of invented numbers, dates, sources and missing HIGH findings |
| Fact-checker, correct summaries wrongly rejected | 0 of 136 per run |
| Scout, held-out requests (30, written before the code) | 23 of 30 handled as expected; **0 of 14 unsafe requests reached the agent** (12 blocked, 2 sent to clarification); **0 of 16 normal requests wrongly blocked**; 5 normal requests sent to clarification instead of understood |
| Scout + agent end-to-end | 12 of 12 checks (tampered, missing, wrong-patient contracts refused; lanes applied; out-of-scope citations rejected) |
| Zetaris vs source files | All 12 tables identical (`ALL MATCH`) |

---

## 7. What the demo must not claim

- **No real-world accuracy.** Say "0 wrong merges on synthetic stress tests", never "accurate in hospitals".
- **Not a diagnosis or treatment tool.** Findings are prompts for a clinician's review. The verifier blocks
  treatment instructions.
- **The rules are a demonstration set.** Thresholds come from cited guidelines (NICE, KDIGO, FDA labels, ADA),
  but no clinician has validated the rule set. The alendronate check uses eGFR as a stand-in for creatinine clearance.
- **Fact-checker blind spots:** it misses most treatment orders worded in new ways (only 30–43% caught) and
  cannot catch a false claim that contains no number. A second, AI-based check is planned.
- **Scout is pattern-based, not an AI classifier.** It understood 77% of new phrasings in our held-out set; unclear
  requests are sent back for clarification rather than guessed. Its held-out set was written by the same person
  who built it, so it is not a fully independent test.
- **AI benchmark not yet done.** Nemotron answered smoke tests through Nightshift; the full benchmark
  (`eval/bench_llm.py`) still has to be run.
- **Production matching** should use the Emirates ID where available (Malaffi, Riayati); name and date-of-birth
  scoring is the fallback.

---

## 8. Checks to run before the demo

```powershell
.\.venv\Scripts\python.exe .\tests\test_rules.py          # 44/44 checks passed
.\.venv\Scripts\python.exe .\tests\test_scout_agent.py    # 12/12 checks passed
.\.venv\Scripts\python.exe .\eval\eval_scout.py           # Scout dev + held-out results
.\.venv\Scripts\python.exe .\tests\stress_twins.py        # 0 wrong merges
.\.venv\Scripts\python.exe .\eval\audit_sources.py        # ALL MATCH
.\.venv\Scripts\python.exe .\smoke_test.py                # Zetaris + Nightshift reachable
```
