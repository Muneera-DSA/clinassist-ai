r"""Register the three ClinAssist source databases in Zetaris, without anyone typing a password.

    .\.venv\Scripts\python.exe .\zetaris\register_sources.py

What it does (through the Zetaris REST API, using the key in .env):
  1. lists the data sources Zetaris already has and drops old hospital_ehr / lab_lis / pharmacy_rx registrations
  2. for each database: connection test, CREATE DATASOURCE, REGISTER DATASOURCE TABLES
  3. finds the name Zetaris gave each of our 12 tables (tries them with a COUNT), and updates config/sources.json
     if a name differs (for example a dbo prefix on SQL Server)
  4. runs one query across all three engines

The read-only passwords are read from sources/.env and never printed (they are masked in any error message).
Synthetic data only.
"""
from __future__ import annotations

import json
import re
import sys
import uuid
from pathlib import Path

import requests
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from clinassist.zetaris_client import ZetarisClient  # noqa: E402

CONFIG = ROOT / "config" / "sources.json"
LOGICAL = {"procedure_history": "procedures"}   # SQL Server table name -> our name (sys.procedures clash)
SAFE_PW = re.compile(r'^[^"\\\'`\s]+$')

SYSTEMS = {
    "hospital_ehr": {
        "label": "Hospital EHR on SQL Server - synthetic",
        "driver": "com.microsoft.sqlserver.jdbc.SQLServerDriver",
        "url": "jdbc:sqlserver://host.docker.internal:55432;databaseName=hospital_ehr;encrypt=false",
        "user_var": "HOSPITAL_DB_USER", "user_default": "hospital_ro", "pw_var": "HOSPITAL_DB_PASSWORD",
        "tables": ["patients", "encounters", "conditions", "procedure_history", "observations", "allergies"],
    },
    "lab_lis": {
        "label": "Laboratory LIS on MySQL - synthetic",
        "driver": "com.mysql.cj.jdbc.Driver",
        "url": "jdbc:mysql://host.docker.internal:55433/lab_lis?useSSL=false&allowPublicKeyRetrieval=true",
        "user_var": "LAB_DB_USER", "user_default": "lab_ro", "pw_var": "LAB_DB_PASSWORD",
        "tables": ["lab_patients", "lab_results", "lab_reports"],
    },
    "pharmacy_rx": {
        "label": "Pharmacy system on PostgreSQL - synthetic",
        "driver": "org.postgresql.Driver",
        "url": "jdbc:postgresql://host.docker.internal:55434/pharmacy_rx",
        "user_var": "PHARMACY_DB_USER", "user_default": "pharmacy_ro", "pw_var": "PHARMACY_DB_PASSWORD",
        "tables": ["pharmacy_patients", "prescriptions", "administrations"],
    },
}


class Z:
    """Sends one statement at a time; masks secrets in anything it prints."""

    def __init__(self, client: ZetarisClient, secrets: list[str]):
        self.c, self.secrets = client, [s for s in secrets if s]

    def mask(self, text: str) -> str:
        for s in self.secrets:
            text = text.replace(s, "******")
        return text

    def run(self, sql: str, timeout: int = 600) -> tuple[bool, list, str]:
        try:
            r = requests.post(self.c.url, headers={"Authorization": "Bearer " + self.c._key, "X-Org-ID": self.c.org_id,
                                                   "X-Request-ID": str(uuid.uuid4())},
                              json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": 5000},
                              timeout=timeout)
        except requests.RequestException as e:
            return False, [], self.mask(f"could not reach Zetaris: {e}")
        if r.status_code >= 400:
            return False, [], self.mask(f"HTTP {r.status_code}: {r.text[:600]}")
        try:
            body = r.json()
        except ValueError:
            return False, [], self.mask(r.text[:600])
        return True, body.get("data") or [], ""


def opts(s: dict, user: str, pw: str, extra: bool) -> str:
    lines = [f'jdbcdriver "{s["driver"]}"', f'jdbcurl "{s["url"]}"', f'username "{user}"', f'password "{pw}"']
    if extra:
        lines.append('fetchsize "1000"')
    return "OPTIONS (\n  " + ",\n  ".join(lines) + "\n)"


def cells(rows: list) -> list[str]:
    out = []
    for row in rows:
        for v in (row if isinstance(row, (list, tuple)) else [row]):
            if v is not None:
                out.append(str(v))
    return out


def main() -> None:
    src_env = dotenv_values(ROOT / "sources" / ".env")
    creds, problems = {}, []
    for name, s in SYSTEMS.items():
        user = (src_env.get(s["user_var"]) or s["user_default"]).strip()
        pw = (src_env.get(s["pw_var"]) or "").strip()
        if not pw or pw.startswith("change-me"):
            problems.append(f"{s['pw_var']} is not set in sources/.env")
        elif not SAFE_PW.match(pw):
            problems.append(f"{s['pw_var']} contains a quote, backslash or space; Zetaris SQL cannot take it")
        creds[name] = (user, pw)
    if problems:
        sys.exit("Stopped: " + "; ".join(problems))

    z = Z(ZetarisClient.from_env(), [pw for _, pw in creds.values()])

    print("1. Data sources Zetaris already has")
    ok, rows, err = z.run("SHOW DATASOURCES", timeout=120)
    if not ok:
        sys.exit(f"   Zetaris is not answering ({err}). Is zetaris-driver-1 running? (docker ps)")
    existing = {c.lower() for c in cells(rows)}
    print("   ", ", ".join(sorted({c for c in cells(rows) if len(c) < 60})) or "(none)")
    for name in SYSTEMS:
        if name in existing:
            ok, _, err = z.run(f"DROP DATASOURCE {name}", timeout=120)
            print(f"   dropped old {name}" if ok else f"   could not drop {name}: {err}")

    mapping: dict[str, str] = {}
    failed = []
    for name, s in SYSTEMS.items():
        user, pw = creds[name]
        print(f"\n2. {name}  ({s['label']})")
        ok, rows, err = z.run(f"LIST DATABASE TABLES {opts(s, user, pw, extra=False)}", timeout=180)
        if not ok:
            print(f"   connection test FAILED: {err}")
            failed.append(name)
            continue
        seen = {c.lower() for c in cells(rows)}
        print(f"   connection OK; our tables visible: {sum(t in seen for t in s['tables'])}/{len(s['tables'])}")

        ok, _, err = z.run(f'CREATE DATASOURCE {name} DESCRIBE BY "{s["label"]}" {opts(s, user, pw, extra=True)}', timeout=180)
        if not ok:
            print(f"   CREATE with description failed ({err}); trying the short form")
            ok, _, err = z.run(f"CREATE DATASOURCE {name} {opts(s, user, pw, extra=False)}", timeout=180)
        if not ok:
            print(f"   CREATE DATASOURCE FAILED: {err}")
            failed.append(name)
            continue
        print("   created")

        ok, _, err = z.run(f"REGISTER DATASOURCE TABLES FROM {name}", timeout=900)
        if not ok:
            print(f"   REGISTER TABLES FAILED: {err}")
            failed.append(name)
            continue
        print("   tables registered")

        ok, rows, err = z.run(f"SHOW DATASOURCE TABLES {name}", timeout=180)
        shown = cells(rows) if ok else []
        for t in s["tables"]:
            cands = [f"{name}.{t}"] + [f"{name}.{c}" if not c.lower().startswith(name + ".") else c
                                       for c in shown if c.lower().endswith(t) and c.lower() != t]
            cands += [f"{name}.dbo_{t}", f"{name}.dbo.{t}"]
            found = None
            for cand in dict.fromkeys(cands):
                ok, rows, _ = z.run(f"SELECT COUNT(*) AS n FROM {cand}", timeout=180)
                if ok and rows:
                    found = (cand, rows[0][0] if isinstance(rows[0], (list, tuple)) else rows[0])
                    break
            if found:
                mapping[f"{name}.{LOGICAL.get(t, t)}"] = found[0]
                print(f"   {t:<18} -> {found[0]:<36} {found[1]} rows")
            else:
                print(f"   {t:<18} -> NOT FOUND (send this output to the ML lead)")
                failed.append(f"{name}.{t}")

    if mapping:
        cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
        changed = {k: v for k, v in mapping.items() if cfg["tables"].get(k) != v}
        if changed:
            cfg["tables"].update(changed)
            CONFIG.write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")
            print(f"\n3. config/sources.json updated for {len(changed)} table name(s): {changed}")
        else:
            print("\n3. config/sources.json already has the right table names")

    need = ["hospital_ehr.patients", "lab_lis.lab_results", "pharmacy_rx.prescriptions"]
    if all(k in mapping for k in need):
        print("\n4. One query across SQL Server, MySQL and PostgreSQL")
        ok, rows, err = z.run(
            f"SELECT 'hospital patients (SQL Server)' AS item, COUNT(*) AS n FROM {mapping[need[0]]} "
            f"UNION ALL SELECT 'lab results (MySQL)', COUNT(*) FROM {mapping[need[1]]} "
            f"UNION ALL SELECT 'pharmacy prescriptions (PostgreSQL)', COUNT(*) FROM {mapping[need[2]]}", timeout=300)
        for row in rows if ok else []:
            print(f"   {row[0]:<38} {row[1]}")
        if not ok:
            print(f"   FAILED: {err}")

    if failed:
        sys.exit(f"\nNot finished: {', '.join(failed)}")
    print("\nDone. Next: .\\.venv\\Scripts\\python.exe .\\eval\\audit_sources.py   (must print ALL MATCH)")


if __name__ == "__main__":
    main()
