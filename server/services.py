"""ClinAssist backend services: everything the web app needs, built on the existing ClinAssist modules.

Meterless supervises everything: every request opens a Meterless run (recorded in the World Model through the
Meterless gateway), Scout decides, and every data fetch, script, Nemotron call, query or identity decision is
approved and recorded by the supervisor before and after it runs. If the gateway is down, nothing runs.
Secrets come from .env and are never returned.
"""
from __future__ import annotations

import csv
import json
import os
import re
import shutil
import subprocess
import threading
import time
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import requests

from clinassist import scripts as S
from clinassist.agent import Agent, ids_in
from clinassist.analysis import analyse, ingredient, load_rules
from clinassist.llm import LLMError, NightshiftLLM
from clinassist.patient_record import TABLES, CsvSource, ZetarisSource, load_record
from clinassist.sources import systems, zt
from clinassist.zetaris_client import ZetarisClient, ZetarisError
from meterless.scout import Scout, load_patients, load_registry, verify_contract
from meterless.supervisor import ActionDenied, GatewayRecorder, MeterlessUnavailable, Supervisor, SupervisedLLM, SupervisedSource

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "derived"
WORLD = DATA / "world"
IDENTITY = DATA / "identity"
EVAL = DATA / "eval"
RUNS = DATA / "runs"
FEEDBACK = DATA / "feedback.jsonl"
# Words that carry no request on their own: "ok", "hmm", "thanks" get a clarifying question, not an answer.
FILLER = {"okay", "hmm", "hmmm", "thanks", "thank", "you", "yes", "sure", "fine", "cool", "great", "alright", "right", "and",
          "the", "then", "what", "about", "more", "please", "tell", "that", "this", "his", "her", "him", "its"}
SYSTEM_TABLES = {
    "hospital_ehr": ["patients", "encounters", "conditions", "procedures", "observations", "allergies"],
    "lab_lis": ["lab_patients", "lab_results", "lab_reports"],
    "pharmacy_rx": ["pharmacy_patients", "prescriptions", "administrations"],
}
PATIENT_COLS = {
    "hospital_ehr": ("hospital_ehr.patients", "mrn", ["mrn", "given_name", "family_name", "birth_date", "sex", "city"]),
    "lab_lis": ("lab_lis.lab_patients", "lab_patient_id", ["lab_patient_id", "surname", "forenames", "dob", "gender"]),
    "pharmacy_rx": ("pharmacy_rx.pharmacy_patients", "pharm_patient_id", ["pharm_patient_id", "full_name", "birth_date", "sex"]),
}
SYSTEM_KEY = {"laboratory": "lab_lis", "pharmacy": "pharmacy_rx", "hospital": "hospital_ehr"}
SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]+$")
READ_ONLY_SQL = re.compile(r"^\s*(select|with)\b", re.I)
WRITE_WORDS = re.compile(r"\b(insert|update|delete|drop|create|alter|register|grant|revoke|truncate|merge|call|exec)\b", re.I)


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class RecordingZetaris:
    """Wraps the Zetaris client so every federated query is timed and shown in the UI (SQL, rows, seconds)."""

    def __init__(self, client: ZetarisClient):
        self.client = client
        self.log: list[dict] = []

    def rows(self, sql: str, columns: list[str], limit: int = 100_000) -> list[dict]:
        t0 = time.time()
        out = self.client.rows(sql, columns, limit)
        m = re.search(r"\bFROM\s+([A-Za-z0-9_.]+)", sql, re.I)
        table = m.group(1) if m else ""
        sysname = table.split(".")[0] if "." in table else ""
        self.log.append({"sql": sql if len(sql) < 600 else sql[:600] + " ...", "table": table, "system": sysname,
                         "engine": systems().get(sysname, {}).get("engine", ""), "rows": len(out),
                         "seconds": round(time.time() - t0, 2)})
        return out


class Services:
    def __init__(self):
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
        self.lock = threading.RLock()
        self.mode = os.environ.get("CLINASSIST_SOURCE", "zetaris")  # "zetaris" (live) or "csv" (offline copy)
        self.as_of = date.fromisoformat(os.environ.get("CLINASSIST_AS_OF", date.today().isoformat()))
        self.years = int(os.environ.get("CLINASSIST_YEARS", "3"))
        self.rules = load_rules()
        self.registry = load_registry()
        self.cache: dict[tuple[str, str], dict] = {}
        self._status_cache: tuple[float, dict] | None = None
        self._counts_cache: tuple[float, dict] | None = None
        self.scout_patients = load_patients(WORLD)
        self.gateway = GatewayRecorder()
        self._catalog_loaded = False

    # ------------------------------------------------------------------ connections
    def zetaris(self) -> ZetarisClient:
        return ZetarisClient.from_env()

    def llm(self) -> NightshiftLLM | None:
        try:
            return NightshiftLLM.from_env()
        except LLMError:
            return None

    def source(self):
        if self.mode == "csv":
            return CsvSource(DATA), None
        rec = RecordingZetaris(self.zetaris())
        return ZetarisSource(rec), rec

    # ------------------------------------------------------------------ Meterless
    def push_catalog(self) -> int:
        """Load the single-action script catalog into Meterless H-MEM (once per gateway start)."""
        out = self.gateway.post("/hmem/catalog", {"scripts": S.catalog()})
        self._catalog_loaded = True
        return out.get("loaded", 0)

    def memory(self, query: str) -> dict:
        if not self._catalog_loaded:
            self.push_catalog()
        out = self.gateway.post("/hmem/query", {"query": query, "topN": 40})
        if not out.get("scripts"):  # gateway restarted since: reload the catalog once
            self.push_catalog()
            out = self.gateway.post("/hmem/query", {"query": query, "topN": 40})
        return out

    def supervised(self, prompt: str, mrn: str, user: dict, ai: bool = False, log=None) -> Supervisor:
        """Open a Meterless run: the request is recorded in the World Model before anything else happens."""
        sup = Supervisor(self.gateway, log=log)
        sup.open(prompt, mrn, user, ai, self.mode)
        return sup

    def scope_of(self, mrn: str, include_pending: bool = False) -> set[str]:
        ident = self.identity_of(mrn)
        ids = {mrn} | {r["record_id"] for r in ident["linked_records"]}
        if include_pending:
            ids |= {r["record_id"] for r in ident["pending_review"]}
        return ids

    def meterless_runs(self) -> dict:
        return self.gateway.get("/world/runs")

    def meterless_run(self, run_id: str) -> dict:
        _safe(run_id)
        return self.gateway.get(f"/world/runs/{run_id}")

    def set_mode(self, mode: str) -> dict:
        if mode not in ("zetaris", "csv"):
            raise ValueError("mode must be zetaris or csv")
        with self.lock:
            self.mode = mode
        return {"mode": self.mode}

    # ------------------------------------------------------------------ status
    def status(self, fresh: bool = False) -> dict:
        if self._status_cache and not fresh and time.time() - self._status_cache[0] < 120:
            return self._status_cache[1]
        out: dict[str, Any] = {"checked_at": now_iso(), "mode": self.mode, "as_of": self.as_of.isoformat(),
                               "years": self.years, "rules_version": self.rules["version"]}
        # Zetaris: one federated query that touches all three engines
        t0 = time.time()
        try:
            out["meterless"] = {"ok": True, **self.gateway.get("/health"), "seconds": round(time.time() - t0, 2)}
        except Exception as e:  # noqa: BLE001
            out["meterless"] = {"ok": False, "error": _clean(str(e))}
        t0 = time.time()
        try:
            if not out["meterless"]["ok"]:
                raise MeterlessUnavailable("not checked: the Meterless gateway must be running before any data is read")
            z = self.zetaris()
            sql = (f"SELECT 'hospital_ehr' AS s, COUNT(*) AS n FROM {zt('hospital_ehr.patients')} "
                   f"UNION ALL SELECT 'lab_lis', COUNT(*) FROM {zt('lab_lis.lab_patients')} "
                   f"UNION ALL SELECT 'pharmacy_rx', COUNT(*) FROM {zt('pharmacy_rx.pharmacy_patients')}")
            sup = self.supervised("Health check: count patients in the three systems", "-", {"id": "clinassist", "role": "admin"})
            rows = sup.act("admin.query", "zetaris:patients x3", {"tables": 3}, lambda: z.rows(sql, ["s", "n"]),
                           actor="health-check", executor="zetaris", summarize=lambda r: f"{len(r)} rows")
            sup.close("ok")
            out["zetaris"] = {"ok": True, "seconds": round(time.time() - t0, 2),
                              "patients": {r["s"]: int(float(r["n"])) for r in rows}}
        except Exception as e:  # noqa: BLE001 - shown to the user as a status, never raised
            out["zetaris"] = {"ok": False, "seconds": round(time.time() - t0, 2), "error": _clean(str(e))}
        # Nightshift: list models (no tokens spent)
        t0 = time.time()
        try:
            base = os.environ.get("METERLESS_BASE_URL", "").rstrip("/")
            tok = os.environ.get("METERLESS_RUNTIME_TOKEN", "")
            if not base or not tok or tok.startswith("copy-"):
                raise RuntimeError("METERLESS_BASE_URL / METERLESS_RUNTIME_TOKEN not set in .env")
            r = requests.get(base + "/models", timeout=8, headers={
                "Authorization": "Bearer " + tok, "meterless-app": os.environ.get("METERLESS_APP", "clinassist-ai"),
                "meterless-scope": "user"})
            r.raise_for_status()
            ids = [m.get("id", "") for m in r.json().get("data", [])]
            out["nightshift"] = {"ok": True, "seconds": round(time.time() - t0, 2), "models": ids,
                                 "fast": os.environ.get("METERLESS_MODEL", "meterless/fast"),
                                 "deep": os.environ.get("METERLESS_MODEL_DEEP", "meterless/deep")}
        except Exception as e:  # noqa: BLE001
            out["nightshift"] = {"ok": False, "seconds": round(time.time() - t0, 2), "error": _clean(str(e))}
        # World Model
        try:
            w = self.world_summary()
            out["world_model"] = {"ok": True, **w}
        except Exception as e:  # noqa: BLE001
            out["world_model"] = {"ok": False, "error": _clean(str(e))}
        key = os.environ.get("SCOUT_SIGNING_KEY", "")
        out["scout"] = {"ok": True, "registry_version": self.registry["version"],
                        "intents": list(self.registry["intents"]), "lanes": self.registry["lanes"],
                        "signing_key": "persistent" if key and not key.startswith("change-me") else "temporary"}
        out["systems"] = systems()
        self._status_cache = (time.time(), out)
        return out

    # ------------------------------------------------------------------ sources
    def source_counts(self, fresh: bool = False) -> dict:
        """Rows and distinct keys per table, through Zetaris, compared with the source CSVs (the audit)."""
        if self._counts_cache and not fresh and time.time() - self._counts_cache[0] < 300:
            return self._counts_cache[1]
        csv_counts = {}
        for kind_rel in [("hospital_ehr", "hospital"), ("lab_lis", "laboratory"), ("pharmacy_rx", "pharmacy")]:
            for t in SYSTEM_TABLES[kind_rel[0]]:
                f = DATA / kind_rel[1] / f"{t}.csv"
                csv_counts[f"{kind_rel[0]}.{t}"] = _csv_rows(f) if f.exists() else None
        out = {"systems": systems(), "tables": [], "zetaris_ok": False}
        try:
            z = self.zetaris()
            parts = [f"SELECT '{s}.{t}' AS t, COUNT(*) AS n FROM {zt(s + '.' + t)}" for s, ts in SYSTEM_TABLES.items() for t in ts]
            t0 = time.time()
            sup = self.supervised("Count the rows of every source table (audit)", "-", {"id": "ui", "role": "admin"})
            raw = sup.act("admin.query", "zetaris:12 tables", {"tables": len(parts)}, lambda: z.rows(" UNION ALL ".join(parts), ["t", "n"]),
                          actor="ui", executor="zetaris", summarize=lambda r: f"{len(r)} rows")
            sup.close("ok")
            out["meterless_run"] = sup.run_id
            rows = {r["t"]: int(float(r["n"])) for r in raw}
            out["zetaris_ok"], out["seconds"] = True, round(time.time() - t0, 2)
            out["sql"] = " UNION ALL ".join(parts[:3]) + " UNION ALL ..."
        except Exception as e:  # noqa: BLE001
            rows, out["error"] = {}, _clean(str(e))
        for s, ts in SYSTEM_TABLES.items():
            for t in ts:
                name = f"{s}.{t}"
                out["tables"].append({"system": s, "table": t, "zetaris_name": zt(name), "rows_zetaris": rows.get(name),
                                      "rows_csv": csv_counts.get(name),
                                      "match": rows.get(name) is not None and rows.get(name) == csv_counts.get(name)})
        self._counts_cache = (time.time(), out)
        return out

    def run_query(self, sql: str) -> dict:
        """Read-only federated SQL for the demo console (SELECT/WITH only, one statement)."""
        sql = sql.strip().rstrip(";").strip()
        if not READ_ONLY_SQL.match(sql) or ";" in sql or WRITE_WORDS.search(sql):
            raise ValueError("Only a single read-only SELECT (or WITH ... SELECT) is allowed here.")
        cols = _select_aliases(sql)
        z = self.zetaris()
        t0 = time.time()
        sup = self.supervised("Federated SQL console query", "-", {"id": "ui", "role": "admin"})
        r = sup.act("admin.query", "zetaris:console", {"sql": sql[:500]},
                    lambda: requests.post(z.url, timeout=z.timeout, json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": 200},
                                          headers={"Authorization": "Bearer " + z._key, "X-Org-ID": z.org_id, "X-Request-ID": str(uuid.uuid4())}),
                    actor="ui", executor="zetaris", summarize=lambda resp: f"HTTP {resp.status_code}")
        sup.close("ok" if r.status_code < 400 else "error")
        if r.status_code >= 400:
            raise ZetarisError(f"Zetaris HTTP {r.status_code}: {_clean(r.text[:300])}")
        body = r.json()
        data = body.get("data") or []
        meta = body.get("columns") or body.get("schema") or body.get("metadata") or None
        if isinstance(meta, list) and meta and all(isinstance(c, (str, dict)) for c in meta):
            cols = [c if isinstance(c, str) else (c.get("name") or c.get("label") or "?") for c in meta]
        width = max((len(x) for x in data), default=len(cols))
        if len(cols) != width:
            cols = [f"col{i + 1}" for i in range(width)]
        return {"columns": cols, "rows": data[:200], "row_count": len(data), "seconds": round(time.time() - t0, 2), "meterless_run": sup.run_id}

    def patient_in_systems(self, mrn: str) -> dict:
        """The same person as each system stores them: shows why matching is needed."""
        _safe(mrn)
        ident = self.identity_of(mrn)
        wanted = {"hospital_ehr": [mrn]}
        for group, label in ((ident["linked_records"], "linked"), (ident["pending_review"], "pending-review")):
            for r in group:
                wanted.setdefault(SYSTEM_KEY[r["system"]], []).append(r["record_id"])
        status_of = {r["record_id"]: r.get("status", "") for r in ident["linked_records"] + ident["pending_review"]}
        out, queries = [], []
        rz = RecordingZetaris(self.zetaris()) if self.mode == "zetaris" else None
        user = {"id": "ui", "role": "clinician"}
        sup = self.supervised("Show how each system stores this patient", mrn, user)
        decision = Scout(self.registry, self.scout_patients).decide("Show his linked source records and identity matches", mrn, user).to_dict()
        sup.decided(decision, self.scope_of(mrn, include_pending=True))
        for s, ids in wanted.items():
            table, key, cols = PATIENT_COLS[s]
            for i in ids:
                _safe(i)
            def fetch(s=s, ids=ids, table=table, key=key, cols=cols):
                if rz:
                    sel = ", ".join(f"date_format({c}, 'yyyy-MM-dd') AS {c}" if (s == "hospital_ehr" and c == "birth_date") else c for c in cols)
                    return rz.rows(f"SELECT {sel} FROM {zt(table)} WHERE {key} IN ({', '.join(repr(i) for i in ids)})", cols)
                rel = {"hospital_ehr": "hospital/patients.csv", "lab_lis": "laboratory/lab_patients.csv",
                       "pharmacy_rx": "pharmacy/pharmacy_patients.csv"}[s]
                return [{c: r.get(c, "") for c in cols} for r in csv.DictReader(open(DATA / rel, encoding="utf-8")) if r[key] in ids]
            rows = sup.act("data.fetch", f"{self.mode}:{table}", {"keys": ids}, fetch, actor="ui", executor=self.mode,
                           summarize=lambda r: f"{len(r)} row(s)")
            for row in rows:
                out.append({"system": s, "engine": systems()[s]["engine"], "record_id": row[key],
                            "status": "master" if s == "hospital_ehr" else status_of.get(row[key], ""), "row": row})
        if rz:
            queries = rz.log
        sup.close("ok")
        return {"mrn": mrn, "label": ident["label"], "records": out, "queries": queries, "mode": self.mode, "meterless_run": sup.run_id}

    # ------------------------------------------------------------------ identity / World Model
    def identity_view(self) -> dict:
        return json.loads((WORLD / "patient_identity.json").read_text(encoding="utf-8"))

    def identity_of(self, mrn: str) -> dict:
        for p in self.identity_view()["patients"]:
            if p["mrn"] == mrn:
                return p
        raise KeyError(f"{mrn} is not in the World Model identity view")

    def world_store(self) -> dict:
        f = WORLD / ".world" / "clinassist.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {"events": [], "audit": [], "mergeQueue": []}

    def world_summary(self) -> dict:
        ident = self.identity_view()["patients"]
        st = self.world_store()
        return {"patients": len(ident), "linked_records": sum(len(p["linked_records"]) for p in ident),
                "pending_review": sum(len(p["pending_review"]) for p in ident),
                "events": len(st["events"]), "audit_entries": len(st["audit"]),
                "built_from": self.identity_view().get("built_from")}

    def identity(self) -> dict:
        report = _json(IDENTITY / "matching_report.json") or {}
        links = (_json(IDENTITY / "identity_links.json") or {}).get("links", [])
        decisions = _json(IDENTITY / "review_decisions.json") or []
        decided = {(d["system"], d["record_id"]): d for d in decisions}
        queue = []
        for l in links:
            if l["decision"] != "review":
                continue
            d = decided.get((l["system"], l["record_id"]))
            queue.append({**l, "reviewed": bool(d), "review": d})
        return {"report": report, "queue": queue, "decisions": decisions, "world": self.world_summary(),
                "auto_links": sum(1 for l in links if l["decision"] == "auto-link"),
                "total_records": len(links)}

    def review(self, system: str, record_id: str, action: str, by: str, note: str = "") -> dict:
        """Record a reviewer's decision in the World Model (meterless/world/review.ts), then rebuild the identity view."""
        if action not in ("approve", "reject"):
            raise ValueError("action must be approve or reject")
        if system not in ("laboratory", "pharmacy"):
            raise ValueError("system must be laboratory or pharmacy")
        _safe(record_id)
        by = re.sub(r"[^A-Za-z0-9 .,'-]", "", by or "").strip()[:60]
        note = re.sub(r"[\r\n\"]", " ", note or "").strip()[:200]
        if not by:
            raise ValueError("a reviewer name is required: every decision needs a named person")
        npx = shutil.which("npx.cmd") or shutil.which("npx")
        if not npx:
            raise RuntimeError("Node (npx) was not found on this computer")
        link = next((l for l in (_json(IDENTITY / "identity_links.json") or {}).get("links", [])
                     if l["system"] == system and l["record_id"] == record_id), None)
        if not link or not link.get("mrn"):
            raise KeyError(f"{system} {record_id} is not a pending match")
        sup = self.supervised(f"Identity decision: {action} {system} {record_id} -> {link['mrn']}", link["mrn"],
                              {"id": by, "role": "records_staff"})

        def node(cmd):
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
            if r.returncode != 0:
                raise RuntimeError((r.stderr or r.stdout).strip()[:400])
            return r

        cmd = [npx, "tsx", "meterless/world/review.ts", action, system, record_id, "--by", by] + (["--note", note] if note else [])
        r1 = sup.act("identity.decision", f"{system}:{record_id}", {"action": action, "mrn": link["mrn"], "by": by}, lambda: node(cmd),
                     actor=by, executor="meterless-world-model", summarize=lambda r: r.stdout.strip()[:200])
        r2 = sup.act("identity.decision", "rebuild identity view", {}, lambda: node([npx, "tsx", "meterless/world/build_world.ts"]),
                     actor=by, executor="meterless-world-model", summarize=lambda r: r.stdout.strip().splitlines()[0][:200])
        sup.close("ok")
        with self.lock:
            self.cache.clear()
            self.scout_patients = load_patients(WORLD)
            self._status_cache = None
        return {"recorded": r1.stdout.strip(), "world": r2.stdout.strip(), "summary": self.world_summary(), "meterless_run": sup.run_id}

    def rematch(self, by: str) -> dict:
        """Supervised batch job: re-run the matcher over all patients through Zetaris, then rebuild the World Model view."""
        by = re.sub(r"[^A-Za-z0-9 .,'-]", "", by or "").strip()[:60]
        if not by:
            raise ValueError("a named person must start the matching job")
        npx = shutil.which("npx.cmd") or shutil.which("npx")
        sup = self.supervised("Batch job: match lab and pharmacy patients to hospital patients", "-", {"id": by, "role": "records_staff"})

        def proc(cmd):
            r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=600)
            if r.returncode != 0:
                raise RuntimeError((r.stderr or r.stdout).strip()[-400:])
            return r

        import sys as _sys
        m = sup.act("batch.matching", "run_matching.py", {"source": self.mode},
                    lambda: proc([_sys.executable, "run_matching.py", "--source", self.mode]), actor=by, executor="python",
                    summarize=lambda r: r.stdout.strip().splitlines()[-1][:200] if r.stdout.strip() else "done")
        w = sup.act("batch.matching", "rebuild identity view", {}, lambda: proc([npx, "tsx", "meterless/world/build_world.ts"]),
                    actor=by, executor="meterless-world-model", summarize=lambda r: r.stdout.strip().splitlines()[0][:200])
        sup.close("ok")
        with self.lock:
            self.cache.clear()
            self.scout_patients = load_patients(WORLD)
        return {"matching": m.stdout.strip()[-1500:], "world": w.stdout.strip(), "summary": self.world_summary(), "meterless_run": sup.run_id}

    def provenance(self, mrn: str) -> dict:
        """Every World Model event about this patient and the records linked (or proposed) to them."""
        ident = self.identity_of(mrn)
        ids = {ident["entity_id"]}
        for r in ident["linked_records"] + ident["pending_review"]:
            ids.add(("lab_patient:lab_lis:" if r["system"] == "laboratory" else "pharmacy_patient:pharmacy_rx:") + r["record_id"])
        events = []
        for e in self.world_store()["events"]:
            p = e["payload"]
            touched = {p.get("id"), p.get("from"), p.get("to"), p.get("about")} & ids
            if touched:
                events.append({"seq": e["seq"], "at": e["at"], "kind": e["kind"], "type": p.get("type") or p.get("predicate"),
                               "from": p.get("from") or p.get("about") or p.get("id"), "to": p.get("to"),
                               "value": p.get("value"), "confidence": p.get("confidence"), "attrs": p.get("attrs"),
                               "source": p.get("source")})
        return {"mrn": mrn, "entity_id": ident["entity_id"], "events": events}

    # ------------------------------------------------------------------ patients
    def patients(self) -> list[dict]:
        out = []
        for p in self.identity_view()["patients"]:
            c = self.cache.get((self.mode, p["mrn"]))
            sev = None
            if c:
                f = c["result"]["findings"]
                sev = {s: sum(1 for x in f if x["severity"] == s) for s in ("high", "review", "info")}
            out.append({"mrn": p["mrn"], "label": p["label"], "linked": len(p["linked_records"]),
                        "pending": len(p["pending_review"]), "systems": sorted({r["system"] for r in p["linked_records"]}),
                        "loaded": bool(c), "findings": sev})
        return out

    def load(self, mrn: str, fresh: bool = False) -> dict:
        _safe(mrn)
        key = (self.mode, mrn)
        if not fresh and key in self.cache:
            return self.cache[key]
        src, rz = self.source()
        user = {"id": "ui", "role": "clinician"}
        sup = self.supervised("Open the patient review", mrn, user)
        decision = Scout(self.registry, self.scout_patients).decide("Prepare a pre-visit summary", mrn, user).to_dict()
        sup.decided(decision, self.scope_of(mrn))
        source = SupervisedSource(src, sup, self.mode)
        t0 = time.time()
        rec = sup.act("view", "load patient record", {"mrn": mrn}, lambda: load_record(source, WORLD, mrn, self.as_of, self.years),
                      actor="ui", executor="python", summarize=lambda r: f"{len(r.items)} items")
        t1 = time.time()
        result = sup.act("view", "patient review analysis", {"checks": "all"}, lambda: analyse(rec, self.rules), actor="ui",
                         executor="python", summarize=lambda r: f"{len(r['findings'])} findings")
        sup.close("ok")
        entry = {"rec": rec, "result": result, "loaded_at": now_iso(), "mode": self.mode,
                 "load_seconds": round(t1 - t0, 2), "analysis_seconds": round(time.time() - t1, 3),
                 "queries": rz.log if rz else [], "meterless_run": sup.run_id,
                 "supervised": [dict(a) for a in sup.actions]}
        with self.lock:
            self.cache[key] = entry
        return entry

    def patient(self, mrn: str, fresh: bool = False) -> dict:
        e = self.load(mrn, fresh)
        r = e["result"]
        used = ids_in({k: r[k] for k in ("findings", "trends", "timeline", "medications", "allergies", "active_conditions")})
        evidence = {i.eid: {"system": i.system, "engine": systems()[i.system]["engine"], "table": TABLES[i.kind][0].split(".")[1],
                            "record_id": i.record_id, "kind": i.kind, "when": i.when.isoformat() if i.when else None,
                            "row": i.row} for i in e["rec"].items if i.eid in used}
        return {**r, "evidence": evidence,
                "load": {"mode": e["mode"], "loaded_at": e["loaded_at"], "seconds": e["load_seconds"],
                         "analysis_seconds": e["analysis_seconds"], "queries": e["queries"],
                         "items": len(e["rec"].items), "meterless_run": e.get("meterless_run"),
                         "supervised": e.get("supervised", [])}}

    def evidence(self, mrn: str, eid: str) -> dict:
        e = self.load(mrn)
        for i in e["rec"].items:
            if i.eid == eid:
                return {"eid": eid, "system": i.system, "engine": systems()[i.system]["engine"],
                        "table": TABLES[i.kind][0].split(".")[1], "record_id": i.record_id, "kind": i.kind,
                        "when": i.when.isoformat() if i.when else None, "row": i.row}
        raise KeyError(f"{eid} is not in this patient's record")

    # ------------------------------------------------------------------ Scout + agent
    def scout_decide(self, prompt: str, mrn: str, user: dict, use_ai: bool = True, sup: Supervisor | None = None) -> dict:
        """Scout's decision. With AI on, Nemotron interprets only the safe requests the rules could not place
        (through the supervisor, so that call is recorded too)."""
        _safe(mrn)
        own = sup is None
        if own:
            sup = self.supervised(prompt, mrn, user, use_ai)
        llm = self.llm() if use_ai else None
        scout = Scout(self.registry, self.scout_patients, llm=SupervisedLLM(llm, sup, "interpreter") if llm else None)
        d = scout.decide(prompt, mrn, user)
        out = d.to_dict()
        if d.contract:
            ok, why = verify_contract(d.contract, mrn)
            out["contract_check"] = {"ok": ok, "reason": why}
        if own:
            sup.decided(out, self.scope_of(mrn))
            sup.close("decision-only")
        out["meterless_run"] = sup.run_id
        return out

    def run_agent(self, prompt: str, mrn: str, user: dict, use_ai: bool, emit, history: list[dict] | None = None) -> dict:
        """One request, fully supervised by Meterless: record -> Scout -> Nemotron as the boss -> enforced checks.
        Every step is sent to `emit` as it happens; the run is recorded in the World Model and saved to data/derived/runs."""
        events: list[dict] = []
        t_start = time.time()

        def send(kind: str, **data):
            ev = {"type": kind, "t": round(time.time() - t_start, 2), **data}
            events.append(ev)
            emit(ev)

        log = lambda entry: send("trace", entry=_jsonable(entry))  # noqa: E731
        try:
            sup = self.supervised(prompt, mrn, user, use_ai, log=log)
        except MeterlessUnavailable as e:
            res = {"status": "error", "summary": f"Not run: {e}. Nothing runs without Meterless supervising it.",
                   "verdict": {}, "plan": [], "rounds": 0}
            send("result", result=res)
            return res
        run_id = sup.run_id
        send("start", run_id=run_id, prompt=prompt, mrn=mrn, user=user, ai=use_ai, mode=self.mode)
        history = [h for h in (history or []) if isinstance(h, dict) and str(h.get("q", "")).strip()][-3:]
        decision = self.scout_decide(prompt, mrn, user, use_ai, sup=sup)
        content = [w for w in re.findall(r"[a-z]{3,}", prompt.lower()) if w not in FILLER]
        if decision["status"] == "clarify" and history and content:
            # A short follow-up ("and his potassium?") may only make sense with the previous question: Scout tries once more
            # with that context. Guards still apply in full; an unsafe follow-up is still blocked.
            prev = str(history[-1]["q"])[:300]
            retry = self.scout_decide(f"{prompt} (follow-up to the previous question: {prev})", mrn, user, use_ai, sup=sup)
            if retry["status"] != "clarify":
                retry["followup_of"] = prev
                decision = retry
        sup.decided(decision, self.scope_of(mrn))
        send("scout", decision=decision)
        if decision["status"] != "approved":
            res = {"status": decision["status"], "summary": decision["message"], "verdict": {}, "plan": [], "rounds": 0}
            sup.close(res["status"])
            send("result", result=res)
            self._save_run(run_id, prompt, mrn, user, use_ai, events, res)
            return res
        src, rz = self.source()
        ctx = S.Ctx(mrn, self.as_of, self.years, SupervisedSource(src, sup, self.mode), WORLD, self.rules)
        llm = self.llm() if use_ai else None
        if use_ai and not llm:
            send("stage", stage="ai-missing", message="Nightshift is not configured in .env: the contract's default plan and the verified rule-based writer are used")
        agent = Agent(llm, supervisor=sup, log=log, memory=self.memory if llm else None)
        task = prompt
        if history:  # earlier questions give context only; they are never evidence
            task += "\n\nEarlier in this conversation (context only, not evidence): " + " | ".join(
                f"{str(h['q'])[:200]} -> {h.get('status', '?')}" for h in history)
        try:
            r = agent.run(task, ctx, contract=decision["contract"], require_contract=True)
            res = {"status": r.status, "summary": r.summary, "verdict": _jsonable(r.verdict), "plan": r.plan, "rounds": r.rounds,
                   "scripts": len(r.plan), "meterless_actions": len(sup.actions), "queries": rz.log if rz else [],
                   "sources": self.cited_sources(ctx.gathered, r.summary)}
        except MeterlessUnavailable as e:
            res = {"status": "error", "summary": f"Stopped: {e}", "verdict": {}, "plan": [], "rounds": 0}
        try:
            sup.close(res["status"], res.get("rounds", 0))
            if llm and res["status"] in ("verified-ai", "escalated"):
                self.gateway.post("/hmem/lessons", {
                    "run_id": run_id, "confidence": 0.7 if res["status"] == "verified-ai" else 0.5,
                    "tags": [str((decision.get("intent") or {}).get("primary")), res["status"]],
                    "content": f"For a '{(decision.get('intent') or {}).get('primary')}' request the boss ran "
                               f"{', '.join(dict.fromkeys(c['tool'] for c in res['plan']))}; result {res['status']} after "
                               f"{res['rounds']} round(s)."})
        except MeterlessUnavailable:
            pass
        send("result", result=res)
        self._save_run(run_id, prompt, mrn, user, use_ai, events, res)
        return res

    def source_info(self, key: str | None) -> dict | None:
        """A rule's public source (title and link) from config/clinical_rules.json; url is None for internal rules."""
        s = (self.rules.get("sources") or {}).get(key or "")
        return {"key": key, "title": s.get("title"), "url": s.get("url")} if s else None

    def cited_sources(self, gathered: dict, summary: str) -> list[dict]:
        """Guideline sources behind the findings whose evidence ids the answer cites (all gathered findings if it cites none)."""
        found: list[dict] = []

        def walk(v):
            if isinstance(v, dict):
                if v.get("source") and isinstance(v.get("evidence"), list):
                    found.append(v)
                for x in v.values():
                    walk(x)
            elif isinstance(v, list):
                for x in v:
                    walk(x)
        walk(gathered)
        cited = [f for f in found if any(re.search(re.escape(e) + r"(?![\w-])", summary or "") for e in f["evidence"])] or found
        out, seen = [], set()
        for f in cited:
            info = self.source_info(f["source"])
            if info and info["key"] not in seen:
                seen.add(info["key"])
                out.append(info)
        return out

    def _save_run(self, run_id, prompt, mrn, user, use_ai, events, res):
        RUNS.mkdir(parents=True, exist_ok=True)
        (RUNS / f"{run_id}.json").write_text(json.dumps(
            {"run_id": run_id, "at": now_iso(), "prompt": prompt, "mrn": mrn, "user": user, "ai": use_ai, "mode": self.mode,
             "status": res["status"], "events": events, "result": res}, default=str, indent=1), encoding="utf-8")

    # ------------------------------------------------------------------ feedback: what ClinAssist learns from people
    def feedback(self, run_id: str, rating: str, comment: str, user: dict) -> dict:
        """A person rates an answer. Recorded as a supervised action in the Meterless World Model, saved as a lesson in
        Meterless H-MEM (later answers to similar questions get it as guidance), and kept in data/derived/feedback.jsonl.
        Lessons guide focus and style only: every answer is still fact-checked against the source records."""
        _safe(run_id)
        if rating not in ("up", "down"):
            raise ValueError("rating must be 'up' or 'down'")
        comment = re.sub(r"\s+", " ", comment or "").strip()[:500]
        run = self.run(run_id)
        intent = next((((e.get("decision") or {}).get("intent") or {}).get("primary")
                       for e in run.get("events", []) if e.get("type") == "scout"), None) or "unknown"
        if rating == "down":
            lesson = (f"Clinician feedback (not helpful) on a '{intent}' answer to \"{run['prompt'][:160]}\""
                      + (f": {comment.rstrip('.')}" if comment else "") + ". Adjust the answer accordingly next time.")
        else:
            lesson = (f"Clinician feedback (helpful) on a '{intent}' answer to \"{run['prompt'][:160]}\""
                      + (f": {comment.rstrip('.')}" if comment else "") + ". Keep this approach.")
        entry = {"at": now_iso(), "run_id": run_id, "rating": rating, "comment": comment, "intent": intent,
                 "prompt": run["prompt"][:300], "status": run.get("status"), "by": user["id"], "role": user["role"],
                 "lesson": lesson}
        sup = self.supervised(f"Feedback on run {run_id}", run.get("mrn") or "-", user)

        def record():
            out = self.gateway.post("/hmem/lessons", {"run_id": run_id, "content": lesson, "confidence": 0.9 if rating == "down" else 0.8,
                                                      "tags": [intent, "feedback", rating]})
            FEEDBACK.parent.mkdir(parents=True, exist_ok=True)
            with FEEDBACK.open("a", encoding="utf-8") as f:
                f.write(json.dumps({**entry, "lesson_id": out.get("id")}) + "\n")
            return out

        out = sup.act("feedback.record", run_id, {"rating": rating, "intent": intent, "comment_chars": len(comment)}, record,
                      actor=f"person:{user['id']}", executor="meterless-hmem", summarize=lambda o: f"lesson {o.get('id')} saved")
        sup.close("feedback-recorded")
        return {"ok": True, "lesson": lesson, "lesson_id": out.get("id"), "meterless_run": sup.run_id}

    # ------------------------------------------------------------------ medicine review (prescription history, safety flags, FDA labels)
    MED_RULES = ("renal-", "rx-", "allergy-", "acei-potassium", "low-bp-on-treatment")

    def drug_labels(self) -> dict:
        """FDA label sections saved once by reference/fetch_drug_labels.py (offline afterwards). Empty if not fetched yet."""
        f = ROOT / "reference" / "drug_labels.json"
        mtime = f.stat().st_mtime if f.exists() else None
        if getattr(self, "_labels_mtime", "x") != mtime:
            self._labels = json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}
            self._labels_mtime = mtime
        return self._labels

    def prescriptions(self, mrn: str, fresh: bool = False) -> dict:
        """Every medicine the patient was prescribed (full pharmacy history), our own safety flags on them, and the FDA
        label reference for each. Data and flags come from the supervised patient load; the label lookup is recorded
        by Meterless as its own action. Reference information, not advice."""
        entry = self.load(mrn, fresh)
        rec, result = entry["rec"], entry["result"]
        admins: dict[str, list] = {}
        for a in rec.of("administration"):
            admins.setdefault(a.row["medication"], []).append(a)
        by_med: dict[str, list] = {}
        for i in rec.of("prescription"):
            by_med.setdefault(i.row["medication"], []).append(i)
        flags = [f for f in result["findings"] if f["rule"].startswith(self.MED_RULES)]
        meds = []
        for med, items in by_med.items():
            items.sort(key=lambda i: i.when or datetime.min)
            eids = {i.eid for i in items}
            active = any(i.row.get("status") == "active" for i in items)
            last = items[-1]
            ad = sorted(admins.get(med, []), key=lambda a: a.when or datetime.min)
            meds.append({
                "medication": med, "ingredient": ingredient(med), "rxnorm_code": last.row.get("rxnorm_code"),
                "status": "active" if active else "past",
                "first_prescribed": items[0].when.date().isoformat() if items[0].when else None,
                "last_prescribed": last.when.date().isoformat() if last.when else None,
                "prescriptions": len(items),
                "prescribers": sorted({i.row.get("prescriber") for i in items if i.row.get("prescriber")})[:4],
                "dosage_text": next((i.row.get("dosage_text") for i in reversed(items) if i.row.get("dosage_text")), ""),
                "recent": [{"date": i.when.date().isoformat() if i.when else None, "status": i.row.get("status"),
                            "prescriber": i.row.get("prescriber"), "eid": i.eid} for i in reversed(items[-6:])],
                "administrations": len(ad), "last_administered": ad[-1].when.date().isoformat() if ad and ad[-1].when else None,
                "evidence": [i.eid for i in reversed(items[-3:])],
                "flags": [{"rule": f["rule"], "level": f["severity"], "title": f["title"], "detail": f["detail"], "source": f.get("source"),
                           "source_info": self.source_info(f.get("source")), "evidence": f["evidence"]}
                          for f in flags if eids & set(f["evidence"])],
            })
        meds.sort(key=lambda m: (m["status"] != "active", -(len(m["flags"])), m["medication"].lower()))
        ref = self.drug_labels()
        user = {"id": "ui", "role": "clinician"}
        sup = self.supervised("Open the medicine review", mrn, user)
        decision = Scout(self.registry, self.scout_patients).decide("Review his medications for safety issues", mrn, user).to_dict()
        sup.decided(decision, self.scope_of(mrn))

        def attach():
            found = 0
            for m in meds:
                lab = (ref.get("labels") or {}).get(str(m["rxnorm_code"]))
                m["label"] = lab
                found += bool(lab)
            return found

        found = sup.act("view", "FDA drug label reference", {"medicines": len(meds)}, attach, actor="ui", executor="python",
                        summarize=lambda n: f"{n} of {len(meds)} medicines have a saved FDA label")
        sup.close("ok")
        return {"mrn": mrn, "patient": rec.label, "as_of": self.as_of.isoformat(), "medications": meds,
                "counts": {"medicines": len(meds), "active": sum(m["status"] == "active" for m in meds),
                           "flagged": sum(bool(m["flags"]) for m in meds), "with_label": found},
                "labels": {"available": bool(ref), "fetched_at": ref.get("fetched_at"), "source": ref.get("source"), "note": ref.get("_note")},
                "allergies": result.get("allergies", []), "meterless_run": sup.run_id, "data_run": entry.get("meterless_run")}

    def scripts(self) -> dict:
        """The catalog Nemotron chooses from: name, what it does, what it returns (no data involved)."""
        S.load_all()
        return {"scripts": [{k: c.get(k) for k in ("name", "does", "returns", "kind", "args")} for c in S.catalog()]}

    def feedback_list(self, limit: int = 50) -> dict:
        items = []
        if FEEDBACK.exists():
            for line in FEEDBACK.read_text(encoding="utf-8").splitlines():
                try:
                    items.append(json.loads(line))
                except ValueError:
                    continue
        items.reverse()
        return {"count": len(items), "up": sum(i.get("rating") == "up" for i in items),
                "down": sum(i.get("rating") == "down" for i in items), "items": items[:limit]}

    def runs(self) -> list[dict]:
        out = []
        if RUNS.exists():
            for f in sorted(RUNS.glob("*.json"), reverse=True)[:100]:
                try:
                    d = json.loads(f.read_text(encoding="utf-8"))
                except ValueError:
                    continue
                out.append({k: d.get(k) for k in ("run_id", "at", "prompt", "mrn", "user", "ai", "mode", "status")}
                           | {"steps": len(d.get("events", []))})
        return out

    def run(self, run_id: str) -> dict:
        _safe(run_id)
        f = RUNS / f"{run_id}.json"
        if not f.exists():
            raise KeyError(run_id)
        return json.loads(f.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ evaluation results
    def evaluation(self) -> dict:
        ver = {}
        for f in sorted(EVAL.glob("verifier_results_seed*.json")):
            d = _json(f) or {}
            ver[f.stem.replace("verifier_results_", "")] = d
        summ = _json(EVAL / "matching_summary.json") or {}
        stress = []
        for sc in summ.get("scenarios", []):
            comp, sweep = summ.get("comparison", {}).get(sc, {}), summ.get("sweep_full", {}).get(sc, {})
            row = {"scenario": sc}
            for label, src in (("exact", comp.get("exact surname+DOB")), ("world_model", comp.get("World Model name resolver")),
                               ("clinassist", sweep.get("11.5"))):
                if src:
                    row[label] = {k: src.get(k) for k in ("records", "wrong_merges", "review", "recall_after_review", "auto")}
            stress.append(row)
        seeds = [v for v in ver.values() if v.get("designed_errors")]
        headline = {
            "verifier_detection": [v["designed_errors"]["detection_rate"] for v in seeds],
            "verifier_false_alarms": [f'{v["clean"]["false_alarms"]}/{v["clean"]["n"]}' for v in seeds],
            "stress": stress, "datasets": summ.get("datasets", []),
        }
        return {"headline": headline, "matching_main": _json(IDENTITY / "matching_report.json"),
                "scout": _json(EVAL / "scout_results.json"), "verifier": ver, "llm_bench": _json(EVAL / "llm_bench.json"),
                "model_probe": _json(EVAL / "model_probe.json")}


# ---------------------------------------------------------------------- helpers
def _json(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _csv_rows(p: Path) -> int:
    with open(p, encoding="utf-8", newline="") as fh:
        return sum(1 for _ in csv.DictReader(fh))


def _safe(s: str) -> str:
    if not s or not SAFE_ID.match(s):
        raise ValueError(f"invalid id: {s!r}")
    return s


def _clean(s: str) -> str:
    """Error text for the UI: no bearer tokens or account identifiers."""
    s = re.sub(r"(Bearer\s+)[A-Za-z0-9._-]+", r"\1***", s)
    s = re.sub(r"(account\s+')[^']+(')", r"\1***\2", s)
    return s[:400]


def _jsonable(x):
    return json.loads(json.dumps(x, default=str))


def _select_aliases(sql: str) -> list[str]:
    """Best-effort column names from the SELECT list (used only when Zetaris does not return them)."""
    m = re.match(r"\s*select\s+(distinct\s+)?(.*?)\s+from\s", sql, re.I | re.S)
    if not m:
        return []
    parts, depth, cur = [], 0, ""
    for ch in m.group(2):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    names = []
    for p in parts:
        p = p.strip()
        a = re.search(r"\bas\s+([A-Za-z_][A-Za-z0-9_]*)\s*$", p, re.I)
        names.append(a.group(1) if a else p.split(".")[-1][:40])
    return names
