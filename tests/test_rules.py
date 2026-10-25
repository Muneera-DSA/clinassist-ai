r"""Scenario tests for the clinical rules: each rule must fire on a planted positive case
and stay silent on a matched negative case.

    .\.venv\Scripts\python.exe .\tests\test_rules.py
"""
from __future__ import annotations

import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clinassist.analysis import analyse, load_rules  # noqa: E402
from clinassist.patient_record import Item, PatientRecord  # noqa: E402

RULES = load_rules()
LOINC = {"egfr": "33914-3", "hb": "718-7", "k": "6298-4", "a1c": "4548-4", "acr": "14959-1", "sbp": "8480-6"}
BP_MEDS = [("lisinopril 10 MG Oral Tablet", "2026-09-01", "active"), ("amLODIPine 2.5 MG Oral Tablet", "2026-09-01", "active")]
AS_OF = date(2026, 10, 24)


def rec(labs=(), conds=(), rx=(), allergies=(), vitals=()):
    r = PatientRecord("MRNTEST", "TEST, PATIENT", AS_OF, date(2023, 10, 24), {"birth_date": "1950-01-01", "sex": "F"}, [], [])
    for n, lab in enumerate(labs):
        code, d, v = lab[:3]
        panel = lab[3] if len(lab) > 3 else "standalone"
        r.items.append(Item(f"E-lab_result-L{n}", "lab_result", "lab_lis", f"L{n}", datetime.fromisoformat(d),
                            {"loinc_code": LOINC.get(code, code), "value_num": str(v), "test_name": code, "panel": panel}))
    for n, (disp, d) in enumerate(conds):
        r.items.append(Item(f"E-condition-C{n}", "condition", "hospital_ehr", f"C{n}", datetime.fromisoformat(d),
                            {"display": disp, "clinical_status": "active"}))
    for n, (med, d, status) in enumerate(rx):
        r.items.append(Item(f"E-prescription-P{n}", "prescription", "pharmacy_rx", f"P{n}", datetime.fromisoformat(d),
                            {"medication": med, "status": status}))
    for n, (sub, cat) in enumerate(allergies):
        r.items.append(Item(f"E-allergy-A{n}", "allergy", "hospital_ehr", f"A{n}", datetime(2015, 1, 1),
                            {"substance": sub, "category": cat, "clinical_status": "active", "reaction": "Rash", "criticality": "low"}))
    for n, (code, d, v) in enumerate(vitals):
        r.items.append(Item(f"E-observation-V{n}", "observation", "hospital_ehr", f"V{n}", datetime.fromisoformat(d),
                            {"loinc_code": LOINC.get(code, code), "value_num": str(v), "test_name": code, "category": "vital-signs"}))
    r.items.sort(key=lambda i: i.when)
    return r


def rules_fired(r):
    return {f["rule"]: f["severity"] for f in analyse(r, RULES)["findings"]}


CASES = [
    # (name, record, rule, expected severity or None if it must NOT fire)
    ("eGFR falls 28% with category change, sustained", rec(labs=[("egfr", "2025-01-10", 50), ("egfr", "2025-06-10", 36),
                                                                 ("egfr", "2025-08-10", 35), ("egfr", "2025-10-10", 34)]), "ckd-accelerated", "high"),
    ("eGFR drifts 50 to 45, same category", rec(labs=[("egfr", "2025-01-10", 50), ("egfr", "2025-06-10", 47),
                                                      ("egfr", "2025-08-10", 46), ("egfr", "2025-10-10", 45)]), "ckd-accelerated", None),
    ("eGFR 140 to 100 on only 3 tests", rec(labs=[("egfr", "2024-03-01", 140), ("egfr", "2025-03-01", 120),
                                                  ("egfr", "2026-03-01", 100)]), "ckd-possible-fast-fall", "review"),
    ("alendronate with eGFR 28", rec(labs=[("egfr", "2026-09-01", 28)], rx=[("Alendronic acid 10 MG Oral Tablet", "2026-09-01", "active")]),
     "renal-alendronate", "high"),
    ("alendronate with eGFR 50", rec(labs=[("egfr", "2026-09-01", 50)], rx=[("Alendronic acid 10 MG Oral Tablet", "2026-09-01", "active")]),
     "renal-alendronate", None),
    ("metformin with eGFR 25", rec(labs=[("egfr", "2026-09-01", 25)], rx=[("metformin hydrochloride 500 MG Oral Tablet", "2026-09-01", "active")]),
     "renal-metformin", "high"),
    ("metformin with eGFR 40", rec(labs=[("egfr", "2026-09-01", 40)], rx=[("metformin hydrochloride 500 MG Oral Tablet", "2026-09-01", "active")]),
     "renal-metformin", "review"),
    ("metformin with eGFR 70", rec(labs=[("egfr", "2026-09-01", 70)], rx=[("metformin hydrochloride 500 MG Oral Tablet", "2026-09-01", "active")]),
     "renal-metformin", None),
    ("type 2 diabetes, last HbA1c 9 months ago", rec(labs=[("a1c", "2026-01-10", 6.8)], conds=[("Diabetes mellitus type 2 (disorder)", "2015-01-01")]),
     "dm-a1c-gap", "review"),
    ("type 2 diabetes, recent HbA1c 7.6", rec(labs=[("a1c", "2026-09-10", 7.6)], conds=[("Diabetes mellitus type 2 (disorder)", "2015-01-01")]),
     "dm-a1c-above-goal", "review"),
    ("type 2 diabetes, recent HbA1c 6.5", rec(labs=[("a1c", "2026-09-10", 6.5)], conds=[("Diabetes mellitus type 2 (disorder)", "2015-01-01")]),
     "dm-a1c-above-goal", None),
    ("lisinopril with potassium 5.6", rec(labs=[("k", "2026-09-01", 5.6)], rx=[("lisinopril 10 MG Oral Tablet", "2026-09-01", "active")]),
     "acei-potassium", "review"),
    ("lisinopril with potassium 4.4", rec(labs=[("k", "2026-09-01", 4.4)], rx=[("lisinopril 10 MG Oral Tablet", "2026-09-01", "active")]),
     "acei-potassium", None),
    ("haemoglobin normal, then low twice (value-added doc example)",
     rec(labs=[("hb", "2024-01-15", 13.1), ("hb", "2025-08-15", 11.4), ("hb", "2026-10-10", 10.6)]), "pattern-crossed-hemoglobin", "review"),
    ("haemoglobin normal throughout", rec(labs=[("hb", "2024-01-15", 13.1), ("hb", "2025-08-15", 12.9), ("hb", "2026-10-10", 12.6)]),
     "pattern-crossed-hemoglobin", None),
    ("haemoglobin low once only (not sustained)", rec(labs=[("hb", "2024-01-15", 13.1), ("hb", "2025-08-15", 11.4), ("hb", "2026-10-10", 12.4)]),
     "pattern-crossed-hemoglobin", None),
    # Two panels report eGFR on the same days with different values (as in the Synthea data): the rules must not
    # read the switch between sources as a decline, and the conflict itself must be flagged.
    ("eGFR from two panels that disagree, each stable", rec(labs=[
        ("egfr", "2025-01-10", 50, "panel A"), ("egfr", "2025-01-10", 31, "panel B"), ("egfr", "2025-04-10", 49, "panel A"),
        ("egfr", "2025-04-10", 30, "panel B"), ("egfr", "2025-07-10", 51, "panel A"), ("egfr", "2025-07-10", 32, "panel B"),
        ("egfr", "2025-10-10", 50, "panel A")]), "ckd-accelerated", None),
    ("eGFR from two panels that disagree: conflict flagged", rec(labs=[
        ("egfr", "2025-01-10", 50, "panel A"), ("egfr", "2025-01-10", 31, "panel B"), ("egfr", "2025-04-10", 49, "panel A"),
        ("egfr", "2025-04-10", 30, "panel B"), ("egfr", "2025-07-10", 51, "panel A"), ("egfr", "2025-07-10", 32, "panel B"),
        ("egfr", "2025-10-10", 50, "panel A")]), "lab-conflict-egfr", "review"),
    ("same value reported by two panels (no conflict)", rec(labs=[
        ("k", "2025-01-10", 4.4, "panel A"), ("k", "2025-01-10", 4.4, "panel B"), ("k", "2025-04-10", 4.5, "panel A"),
        ("k", "2025-04-10", 4.5, "panel B"), ("k", "2025-07-10", 4.3, "panel A"), ("k", "2025-07-10", 4.3, "panel B")]),
     "lab-conflict-potassium", None),
    ("lisinopril active with a recorded lisinopril allergy", rec(rx=[("lisinopril 10 MG Oral Tablet", "2026-09-01", "active")],
                                                               allergies=[("Lisinopril", "medication")]), "allergy-match", "high"),
    ("amoxicillin active with a recorded penicillin allergy", rec(rx=[("amoxicillin 500 MG Oral Capsule", "2026-09-01", "active")],
                                                                allergies=[("Penicillin V", "medication")]), "allergy-match", "high"),
    ("pollen allergy, unrelated medicine", rec(rx=[("lisinopril 10 MG Oral Tablet", "2026-09-01", "active")],
                                               allergies=[("Grass pollen (substance)", "environment")]), "allergy-match", None),
    ("systolic BP normal, then high on two visits", rec(vitals=[("sbp", "2024-02-01", 128), ("sbp", "2025-05-01", 146),
                                                              ("sbp", "2026-08-01", 152)]), "pattern-crossed-sbp", "review"),
    ("systolic BP high once only", rec(vitals=[("sbp", "2024-02-01", 128), ("sbp", "2025-05-01", 146), ("sbp", "2026-08-01", 131)]),
     "pattern-crossed-sbp", None),
    ("systolic BP 84 and 79 on two blood-pressure medicines", rec(vitals=[("sbp", "2026-05-01", 84), ("sbp", "2026-08-01", 79)],
                                                                    rx=BP_MEDS), "low-bp-on-treatment", "review"),
    ("systolic BP 84 and 79, no blood-pressure medicine", rec(vitals=[("sbp", "2026-05-01", 84), ("sbp", "2026-08-01", 79)]),
     "low-bp-on-treatment", None),
    ("systolic BP 84 and 79, blood-pressure medicine last prescribed 2019", rec(
        vitals=[("sbp", "2026-05-01", 84), ("sbp", "2026-08-01", 79)], rx=[("lisinopril 10 MG Oral Tablet", "2019-09-01", "active")]),
     "low-bp-on-treatment", None),
    ("systolic BP 118 on blood-pressure medicines", rec(vitals=[("sbp", "2026-05-01", 118), ("sbp", "2026-08-01", 121)], rx=BP_MEDS),
     "low-bp-on-treatment", None),
    ("CKD with no albumin/creatinine ratio", rec(labs=[("egfr", "2026-09-01", 50)], conds=[("Chronic kidney disease stage 3 (disorder)", "2024-01-01")]),
     "gap-ckd-acr", "review"),
    ("CKD with recent albumin/creatinine ratio", rec(labs=[("egfr", "2026-09-01", 50), ("acr", "2026-09-01", 20)],
                                                    conds=[("Chronic kidney disease stage 3 (disorder)", "2024-01-01")]), "gap-ckd-acr", None),
    ("anaemia with no haemoglobin result", rec(conds=[("Anemia (disorder)", "2020-01-01")]), "gap-hemoglobin", "review"),
    ("medicine 'active' but last prescribed 2019", rec(rx=[("Simvastatin 20 MG Oral Tablet", "2019-05-01", "active")]), "rx-stale-active", "review"),
    ("two active simvastatin products", rec(rx=[("Simvastatin 20 MG Oral Tablet", "2026-05-01", "active"),
                                                ("Simvastatin 10 MG Oral Tablet", "2026-06-01", "active")]), "rx-duplicate", "review"),
    ("metformin and 24 HR extended-release metformin both active", rec(rx=[
        ("metformin hydrochloride 500 MG Oral Tablet", "2026-05-01", "active"),
        ("24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet", "2026-06-01", "active")]), "rx-duplicate", "review"),
    ("acetaminophen tablets plus an acetaminophen-containing combination", rec(rx=[
        ("Acetaminophen 325 MG Oral Tablet", "2026-05-01", "active"),
        ("Acetaminophen 21.7 MG/ML / Dextromethorphan Hydrobromide 1 MG/ML / doxylamine succinate 0.417 MG/ML Oral Solution",
         "2026-06-01", "active")]), "rx-duplicate", "review"),
    ("metformin and simvastatin (different medicines)", rec(rx=[
        ("metformin hydrochloride 500 MG Oral Tablet", "2026-05-01", "active"),
        ("Simvastatin 20 MG Oral Tablet", "2026-06-01", "active")]), "rx-duplicate", None),
]

# Ingredient parsing (product names exactly as they appear in the Synthea pharmacy data)
INGREDIENT_CASES = [
    ("24 HR Metformin hydrochloride 500 MG Extended Release Oral Tablet", "metformin hydrochloride"),
    ("metformin hydrochloride 500 MG Oral Tablet", "metformin hydrochloride"),
    ("1 ML Epoetin Alfa 4000 UNT/ML Injection [Epogen]", "epoetin alfa"),
    ("NDA020503 200 ACTUAT Albuterol 0.09 MG/ACTUAT Metered Dose Inhaler", "albuterol"),
    ("60 ACTUAT Fluticasone propionate 0.25 MG/ACTUAT / salmeterol 0.05 MG/ACTUAT Dry Powder Inhaler",
     "fluticasone propionate / salmeterol"),
    ("heparin sodium, porcine 100 UNT/ML Injectable Solution", "heparin sodium, porcine"),
    ("{28 (norethindrone 0.35 MG Oral Tablet) } Pack [Camila 28 Day]", "norethindrone"),
    ("aspirin 81 MG Oral Capsule [Vazalore]", "aspirin"),
]


def main() -> None:
    from clinassist.analysis import ingredient
    failed = 0
    for name, want in INGREDIENT_CASES:
        got = ingredient(name)
        failed += got != want
        print(f"{'PASS' if got == want else 'FAIL'}  ingredient: {name[:60]:62s} -> {got!r}")
    for name, r, rule, expected in CASES:
        got = rules_fired(r).get(rule)
        ok = got == expected
        failed += not ok
        print(f"{'PASS' if ok else 'FAIL'}  {name:62s} {rule:28s} expected={expected} got={got}")
    total = len(CASES) + len(INGREDIENT_CASES)
    print(f"\n{total - failed}/{total} checks passed ({len(CASES)} rule scenarios, {len(INGREDIENT_CASES)} ingredient parses)")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
