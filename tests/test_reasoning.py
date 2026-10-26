r"""Checks for the clinical-reasoning sections Nemotron writes (no AI or network needed).

    .\.venv\Scripts\python.exe .\tests\test_reasoning.py

The writer produces three sections: '# Pre-visit summary', '## How the findings connect' and
'## Questions for the clinician'. The checker must accept grounded links between findings, reject a "link"
that stands on only one finding, still catch invented numbers and treatment orders in the new sections,
and the answer extractor must keep the sub-sections.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clinassist.verifier import evaluate, ids_in, template_summary  # noqa: E402
from clinassist.analysis import analyse, load_rules  # noqa: E402
from clinassist.llm import final_answer  # noqa: E402
from clinassist.patient_record import CsvSource, load_record  # noqa: E402

DATA = Path("data/derived")


def main() -> None:
    rec = load_record(CsvSource(DATA), DATA / "world", "MRN91862E3E", date(2026, 10, 24), 3)
    result = analyse(rec, load_rules())
    retrieved = ids_in(result)
    by_rule = {f["rule"]: f for f in result["findings"]}
    kidney, alen, bp = by_rule["ckd-accelerated"], by_rule["renal-alendronate"], by_rule["low-bp-on-treatment"]
    cite = lambda *fs: "[" + ", ".join(e for f in fs for e in f["evidence"][:2]) + "]"  # noqa: E731
    summary = template_summary(result)
    checks = []

    def check(name, cond, detail=""):
        checks.append(cond)
        print(f"{'PASS' if cond else 'FAIL'}  {name}  {detail}")

    good = (summary + "\n\n## How the findings connect\n"
            f"- The accelerated fall in kidney function bears directly on the alendronate finding, whose safety depends on kidney function. {cite(kidney, alen)}\n"
            f"- Low blood pressure readings sit alongside the kidney decline, so both belong in one review. {cite(bp, kidney)}\n"
            "\n## Questions for the clinician\n"
            f"- Has creatinine clearance been calculated for the alendronate review? {cite(alen)}\n")
    v = evaluate(good, retrieved, rec, result)
    check("grounded connections and questions pass", v.passed and v.stats["connections"] == 2 and v.stats["questions"] == 1,
          f"{v.stats} {[i['type'] for i in v.issues]}")

    one = summary + f"\n\n## How the findings connect\n- Kidney function is falling over time. {cite(kidney)}\n"
    v = evaluate(one, retrieved, rec, result)
    check("a 'connection' citing only one finding is rejected", any(i["type"] == "connection-not-grounded" for i in v.issues),
          str([i["type"] for i in v.issues]))

    invented = summary + f"\n\n## How the findings connect\n- Kidney function fell by 61 points while alendronate continued. {cite(kidney, alen)}\n"
    v = evaluate(invented, retrieved, rec, result)
    check("an invented number in a connection is rejected", any(i["type"] == "unsupported-number" for i in v.issues),
          str([(i["type"], i.get("value")) for i in v.issues]))

    order = summary + f"\n\n## Questions for the clinician\n- Alendronate should be stopped given the kidney decline? {cite(kidney, alen)}\n"
    v = evaluate(order, retrieved, rec, result)
    check("a treatment order disguised as a question is rejected", any(i["type"] == "treatment-directive" for i in v.issues),
          str([i["type"] for i in v.issues]))

    thinking = "The user wants three sections. I will write # Pre-visit summary first.\nLet me check.\n\n" + good
    out = final_answer(thinking)
    check("answer extraction keeps the '##' sections", out.startswith("# Pre-visit summary") and "## Questions for the clinician" in out
          and "The user wants" not in out)

    print(f"\n{sum(checks)}/{len(checks)} checks passed")
    sys.exit(0 if all(checks) else 1)


if __name__ == "__main__":
    main()
