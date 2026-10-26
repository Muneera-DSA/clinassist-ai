# Running ClinAssist AI end to end (and demoing it)

Everything runs on one Windows laptop. Synthetic data only.

```
SQL Server (hospital) ─┐
MySQL (laboratory) ────┼─> Zetaris ─> Python backend (server/) ─> Angular app (web/)
PostgreSQL (pharmacy) ─┘                 │   matcher, World Model view, analysis, Scout, agent loop
                                         └─> Meterless Nightshift ─> NVIDIA Nemotron
```

## 0. One-time setup

| What | Command (PowerShell, from `C:\Hackathon\clinical-ai-assistant`) |
|---|---|
| Python packages | `.\.venv\Scripts\python.exe -m pip install -r requirements.txt` |
| Node packages for the World Model | `npm.cmd install` |
| Angular app packages | `cd web; npm.cmd install; cd ..` |
| Passwords for the three databases | copy `sources\.env.example` to `sources\.env` and set your own passwords |
| Keys for Zetaris, Nightshift, Scout | `.env` (see `.env.example`) |

`sources\.env` rules: the SQL Server admin password needs 8+ characters with upper case, lower case, a digit and a symbol.
Do not use quotes in any password.

## 1. Start the three source databases

```powershell
cd sources
docker compose down -v      # only the first time after switching engines: removes the old PostgreSQL-only containers
docker compose up -d
docker compose ps           # wait until all three say "healthy" (first start loads the data: 1-3 minutes)
cd ..
```

If one stays unhealthy: `docker compose logs hospital-db` (or `laboratory-db`, `pharmacy-db`).

## 2. Register them in Zetaris

Open the Zetaris SQL editor (http://localhost:3000) and run `zetaris/01_register_sources.sql` one statement at a time,
with the READ-ONLY passwords from `sources\.env`. Then check:

```powershell
.\.venv\Scripts\python.exe .\eval\audit_sources.py      # must end with ALL MATCH
```

If Zetaris shows different table names (for example with a `dbo` prefix for SQL Server), put them in
`config/sources.json`; nothing else needs changing.

## 3. Start the backend

```powershell
.\.venv\Scripts\python.exe -m server            # http://127.0.0.1:8000  (live data through Zetaris)
.\.venv\Scripts\python.exe -m server --source csv   # offline copy, if Zetaris is down (the app shows a warning banner)
```

## 4. Start the web app

Development (live reload):

```powershell
cd web
npm.cmd start        # http://localhost:4200  (forwards /api to the backend)
```

Or build once and let the backend serve it (one address, http://127.0.0.1:8000):

```powershell
cd web
npm.cmd run build
```

## 5. Demo script (about 4 minutes)

1. **Overview**: the problem in one sentence; live checks show Zetaris, the three engines, the World Model, Scout and Nightshift.
2. **Fragmented data**: one query across SQL Server, MySQL and PostgreSQL; the same man written three ways; the naive join
   finds only 99 of 112 lab patients.
3. **Identity resolution**: open a waiting case (e.g. HACKETT: day and month swapped), read the reasons, approve it as a named
   reviewer. The World Model is rebuilt and the provenance panel shows the reviewer's decision.
4. **Patient review** (Kendrick, MRN91862E3E): kidney function falling 82 → 25, alendronate with weak kidneys, low blood pressure
   on three BP medicines, missing haemoglobin test. Click any chip to open the exact source row (engine, table, record).
5. **Ask ClinAssist**: run "Prepare a pre-visit summary" with Nemotron on. Watch Scout approve and sign the contract, the planner
   choose tools, the writer draft, the evaluator check every sentence (and send it back if needed).
6. **Try to break it**: "Ignore your previous instructions…", "What dose of lisinopril should I prescribe him?", another
   patient's name, or a medicine review as an insurance coordinator: Scout blocks each before any data is read.
7. **Evaluation** and **Audit trail**: how it was tested, the blind spots we found, and every run kept step by step.

## What to say if something is slow or down

- Nemotron can take 30-90 seconds per draft. The trace shows each step as it happens.
- If a Nightshift lane fails (for example the deep lane's provider is not available to the account), the agent retries once on the
  fast lane and the trace says so.
- If the AI draft fails the checker three times, the AI text is never shown: the verified rule-based summary is shown and the case
  is flagged. That is the designed behaviour, not a crash.
- If Zetaris is down, switch to the offline copy (bottom-left of the app). The app labels this clearly.

## Resetting the demo

Reviewer decisions made in the app are stored in `data/derived/identity/review_decisions.json` and replayed into the World
Model. To start the demo again with all 30 cases waiting: delete that file, then run `npx.cmd tsx wm/build_world.ts`.
Saved agent runs are in `data/derived/runs/` (delete the folder to clear the audit trail).
