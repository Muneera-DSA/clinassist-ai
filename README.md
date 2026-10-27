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

## Requirements (install these first)

Install and check every item below **before** cloning. Each "check" command should print a version.

| Tool | Version | Why it is needed | Check in PowerShell | Get it |
|---|---|---|---|---|
| Windows + PowerShell | Windows 10/11, PowerShell 5.1+ (built in) | All commands below are PowerShell | `$PSVersionTable.PSVersion` | built in |
| Git | any recent | Clone the repository | `git --version` | git-scm.com |
| Python | **3.12 or newer** (tick *Add python.exe to PATH* when installing) | Backend, agent, scripts, data build | `python --version` | python.org |
| Node.js (includes npm) | **20.19+ or 22.12+** (LTS) | Meterless gateway, World Model, H-MEM, Angular build | `node --version` and `npm.cmd --version` | nodejs.org |
| Angular CLI | 20.3 (installed **locally** by `npm.cmd install` in `web\`; no global install needed) | Builds the web app | `cd web; npx.cmd ng version` (after step 4) | via npm |
| Docker Desktop | recent, **running**, WSL 2 backend, about 4 GB RAM free | The three source databases (SQL Server 2022, MySQL 8.4, PostgreSQL 16) | `docker --version` and `docker compose version` | docker.com |
| Zetaris | local Docker install, with an API key | The only data path to the three databases | open `http://localhost:3000` | from the Zetaris sponsor resources |
| Meterless Nightshift | runtime with a token, and NVIDIA Nemotron access | Supervision and model routing (the NVIDIA key stays in Nightshift, never in this repo) | Nightshift app is running | from the Meterless sponsor resources |

Python packages (`requirements.txt`: `requests`, `python-dotenv`), Node packages (`package.json`: World Model, H-MEM,
`tsx`) and the Angular packages (`web/package.json`) are installed by the steps below. Without Zetaris you can still run
the app on the offline copy of the same data (`--source csv`, step F); without Nightshift, the rule-based answers work and
the Nemotron switch on the Ask page fails.

> **PowerShell tip:** if `npm` or `npx` fails with *"running scripts is disabled on this system"*, use `npm.cmd` and
> `npx.cmd` instead (as below). They do the same thing and need no policy change.

## Installation

All commands run in PowerShell from the project folder unless a step says otherwise.

### 1. Clone the repository

```powershell
git clone https://github.com/Muneera-DSA/clinassist-ai.git
cd clinassist-ai
git branch --show-current     # should print main; the synthetic data folder data\synthea_fhir\ must exist
dir data\synthea_fhir | Measure-Object   # about 114 files
```

### 2. Create the Python environment

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### 3. Install the Node.js dependencies (Meterless gateway, World Model, H-MEM)

```powershell
npm.cmd install
```

### 4. Install the Angular app dependencies

```powershell
cd web
npm.cmd install
cd ..
```

### 5. Configure the environment files

```powershell
copy .env.example .env                    # Zetaris, Meterless/Nightshift and Scout settings
copy sources\.env.example sources\.env    # passwords for the three source databases
```

- In `sources\.env`, choose your own database passwords (admin and read-only user for each system).
- In `.env`, fill in your Zetaris URL, organisation and API key, your Meterless runtime token, and a Scout signing key.
  Generate the signing key with:
  `.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_hex(32))"`
- Both files are git-ignored. Never commit them or paste their values anywhere.

### 6. Build the synthetic source data (once)

`data/derived/` is not in git; it is regenerated from the Synthea files in `data/synthea_fhir/`.

```powershell
.\.venv\Scripts\python.exe .\clinassist_build_sources.py    # hospital, laboratory and pharmacy CSVs + answer key in data\derived\
```

### 7. Optional (needs internet): FDA label sections for Medicine review

The saved labels are already in `reference/drug_labels.json`. To fetch them again:

```powershell
.\.venv\Scripts\python.exe .\reference\fetch_drug_labels.py
```

---

## Running the system

Do the one-time steps (A–D) after installation, then start the three components (E–G), each in its own PowerShell window,
**in this order**.

### A. Start the source databases

```powershell
cd sources
docker compose up -d
docker compose ps    # wait until all three show "healthy" (first run: 1–3 min; the CSVs load on first start)
cd ..
```

### B. Register the sources in Zetaris (once)

Open the Zetaris SQL editor at `http://localhost:3000`, run `zetaris/01_register_sources.sql` **one statement at a time**
with the read-only passwords from `sources\.env` (details in `docs/run_the_demo.md`), then verify:

```powershell
.\.venv\Scripts\python.exe .\eval\audit_sources.py    # must end with ALL MATCH
```

### C. Match patients across the three systems (once)

```powershell
.\.venv\Scripts\python.exe .\run_matching.py --score    # data\derived\identity\ (links, review queue, report)
```

### D. Build the Meterless World Model of identities (once)

```powershell
npx.cmd tsx meterless/world/build_world.ts    # 112 patients, links and the records waiting for a person
```

### E. Start the Meterless gateway (window 1, start first)

```powershell
npx.cmd tsx meterless/gateway/server.ts    # http://127.0.0.1:8090
```

### F. Start the Python backend (window 2)

```powershell
.\.venv\Scripts\python.exe -m server                 # live data through Zetaris, http://127.0.0.1:8000
# or, if Zetaris is not running (offline copy of the same CSVs):
.\.venv\Scripts\python.exe -m server --source csv
```

### G. Build the web app (window 3)

Build once and let the backend serve it:

```powershell
cd web
npx.cmd ng build --configuration development
```

Open **http://127.0.0.1:8000**, choose a role, and (for judges) switch on **Judge view** in the sidebar.

For live reload during development instead: `cd web` then `npm.cmd start` and open **http://localhost:4200**
(it forwards `/api` to the backend on port 8000).

### Troubleshooting

| Symptom | Fix |
|---|---|
| `npm`/`npx` "running scripts is disabled" | Use `npm.cmd` / `npx.cmd` |
| A database is not "healthy" | `docker compose logs <service>` in `sources\`; check the passwords in `sources\.env` |
| `audit_sources.py` does not print ALL MATCH | Re-run the registration statements in Zetaris; check the read-only passwords |
| Answers fail with "gateway down" | Start the Meterless gateway (step E) before the backend |
| Nemotron answers fail, rule-based ones work | Check the Meterless token in `.env` and that Nightshift is running |
| No patients / empty tables after cloning | Run step 6 (`clinassist_build_sources.py`) **before** step A. If the databases were already started empty, reset them: `cd sources; docker compose down -v; docker compose up -d; cd ..`, then redo B–D |
| `data\synthea_fhir\` is missing or empty | You cloned an old copy: `git pull`, and check that you are on the latest `main` |
| `python` opens the Microsoft Store or is not found | Reinstall Python 3.12 with *Add python.exe to PATH* ticked, then open a new PowerShell window |
| Identity resolution or patient lists are empty | Steps C and D were skipped: run `run_matching.py --score` and `build_world.ts`, then restart the backend |
| Evaluation page is empty | The evaluation files are regenerated by the scripts in `eval\` (see `docs/ml_handoff.md`) |

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
