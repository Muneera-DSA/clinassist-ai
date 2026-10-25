r"""Experiment: NVIDIA Nemotron (via Meterless Nightshift) as the summary writer, measured by the verifier.

For each selected patient and each writer lane (fast / deep) the full agent loop runs:
plan -> fetch evidence -> Nemotron draft -> verifier -> redraft or escalate.

Reported per lane:
  first-draft pass rate, final status (verified-ai / escalated), rounds used,
  verifier issues per draft by type, latency, and which model actually served each call.
Every sentence the verifier rejects is exported for human labelling (was the rejection right?),
which is how the verifier's false-alarm rate on real AI text is measured.

    .\.venv\Scripts\python.exe .\eval\bench_llm.py --patients 10
Writes data\derived\eval\llm_bench.json, llm_rejected_sentences.csv and traces\<lane>_<MRN>.jsonl
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
import time
from collections import Counter
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from clinassist.agent import Agent  # noqa: E402
from clinassist.analysis import analyse, load_rules  # noqa: E402
from clinassist.llm import NightshiftLLM  # noqa: E402
from clinassist.patient_record import ZetarisSource, load_record  # noqa: E402

TASK = "Prepare a short pre-visit summary for the clinician: the most important risks, changes over time and missing information."


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--patients", type=int, default=10)
    ap.add_argument("--lanes", default="fast,deep")
    ap.add_argument("--source", choices=["zetaris", "csv"], default="zetaris")
    ap.add_argument("--as-of", default="2026-10-24")
    ap.add_argument("--max-rounds", type=int, default=3)
    a = ap.parse_args()
    data = Path("data/derived")
    rules = load_rules()
    if a.source == "zetaris":
        from clinassist.zetaris_client import ZetarisClient
        src = ZetarisSource(ZetarisClient.from_env())
    else:
        from eval_verifier import CachedCsvSource
        src = CachedCsvSource(data)
    llm = NightshiftLLM.from_env()

    # Patient selection: deterministic, the most clinically eventful records first
    ident = json.loads((data / "world" / "patient_identity.json").read_text(encoding="utf-8"))["patients"]
    cands = []
    for p in ident:
        rec = load_record(src, data / "world", p["mrn"], date.fromisoformat(a.as_of), 3)
        res = analyse(rec, rules)
        nf = len([f for f in res["findings"] if f["severity"] in ("high", "review")])
        if nf >= 2:
            cands.append((-sum(f["severity"] == "high" for f in res["findings"]), -nf, p["mrn"], rec, res))
    cands.sort(key=lambda c: c[:3])
    chosen = cands[: a.patients]
    print(f"{len(cands)} eligible patients; benchmarking {len(chosen)}: {[c[2] for c in chosen]}", flush=True)

    out = data / "eval"
    (out / "traces").mkdir(parents=True, exist_ok=True)
    runs, rejected = [], []
    for lane in a.lanes.split(","):
        for _, _, mrn, rec, res in chosen:
            agent = Agent(llm, max_rounds=a.max_rounds, writer_deep=(lane == "deep"))
            t0 = time.time()
            try:
                r = agent.run(TASK, rec, res, rules)
                err = None
            except Exception as e:  # keep the benchmark going; record the failure
                r, err = None, f"{type(e).__name__}: {str(e)[:200]}"
            secs = round(time.time() - t0, 1)
            trace = agent.trace
            (out / "traces" / f"{lane}_{mrn}.jsonl").write_text("\n".join(json.dumps(t, default=str) for t in trace), encoding="utf-8")
            verdicts = [t for t in trace if t["agent"] == "evaluator"]
            drafts = [t for t in trace if t["agent"] == "writer" and t["action"] == "draft"]
            for v, d in zip(verdicts, drafts):
                for i in v["issues"]:
                    if "sentence" in i:
                        rejected.append({"lane": lane, "mrn": mrn, "round": v["round"], "issue": i["type"],
                                         "value": i.get("value", ""), "sentence": i["sentence"],
                                         "label_rejection_correct": ""})
            runs.append({
                "lane": lane, "mrn": mrn, "error": err, "status": r.status if r else "error", "rounds": len(verdicts),
                "first_draft_passed": bool(verdicts and verdicts[0]["passed"]),
                "first_draft_issues": Counter(i["type"] for i in verdicts[0]["issues"]) if verdicts else {},
                "first_draft_sentences": verdicts[0]["stats"].get("sentences") if verdicts else None,
                "served_models": sorted({t.get("model", "") for t in trace if t.get("model")}),
                "writer_seconds": [d["seconds"] for d in drafts], "total_seconds": secs,
                "plan": [s["tool"] for s in (r.plan if r else [])],
            })
            print(f"{lane:5s} {mrn}  {runs[-1]['status']:15s} rounds {runs[-1]['rounds']}  first-pass {runs[-1]['first_draft_passed']}  "
                  f"{secs}s  models {runs[-1]['served_models']}", flush=True)

    summary = {}
    for lane in a.lanes.split(","):
        rs = [r for r in runs if r["lane"] == lane]
        ok = [r for r in rs if r["status"] != "error"]
        issues = Counter()
        for r in ok:
            issues.update(r["first_draft_issues"])
        summary[lane] = {
            "runs": len(rs), "errors": len(rs) - len(ok),
            "verified_ai": sum(r["status"] == "verified-ai" for r in ok),
            "escalated": sum(r["status"] == "escalated" for r in ok),
            "first_draft_pass_rate": round(sum(r["first_draft_passed"] for r in ok) / len(ok), 3) if ok else None,
            "mean_rounds": round(statistics.mean(r["rounds"] for r in ok), 2) if ok else None,
            "median_total_seconds": statistics.median(r["total_seconds"] for r in ok) if ok else None,
            "first_draft_issues_per_draft": {k: round(v / len(ok), 2) for k, v in issues.items()} if ok else {},
            "served_models": sorted({m for r in rs for m in r["served_models"]}),
        }
    (out / "llm_bench.json").write_text(json.dumps({"task": TASK, "summary": summary, "runs": runs}, indent=2, default=str), encoding="utf-8")
    with open(out / "llm_rejected_sentences.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["lane", "mrn", "round", "issue", "value", "sentence", "label_rejection_correct"])
        w.writeheader()
        w.writerows(rejected)
    print("\n" + json.dumps(summary, indent=2))
    print(f"\nRejected sentences for labelling: {len(rejected)} -> {out / 'llm_rejected_sentences.csv'}")


if __name__ == "__main__":
    main()
