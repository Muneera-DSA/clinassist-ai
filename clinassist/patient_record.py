"""Assemble one patient's record from the three systems, with an evidence id on every item.

Identity comes from the Meterless World Model view (data/derived/world/patient_identity.json):
only links that were auto-linked or confirmed by a reviewer are used. Records still
pending review are NOT pulled in; they are reported so a person can decide.

Data comes through Zetaris (federated SQL) by default, or from the local CSVs
for offline testing. Every row keeps its source: system, table and record id.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

SAFE_ID = re.compile(r"^[A-Za-z0-9_.-]+$")

# (zetaris table, csv path, id column, patient key column, date column, columns)
TABLES: dict[str, tuple[str, str, str, str, str | None, list[str]]] = {
    "patient":        ("hospital_ehr.patients", "hospital/patients.csv", "mrn", "mrn", None,
                       ["mrn", "given_name", "family_name", "birth_date", "sex", "deceased_at"]),
    "encounter":      ("hospital_ehr.encounters", "hospital/encounters.csv", "encounter_id", "mrn", "start_at",
                       ["encounter_id", "mrn", "encounter_class", "type_display", "start_at", "end_at", "reason_display", "provider_org"]),
    "condition":      ("hospital_ehr.conditions", "hospital/conditions.csv", "condition_id", "mrn", None,
                       ["condition_id", "mrn", "snomed_code", "display", "clinical_status", "onset_at", "abatement_at"]),
    "procedure":      ("hospital_ehr.procedures", "hospital/procedures.csv", "procedure_id", "mrn", "performed_start",
                       ["procedure_id", "mrn", "display", "status", "performed_start"]),
    "lab_result":     ("lab_lis.lab_results", "laboratory/lab_results.csv", "result_id", "lab_patient_id", "collected_at",
                       ["result_id", "lab_patient_id", "accession_no", "loinc_code", "test_name", "value_num", "value_text", "unit", "status", "collected_at"]),
    "prescription":   ("pharmacy_rx.prescriptions", "pharmacy/prescriptions.csv", "rx_id", "pharm_patient_id", None,
                       ["rx_id", "pharm_patient_id", "rxnorm_code", "medication", "status", "authored_on", "dosage_text", "prescriber"]),
    "administration": ("pharmacy_rx.administrations", "pharmacy/administrations.csv", "admin_id", "pharm_patient_id", "administered_at",
                       ["admin_id", "pharm_patient_id", "medication", "status", "administered_at"]),
}
SYSTEM_OF = {"patient": "hospital_ehr", "encounter": "hospital_ehr", "condition": "hospital_ehr", "procedure": "hospital_ehr",
             "lab_result": "lab_lis", "prescription": "pharmacy_rx", "administration": "pharmacy_rx"}
TIMESTAMP_COLS = {"start_at", "end_at", "onset_at", "abatement_at", "performed_start", "collected_at", "authored_on",
                  "administered_at", "deceased_at"}


def parse_dt(v: str) -> datetime | None:
    v = (v or "").strip()
    if not v:
        return None
    v = v.replace(" ", "T")[:19]
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(v[: 19 if "T" in fmt else 10], fmt)
        except ValueError:
            continue
    return None


class CsvSource:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def fetch(self, kind: str, keys: list[str], since: str | None) -> list[dict[str, str]]:
        _, rel, _, key_col, date_col, cols = TABLES[kind]
        out = []
        with open(self.data_dir / rel, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r[key_col] in keys and (not since or not date_col or (r[date_col] or "") >= since):
                    out.append({c: r.get(c, "") or "" for c in cols})
        return out


class ZetarisSource:
    def __init__(self, client):
        self.z = client

    def fetch(self, kind: str, keys: list[str], since: str | None) -> list[dict[str, str]]:
        table, _, _, key_col, date_col, cols = TABLES[kind]
        if not keys:
            return []
        for k in keys:  # ids are interpolated into SQL, so only allow plain identifiers
            if not SAFE_ID.match(k):
                raise ValueError(f"unsafe id: {k!r}")
        select = ", ".join(f"date_format({c}, \"yyyy-MM-dd'T'HH:mm:ss\") AS {c}" if c in TIMESTAMP_COLS
                           else (f"date_format({c}, 'yyyy-MM-dd') AS {c}" if c == "birth_date" else c) for c in cols)
        where = f"{key_col} IN ({', '.join(repr(k) for k in keys)})"
        if since and date_col:
            where += f" AND {date_col} >= '{since}'"
        return self.z.rows(f"SELECT {select} FROM {table} WHERE {where}", cols)


@dataclass
class Item:
    """One source row with a stable evidence id (E-<kind>-<record id>)."""
    eid: str
    kind: str
    system: str
    record_id: str
    when: datetime | None
    row: dict[str, Any]

    def ref(self) -> str:
        return f"{self.system}.{TABLES[self.kind][0].split('.')[1]}/{self.record_id}"


@dataclass
class PatientRecord:
    mrn: str
    label: str
    as_of: date
    since: date
    patient: dict[str, str]
    linked: list[dict]
    pending: list[dict]
    items: list[Item] = field(default_factory=list)

    def of(self, kind: str) -> list[Item]:
        return [i for i in self.items if i.kind == kind]

    def by_eid(self) -> dict[str, Item]:
        return {i.eid: i for i in self.items}


def load_identity(world_dir: Path, mrn: str) -> dict:
    data = json.loads((world_dir / "patient_identity.json").read_text(encoding="utf-8"))
    for p in data["patients"]:
        if p["mrn"] == mrn:
            return p
    raise KeyError(f"{mrn} is not in the World Model identity view")


def load_record(source, world_dir: Path, mrn: str, as_of: date, years: int = 3) -> PatientRecord:
    if not SAFE_ID.match(mrn):
        raise ValueError("unsafe MRN")
    ident = load_identity(world_dir, mrn)
    since = as_of - timedelta(days=round(365.25 * years))
    since_s = since.isoformat()
    lab_ids = [r["record_id"] for r in ident["linked_records"] if r["system"] == "laboratory"]
    rx_ids = [r["record_id"] for r in ident["linked_records"] if r["system"] == "pharmacy"]

    patient_rows = source.fetch("patient", [mrn], None)
    if not patient_rows:
        raise KeyError(f"{mrn} not found in hospital_ehr.patients")
    rec = PatientRecord(mrn, ident["label"], as_of, since, patient_rows[0], ident["linked_records"], ident["pending_review"])

    plan = [("encounter", [mrn], since_s), ("condition", [mrn], None), ("procedure", [mrn], since_s),
            ("lab_result", lab_ids, since_s), ("prescription", rx_ids, None), ("administration", rx_ids, since_s)]
    for kind, keys, since_filter in plan:
        _, _, id_col, _, date_col, _ = TABLES[kind]
        for row in source.fetch(kind, keys, since_filter):
            when_col = date_col or {"condition": "onset_at", "prescription": "authored_on"}.get(kind)
            when = parse_dt(row.get(when_col, "")) if when_col else None
            if when and when.date() > as_of:
                continue  # nothing from after the review date (no future information)
            rec.items.append(Item(f"E-{kind}-{row[id_col]}", kind, SYSTEM_OF[kind], row[id_col], when, row))
    rec.items.sort(key=lambda i: (i.when or datetime.min, i.eid))
    return rec
