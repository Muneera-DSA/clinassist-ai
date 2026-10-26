r"""Audit: do the three databases, as seen through Zetaris, hold exactly what the CSVs hold?

For every table: row count, distinct primary keys, and (for numeric tables) the sum of the value column,
read through Zetaris and compared with the local CSV files. Read-only.

    .\.venv\Scripts\python.exe .\eval\audit_sources.py
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clinassist.sources import systems, zt  # noqa: E402
from clinassist.zetaris_client import ZetarisClient  # noqa: E402

D = Path("data/derived")
CHECKS = [  # zetaris table, csv, primary key, numeric column (or None)
    ("hospital_ehr.patients", "hospital/patients.csv", "mrn", None),
    ("hospital_ehr.encounters", "hospital/encounters.csv", "encounter_id", None),
    ("hospital_ehr.conditions", "hospital/conditions.csv", "condition_id", None),
    ("hospital_ehr.procedures", "hospital/procedures.csv", "procedure_id", None),
    ("hospital_ehr.observations", "hospital/observations.csv", "observation_id", "value_num"),
    ("hospital_ehr.allergies", "hospital/allergies.csv", "allergy_id", None),
    ("lab_lis.lab_patients", "laboratory/lab_patients.csv", "lab_patient_id", None),
    ("lab_lis.lab_results", "laboratory/lab_results.csv", "result_id", "value_num"),
    ("lab_lis.lab_reports", "laboratory/lab_reports.csv", "report_id", None),
    ("pharmacy_rx.pharmacy_patients", "pharmacy/pharmacy_patients.csv", "pharm_patient_id", None),
    ("pharmacy_rx.prescriptions", "pharmacy/prescriptions.csv", "rx_id", "dose_value"),
    ("pharmacy_rx.administrations", "pharmacy/administrations.csv", "admin_id", None),
]


def main() -> None:
    z = ZetarisClient.from_env()
    ok = True
    for table, rel, pk, num in CHECKS:
        rows = list(csv.DictReader(open(D / rel, encoding="utf-8")))
        c_n, c_pk = len(rows), len({r[pk] for r in rows})
        c_sum = round(sum(float(r[num]) for r in rows if r[num] not in ("", None)), 2) if num else None
        sel = f"COUNT(*) AS n, COUNT(DISTINCT {pk}) AS k" + (f", ROUND(SUM({num}), 2) AS s" if num else "")
        cols = ["n", "k"] + (["s"] if num else [])
        got = z.rows(f"SELECT {sel} FROM {zt(table)}", cols)[0]
        z_n, z_pk = int(float(got["n"])), int(float(got["k"]))
        z_sum = round(float(got["s"]), 2) if num and got["s"] not in ("", None) else None
        match = z_n == c_n and z_pk == c_pk and (num is None or abs((z_sum or 0) - (c_sum or 0)) < 0.05)
        ok &= match
        engine = {"Microsoft SQL Server 2022": "SQL Server"}.get(systems()[table.split(".")[0]]["engine"],
                                                               systems()[table.split(".")[0]]["engine"].split(" ")[0])
        print(f"{'OK  ' if match else 'DIFF'} {table:32s} [{engine:20s}] rows csv {c_n:6d} / zetaris {z_n:6d}   keys {c_pk:6d} / {z_pk:6d}"
              + (f"   sum({num}) {c_sum} / {z_sum}" if num else ""))
    print("\nALL MATCH" if ok else "\nMISMATCH FOUND - see DIFF lines")


if __name__ == "__main__":
    main()
