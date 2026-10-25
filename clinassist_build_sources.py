#!/usr/bin/env python
r"""
ClinAssist AI - build three *fragmented* simulated source systems from Synthea FHIR.

Why this exists
---------------
The first extraction (clinassist_extract_fhir.py) gave every system the same
Synthea patient UUID, so "reconciling" the systems was a plain join. Real
hospital, laboratory and pharmacy systems do not share a patient key. This
script produces three systems that each have their OWN identifiers and their
own demographic conventions, with realistic, seeded data-entry variation, and
writes the true identity mapping to a separate _truth folder that the agent
never reads. The truth file is used only to MEASURE reconciliation accuracy.

Input   : data/synthea_fhir/*.json        (read-only; never modified)
Output  : data/derived/
            hospital/    patients, encounters, conditions, procedures, vitals
            laboratory/  lab_patients, lab_results, lab_reports
            pharmacy/    pharmacy_patients, prescriptions, administrations
            _truth/      identity_crosswalk.csv, perturbation_log.csv  (evaluation only)
            build_manifest.json

Rules followed
--------------
* Synthetic data only. Clinical values are copied from Synthea, never invented.
* Missing fields stay blank (no imputation).
* Only DEMOGRAPHIC identifiers are perturbed (names, date formats, a few typos),
  to mimic cross-system identity noise. Every perturbation is logged.
* Deterministic: the same --seed gives byte-identical output.

Usage (from the project folder, Windows PowerShell):
    .\.venv\Scripts\python.exe .\clinassist_build_sources.py
    .\.venv\Scripts\python.exe .\clinassist_build_sources.py --seed 42 --out data\derived
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent

# --------------------------------------------------------------------------- helpers


def strip_synthea_digits(name: str) -> str:
    """Synthea appends digits to names (Kendrick479). Real systems don't."""
    return re.sub(r"\d+", "", name or "").strip()


def ascii_fold(text: str) -> str:
    return unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")


def ref_id(obj: Any) -> str:
    """'urn:uuid:<id>' or 'Patient/<id>' -> '<id>'."""
    if not isinstance(obj, dict):
        return ""
    ref = str(obj.get("reference") or "")
    return ref.split(":")[-1].split("/")[-1]


def coding(obj: Any) -> tuple[str, str, str]:
    """(system, code, display) of the first coding, with text fallback."""
    if not isinstance(obj, dict):
        return "", "", ""
    codings = obj.get("coding") or []
    if codings:
        c = codings[0]
        return str(c.get("system", "")), str(c.get("code", "")), str(c.get("display") or obj.get("text") or "")
    return "", "", str(obj.get("text") or "")


def first_list(obj: Any) -> Any:
    return obj[0] if isinstance(obj, list) and obj else (obj if isinstance(obj, dict) else {})


def period(obj: Any) -> tuple[str, str]:
    if isinstance(obj, dict):
        return str(obj.get("start") or ""), str(obj.get("end") or "")
    return "", ""


def short_id(prefix: str, *parts: str, n: int = 8) -> str:
    """Stable opaque ID that does not reveal the Synthea UUID."""
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()[:n].upper()
    return f"{prefix}{digest}"


# --------------------------------------------------------------------------- perturbations


class Perturber:
    """Seeded, logged demographic noise. Rates are deliberately modest."""

    def __init__(self, seed: int):
        self.rng = random.Random(seed)
        self.log: list[dict[str, str]] = []

    def _note(self, pid: str, system: str, field: str, before: str, after: str, kind: str):
        if before != after:
            self.log.append({"synthea_id": pid, "system": system, "field": field,
                             "kind": kind, "original": before, "recorded": after})

    def typo(self, s: str) -> tuple[str, str]:
        if len(s) < 4:
            return s, ""
        i = self.rng.randrange(1, len(s) - 1)
        kind = self.rng.choice(["swap", "drop", "double"])
        if kind == "swap":
            out = s[:i] + s[i + 1] + s[i] + s[i + 2:]
        elif kind == "drop":
            out = s[:i] + s[i + 1:]
        else:
            out = s[:i] + s[i] + s[i:]
        return out, f"typo-{kind}"

    def maybe(self, rate: float) -> bool:
        return self.rng.random() < rate

    def lab_identity(self, pid: str, given: str, family: str, dob: str, sex: str) -> dict[str, str]:
        out_family, out_given, out_dob, out_sex = family.upper(), given, dob, sex
        if self.maybe(0.08):
            t, k = self.typo(family)
            out_family = t.upper(); self._note(pid, "laboratory", "surname", family.upper(), out_family, k)
        if self.maybe(0.03):  # day/month transposition, only when ambiguous
            y, m, d = dob.split("-")
            if int(d) <= 12 and d != m:
                out_dob = f"{y}-{d}-{m}"; self._note(pid, "laboratory", "dob", dob, out_dob, "day-month-swap")
        if self.maybe(0.05):
            out_sex = ""; self._note(pid, "laboratory", "sex", sex, "", "missing")
        y, m, d = out_dob.split("-")
        return {"surname": out_family, "forenames": out_given,
                "dob": f"{d}/{m}/{y}",                        # lab uses DD/MM/YYYY
                "gender": {"M": "MALE", "F": "FEMALE"}.get(out_sex, "UNKNOWN")}

    def pharmacy_identity(self, pid: str, given: str, family: str, dob: str, sex: str) -> dict[str, str]:
        g, f = given, family
        if self.maybe(0.10) and len(given) > 5:   # shortened / informal first name
            g = given[:3]; self._note(pid, "pharmacy", "given", given, g, "shortened")
        if self.maybe(0.06):
            folded = ascii_fold(f)
            if folded != f:
                self._note(pid, "pharmacy", "family", f, folded, "diacritics-dropped"); f = folded
            else:
                t, k = self.typo(f); self._note(pid, "pharmacy", "family", f, t, k); f = t
        out_dob = dob
        if self.maybe(0.03):  # single-digit keying error in the day
            y, m, d = dob.split("-")
            nd = f"{max(1, min(28, int(d) + self.rng.choice([-1, 1]))):02d}"
            out_dob = f"{y}-{m}-{nd}"; self._note(pid, "pharmacy", "dob", dob, out_dob, "day-off-by-one")
        return {"full_name": f"{f.upper()}, {g}",           # pharmacy uses 'SURNAME, Given'
                "birth_date": out_dob.replace("-", ""),     # YYYYMMDD
                "sex": sex or "U"}


# --------------------------------------------------------------------------- extraction


def load_bundles(fhir_dir: Path):
    for path in sorted(fhir_dir.glob("*.json")):
        with path.open(encoding="utf-8") as fh:
            bundle = json.load(fh)
        resources = [e.get("resource", {}) for e in bundle.get("entry", [])]
        patients = [r for r in resources if r.get("resourceType") == "Patient"]
        if patients:  # skip shared hospitalInformation / practitionerInformation bundles
            yield path.name, patients[0], resources


def build(fhir_dir: Path, out_dir: Path, seed: int) -> dict[str, Any]:
    pert = Perturber(seed)
    tables: dict[str, list[dict[str, Any]]] = defaultdict(list)
    crosswalk: list[dict[str, str]] = []
    med_names: dict[str, tuple[str, str]] = {}  # Medication resource id -> (rxnorm, name)

    for fname, patient, resources in load_bundles(fhir_dir):
        pid = patient["id"]
        name = first_list(patient.get("name"))
        given_all = [strip_synthea_digits(g) for g in name.get("given", [])]
        given, middle = (given_all[0] if given_all else ""), " ".join(given_all[1:])
        family = strip_synthea_digits(name.get("family", ""))
        dob = patient.get("birthDate", "")
        sex = {"male": "M", "female": "F"}.get(patient.get("gender", ""), "")
        addr = first_list(patient.get("address"))

        mrn = short_id("MRN", "hospital", pid)
        lab_pid = short_id("LP", "laboratory", pid, n=7)
        rx_pid = short_id("RX", "pharmacy", pid, n=7)

        # --- HOSPITAL (canonical-ish demographics, ISO dates) ---
        tables["hospital/patients"].append({
            "mrn": mrn, "given_name": given, "middle_name": middle, "family_name": family,
            "birth_date": dob, "sex": sex, "deceased_at": patient.get("deceasedDateTime", ""),
            "city": addr.get("city", ""), "postcode": addr.get("postalCode", ""),
        })

        has_lab = has_rx = False
        for r in resources:
            rt = r.get("resourceType")
            if rt == "Medication":
                _, code, disp = coding(r.get("code"))
                med_names[r.get("id", "")] = (code, disp)

        for r in resources:
            rt = r.get("resourceType")
            rid = r.get("id", "")
            if rt == "Encounter":
                s, e = period(r.get("period"))
                _, tcode, tdisp = coding(first_list(r.get("type")))
                _, rcode, rdisp = coding(first_list(r.get("reasonCode")))
                tables["hospital/encounters"].append({
                    "encounter_id": rid, "mrn": mrn, "encounter_class": (r.get("class") or {}).get("code", ""),
                    "type_code": tcode, "type_display": tdisp, "status": r.get("status", ""),
                    "start_at": s, "end_at": e, "reason_code": rcode, "reason_display": rdisp,
                    "provider_org": (r.get("serviceProvider") or {}).get("display", ""),
                })
            elif rt == "Condition":
                _, code, disp = coding(r.get("code"))
                tables["hospital/conditions"].append({
                    "condition_id": rid, "mrn": mrn, "encounter_id": ref_id(r.get("encounter")),
                    "snomed_code": code, "display": disp,
                    "clinical_status": coding(r.get("clinicalStatus"))[1],
                    "verification_status": coding(r.get("verificationStatus"))[1],
                    "onset_at": r.get("onsetDateTime", ""), "abatement_at": r.get("abatementDateTime", ""),
                    "recorded_at": r.get("recordedDate", ""),
                })
            elif rt == "Procedure":
                _, code, disp = coding(r.get("code"))
                s, e = period(r.get("performedPeriod"))
                tables["hospital/procedures"].append({
                    "procedure_id": rid, "mrn": mrn, "encounter_id": ref_id(r.get("encounter")),
                    "snomed_code": code, "display": disp, "status": r.get("status", ""),
                    "performed_start": s or r.get("performedDateTime", ""), "performed_end": e,
                })
            elif rt == "Observation":
                cat = coding(first_list(r.get("category")))[1]
                sysuri, code, disp = coding(r.get("code"))
                vq = r.get("valueQuantity") or {}
                value_num = vq.get("value", "")
                value_text = coding(r.get("valueCodeableConcept"))[2] if r.get("valueCodeableConcept") else str(r.get("valueString", "") or "")
                row_common = {"loinc_code": code, "test_name": disp, "value_num": value_num,
                              "value_text": value_text, "unit": vq.get("unit", ""),
                              "status": r.get("status", "")}
                if cat == "laboratory":
                    has_lab = True
                    tables["laboratory/lab_results"].append({
                        "result_id": short_id("R", rid, n=10), "lab_patient_id": lab_pid,
                        "accession_no": short_id("ACC", pid, r.get("effectiveDateTime", ""), n=8),
                        **row_common, "collected_at": r.get("effectiveDateTime", ""),
                        "reported_at": r.get("issued", ""),
                        "reference_range": "",   # Synthea supplies none; never invented here
                    })
                elif r.get("component"):
                    # Panels such as blood pressure carry their values in components (systolic, diastolic):
                    # one row per component, so the values are not lost.
                    for comp in r["component"]:
                        _, ccode, cdisp = coding(comp.get("code"))
                        cq = comp.get("valueQuantity") or {}
                        ctext = coding(comp.get("valueCodeableConcept"))[2] if comp.get("valueCodeableConcept") \
                            else str(comp.get("valueString", "") or "")
                        tables["hospital/observations"].append({
                            "observation_id": f"{rid}:{ccode}", "mrn": mrn, "encounter_id": ref_id(r.get("encounter")),
                            "category": cat, "loinc_code": ccode, "test_name": cdisp, "value_num": cq.get("value", ""),
                            "value_text": ctext, "unit": cq.get("unit", ""), "status": r.get("status", ""),
                            "observed_at": r.get("effectiveDateTime", ""),
                        })
                else:  # vitals, surveys, social history stay in the hospital chart
                    tables["hospital/observations"].append({
                        "observation_id": rid, "mrn": mrn, "encounter_id": ref_id(r.get("encounter")),
                        "category": cat, **row_common, "observed_at": r.get("effectiveDateTime", ""),
                    })
            elif rt == "AllergyIntolerance":
                _, code, disp = coding(r.get("code"))
                reaction = first_list(r.get("reaction"))
                tables["hospital/allergies"].append({
                    "allergy_id": rid, "mrn": mrn, "snomed_code": code, "substance": disp,
                    "category": ";".join(r.get("category") or []), "criticality": r.get("criticality", ""),
                    "clinical_status": coding(r.get("clinicalStatus"))[1],
                    "verification_status": coding(r.get("verificationStatus"))[1],
                    "reaction": coding(first_list(reaction.get("manifestation")))[2] if reaction else "",
                    "recorded_at": r.get("recordedDate", ""),
                })
            elif rt == "DiagnosticReport":
                cat = coding(first_list(r.get("category")))[1]
                if cat == "LAB" or "lab" in cat.lower():
                    has_lab = True
                    _, code, disp = coding(r.get("code"))
                    tables["laboratory/lab_reports"].append({
                        "report_id": short_id("RPT", rid, n=10), "lab_patient_id": lab_pid,
                        "loinc_code": code, "report_name": disp, "status": r.get("status", ""),
                        "issued_at": r.get("issued", ""), "effective_at": r.get("effectiveDateTime", ""),
                        "result_ids": ";".join(short_id("R", ref_id(x), n=10) for x in r.get("result", [])),
                    })
            elif rt == "MedicationRequest":
                has_rx = True
                if r.get("medicationCodeableConcept"):
                    _, code, disp = coding(r["medicationCodeableConcept"])
                else:
                    code, disp = med_names.get(ref_id(r.get("medicationReference")), ("", ""))
                di = first_list(r.get("dosageInstruction"))
                timing = (di.get("timing") or {}).get("repeat", {}) if di else {}
                dose = first_list(di.get("doseAndRate")).get("doseQuantity", {}) if di else {}
                tables["pharmacy/prescriptions"].append({
                    "rx_id": short_id("RXN", rid, n=10), "pharm_patient_id": rx_pid,
                    "rxnorm_code": code, "medication": disp, "status": r.get("status", ""),
                    "intent": r.get("intent", ""), "authored_on": r.get("authoredOn", ""),
                    "dose_value": dose.get("value", ""), "dose_unit": dose.get("unit", ""),
                    "frequency": timing.get("frequency", ""), "period": timing.get("period", ""),
                    "period_unit": timing.get("periodUnit", ""),
                    "as_needed": di.get("asNeededBoolean", "") if di else "",
                    "dosage_text": di.get("text", "") if di else "",
                    "prescriber": (r.get("requester") or {}).get("display", ""),
                })
            elif rt == "MedicationAdministration":
                has_rx = True
                if r.get("medicationCodeableConcept"):
                    _, code, disp = coding(r["medicationCodeableConcept"])
                else:
                    code, disp = med_names.get(ref_id(r.get("medicationReference")), ("", ""))
                tables["pharmacy/administrations"].append({
                    "admin_id": short_id("ADM", rid, n=10), "pharm_patient_id": rx_pid,
                    "rxnorm_code": code, "medication": disp, "status": r.get("status", ""),
                    "administered_at": r.get("effectiveDateTime", "") or period(r.get("effectivePeriod"))[0],
                })

        # Each system only knows patients it has actually served.
        if has_lab:
            tables["laboratory/lab_patients"].append({"lab_patient_id": lab_pid,
                                                      **pert.lab_identity(pid, given, family, dob, sex)})
        if has_rx:
            tables["pharmacy/pharmacy_patients"].append({"pharm_patient_id": rx_pid,
                                                         **pert.pharmacy_identity(pid, given, family, dob, sex)})
        crosswalk.append({"synthea_id": pid, "source_file": fname, "mrn": mrn,
                          "lab_patient_id": lab_pid if has_lab else "",
                          "pharm_patient_id": rx_pid if has_rx else ""})

    tables["_truth/identity_crosswalk"] = crosswalk
    tables["_truth/perturbation_log"] = pert.log

    counts = {}
    for name, rows in sorted(tables.items()):
        path = out_dir / f"{name}.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        fields = list(rows[0].keys()) if rows else ["empty"]
        with path.open("w", encoding="utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)
        counts[name] = len(rows)

    # Pharmacy also published as JSON, the shape its REST API will serve.
    for name in ("pharmacy/pharmacy_patients", "pharmacy/prescriptions", "pharmacy/administrations"):
        (out_dir / f"{name}.json").write_text(json.dumps({"data": tables[name]}, ensure_ascii=False), encoding="utf-8")

    perturb_summary = Counter(f"{p['system']}:{p['kind']}" for p in pert.log)
    manifest = {"seed": seed, "fhir_dir": str(fhir_dir), "row_counts": counts,
                "perturbations": dict(sorted(perturb_summary.items())),
                "note": "Synthetic data derived from Synthea. _truth/ is for evaluation only; the agent must not read it."}
    (out_dir / "build_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--fhir", default=str(ROOT / "data" / "synthea_fhir"))
    ap.add_argument("--out", default=str(ROOT / "data" / "derived"))
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    manifest = build(Path(a.fhir), Path(a.out), a.seed)
    print(json.dumps(manifest, indent=2))
    print("\nDONE. Original FHIR JSON files were not changed. Output:", a.out)


if __name__ == "__main__":
    main()
