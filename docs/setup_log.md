# ClinAssist AI — Setup Log

A record of how the development environment was built, reconstructed from the
PowerShell history (Cursor terminal) and the Ubuntu (WSL) history, 21–24 October 2026.
No passwords, keys or tokens are reproduced here.

**Machine:** Windows laptop, Intel UHD Graphics, 20 GB RAM · **Editor:** Cursor ·
**Shells:** PowerShell (Cursor terminal) and Ubuntu on WSL 2

---

## Current status (25 Oct 2026)

| Component | Status |
|---|---|
| WSL 2 + Ubuntu, Docker Desktop | ✅ Working |
| Zetaris local platform (Docker) | ✅ Running, `verify.sh` 9/9 |
| Synthea FHIR data (114 files, 112 patients) | ✅ Extracted |
| Three fragmented source systems (hospital / lab / pharmacy) | ✅ Built and running in Docker |
| Sources registered in Zetaris (`hospital_ehr`, `lab_lis`, `pharmacy_rx`) | ✅ Cross-source SQL verified |
| Meterless World Model reference | ✅ Tests pass; clinical integration pending |
| Meterless Nightshift | ✅ v1.2.1, NVIDIA key stored, runtime token in `.env` |
| NVIDIA Nemotron via Nightshift | ✅ smoke test 4/4 PASS (25 Oct) |
| Agent, reconciliation, timeline, UI | ⏳ To build |

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
exercise matching — that is the planned integration (Phase B).

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
-- same pattern for lab_lis (:55433) and pharmacy_rx (:55434)
```

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
8. Known issue: the runtime endpoint on `127.0.0.1:8088` went offline under heavy load (CPU 99%, memory 88% with Docker, Zetaris and other apps open). Fix: close unneeded apps, fully quit and restart Nightshift.

---

## Security notes

- Secrets live only in `.env` and `sources\.env` (both git-ignored) and in Nightshift's Providers tab.
- The Zetaris metastore password was printed once during the 23 Oct inspection and appears in a
  shared ChatGPT link — delete that shared link. The database is bound to localhost.
- Change the default Zetaris admin password from the user menu if not already done.
