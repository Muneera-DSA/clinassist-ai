#!/usr/bin/env python
"""
ClinAssist AI — extract selected Synthea FHIR resources into simulated CSV source systems.

Input:
  data/synthea_fhir/**/*.json

Output:
  data/simulated_sources/
    hospital/Patient.csv, Encounter.csv, Condition.csv, Procedure.csv
    laboratory/Observation.csv, DiagnosticReport.csv
    pharmacy/MedicationRequest.csv, Medication.csv, MedicationAdministration.csv

The JSON files remain unchanged. Missing fields are left blank; no clinical values are invented.
These outputs are simulated source-system exports, not live hospital systems.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable

PROJECT_ROOT = Path(__file__).resolve().parent
FHIR_ROOT = PROJECT_ROOT / "data" / "synthea_fhir"
OUTPUT_ROOT = PROJECT_ROOT / "data" / "simulated_sources"

RESOURCE_DESTINATIONS = {
    "Patient": ("hospital", "Patient.csv"),
    "Encounter": ("hospital", "Encounter.csv"),
    "Condition": ("hospital", "Condition.csv"),
    "Procedure": ("hospital", "Procedure.csv"),
    "Observation": ("laboratory", "Observation.csv"),
    "DiagnosticReport": ("laboratory", "DiagnosticReport.csv"),
    "MedicationRequest": ("pharmacy", "MedicationRequest.csv"),
    "Medication": ("pharmacy", "Medication.csv"),
    "MedicationAdministration": ("pharmacy", "MedicationAdministration.csv"),
}

# Consistent columns across resources. Resource-specific detail columns are retained too.
BASE_FIELDS = [
    "resource_type", "record_id", "patient_ref", "encounter_ref",
    "status", "record_date", "code", "description", "value", "unit",
    "interpretation", "reference_range", "medication", "dosage",
    "route", "frequency", "period_start", "period_end", "source_system",
    "source_file",
]


def first_coding_text(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    codings = obj.get("coding") or []
    if codings and isinstance(codings[0], dict):
        return str(codings[0].get("display") or codings[0].get("code") or "")
    return str(obj.get("text") or "")


def reference_id(obj: Any) -> str:
    if not isinstance(obj, dict):
        return ""
    ref = str(obj.get("reference") or "")
    # Keep the FHIR reference form (e.g. Patient/<id>) for traceability.
    return ref


def quantity_value(obj: Any) -> tuple[str, str]:
    if not isinstance(obj, dict):
        return "", ""
    if "value" in obj:
        return str(obj.get("value", "")), str(obj.get("unit") or obj.get("code") or "")
    return "", ""


def date_value(resource: dict[str, Any]) -> str:
    for key in (
        "effectiveDateTime", "effectivePeriod", "onsetDateTime", "onsetPeriod",
        "authoredOn", "recordedDate", "issued", "performedDateTime",
        "performedPeriod", "occurrenceDateTime", "occurrencePeriod",
        "period", "date", "birthDate",
    ):
        value = resource.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            start = value.get("start") or value.get("low", {}).get("value")
            end = value.get("end") or value.get("high", {}).get("value")
            if start and end:
                return f"{start}/{end}"
            if start:
                return str(start)
            if end:
                return str(end)
    return ""


def period_bounds(resource: dict[str, Any]) -> tuple[str, str]:
    for key in ("period", "effectivePeriod", "performedPeriod", "occurrencePeriod"):
        value = resource.get(key)
        if isinstance(value, dict):
            return str(value.get("start") or ""), str(value.get("end") or "")
    return "", ""


def get_patient_ref(resource: dict[str, Any]) -> str:
    for key in ("subject", "patient", "beneficiary", "individual"):
        value = resource.get(key)
        if isinstance(value, dict) and value.get("reference"):
            return reference_id(value)
    return ""


def get_encounter_ref(resource: dict[str, Any]) -> str:
    return reference_id(resource.get("encounter"))


def get_medication_name(resource: dict[str, Any]) -> str:
    for key in ("medicationCodeableConcept", "medication"):
        value = resource.get(key)
        if isinstance(value, dict):
            text = value.get("text")
            if text:
                return str(text)
            display = first_coding_text(value)
            if display:
                return display
            concept = value.get("concept")
            if isinstance(concept, dict):
                text = concept.get("text") or first_coding_text(concept)
                if text:
                    return str(text)
        if isinstance(value, dict) and value.get("reference"):
            return reference_id(value)
    return ""


def extract(resource: dict[str, Any], source_file: str) -> dict[str, str]:
    rtype = str(resource.get("resourceType") or "")
    code_obj = resource.get("code") or resource.get("type") or resource.get("category")
    code = first_coding_text(code_obj)

    value = ""
    unit = ""
    if isinstance(resource.get("valueQuantity"), dict):
        value, unit = quantity_value(resource["valueQuantity"])
    elif isinstance(resource.get("valueCodeableConcept"), dict):
        value = first_coding_text(resource["valueCodeableConcept"])
    elif isinstance(resource.get("valueString"), (str, int, float)):
        value = str(resource["valueString"])
    elif isinstance(resource.get("valueBoolean"), bool):
        value = str(resource["valueBoolean"])

    interpretation = first_coding_text(
        (resource.get("interpretation") or [{}])[0]
        if isinstance(resource.get("interpretation"), list) and resource.get("interpretation")
        else resource.get("interpretation")
    )

    reference_range = ""
    ranges = resource.get("referenceRange") or []
    if isinstance(ranges, list):
        pieces = []
        for rr in ranges:
            if not isinstance(rr, dict):
                continue
            low = rr.get("low") or {}
            high = rr.get("high") or {}
            low_v = low.get("value", "")
            high_v = high.get("value", "")
            rr_unit = low.get("unit") or high.get("unit") or ""
            text = rr.get("text") or ""
            if text:
                pieces.append(str(text))
            elif low_v != "" or high_v != "":
                pieces.append(f"{low_v}–{high_v} {rr_unit}".strip())
        reference_range = " | ".join(pieces)

    dosage = ""
    route = ""
    frequency = ""
    dosage_instructions = resource.get("dosageInstruction") or []
    if isinstance(dosage_instructions, list):
        for instruction in dosage_instructions:
            if not isinstance(instruction, dict):
                continue
            parts = []
            dose = instruction.get("doseAndRate") or []
            if dose and isinstance(dose[0], dict):
                dose_quantity = dose[0].get("doseQuantity")
                if isinstance(dose_quantity, dict):
                    amount, dose_unit = quantity_value(dose_quantity)
                    if amount:
                        parts.append(f"{amount} {dose_unit}".strip())
            if instruction.get("text"):
                parts.append(str(instruction["text"]))
            dosage = " | ".join(parts)
            route = first_coding_text(instruction.get("route"))
            timing = instruction.get("timing") or {}
            repeat = timing.get("repeat") or {}
            frequency_parts = []
            if repeat.get("frequency") is not None:
                frequency_parts.append(f"frequency={repeat['frequency']}")
            if repeat.get("period") is not None:
                frequency_parts.append(f"period={repeat['period']} {repeat.get('periodUnit', '')}".strip())
            if repeat.get("when"):
                frequency_parts.append("when=" + ",".join(str(x) for x in repeat["when"]))
            frequency = "; ".join(frequency_parts)
            if dosage or route or frequency:
                break

    period_start, period_end = period_bounds(resource)
    if not period_start:
        period_start = str((resource.get("dispenseRequest") or {}).get("validityPeriod", {}).get("start") or "")
    if not period_end:
        period_end = str((resource.get("dispenseRequest") or {}).get("validityPeriod", {}).get("end") or "")

    description = ""
    for key in ("display", "description", "text"):
        val = resource.get(key)
        if isinstance(val, str):
            description = val
            break
    if not description:
        description = code

    source_system = {
        "Patient": "simulated_hospital",
        "Encounter": "simulated_hospital",
        "Condition": "simulated_hospital",
        "Procedure": "simulated_hospital",
        "Observation": "simulated_laboratory",
        "DiagnosticReport": "simulated_laboratory",
        "MedicationRequest": "simulated_pharmacy",
        "Medication": "simulated_pharmacy",
        "MedicationAdministration": "simulated_pharmacy",
    }.get(rtype, "simulated_unknown")

    row = {
        "resource_type": rtype,
        "record_id": str(resource.get("id") or ""),
        "patient_ref": get_patient_ref(resource),
        "encounter_ref": get_encounter_ref(resource),
        "status": str(resource.get("status") or resource.get("clinicalStatus", {}).get("coding", [{}])[0].get("code", "") if isinstance(resource.get("clinicalStatus"), dict) else resource.get("status") or ""),
        "record_date": date_value(resource),
        "code": code,
        "description": description,
        "value": value,
        "unit": unit,
        "interpretation": interpretation,
        "reference_range": reference_range,
        "medication": get_medication_name(resource) if rtype.startswith("Medication") else "",
        "dosage": dosage,
        "route": route,
        "frequency": frequency,
        "period_start": period_start,
        "period_end": period_end,
        "source_system": source_system,
        "source_file": source_file,
    }
    return {key: safe_cell(row.get(key, "")) for key in BASE_FIELDS}


def safe_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)


def iter_resources(path: Path) -> Iterable[dict[str, Any]]:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"SKIP (could not read JSON): {path.name}: {exc}")
        return

    if isinstance(data, dict) and data.get("resourceType") == "Bundle":
        for entry in data.get("entry") or []:
            resource = entry.get("resource") if isinstance(entry, dict) else None
            if isinstance(resource, dict) and resource.get("resourceType") in RESOURCE_DESTINATIONS:
                yield resource
    elif isinstance(data, dict) and data.get("resourceType") in RESOURCE_DESTINATIONS:
        yield data
    elif isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and item.get("resourceType") in RESOURCE_DESTINATIONS:
                yield item


def main() -> None:
    if not FHIR_ROOT.exists():
        raise SystemExit(
            f"FHIR input folder not found: {FHIR_ROOT}\n"
            "Save this script in C:\\Hackathon\\clinical-ai-assistant and check data\\synthea_fhir."
        )

    collected: dict[tuple[str, str], list[dict[str, str]]] = {}
    seen: set[tuple[str, str]] = set()
    json_files = sorted(FHIR_ROOT.rglob("*.json"))
    if not json_files:
        raise SystemExit(f"No JSON files found under {FHIR_ROOT}")

    for path in json_files:
        for resource in iter_resources(path):
            rtype = str(resource.get("resourceType") or "")
            destination = RESOURCE_DESTINATIONS.get(rtype)
            if not destination:
                continue
            record_id = str(resource.get("id") or "")
            # Avoid duplicate rows if the same resource appears in more than one file.
            dedupe_key = (rtype, record_id)
            if record_id and dedupe_key in seen:
                continue
            if record_id:
                seen.add(dedupe_key)
            folder, filename = destination
            key = (folder, filename)
            collected.setdefault(key, []).append(extract(resource, str(path.relative_to(FHIR_ROOT))))

    for folder in ("hospital", "laboratory", "pharmacy"):
        (OUTPUT_ROOT / folder).mkdir(parents=True, exist_ok=True)

    print(f"Input JSON files scanned: {len(json_files)}")
    print(f"Output folder: {OUTPUT_ROOT}")
    for (folder, filename), rows in sorted(collected.items()):
        output_path = OUTPUT_ROOT / folder / filename
        with output_path.open("w", newline="", encoding="utf-8-sig") as handle:
            writer = csv.DictWriter(handle, fieldnames=BASE_FIELDS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"{folder}\\{filename}: {len(rows)} rows")

    print("\nDONE. Original FHIR JSON files were not changed.")
    print("Reminder: these are simulated source-system exports derived from synthetic Synthea data.")


if __name__ == "__main__":
    main()
