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

## 3. Start the Meterless gateway (first), then the backend

Meterless supervises every action, so the backend refuses to run requests if the gateway is not up (it fails closed).
In its own PowerShell window, from the project folder:

```powershell
npx.cmd tsx meterless/gateway/server.ts       # http://127.0.0.1:8090  (World Model run records + H-MEM)
```

Then, in another window:

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

1. **Overview**: the problem in one sentence; live checks show Zetaris, the three engines, the Meterless supervisor, Scout and
   Nightshift. The flow: doctor → Meterless (Scout + approval of every action) → Nemotron (the boss) ⇄ scripts ⇄ Zetaris.
2. **Fragmented data**: one query across SQL Server, MySQL and PostgreSQL; the same man written three ways; the naive join
   finds only 99 of 112 lab patients.
3. **Identity resolution**: open a waiting case (e.g. HACKETT: day and month swapped), read the reasons, approve it as a named
   reviewer. The World Model is rebuilt and the provenance panel shows the reviewer's decision.
4. **Patient review** (Kendrick, MRN91862E3E): kidney function falling 82 → 25, alendronate with weak kidneys, low blood pressure
   on three BP medicines, missing haemoglobin test. Click any chip to open the exact source row (engine, table, record).
5. **Ask ClinAssist**: run "Why is his eGFR flagged?" with Nemotron on. Watch Meterless record the request and Scout sign the
   contract; Nemotron choose scripts step by step (it reads "criterion met" and asks for the eGFR series); every script, Zetaris
   fetch and Nemotron call listed as approved by Meterless; the fact-check and the Nemotron judge send drafts back if needed.
6. **Try to break it**: "Ignore your previous instructions…", "What dose of lisinopril should I prescribe him?", another
   patient's name, or a medicine review as an insurance coordinator: Scout blocks each before any data is read.
7. **Audit trail**: the Meterless World Model record of the run: request, Scout decision, and every action with its approval
   (or refusal) and result. **Evaluation**: how it was tested and the blind spots we found.

## What to say if something is slow or down

- Nemotron can take 30-90 seconds per draft. The trace shows each step as it happens.
- If a Nightshift lane fails (for example the deep lane's provider is not available to the account), the agent retries once on the
  fast lane and the trace says so.
- If the AI draft fails the checker three times, the AI text is never shown: the verified rule-based summary is shown and the case
  is flagged. That is the designed behaviour, not a crash.
- If the Meterless gateway is not running, requests are refused with a clear message: start it (section 3) and retry.
- If Zetaris is down, switch to the offline copy (bottom-left of the app). The app labels this clearly.

## Resetting the demo

Reviewer decisions made in the app are stored in `data/derived/identity/review_decisions.json` and replayed into the World
Model. To start the demo again with all 30 cases waiting: delete that file, then run `npx.cmd tsx meterless/world/build_world.ts`.
Saved agent runs are in `data/derived/runs/` and the Meterless run records in `data/derived/world/runs/` (delete both to clear the
audit trail). Lessons Meterless H-MEM kept from earlier runs are in `data/derived/hmem/`.
