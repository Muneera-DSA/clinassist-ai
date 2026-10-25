r"""ClinAssist AI: build one patient's evidence-linked review (no AI needed for this step).

    .\.venv\Scripts\python.exe .\run_patient_review.py --mrn MRN91862E3E
    .\.venv\Scripts\python.exe .\run_patient_review.py --mrn MRN91862E3E --source csv     (offline)

Reads identity from the Meterless World Model view, data through Zetaris, and writes
    data\derived\reviews\<MRN>.json   full structured result (evidence ids on everything)
    data\derived\reviews\<MRN>.md     readable evidence pack
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from clinassist.analysis import analyse  # noqa: E402
from clinassist.patient_record import CsvSource, ZetarisSource, load_record  # noqa: E402

ICON = {"high": "HIGH", "review": "REVIEW", "info": "info"}


def to_markdown(r: dict) -> str:
    p, w = r["patient"], r["window"]
    L = [f"# Evidence pack: {p['label']}", "",
         f"MRN {p['mrn']} | review date {w['as_of']} | look-back from {w['since']} | rules {r['rules_version']}",
         "Synthetic data. Findings are prompts for a qualified professional, not diagnoses or treatment advice.", ""]
    linked = ", ".join(f"{x['system']} {x['record_id']} ({x['status']})" for x in r["identity"]["linked_records"]) or "none"
    L += ["## Records used", f"Hospital {p['mrn']}; linked: {linked}."]
    if r["identity"]["pending_review"]:
        L.append("Waiting for identity review (not used): " +
                 ", ".join(f"{x['system']} {x['record_id']}" for x in r["identity"]["pending_review"]))
    c = r["counts"]
    L += [f"Items in window: {c['encounter']} encounters, {c['lab_result']} lab results, {c['observation']} vital-sign readings, "
          f"{c['procedure']} procedures, "
          f"{c['administration']} administrations; {c['condition']} conditions and {c['prescription']} prescriptions (all time).", ""]
    L += ["## Findings"]
    for f in r["findings"]:
        src = f" Source: {r['sources'][f['source']]['title']}." if f["source"] else ""
        L.append(f"- **[{ICON[f['severity']]}] {f['title']}.** {f['detail']}{src} Evidence: {', '.join(f['evidence']) or 'n/a'}")
    if not r["findings"]:
        L.append("- No rule-based findings.")
    L += ["", "## Lab trends (look-back window)", "| Test | n | First | Latest | Trend | Per year | Outside band |", "|---|---|---|---|---|---|---|"]
    for t in r["trends"].values():
        per = f"{t['slope_per_year']:+.2f} {t['unit']}" if t["slope_per_year"] is not None else "-"
        L.append(f"| {t['label']} | {t['n']} | {t['first']['value']:g} ({t['first']['date']}) | {t['latest']['value']:g} "
                 f"({t['latest']['date']}) | {t['direction']} ({t['change_pct']:+.0f}%) | {per} | "
                 f"{t['above_band']} high, {t['below_band']} low |" if t["change_pct"] is not None else
                 f"| {t['label']} | {t['n']} | {t['first']['value']:g} | {t['latest']['value']:g} | {t['direction']} | - | - |")
    L += ["", "## Medications", "| Medication | Status | First prescribed | Last prescribed | Prescriptions in window |", "|---|---|---|---|---|"]
    for m in r["medications"]:
        L.append(f"| {m['medication']} | {m['status']} | {m['first_prescribed']} | {m['last_prescribed']} | {m['prescriptions_in_window']} |")
    L += ["", "## Allergies"] + ([f"- {a['substance']} ({a['category']}; reaction: {a['reaction'] or 'not stated'})"
                                  for a in r["allergies"]] or ["- None recorded"])
    L += ["", "## Active problems"] + [f"- {x['display']} (since {x['onset']})" for x in r["active_conditions"]]
    L += ["", "## Timeline (key events)"] + [f"- {e['date']} [{e['type']}] {e['text']}" for e in r["timeline"]]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mrn", required=True)
    ap.add_argument("--as-of", default=date.today().isoformat(), help="review date, YYYY-MM-DD (default today)")
    ap.add_argument("--years", type=int, default=3)
    ap.add_argument("--source", choices=["zetaris", "csv"], default="zetaris")
    ap.add_argument("--data", default="data/derived")
    a = ap.parse_args()
    data = Path(a.data)
    if a.source == "zetaris":
        from clinassist.zetaris_client import ZetarisClient
        src = ZetarisSource(ZetarisClient.from_env())
    else:
        src = CsvSource(data)
    rec = load_record(src, data / "world", a.mrn, date.fromisoformat(a.as_of), a.years)
    result = analyse(rec)
    out = data / "reviews"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{a.mrn}.json").write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    md = to_markdown(result)
    (out / f"{a.mrn}.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"Wrote {out / (a.mrn + '.json')} and .md")


if __name__ == "__main__":
    main()
