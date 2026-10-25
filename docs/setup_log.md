# ClinAssist AI — Setup Log

A record of how the development environment was built, reconstructed from the
PowerShell history (Cursor terminal) and the Ubuntu (WSL) history, 21–25 October 2026.
No passwords, keys or tokens are reproduced here.

**Machine:** Windows laptop, Intel UHD Graphics, 20 GB RAM · **Editor:** Cursor ·
**Shells:** PowerShell (Cursor terminal) and Ubuntu on WSL 2

---

## Current status (25 Oct 2026, evening)

| Component | Status |
|---|---|
| WSL 2 + Ubuntu, Docker Desktop | ✅ Working |
| Zetaris local platform (Docker) | ✅ Running, `verify.sh` 9/9 |
| Synthea FHIR data (114 files, 112 patients) | ✅ Extracted, unchanged |
| Three fragmented source systems (hospital / lab / pharmacy) | ✅ Built and running in Docker; rebuilt 25 Oct with blood-pressure values and an allergies table |
| Sources registered in Zetaris (`hospital_ehr`, `lab_lis`, `pharmacy_rx`) | ✅ 12 tables; `eval/audit_sources.py` → **ALL MATCH** |
| Patient matching (`clinassist/matching.py`, strict cut-off 11.5) | ✅ Lab 99 auto + 13 review, pharmacy 91 auto + 17 review, 0 wrong merges |
| Meterless World Model integration (`wm/`) | ✅ 190 links confirmed, 30 pending human review, with provenance |
| Longitudinal analytics and rules (`clinassist/analysis.py`) | ✅ 36 rule scenarios + 8 ingredient checks pass (`tests/test_rules.py`) |
| Meterless Scout Intent (`clinassist/scout.py`, our implementation of the spec) | ✅ Built 26 Oct; held-out: 0 of 14 unsafe requests reached the agent, 0 of 16 normal requests blocked; agent refuses unsigned plans (12/12 checks) |
| Agent loop + groundedness verifier (`clinassist/agent.py`) | ✅ Built; verifier catches 87–91% of planted errors, 0 of 136 correct summaries rejected |
| Meterless Nightshift runtime (port 8088) | ✅ v1.2.1, answering; smoke test 4/4 PASS |
| Nightshift lane manager (`meterlessd`) | ⚠️ Not answering on 25 Oct evening, so lanes cannot be viewed or changed (see §7) |
| NVIDIA Nemotron via Nightshift | ✅ Answering; Nightshift chooses the model (see §7) |
| Nemotron benchmark (`eval/bench_llm.py`), second "judge" check | ⏳ Not run / not built yet |
| Backend API, dashboard, README | ⏳ Developers |

How to rebuild everything in order, the outputs, and what the demo may claim: `docs/ml_handoff.md`.

---

## 1. Ubuntu (WSL) — Docker access and Zetaris install

| Step | Commands | Purpose |
|---|---|---|
| Update Ubuntu | `sudo apt update` · `sudo apt upgrade -y` · `lsb_release -a` | Patch the Linux environment |
| Check Docker from WSL | `docker --version` · `docker version` · `docker compose version` · `df -h /` | Docker Desktop reachable; ≥15 GB free disk |
| Grant Docker permission | `sudo usermod -aG docker "$USER"` · `newgrp docker` · `docker run hello-world` | Run Docker without `sudo` |
| Registry sign-in | `docker login zetarishackathon.azurecr.io` *(credentials from Zetaris Cloud → Run locally; not recorded)* | Access the private Zetaris images |
| Readiness check | `./preflight.sh` | Docker, memory, disk and registry checks |
| Download + start | `docker compose pull` · `docker compose up -d` | ~4 GB of images; starts postgres, driver, api, ui |
| Verify | `./verify.sh` | 9/9 checks passed |

Zetaris web UI: `http://localhost:3000` · REST API: `http://localhost:8888/api/v1.0` · JDBC: `localhost:10000`.

---

## 2. PowerShell — project and Python environment

```powershell
mkdir C:\Hackathon\clinical-ai-assistant
cd C:\Hackathon\clinical-ai-assistant
& "C:\Users\marbs\anaconda3\python.exe" -m venv .venv
.\.venv\Scripts\python.exe --version
```

Python is always called as `.\.venv\Scripts\python.exe` because `Activate.ps1` is
blocked by the execution policy (deliberately left unchanged).
Node.js was added to the session path when needed: `$env:Path = "C:\Program Files\nodejs;$env:Path"`.

---

## 3. Meterless World Model (required Meterless Engine)

```powershell
git clone --depth 1 https://github.com/Meterless/Meterless.git C:\Hackathon\meterless-world-model-evaluation\Meterless
Set-Location C:\Hackathon\meterless-world-model-evaluation\Meterless\engines\world-model\reference
npm.cmd install                            # 7 audit warnings, not force-fixed
npm.cmd test                               # 10 tests passed
npx.cmd tsx scripts/idempotency-check.ts   # re-ingest -> empty diff
& ".\node_modules\.bin\tsx.cmd" "C:\Hackathon\meterless-world-model-evaluation\clinical-patient-test\clinical-demo.ts"   # RESULT: PASS
```

What the engine actually does (read from `src/resolve.ts`, `src/index.ts`):
event-sourced shared state with provenance on every write; name-keyed entities
are resolved by Levenshtein similarity (≥0.85 auto-merge, 0.82–0.85 operator
review queue). `clinical-demo.ts` used hard-coded ID mappings, so it did not yet
exercise matching.

**Integration in this project (done 24–25 Oct).** The engine's source is vendored in
`vendor/meterless-world-model/` (declared as pre-existing code). `wm/build_world.ts` writes every
patient, lab record and pharmacy record as an entity, auto-links as `same_person_as` and uncertain
matches as `possible_same_person` (pending review), with provenance on every write; it builds in
memory and saves once (much faster on Windows). `wm/review.ts` records a reviewer's approve/reject
decision with their name as the source, and a reviewer always overrides the matcher (confidence 1.0
vs at most 0.99). Output: `data\derived\world\patient_identity.json`.

```powershell
npm.cmd install
npx.cmd tsx wm/build_world.ts                  # 112 patients, 190 links, 30 pending review
npx.cmd tsx wm/review.ts list
```

The engine's own name-similarity resolver was **not** used for patients: in `eval/eval_matching.py` it
merged 112 same-name strangers, because it compares names only.

---

## 4. Synthea data

```powershell
Expand-Archive "$env:USERPROFILE\Downloads\synthea_sample_data_fhir_latest.zip" -DestinationPath C:\Hackathon\clinical-ai-assistant\data\synthea_fhir
.\.venv\Scripts\python.exe .\clinassist_extract_fhir.py      # first extraction: 9 CSVs, shared patient UUIDs
```

The first extraction gave every system the same patient UUID, so cross-system
"reconciliation" was a plain join. It was replaced by:

```powershell
.\.venv\Scripts\python.exe .\clinassist_build_sources.py     # writes data\derived\
```

`clinassist_build_sources.py` creates three systems with their **own identifiers
and conventions** and logged, seeded demographic noise:

| System | Patient ID | Name format | DOB format | Records |
|---|---|---|---|---|
| Hospital EHR | `MRN…` | Given / middle / family | `YYYY-MM-DD` | 112 patients, 5,087 encounters, 3,418 conditions, 13,737 procedures |
| Laboratory LIS | `LP…` | `SURNAME`, forenames | `DD/MM/YYYY` | 19,903 results, 2,143 reports |
| Pharmacy | `RX…` | `SURNAME, Given` | `YYYYMMDD` | 3,221 prescriptions, 571 administrations |

Added on 25 Oct after the audit: blood-pressure panels are split into one row per component
(systolic, diastolic; previously all 1,413 readings were empty), and a hospital `allergies` table
(101 allergies, 7 of them to medicines). All other tables rebuilt byte-identical. Extra datasets for
the experiments: `clinassist_build_sources.py --seed 7 --out data\derived\holdout_seed7` (also 2026, 99).

39 perturbations (surname typos, shortened names, swapped/off-by-one dates, missing sex)
are logged in `data\derived\_truth\`, together with the true identity crosswalk.
`_truth` is used only to measure reconciliation accuracy; the agent never reads it.

---

## 5. Source databases and Zetaris registration

```powershell
cd sources
Copy-Item .env.example .env        # database passwords (local only, synthetic data)
docker compose up -d               # hospital-db :55432, laboratory-db :55433, pharmacy-db :55434
docker compose ps                  # all healthy
docker exec (docker ps -qf "name=driver") bash -c "exec 3<>/dev/tcp/host.docker.internal/55432 && echo REACHABLE"
```

Registered in the Zetaris SQL Editor (`zetaris\01_register_sources.sql`), one statement at a time:

```sql
CREATE DATASOURCE hospital_ehr DESCRIBE BY "Simulated hospital EHR - synthetic" OPTIONS (
  jdbcdriver "org.postgresql.Driver",
  jdbcurl "jdbc:postgresql://host.docker.internal:55432/hospital_ehr",
  username "hospital_ro", password "<from sources\.env>", fetchsize "1000")
REGISTER DATASOURCE TABLES ("patients","encounters","conditions","procedures","observations") FROM hospital_ehr
REGISTER DATASOURCE TABLES ("allergies") FROM hospital_ehr      -- added 25 Oct
-- same pattern for lab_lis (:55433) and pharmacy_rx (:55434)
```

After the 25 Oct rebuild: `docker compose down -v`, `docker compose up -d`, register the `allergies`
table, then `.\.venv\Scripts\python.exe .\eval\audit_sources.py` → **ALL MATCH** (12 tables:
row counts, distinct keys and value sums identical to the CSVs).

**Note on database users:** the users are named `hospital_ro`, `lab_ro`, `pharmacy_ro`, but in
`docker-compose.yml` each is the database **owner**, not a read-only role. Our code only runs
`SELECT`, but do not describe this as read-only access. Creating separate read-only roles is listed
as a post-hackathon hardening step.

Lessons: Zetaris lists only the `public` schema, so tables live there;
single-letter table aliases returned *Bad Request* in one test — use `AS hp`, `AS lp`.

Verified (`zetaris\02_verify_federation.sql`):

| Query | Result |
|---|---|
| Counts across all three systems in one statement | 112 / 19,903 / 3,221 ✅ |
| Naive hospital↔lab match on exact surname + DOB | **99 of 112** — the 13 misses are the reconciliation problem |

---

## 6. Approaches tried and abandoned (23 Oct)

Uploading CSVs through Zetaris's *NDP File System* screen: hospital files uploaded,
but `Observation.csv` (12 MB) failed with `MalformedMessageBodyFailure: Invalid boundary`.
Files were then copied into the container as root (`docker exec --user 0 … cat > …`, SHA-256 verified)
and duplicated into `file-store/clinassist`, but no supported way to register them as a separate
source was found (Create Table was only offered under the `NY_TAXI` sample, and was cancelled).
Read-only inspection of Zetaris's internal metastore followed. Nothing was modified.

Leftovers (harmless): 9 CSVs in NDP `clinassist/` and `file-store/clinassist/`;
`data\simulated_sources\laboratory\Observation_test.csv`; pandas in `.venv`.
The JDBC-datasource route (section 5) replaced this approach — it is documented in the
Zetaris getting-started repo and gives three genuinely separate systems.

---

## 7. Power layer — Nightshift and Nemotron (connected 25 Oct)

1. Nightshift installed (v0.6.2, auto-updated to **v1.2.1** on 25 Oct; installer hash checked with `Get-FileHash`).
2. NVIDIA key (team key) pasted by the user in **Setup → Providers → Cloud provider keys → NVIDIA → Add**; card shows "stored in daemon". The key is held only by the Nightshift daemon.
3. Local model downloads skipped (Intel UHD graphics, no discrete GPU; Nemotron runs on NVIDIA's hosted endpoints).
4. Runtime token: Nightshift writes it to `%LOCALAPPDATA%\ai.meterless.runtime\proxy-token` (also shown in **Setup → Fix endpoint → Console → API KEY**). Copied into `.env` (`METERLESS_RUNTIME_TOKEN`) with a PowerShell one-liner that never prints it.
5. Model ids are routing modes (`meterless/fast`, `meterless/deep`); Nightshift chooses the serving model. Requesting an explicit `nvidia/...` id was still served by `nvidia/nemotron-3-ultra-550b-a55b`, so `.env` uses the routing modes and every call records the model that actually served it.
6. Zetaris API key: **Management → API Tokens** → `.env` (`ZETARIS_API_KEY`).
7. Verify: `.\.venv\Scripts\python.exe .\smoke_test.py` → 4/4 PASS on 25 Oct (served by Nemotron Ultra 550B).
8. Known issue: the runtime endpoint on `127.0.0.1:8088` went offline under heavy load (CPU 99%, memory 88% with Docker, Zetaris and other apps open). Fix: close unneeded apps, fully quit and restart Nightshift. Back up on 25 Oct evening (port 8088 listening; smoke test 4/4 PASS).

**Model probe (25 Oct, `eval/probe_models.py`):** one tiny request per model id, recording which model
actually served it.

| Requested | Served by | Seconds |
|---|---|---|
| `meterless/fast` | `nvidia/nemotron-3.5-super-vl-120b-a12b` | 1.3 |
| `meterless/deep` | `nvidia/nemotron-3-ultra-550b-a55b` | 10.0 |
| `meterless/judge` | `nvidia/nemotron-3-ultra-550b-a55b` | 8.5 |
| 6 explicit `nvidia/...` ids (Nano 30B, Lightning 30B, Super 49B, Super 120B, Ultra 253B, Ultra 550B) | Nightshift's own choice: **0 of 6 honoured** | 7.8–13.5 |

Findings: (a) only the routing mode has an effect; the code cannot pin a model, so every call logs the
model that served it; (b) routing is not fixed: in the smoke test minutes earlier `meterless/fast`
was served by Ultra 550B; (c) Ultra prints its reasoning before the answer; `llm.final_answer`
strips it.

**Lanes:** model-per-lane settings are under **NIGHT → LANES → Lanes & memory** (stored in
`lanes.toml`). On 25 Oct evening that screen showed *"Unreachable — meterlessd is not answering its
control socket"*, and Setup showed "Lanes ready 0/0" and "0 of 17 cloud keys" for the same reason
(the runtime kept serving requests). Fix: the **Daemon controls ›** banner → Restart runtime, or quit
Nightshift from the tray and reopen it. Plan once lanes are reachable: fast → a small Nemotron for the
planner, deep → Ultra for the writer, judge → a Nemotron model different from the writer.

---

## Security notes

- Secrets live only in `.env` and `sources\.env` (both git-ignored) and in Nightshift's Providers tab.
- Nightshift Setup → Controls shows a phone pairing code; keep that page out of screenshots and slides.
- The Zetaris metastore password was printed once during the 23 Oct inspection and appears in a
  shared ChatGPT link — delete that shared link. The database is bound to localhost.
- Change the default Zetaris admin password from the user menu if not already done.
