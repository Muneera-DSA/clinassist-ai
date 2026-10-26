"""ClinAssist backend services: everything the web app needs, built on the existing ClinAssist modules.

Nothing here re-implements analysis, matching, Scout or the agent: it loads patients through Zetaris
(or the offline CSV copy, clearly labelled), runs the same code the command-line tools run, and keeps
small in-memory caches so the demo is responsive. Secrets come from .env and are never returned.
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

from clinassist.agent import Agent, ids_in
from clinassist.analysis import analyse, load_rules
from clinassist.llm import LLMError, NightshiftLLM
from clinassist.patient_record import TABLES, CsvSource, ZetarisSource, load_record
from clinassist.scout import Scout, load_patients, load_registry, verify_contract
from clinassist.sources import systems, zt
from clinassist.zetaris_client import ZetarisClient, ZetarisError

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "derived"
WORLD = DATA / "world"
IDENTITY = DATA / "identity"
EVAL = DATA / "eval"
RUNS = DATA / "runs"
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
        self.scout = Scout(self.registry, load_patients(WORLD))

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

    def set_mode(self, mode: str) -> dict:
        if mode not in ("zetaris", "csv"):
            raise ValueError("mode must be zetaris or csv")
        with self.lock:
            self.mode = mode
        return {"mode": self.mode}

    # ------------------------------------------------------------------ status
    def status(self, fresh: bool = False) -> dict:
        if self._status_cache and not fresh and time.time() - self._status_cache[0] < 20:
            return self._status_cache[1]
        out: dict[str, Any] = {"checked_at": now_iso(), "mode": self.mode, "as_of": self.as_of.isoformat(),
                               "years": self.years, "rules_version": self.rules["version"]}
        # Zetaris: one federated query that touches all three engines
        t0 = time.time()
        try:
            z = self.zetaris()
            sql = (f"SELECT 'hospital_ehr' AS s, COUNT(*) AS n FROM {zt('hospital_ehr.patients')} "
                   f"UNION ALL SELECT 'lab_lis', COUNT(*) FROM {zt('lab_lis.lab_patients')} "
                   f"UNION ALL SELECT 'pharmacy_rx', COUNT(*) FROM {zt('pharmacy_rx.pharmacy_patients')}")
            rows = z.rows(sql, ["s", "n"])
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
            rows = {r["t"]: int(float(r["n"])) for r in z.rows(" UNION ALL ".join(parts), ["t", "n"])}
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
        r = requests.post(z.url, timeout=z.timeout, json={"queryId": str(uuid.uuid4()), "sql": sql, "source": "SqlEditor", "limit": 200},
                          headers={"Authorization": "Bearer " + z._key, "X-Org-ID": z.org_id, "X-Request-ID": str(uuid.uuid4())})
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
        return {"columns": cols, "rows": data[:200], "row_count": len(data), "seconds": round(time.time() - t0, 2)}

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
        for s, ids in wanted.items():
            table, key, cols = PATIENT_COLS[s]
            for i in ids:
                _safe(i)
            if rz:
                sel = ", ".join(f"date_format({c}, 'yyyy-MM-dd') AS {c}" if (s == "hospital_ehr" and c == "birth_date") else c for c in cols)
                rows = rz.rows(f"SELECT {sel} FROM {zt(table)} WHERE {key} IN ({', '.join(repr(i) for i in ids)})", cols)
            else:
                rel = {"hospital_ehr": "hospital/patients.csv", "lab_lis": "laboratory/lab_patients.csv",
                       "pharmacy_rx": "pharmacy/pharmacy_patients.csv"}[s]
                rows = [{c: r.get(c, "") for c in cols} for r in csv.DictReader(open(DATA / rel, encoding="utf-8")) if r[key] in ids]
            for row in rows:
                out.append({"system": s, "engine": systems()[s]["engine"], "record_id": row[key],
                            "status": "master" if s == "hospital_ehr" else status_of.get(row[key], ""), "row": row})
        if rz:
            queries = rz.log
        return {"mrn": mrn, "label": ident["label"], "records": out, "queries": queries, "mode": self.mode}

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
        """Record a reviewer's decision in the World Model (wm/review.ts), then rebuild the identity view."""
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
        cmd = [npx, "tsx", "wm/review.ts", action, system, record_id, "--by", by] + (["--note", note] if note else [])
        r1 = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=120)
        if r1.returncode != 0:
            raise RuntimeError((r1.stderr or r1.stdout).strip()[:400])
        r2 = subprocess.run([npx, "tsx", "wm/build_world.ts"], cwd=ROOT, capture_output=True, text=True, timeout=300)
        if r2.returncode != 0:
            raise RuntimeError((r2.stderr or r2.stdout).strip()[:400])
        with self.lock:
            self.cache.clear()
            self.scout = Scout(self.registry, load_patients(WORLD))
            self._status_cache = None
        return {"recorded": r1.stdout.strip(), "world": r2.stdout.strip(), "summary": self.world_summary()}

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
        t0 = time.time()
        rec = load_record(src, WORLD, mrn, self.as_of, self.years)
        t1 = time.time()
        result = analyse(rec, self.rules)
        entry = {"rec": rec, "result": result, "loaded_at": now_iso(), "mode": self.mode,
                 "load_seconds": round(t1 - t0, 2), "analysis_seconds": round(time.time() - t1, 3),
                 "queries": rz.log if rz else []}
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
                         "items": len(e["rec"].items)}}

    def evidence(self, mrn: str, eid: str) -> dict:
        e = self.load(mrn)
        for i in e["rec"].items:
            if i.eid == eid:
                return {"eid": eid, "system": i.system, "engine": systems()[i.system]["engine"],
                        "table": TABLES[i.kind][0].split(".")[1], "record_id": i.record_id, "kind": i.kind,
                        "when": i.when.isoformat() if i.when else None, "row": i.row}
        raise KeyError(f"{eid} is not in this patient's record")

    # ------------------------------------------------------------------ Scout + agent
    def scout_decide(self, prompt: str, mrn: str, user: dict) -> dict:
        _safe(mrn)
        d = self.scout.decide(prompt, mrn, user)
        out = d.to_dict()
        if d.contract:
            ok, why = verify_contract(d.contract, mrn)
            out["contract_check"] = {"ok": ok, "reason": why}
        return out

    def run_agent(self, prompt: str, mrn: str, user: dict, use_ai: bool, emit) -> dict:
        """Scout -> load record -> agent loop; every step is sent to `emit` as it happens and saved to data/derived/runs."""
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
        events: list[dict] = []
        t_start = time.time()

        def send(kind: str, **data):
            ev = {"type": kind, "t": round(time.time() - t_start, 2), **data}
            events.append(ev)
            emit(ev)

        send("start", run_id=run_id, prompt=prompt, mrn=mrn, user=user, ai=use_ai, mode=self.mode)
        decision = self.scout_decide(prompt, mrn, user)
        send("scout", decision=decision)
        if decision["status"] != "approved":
            res = {"status": decision["status"], "summary": decision["message"], "verdict": {}, "plan": [], "rounds": 0}
            send("result", result=res)
            self._save_run(run_id, prompt, mrn, user, use_ai, events, res)
            return res
        send("stage", stage="loading", message=f"Loading the patient's 3-year record through "
                                                  f"{'Zetaris (live)' if self.mode == 'zetaris' else 'the offline CSV copy'}")
        hit = (self.mode, mrn) in self.cache
        try:
            e = self.load(mrn)
        except Exception as ex:  # noqa: BLE001
            res = {"status": "error", "summary": f"Could not load the record: {_clean(str(ex))}", "verdict": {}, "plan": [], "rounds": 0}
            send("result", result=res)
            self._save_run(run_id, prompt, mrn, user, use_ai, events, res)
            return res
        send("stage", stage="loaded", items=len(e["rec"].items), seconds=e["load_seconds"], queries=e["queries"],
             cached=hit, mode=e["mode"])
        llm = self.llm() if use_ai else None
        if use_ai and not llm:
            send("stage", stage="ai-missing", message="Nightshift is not configured in .env: using the verified rule-based writer")
        agent = Agent(llm, log=lambda entry: send("trace", entry=_jsonable(entry)))
        r = agent.run(prompt, e["rec"], e["result"], self.rules, contract=decision["contract"], require_contract=True)
        res = {"status": r.status, "summary": r.summary, "verdict": _jsonable(r.verdict), "plan": r.plan, "rounds": r.rounds,
               "retrieved": len(ids_in(e["result"]))}
        send("result", result=res)
        self._save_run(run_id, prompt, mrn, user, use_ai, events, res)
        return res

    def _save_run(self, run_id, prompt, mrn, user, use_ai, events, res):
        RUNS.mkdir(parents=True, exist_ok=True)
        (RUNS / f"{run_id}.json").write_text(json.dumps(
            {"run_id": run_id, "at": now_iso(), "prompt": prompt, "mrn": mrn, "user": user, "ai": use_ai, "mode": self.mode,
             "status": res["status"], "events": events, "result": res}, default=str, indent=1), encoding="utf-8")

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
