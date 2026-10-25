r"""Experiment: how well does the groundedness verifier catch unsupported summary text?

No AI needed. For every patient we take a verified, evidence-cited summary, then:
  * build CLEAN variants (reordered, numbers rounded, reworded) -> the verifier should PASS them;
  * inject one known error at a time (mutations below)           -> the verifier should FAIL them.

Reported per mutation type: detection rate with a 95% Wilson interval; plus the false-alarm rate
on clean variants. Mutations the verifier is NOT designed to catch (a plausible claim with a valid
citation and no number) are included on purpose, to measure the blind spot honestly.

    .\.venv\Scripts\python.exe .\eval\eval_verifier.py --seed 7      (reads the local CSVs; no Zetaris or AI needed)
Writes data\derived\eval\verifier_results.json and verifier_cases.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clinassist.agent import CITE, DATE, NUM, evaluate, ids_in, sentences, template_summary  # noqa: E402
from clinassist.analysis import analyse, load_rules  # noqa: E402
from clinassist.patient_record import TABLES, load_record  # noqa: E402


class CachedCsvSource:
    """Loads each CSV once and indexes it by patient key (fast batch evaluation)."""

    def __init__(self, data_dir: Path):
        self.idx: dict[str, dict[str, list[dict]]] = {}
        for kind, (_, rel, _, key_col, _, cols) in TABLES.items():
            d: dict[str, list[dict]] = defaultdict(list)
            with open(data_dir / rel, newline="", encoding="utf-8") as fh:
                for r in csv.DictReader(fh):
                    d[r[key_col]].append({c: r.get(c, "") or "" for c in cols})
            self.idx[kind] = d

    def fetch(self, kind, keys, since):
        date_col = TABLES[kind][4]
        return [r for k in keys for r in self.idx[kind].get(k, [])
                if not since or not date_col or (r[date_col] or "") >= since]


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    if n == 0:
        return [0.0, 0.0]
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(max(0, c - h), 4), round(min(1, c + h), 4)]


# ------------------------------------------------------------------ clean variants

def clean_variants(text: str, rng: random.Random) -> dict[str, str]:
    lines = text.splitlines()
    head, body = lines[:1], lines[1:]
    shuffled = body[:]
    rng.shuffle(shuffled)

    def round_big(m):  # 47.89 -> 48 : a faithful rounding a writer might do
        v = float(m.group(0))
        return str(round(v)) if v >= 10 and "." in m.group(0) else m.group(0)

    def protect(line, fn):  # apply fn to text outside citations and dates
        keep = []
        tmp = DATE.sub(lambda m: keep.append(m.group(0)) or f"\x00{len(keep) - 1}\x00", CITE.sub(
            lambda m: keep.append(m.group(0)) or f"\x00{len(keep) - 1}\x00", line))
        parts = tmp.split("\x00")
        return "".join(keep[int(x)] if k % 2 else fn(x) for k, x in enumerate(parts))

    out_r = [protect(l, lambda t: NUM.sub(round_big, t)) for l in body]
    reworded = [re.sub(r"^- ", "- Of note, ", l) for l in body]
    return {"original": text, "reordered": "\n".join(head + shuffled),
            "rounded": "\n".join(head + out_r), "reworded": "\n".join(head + reworded)}


# ------------------------------------------------------------------ mutations (one error each)

def _pick(rng, items):
    return rng.choice(items) if items else None


def mutate(text: str, kind: str, rng: random.Random, retrieved: list[str], result: dict) -> str | None:
    lines = text.splitlines()
    idx = [i for i, l in enumerate(lines) if l.startswith("- ")]
    if kind == "number-changed":
        cands = [i for i in idx if [n for n in NUM.findall(DATE.sub("", CITE.sub("", lines[i]))) if float(n) >= 10]]
        i = _pick(rng, cands)
        if i is None:
            return None
        body, cites = CITE.sub("\x00", lines[i]), CITE.findall(lines[i])
        nums = [m for m in NUM.finditer(DATE.sub(lambda d: "#" * len(d.group(0)), body)) if float(m.group(0)) >= 10]
        m = rng.choice(nums)
        v = float(m.group(0))
        new = v * rng.choice([0.8, 0.85, 1.15, 1.25, 1.5])
        rep = f"{new:.{len(m.group(0).split('.')[1]) if '.' in m.group(0) else 0}f}"
        if float(rep) == v:
            rep = str(int(v) + 7)
        body = body[:m.start()] + rep + body[m.end():]
        for c in cites:
            body = body.replace("\x00", f"[{c}]", 1)
        lines[i] = body
    elif kind == "date-shifted":
        cands = [i for i in idx if DATE.search(CITE.sub("", lines[i]))]
        i = _pick(rng, cands)
        if i is None:
            return None
        d = DATE.search(CITE.sub("", lines[i])).group(0)
        nd = (date.fromisoformat(d) + timedelta(days=rng.choice([-40, -9, 3, 14, 60]))).isoformat()
        lines[i] = lines[i].replace(d, nd, 1)
    elif kind == "fabricated-citation":
        cands = [i for i in idx if CITE.search(lines[i])]
        i = _pick(rng, cands)
        if i is None:
            return None
        lines[i] = CITE.sub(lambda c: f"[E-lab_result-R{rng.randrange(16**10):010X}]", lines[i], count=1)
    elif kind == "citation-swapped":   # real id that was retrieved, but does not support the sentence
        cands = [i for i in idx if CITE.search(lines[i])]
        i = _pick(rng, cands)
        if i is None:
            return None
        own = set(c.strip() for g in CITE.findall(lines[i]) for c in g.split(","))
        other = [r for r in retrieved if r not in own and r.startswith("E-prescription")] or [r for r in retrieved if r not in own]
        if not other:
            return None
        lines[i] = CITE.sub("", lines[i]).rstrip(" .") + f" [{rng.choice(other)}]."
    elif kind == "citation-dropped":
        cands = [i for i in idx if CITE.search(lines[i])]
        i = _pick(rng, cands)
        if i is None:
            return None
        lines[i] = CITE.sub("", lines[i]).replace(" .", ".")
    elif kind == "high-finding-omitted":
        highs = [f for f in result["findings"] if f["severity"] == "high" and f["evidence"]]
        if not highs:
            return None
        f = rng.choice(highs)
        ev = set(f["evidence"])
        need = min(2, len(ev))
        # all-lines: delete every line that cites any of the finding's evidence (easy to catch)
        # own-line: delete only the finding's own statement; other lines may still cite some of the same records
        mutate.variant = rng.choice(["all-lines", "own-line"])
        def cites(l):
            return set(c.strip() for g in CITE.findall(l) for c in g.split(","))
        if mutate.variant == "all-lines":
            keep = [l for l in lines if not (cites(l) & ev)]
        else:
            keep = [l for l in lines if len(cites(l) & ev) < need]
        if len(keep) == len(lines):
            return None
        lines = keep
    elif kind == "treatment-directive":
        med = _pick(rng, [m for m in result["medications"] if m["status"] == "active"])
        if med is None:
            return None
        # half the phrasings were used while building the detector, half were held out to test generalisation
        phr = ["{m} should be stopped", "{m} should be discontinued", "{m} should be increased", "{m} must be switched",
                           "Recommend discontinuing {m}", "{m} ought to be reduced", "Hold {m} until review",
                           "Begin a lower dose of {m}", "Taper {m} over two weeks", "Avoid further doses of {m}"]
        j = rng.randrange(len(phr))
        mutate.variant = "tuned" if j < 4 else "held-out"
        lines.append(f"- {phr[j].format(m=med['medication'])} [{med['evidence'][0]}].")
    elif kind == "unsupported-claim-no-number":  # semantic error: deliberately outside this verifier's design
        cands = [r for r in retrieved if r.startswith("E-lab_result")]
        if not cands:
            return None
        claim = rng.choice(["The patient has documented heart failure", "Liver function tests are abnormal",
                            "The patient was admitted to intensive care", "A penicillin allergy is recorded"])
        lines.append(f"- {claim} [{rng.choice(cands)}].")
    else:
        raise ValueError(kind)
    return "\n".join(lines)


MUTATIONS = ["number-changed", "date-shifted", "fabricated-citation", "citation-swapped", "citation-dropped",
             "high-finding-omitted", "treatment-directive", "unsupported-claim-no-number"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/derived")
    ap.add_argument("--as-of", default="2026-10-24")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--reps", type=int, default=3, help="mutations of each type per patient")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    data = Path(a.data)
    rules = load_rules()
    src = CachedCsvSource(data)
    ident = json.loads((data / "world" / "patient_identity.json").read_text(encoding="utf-8"))["patients"]

    rows, clean_n, clean_fp, skipped = [], 0, 0, 0
    per = defaultdict(lambda: [0, 0])
    issues_seen = defaultdict(lambda: defaultdict(int))
    for p in ident:
        rec = load_record(src, data / "world", p["mrn"], date.fromisoformat(a.as_of), 3)
        result = analyse(rec, rules)
        base = template_summary(result)
        retrieved = sorted(ids_in(result))
        if len(sentences(base)) < 2:
            skipped += 1  # too little content to mutate (patients with few or no findings)
            continue
        if not evaluate(base, set(retrieved), rec, result).passed:
            clean_n += 1  # the verified starting point itself was rejected: a false alarm, not a skip
            clean_fp += 1
            rows.append({"mrn": p["mrn"], "case": "clean:base", "expected": "pass", "got": "fail", "issues": "base-rejected"})
            continue
        for name, text in clean_variants(base, rng).items():
            v = evaluate(text, set(retrieved), rec, result)
            clean_n += 1
            clean_fp += not v.passed
            rows.append({"mrn": p["mrn"], "case": f"clean:{name}", "expected": "pass",
                         "got": "pass" if v.passed else "fail", "issues": ";".join(sorted({i["type"] for i in v.issues}))})
        for kind in MUTATIONS:
            for _ in range(a.reps):
                mutate.variant = ""
                text = mutate(base, kind, rng, retrieved, result)
                if text is None or text == base:
                    continue
                v = evaluate(text, set(retrieved), rec, result)
                per[kind][1] += 1
                per[kind][0] += not v.passed
                if mutate.variant:
                    per[f"{kind}:{mutate.variant}"][1] += 1
                    per[f"{kind}:{mutate.variant}"][0] += not v.passed
                for t in {i["type"] for i in v.issues}:
                    issues_seen[kind][t] += 1
                rows.append({"mrn": p["mrn"], "case": kind + (f":{mutate.variant}" if mutate.variant else ""), "expected": "fail", "got": "fail" if not v.passed else "pass",
                             "issues": ";".join(sorted({i["type"] for i in v.issues}))})

    designed = [k for k in MUTATIONS if k != "unsupported-claim-no-number"]
    det_k = sum(per[k][0] for k in designed)
    det_n = sum(per[k][1] for k in designed)
    res = {
        "seed": a.seed, "patients_used": len(ident) - skipped, "patients_skipped": skipped,
        "clean": {"n": clean_n, "false_alarms": clean_fp, "false_alarm_rate": round(clean_fp / clean_n, 4) if clean_n else None,
                  "ci95": wilson(clean_fp, clean_n)},
        "designed_errors": {"n": det_n, "detected": det_k, "detection_rate": round(det_k / det_n, 4) if det_n else None,
                            "ci95": wilson(det_k, det_n)},
        "by_mutation": {k: {"n": per[k][1], "detected": per[k][0],
                            "rate": round(per[k][0] / per[k][1], 4) if per[k][1] else None, "ci95": wilson(per[k][0], per[k][1]),
                            "issue_types": dict(issues_seen[k])} for k in sorted(per)},
        "caveat": "Clean variants are derived from the rule-based summary, so the false-alarm rate here is a lower bound; "
                  "it must be re-measured on real AI drafts. 'unsupported-claim-no-number' is outside the verifier's design "
                  "(semantic check) and is reported to show the blind spot.",
    }
    out = data / "eval"
    out.mkdir(parents=True, exist_ok=True)
    (out / "verifier_results.json").write_text(json.dumps(res, indent=2), encoding="utf-8")
    with open(out / "verifier_cases.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["mrn", "case", "expected", "got", "issues"])
        w.writeheader()
        w.writerows(rows)
    print(f"patients used {res['patients_used']} (skipped {skipped})")
    print(f"clean variants: {clean_fp}/{clean_n} false alarms  CI95 {res['clean']['ci95']}")
    print(f"designed errors: {det_k}/{det_n} detected  rate {res['designed_errors']['detection_rate']}  CI95 {res['designed_errors']['ci95']}")
    for k, v in res["by_mutation"].items():
        print(f"  {k:30s} {v['detected']:4d}/{v['n']:<4d} rate {v['rate']}  CI95 {v['ci95']}  {v['issue_types']}")


if __name__ == "__main__":
    main()
