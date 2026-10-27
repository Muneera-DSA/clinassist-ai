# ClinAssist AI

**A supervised AI agent that reads a patient's fragmented hospital, laboratory and pharmacy records and answers clinical
questions with cited, fact-checked evidence.**

Open Agent Hackathon 2026 · Track: **Reasoning Architecture** · NexAgent team · Synthetic data only

---

## The problem

A patient's story is split across systems that do not talk to each other. In ClinAssist the hospital record runs on
**Microsoft SQL Server**, the outside laboratory on **MySQL** and the pharmacy on **PostgreSQL**, each with its own patient
numbers, name formats and date formats. Joining hospital and laboratory patients on exact surname and date of birth finds only
99 of 112: the rest silently lose their results. Clinicians, hospital staff and insurance coordinators need the whole history,
with evidence they can trust, and an AI that cannot be talked into diagnosing, prescribing or reading the wrong patient.

## What ClinAssist does

| Page | Who sees it | What it does |
|---|---|---|
| **Ask ClinAssist** | every role | Chat in plain language. Cited, fact-checked answers; asks back when unclear; says plainly when something is not in the records; switches patient when another one is named; learns from 👍/👎 feedback. |
| **Patient review** | Doctor, Insurance coordinator | Three-year, evidence-linked view: trends, guideline-based findings, problems and timeline. Every flag opens its source record. |
| **Medicine review** | Doctor | Every medicine ever prescribed, safety flags (risky combinations, Beers list for 65+, kidney limits, allergies, duplicates) and the official FDA label sections. |
| **Identity resolution** | Authorised hospital staff | Which lab and pharmacy records belong to which hospital patient; uncertain matches are decided by a named person and recorded in the Meterless World Model. |
| **Overview, Fragmented data, Evaluation, Audit trail** | Judge view | The architecture, the live federated SQL console, how it was tested, and the full Meterless record of every run. |

On first opening, the app asks **"Who are you?"**: *Doctor*, *Authorised hospital staff* or *Insurance coordinator*. The role
decides which pages appear and is enforced on every request by Scout and Meterless. **Judge view** is a switch in the sidebar
(available in every role) that shows all pages plus the technical panels: live Nemotron decisions, Meterless supervision, a
step-by-step **workflow trace** (database → Zetaris → Meterless → Nightshift lane → Nemotron → script), the H-MEM memory log,
the learning loop and the Scout safety tests. Chat permissions still follow the chosen role.

## How a request flows

```
Doctor asks the chatbot
   │
   ▼
Meterless Scout ── unsafe? ──► stopped on purpose (injection, diagnosis/prescribing, other patient, bulk export, wrong role)
   │ signs a 15-minute contract (allowed scripts + model lanes)
   ▼
Meterless Nightshift ──► NVIDIA Nemotron, the boss ◄── Meterless H-MEM (ranked script catalog + lessons)
   │   chooses single-action scripts step by step, reads each result, decides what to look at next
   ▼
Single-action Python scripts (31) ──► Zetaris ──► SQL Server · MySQL · PostgreSQL   (only this patient's linked records)
   │
   ▼
Fact-check (deterministic, enforced) + Nemotron judge ── fails? ──► back to Nemotron (up to 3 rounds) ──► else escalated to a person
   │
   ▼
Cited answer for the clinician to review.  Every step above is approved against the contract and recorded in the Meterless World Model.
```

## Use of sponsor technology

| Sponsor | How ClinAssist uses it |
|---|---|
| **Zetaris** | The only data path. Federates SQL Server, MySQL and PostgreSQL into one SQL dialect. Every patient fetch is a federated query (shown with its SQL in the workflow trace); the Fragmented data page runs cross-engine joins live. All 12 tables verified identical to the source files through Zetaris. |
| **Meterless** | Supervises the whole agent. **Scout** checks every request and signs a contract; the **supervisor** authorises and records every script, data fetch, model call and memory lookup (fails closed if unavailable); the **World Model** holds identity links, reviewer decisions and every run (the audit trail); **H-MEM** ranks the script catalog for each question and stores lessons from clinician feedback; **Nightshift** routes model calls through lanes (planner, writer, judge, interpreter). |
| **NVIDIA Nemotron** | The reasoning layer, reached through Nightshift: the boss that chooses scripts, the interpreter for requests the rules cannot place, the writer, and the judge. All lanes use `nvidia/nemotron-3.5-lightning-30b-a3b`, with retry and lane fallback. |
| **Cursor** | The development environment for the whole build. |

What is unusual: the model makes every decision but can only act through approved single-action scripts, every action is
recorded by Meterless, and nothing it writes is shown until a deterministic fact-check (every citation retrieved, every number
and date found in the cited record) and a second Nemotron reviewer have passed it.

## Repository layout

| Path | Contents |
|---|---|
| `sources/` | Docker Compose for the three source databases (SQL Server, MySQL, PostgreSQL) and their init scripts |
| `zetaris/` | SQL and script to register the three sources in Zetaris |
| `clinassist/` | Patient record loading, identity matching, clinical rules (`analysis.py`), the agent loop (`agent.py`), the fact-checker (`verifier.py`) and the 31 single-action scripts (`scripts/`) |
| `meterless/` | Scout (`scout/`, intent registry `intents.json`), the supervisor (`supervisor/`), the gateway (`gateway/server.ts`), World Model build and review (`world/`) and the vendored World Model and H-MEM libraries (`vendor/`) |
| `server/` | Python HTTP backend (`python -m server`), serves the API and the built web app |
| `web/` | Angular 20 front end |
| `config/` | Clinical rules with their public sources (`clinical_rules.json`), source table names (`sources.json`) |
| `reference/` | One-time FDA label fetcher (openFDA) and the saved label sections used offline |
| `eval/`, `tests/` | Evaluation scripts (matching, Scout, verifier, model benchmark) and automated tests |
| `data/` | Synthetic Synthea data and derived files |
| `docs/` | Detailed run guide, Zetaris registration guide, setup log |

## Requirements

- Windows 10/11 (tested), Docker Desktop
- Python 3.12+ and Node.js 20.19+ (npm)
- Zetaris (local Docker install) with an API key
- Meterless Nightshift runtime with access to NVIDIA Nemotron (the NVIDIA key stays in Nightshift, never in this repo)

Python dependencies: `requirements.txt` (`requests`, `python-dotenv`). Node dependencies: `package.json` (World Model,
H-MEM, gateway via `tsx`) and `web/package.json` (Angular).

## Setup

From `C:\Hackathon\clinical-ai-assistant` in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm.cmd install
cd web; npm.cmd install; cd ..
copy .env.example .env                    # Zetaris, Nightshift and Scout settings (never commit .env)
copy sources\.env.example sources\.env    # your own database passwords
```

Generate a Scout signing key for `.env`:
`.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"`

Start the databases and register them in Zetaris (details in `docs/run_the_demo.md`):

```powershell
cd sources; docker compose up -d; docker compose ps; cd ..     # wait until all three are healthy
# run zetaris/01_register_sources.sql in the Zetaris SQL editor (http://localhost:3000)
.\.venv\Scripts\python.exe .\eval\audit_sources.py              # must end with ALL MATCH
```

Optional, once (needs internet): fetch the FDA label sections used by Medicine review.

```powershell
.\.venv\Scripts\python.exe .\reference\fetch_drug_labels.py
```

## Running

Three terminals, in this order:

```powershell
npx.cmd tsx meterless/gateway/server.ts                         # 1. Meterless gateway, http://127.0.0.1:8090 (start first)
.\.venv\Scripts\python.exe -m server                            # 2. backend, http://127.0.0.1:8000
cd web; npx.cmd ng build --configuration development            # 3. build the web app once (served by the backend)
```

Open **http://127.0.0.1:8000**, choose a role, and (for judges) switch on **Judge view** in the sidebar.
For live reload during development use `cd web; npm.cmd start` (http://localhost:4200).

## Try it

- **Doctor**, patient *OBERBRUNNER, KENDRICK*: Patient review (kidney function falling 82 → 25, alendronate with weak kidneys,
  low blood pressure on three medicines); Medicine review (duplicate simvastatin, FDA labels); ask *"Which results are flagged?"*
  or *"Any risky drug combinations?"* with Nemotron on, then open **⛓ Workflow trace**.
- Ask about another patient by name (*"show kendrick's labs"* while someone else is selected): ClinAssist switches patient.
- **Try to break it** (Judge view, Ask page): prompt injection, prescribing, diagnosis, another patient, wrong role, indirect
  wording. Scout stops each before any data is read.
- **Authorised hospital staff**: Identity resolution queue; ask *"List previous hospital visits and admissions"* (no clinical results).
- **Insurance coordinator**: a medicine review is refused, with a message listing what the role can ask.

## Tests and evaluation

```powershell
.\.venv\Scripts\python.exe .\tests\test_rules.py         # 59 clinical rule scenarios
.\.venv\Scripts\python.exe .\tests\test_scout_agent.py   # 26 agent + Meterless checks
.\.venv\Scripts\python.exe .\tests\test_scout_ai.py      # 9 Scout + Nemotron checks (stand-in model)
.\.venv\Scripts\python.exe .\tests\test_reasoning.py     # 5 reasoning checks
```

Results on synthetic data (shown on the Evaluation page): **0** wrong patient merges in 4 stress scenarios × 4 datasets;
**87–91%** of planted summary errors caught with **0 of 136** correct summaries rejected; **0 of 14** held-out unsafe requests
reached the agent; **12 of 12** tables identical through Zetaris. These show the engineering works as designed; they are not
clinical accuracy claims.

## Safety and limitations

- Synthetic data only (Synthea). No real patient data. Secrets live in `.env` files that are git-ignored.
- ClinAssist never diagnoses, prescribes, gives doses, approves claims or submits anything. Every answer is for a qualified
  professional to review.
- The clinical rule set is a demonstration with cited public thresholds; it has not been clinically validated.
- Roles are enforced on every agent request; page-level access control is not yet implemented.
- Not yet built (roadmap): prior-authorization readiness checklist and packet, ICD-10 coding (needs a licensed SNOMED map),
  abnormal-results follow-up, and integration with Malaffi / Riayati through an approved route.

## Pre-existing components (declared)

- **Meterless World Model** and **H-MEM** libraries, vendored in `meterless/vendor/` (sponsor components).
- **Synthea** synthetic patient generator (data in `data/`).
- **openFDA** drug label API (public data, fetched once into `reference/drug_labels.json`).
- Open-source packages listed in `requirements.txt`, `package.json` and `web/package.json`.

All ClinAssist code in this repository was written during the build window (from 22 October 2026).

---

NexAgent team · Open Agent Hackathon 2026
