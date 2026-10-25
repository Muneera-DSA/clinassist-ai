r"""Experiment: patient-matching threshold sweep, ablation of the safety rules, and baselines.

Questions answered:
  1. How do wrong merges, missed links and review workload change as the auto-link threshold moves?
  2. What does each safety rule (exact date of birth for auto-link; ambiguity margin) contribute?
  3. How does ClinAssist compare with (a) exact surname + date-of-birth matching and
     (b) the Meterless World Model's built-in name-similarity resolver (Levenshtein, 0.85 / 0.82)?

Run on every generated dataset (different random seeds) with and without 50 look-alike "twins".
    .\.venv\Scripts\python.exe .\eval\eval_matching.py
Writes data\derived\eval\matching_sweep.csv and matching_summary.json
"""
from __future__ import annotations

import csv
import json
import random
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clinassist import matching as m  # noqa: E402

DATA = Path("data/derived")


def load(ds: Path):
    rd = lambda p: list(csv.DictReader(open(ds / p, encoding="utf-8")))  # noqa: E731
    hosp = [m.from_hospital(r) for r in rd("hospital/patients.csv")]
    others = {"laboratory": [m.from_laboratory(r) for r in rd("laboratory/lab_patients.csv")],
              "pharmacy": [m.from_pharmacy(r) for r in rd("pharmacy/pharmacy_patients.csv")]}
    truth = {"laboratory": {}, "pharmacy": {}}
    for r in rd("_truth/identity_crosswalk.csv"):
        if r["lab_patient_id"]:
            truth["laboratory"][r["lab_patient_id"]] = r["mrn"]
        if r["pharm_patient_id"]:
            truth["pharmacy"][r["pharm_patient_id"]] = r["mrn"]
    return hosp, others, truth


def add_twins(hosp: list[m.Person], seed: int) -> list[m.Person]:
    """50 extra hospital patients sharing surname, DOB and sex with a real one (10 with a 1-letter first-name change)."""
    rng = random.Random(seed)
    names = [h.given for h in hosp]
    twins = []
    for h in rng.sample(hosp, 40):
        g = rng.choice([n for n in names if n != h.given and n[:3] != h.given[:3]])
        twins.append(m.Person("hospital", "TWIN-" + h.record_id, h.family, g, h.dob, h.sex))
    for h in rng.sample(hosp, 10):
        twins.append(m.Person("hospital", "TWIN1-" + h.record_id, h.family, h.given[:-1] + ("A" if h.given[-1] != "A" else "E"), h.dob, h.sex))
    return hosp + twins


# ------------------------------------------------------------------ Meterless World Model resolver (ported 1:1 from resolve.ts)

def wm_normalize(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.lower().split())


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i in range(1, len(a) + 1):
        cur = [i] + [0] * len(b)
        for j in range(1, len(b) + 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] != b[j - 1]))
        prev = cur
    return prev[len(b)]


def wm_similarity(a: str, b: str) -> float:
    a, b = wm_normalize(a), wm_normalize(b)
    mx = max(len(a), len(b))
    return 1.0 if mx == 0 else 1 - levenshtein(a, b) / mx


def wm_links(hosp, others, auto=0.85, review=0.82):
    """Name-only resolution as the World Model would do for name-keyed entities: best-scoring hospital patient."""
    out = []
    for o in others:
        best, sim = None, -1.0
        for h in hosp:
            s = wm_similarity(f"{o.given} {o.family}", f"{h.given} {h.family}")
            if s > sim:
                best, sim = h, s
        d = "auto-link" if sim >= auto else ("review" if sim >= review else "no-match")
        out.append(m.Link(o.system, o.record_id, o.label(), d, best.record_id if d != "no-match" else None, None, sim, []))
    return out


# ------------------------------------------------------------------ metrics

def make_scenario(name: str, hosp0: list[m.Person], seed: int) -> list[m.Person]:
    """Stress scenarios. Truth never changes; only the hospital index does."""
    rng = random.Random(seed)
    if name == "plain":
        return hosp0
    if name == "twins":  # look-alikes added next to the real patient
        return add_twins(hosp0, seed)
    names = [h.given for h in hosp0]
    if name == "out-of-index":  # real patient NOT in the index, a look-alike is (e.g. registered at another hospital)
        chosen = rng.sample(hosp0, 20)
        gone = {h.record_id for h in chosen}
        extra = []
        for k, h in enumerate(chosen):
            g = (h.given[:-1] + ("A" if h.given[-1] != "A" else "E")) if k % 2 else \
                rng.choice([n for n in names if n != h.given and n[:3] != h.given[:3]])
            extra.append(m.Person("hospital", "LOOKALIKE-" + h.record_id, h.family, g, h.dob, h.sex))
        return [h for h in hosp0 if h.record_id not in gone] + extra
    if name == "namesakes":  # same full name, different person (different DOB); half without the real patient
        chosen = rng.sample(hosp0, 30)
        gone = {h.record_id for h in chosen[:15]}
        extra = []
        for h in chosen:
            if h.dob is None:
                continue
            dob = h.dob.replace(year=h.dob.year + rng.choice([-20, -9, -3, -1, 1, 4, 11]), day=min(h.dob.day, 28))
            extra.append(m.Person("hospital", "NAMESAKE-" + h.record_id, h.family, h.given, dob, h.sex))
        return [h for h in hosp0 if h.record_id not in gone] + extra
    raise ValueError(name)


SCENARIOS = ["plain", "twins", "out-of-index", "namesakes"]


def score(links, truth, present: set[str]) -> dict:
    """present = MRNs in this hospital index. A record whose true patient is absent must NOT be auto-linked."""
    auto = [l for l in links if l.decision == "auto-link"]
    rev = [l for l in links if l.decision == "review"]
    has_true = [rid for rid, mrn in truth.items() if mrn in present]
    absent = [rid for rid, mrn in truth.items() if mrn not in present]
    auto_ok = sum(truth.get(l.record_id) == l.mrn for l in auto)
    rev_ok = sum(truth.get(l.record_id) == l.mrn for l in rev)
    by_id = {l.record_id: l for l in links}
    n = len(has_true)
    return {"records": len(truth), "records_true_present": n, "records_true_absent": len(absent),
            "auto": len(auto), "auto_correct": auto_ok, "wrong_merges": len(auto) - auto_ok,
            "review": len(rev), "review_correct": rev_ok,
            "missed": sum(1 for rid in has_true if by_id.get(rid) and by_id[rid].decision == "no-match"),
            "absent_not_autolinked": sum(1 for rid in absent if by_id.get(rid) and by_id[rid].decision != "auto-link"),
            "recall_auto": round(auto_ok / n, 4) if n else None,
            "recall_after_review": round((auto_ok + rev_ok) / n, 4) if n else None}


METHODS = (("ClinAssist (full)", {}), ("no exact-DOB rule", {"require_exact_dob": False}),
           ("no ambiguity margin", {"margin": None}), ("no safety rules", {"require_exact_dob": False, "margin": None}))
THRESHOLDS = [x / 2 for x in range(8, 26)]  # 4.0 .. 12.5
SUM_KEYS = ("records", "records_true_present", "records_true_absent", "auto", "auto_correct", "wrong_merges",
            "review", "review_correct", "missed", "absent_not_autolinked")


def main() -> None:
    import functools
    m.compare = functools.lru_cache(maxsize=None)(m.compare)  # same pairs are re-scored at every threshold
    datasets = [("seed42", DATA)] + [(p.name.replace("holdout_", ""), p) for p in sorted(DATA.glob("holdout_seed*"))]
    rows = []
    for di, (ds_name, ds) in enumerate(datasets):
        hosp0, others, truth = load(ds)
        for sc in SCENARIOS:
            hosp = make_scenario(sc, hosp0, 100 + di)
            present = {h.record_id for h in hosp}
            for system, recs in others.items():
                t = truth[system]
                base = {"dataset": ds_name, "scenario": sc, "system": system}
                ex = m.naive_exact(hosp, recs)
                ex_links = [m.Link(system, o.record_id, "", "auto-link" if o.record_id in ex else "no-match",
                                   ex.get(o.record_id), None, None, []) for o in recs]
                rows.append({**base, "method": "exact surname+DOB", "threshold": "", **score(ex_links, t, present)})
                rows.append({**base, "method": "World Model name resolver", "threshold": 0.85,
                             **score(wm_links(hosp, recs), t, present)})
                for label, kw in METHODS:
                    for th in THRESHOLDS:
                        rows.append({**base, "method": label, "threshold": th,
                                     **score(m.link_system(hosp, recs, auto_link=th, **kw), t, present)})
            print(f"done {ds_name} {sc}", flush=True)

    out = DATA / "eval"
    out.mkdir(parents=True, exist_ok=True)
    with open(out / "matching_sweep.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)

    def pooled(method, th, sc):
        sel = [r for r in rows if r["method"] == method and str(r["threshold"]) == str(th) and r["scenario"] == sc]
        agg = {k: sum(r[k] for r in sel) for k in SUM_KEYS}
        n = agg["records_true_present"]
        agg["recall_auto"] = round(agg["auto_correct"] / n, 4)
        agg["recall_after_review"] = round((agg["auto_correct"] + agg["review_correct"]) / n, 4)
        return agg

    summary = {"datasets": [d for d, _ in datasets], "scenarios": SCENARIOS, "comparison": {}, "ablation_at_9": {}, "sweep_full": {}}
    for sc in SCENARIOS:
        summary["comparison"][sc] = {"exact surname+DOB": pooled("exact surname+DOB", "", sc),
                                     "World Model name resolver": pooled("World Model name resolver", 0.85, sc),
                                     "ClinAssist (full, threshold 9)": pooled("ClinAssist (full)", 9.0, sc)}
        summary["ablation_at_9"][sc] = {lab: pooled(lab, 9.0, sc) for lab, _ in METHODS}
        summary["sweep_full"][sc] = {th: pooled("ClinAssist (full)", th, sc) for th in THRESHOLDS}
    (out / "matching_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    fmt = lambda k, v: (f"  {k:32s} auto {v['auto']:4d} WRONG {v['wrong_merges']:3d} review {v['review']:3d} "  # noqa: E731
                        f"missed {v['missed']:3d} recall_auto {v['recall_auto']:.3f} after_review {v['recall_after_review']:.3f} "
                        f"absent-safe {v['absent_not_autolinked']}/{v['records_true_absent']}")
    for sc in SCENARIOS:
        print(f"\n== {sc}: methods (pooled over {len(datasets)} datasets x 2 systems)")
        for k, v in summary["comparison"][sc].items():
            print(fmt(k, v))
        print(f"-- {sc}: ablation at threshold 9")
        for k, v in summary["ablation_at_9"][sc].items():
            print(fmt(k, v))
    print("\n== threshold sweep, ClinAssist (full), scenario out-of-index")
    for th, v in summary["sweep_full"]["out-of-index"].items():
        print(f"  {th:5.1f} WRONG {v['wrong_merges']:3d} review {v['review']:3d} recall_auto {v['recall_auto']:.3f}")


if __name__ == "__main__":
    main()
