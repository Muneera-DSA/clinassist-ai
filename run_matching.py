r"""ClinAssist AI: match the same patient across hospital, lab and pharmacy systems.

Default: reads the three systems through Zetaris (federated SQL over REST).
    .\.venv\Scripts\python.exe .\run_matching.py

Offline check against local CSVs (for testing without Zetaris):
    .\.venv\Scripts\python.exe .\run_matching.py --source csv --data data\derived

Writes:
    data\derived\identity\identity_links.csv   one row per lab / pharmacy patient
    data\derived\identity\review_queue.csv     the cases a person must confirm
    data\derived\identity\matching_report.json counts, and accuracy if --score
    data\derived\identity\identity_links.json  hand-off to the Meterless World Model

--score compares the result with the answer key in data\derived\_truth. The
answer key is only read for scoring, after all decisions are made.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clinassist import matching as m  # noqa: E402

SQL = {
    "hospital": ("SELECT mrn, given_name, family_name, date_format(birth_date, 'yyyy-MM-dd') AS birth_date, sex "
                 "FROM hospital_ehr.patients",
                 ["mrn", "given_name", "family_name", "birth_date", "sex"]),
    "laboratory": ("SELECT lab_patient_id, surname, forenames, dob, gender FROM lab_lis.lab_patients",
                   ["lab_patient_id", "surname", "forenames", "dob", "gender"]),
    "pharmacy": ("SELECT pharm_patient_id, full_name, birth_date, sex FROM pharmacy_rx.pharmacy_patients",
                 ["pharm_patient_id", "full_name", "birth_date", "sex"]),
}
CSV = {"hospital": "hospital/patients.csv", "laboratory": "laboratory/lab_patients.csv",
       "pharmacy": "pharmacy/pharmacy_patients.csv"}


def load(source: str, data_dir: Path) -> dict[str, list[dict]]:
    if source == "zetaris":
        from clinassist.zetaris_client import ZetarisClient
        z = ZetarisClient.from_env()
        return {k: z.rows(sql, cols) for k, (sql, cols) in SQL.items()}
    out = {}
    for k, rel in CSV.items():
        with open(data_dir / rel, newline="", encoding="utf-8") as fh:
            out[k] = list(csv.DictReader(fh))
    return out


def load_truth(data_dir: Path) -> dict[str, dict[str, str]]:
    lab, rx = {}, {}
    with open(data_dir / "_truth" / "identity_crosswalk.csv", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["lab_patient_id"]:
                lab[r["lab_patient_id"]] = r["mrn"]
            if r["pharm_patient_id"]:
                rx[r["pharm_patient_id"]] = r["mrn"]
    return {"laboratory": lab, "pharmacy": rx}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", choices=["zetaris", "csv"], default="zetaris")
    ap.add_argument("--data", default="data/derived", help="folder with the CSVs and _truth (csv mode / scoring)")
    ap.add_argument("--out", default=None, help="output folder (default: <data>/identity)")
    ap.add_argument("--score", action="store_true", help="score against the answer key after matching")
    a = ap.parse_args()
    data_dir = Path(a.data)
    out_dir = Path(a.out) if a.out else data_dir / "identity"
    out_dir.mkdir(parents=True, exist_ok=True)

    raw = load(a.source, data_dir)
    hospital = [m.from_hospital(r) for r in raw["hospital"]]
    others = {"laboratory": [m.from_laboratory(r) for r in raw["laboratory"]],
              "pharmacy": [m.from_pharmacy(r) for r in raw["pharmacy"]]}
    print(f"Loaded via {a.source}: hospital {len(hospital)}, laboratory {len(others['laboratory'])}, "
          f"pharmacy {len(others['pharmacy'])} patients")

    all_links, report = [], {"source": a.source,
                             "thresholds": {"auto_link": m.AUTO_LINK, "review": m.REVIEW,
                                            "ambiguity_margin": m.AMBIGUITY_MARGIN}, "systems": {}}
    for system, people in others.items():
        links = m.link_system(hospital, people)
        all_links += links
        counts = {d: sum(l.decision == d for l in links) for d in ("auto-link", "review", "no-match")}
        baseline = m.naive_exact(hospital, people)
        report["systems"][system] = {"records": len(people), **counts, "baseline_exact_links": len(baseline)}
        print(f"\n{system}: {len(people)} patients -> auto-link {counts['auto-link']}, "
              f"review {counts['review']}, no match {counts['no-match']}   "
              f"(exact surname+DOB baseline links {len(baseline)})")
        if a.score:
            truth = load_truth(data_dir)[system]
            ev = m.evaluate(links, truth, baseline)
            report["systems"][system]["accuracy"] = ev
            print(f"   vs answer key: auto-links correct {ev['auto_link_correct']}/{ev['auto_link']} "
                  f"(wrong merges {ev['auto_link_wrong_merges']}), review top candidate correct "
                  f"{ev['review_top_candidate_correct']}/{ev['review']}, missed {ev['no_match_but_truth_exists']}; "
                  f"baseline correct {ev['baseline_exact_correct']}/{ev['records']}")

    fields = ["system", "record_id", "record_label", "decision", "mrn", "hospital_label", "score",
              "runner_up_mrn", "runner_up_score", "reasons"]
    with open(out_dir / "identity_links.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for l in all_links:
            row = {f: getattr(l, f) for f in fields if f != "reasons"}
            row["reasons"] = " | ".join(l.reasons)
            w.writerow(row)
    with open(out_dir / "review_queue.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for l in all_links:
            if l.decision != "auto-link":
                row = {f: getattr(l, f) for f in fields if f != "reasons"}
                row["reasons"] = " | ".join(l.reasons)
                w.writerow(row)
    (out_dir / "matching_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Machine-readable hand-off to the Meterless World Model (wm/build_world.ts).
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    (out_dir / "identity_links.json").write_text(json.dumps({
        "generated_at": now,
        "run_id": "match-" + now.replace(":", "").replace("-", ""),
        "source": a.source,
        "hospital": [{"mrn": h.record_id, "label": h.label()} for h in hospital],
        "links": [{**{f: getattr(l, f) for f in fields if f != "reasons"}, "reasons": l.reasons} for l in all_links],
    }, indent=2), encoding="utf-8")

    print("\nCases for a person to confirm:")
    for l in all_links:
        if l.decision != "auto-link":
            print(f"  [{l.decision}] {l.system} {l.record_id} {l.record_label} -> {l.mrn} {l.hospital_label or ''}")
            print(f"      why: {l.reasons[-1]}")
    print(f"\nWrote {out_dir}")


if __name__ == "__main__":
    main()
