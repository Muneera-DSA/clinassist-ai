"""Patient identity matching across the hospital, laboratory and pharmacy systems.

Design (deliberately simple and explainable, Fellegi-Sunter style):

* Normalise each system's own conventions (name order, case, accents, date
  format, sex codes) into one canonical record.
* Compare every lab / pharmacy patient with every hospital patient on four
  fields. Each field gets an agreement level and a fixed, hand-set weight
  (not fitted to the answer key). The score is the sum.
* Decide with clinical-safety rules: a wrong merge (two people's records
  combined) is worse than a missed link, so

    auto-link  only if score >= AUTO_LINK, date of birth agrees exactly,
               sex does not conflict, and no other candidate is close;
    review     if score >= REVIEW (a human confirms; the evidence is shown);
    no match   otherwise.

* One-to-one: a hospital patient is linked to at most one record per system.

Every decision carries field-level evidence so a reviewer can see why.
The hospital EHR is treated as the master patient index (MRN).
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

# Auto-link only when every field agrees exactly (sex may be missing): 11.5 of a maximum 12.5.
# Chosen from the threshold experiment (eval/eval_matching.py): at 9.0 a look-alike whose first name
# differs by one letter was auto-linked when the real patient was absent from the index; at 11.5
# there were 0 wrong merges in every scenario, at the cost of more cases sent to a person.
AUTO_LINK = 11.5
REVIEW = 4.0
AMBIGUITY_MARGIN = 3.0

DOB_FORMATS = {"hospital": "%Y-%m-%d", "laboratory": "%d/%m/%Y", "pharmacy": "%Y%m%d"}


# --------------------------------------------------------------------------- normalisation

def fold(s: str) -> str:
    """Upper-case, strip accents, keep letters only."""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return "".join(ch for ch in s.upper() if "A" <= ch <= "Z")


@dataclass(frozen=True)
class Person:
    system: str
    record_id: str
    family: str
    given: str
    dob: date | None
    sex: str | None          # "M", "F" or None when not recorded
    raw: dict = field(default_factory=dict, compare=False, hash=False)

    def label(self) -> str:
        d = self.dob.isoformat() if self.dob else "?"
        return f"{self.family}, {self.given} ({d}, {self.sex or '?'})"


def _dob(system: str, value: str) -> date | None:
    value = (value or "").strip()[:10]
    try:
        return datetime.strptime(value, DOB_FORMATS[system]).date()
    except ValueError:
        return None


def _sex(value: str) -> str | None:
    v = (value or "").strip().upper()[:1]
    return v if v in ("M", "F") else None


def from_hospital(r: dict) -> Person:
    return Person("hospital", r["mrn"], fold(r["family_name"]), fold((r["given_name"] or "").split(" ")[0]),
                  _dob("hospital", r["birth_date"]), _sex(r["sex"]), r)


def from_laboratory(r: dict) -> Person:
    return Person("laboratory", r["lab_patient_id"], fold(r["surname"]), fold((r["forenames"] or "").split(" ")[0]),
                  _dob("laboratory", r["dob"]), _sex(r["gender"]), r)


def from_pharmacy(r: dict) -> Person:
    family, _, given = (r["full_name"] or "").partition(",")
    return Person("pharmacy", r["pharm_patient_id"], fold(family), fold(given.strip().split(" ")[0]),
                  _dob("pharmacy", r["birth_date"]), _sex(r["sex"]), r)


# --------------------------------------------------------------------------- string similarity

def osa_distance(a: str, b: str) -> int:
    """Edit distance counting an adjacent transposition as one edit."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def jaro_winkler(a: str, b: str, p: float = 0.1) -> float:
    if a == b:
        return 1.0
    la, lb = len(a), len(b)
    if not la or not lb:
        return 0.0
    window = max(la, lb) // 2 - 1
    ma, mb, m = [False] * la, [False] * lb, 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - window), min(i + window + 1, lb)):
            if not mb[j] and b[j] == ch:
                ma[i] = mb[j] = True
                m += 1
                break
    if not m:
        return 0.0
    t, k = 0, 0
    for i in range(la):
        if ma[i]:
            while not mb[k]:
                k += 1
            t += a[i] != b[k]
            k += 1
    jaro = (m / la + m / lb + (m - t / 2) / m) / 3
    prefix = 0
    for x, y in zip(a[:4], b[:4]):
        if x != y:
            break
        prefix += 1
    return jaro + prefix * p * (1 - jaro)


# --------------------------------------------------------------------------- field comparison

@dataclass
class Evidence:
    field: str
    level: str
    weight: float
    detail: str

    def text(self) -> str:
        return f"{self.field}: {self.detail} [{self.level}, {self.weight:+.1f}]"


def cmp_family(a: str, b: str) -> Evidence:
    if a and a == b:
        return Evidence("surname", "exact", 4.0, a)
    if a and b and min(len(a), len(b)) >= 4 and osa_distance(a, b) == 1:
        return Evidence("surname", "one typing difference", 2.5, f"{a} vs {b}")
    if a and b and jaro_winkler(a, b) >= 0.92:
        return Evidence("surname", "similar", 1.5, f"{a} vs {b}")
    return Evidence("surname", "different", -4.0, f"{a or '?'} vs {b or '?'}")


def cmp_given(a: str, b: str) -> Evidence:
    if a and a == b:
        return Evidence("given name", "exact", 3.0, a)
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 3 and long_.startswith(short):
        return Evidence("given name", "shortened form", 1.5, f"{a} vs {b}")
    if a and b and min(len(a), len(b)) >= 4 and osa_distance(a, b) == 1:
        return Evidence("given name", "one typing difference", 1.5, f"{a} vs {b}")
    if a and b and jaro_winkler(a, b) >= 0.90:
        return Evidence("given name", "similar", 1.0, f"{a} vs {b}")
    return Evidence("given name", "different", -3.0, f"{a or '?'} vs {b or '?'}")


def cmp_dob(a: date | None, b: date | None) -> Evidence:
    if a is None or b is None:
        return Evidence("date of birth", "missing or unreadable", 0.0, f"{a} vs {b}")
    if a == b:
        return Evidence("date of birth", "exact", 5.0, a.isoformat())
    if a.year == b.year and a.day == b.month and a.month == b.day:
        return Evidence("date of birth", "day and month swapped", 2.0, f"{a} vs {b}")
    if a.year == b.year and a.month == b.month and abs(a.day - b.day) == 1:
        return Evidence("date of birth", "day differs by 1", 2.0, f"{a} vs {b}")
    return Evidence("date of birth", "different", -6.0, f"{a} vs {b}")


def cmp_sex(a: str | None, b: str | None) -> Evidence:
    if a is None or b is None:
        return Evidence("sex", "not recorded", 0.0, f"{a or '?'} vs {b or '?'}")
    if a == b:
        return Evidence("sex", "agrees", 0.5, a)
    return Evidence("sex", "conflict", -3.0, f"{a} vs {b}")


@dataclass
class Candidate:
    hospital: Person
    other: Person
    evidence: list[Evidence]

    @property
    def score(self) -> float:
        return sum(e.weight for e in self.evidence)

    def ev(self, name: str) -> Evidence:
        return next(e for e in self.evidence if e.field == name)


def compare(h: Person, o: Person) -> Candidate:
    return Candidate(h, o, [cmp_family(h.family, o.family), cmp_given(h.given, o.given),
                            cmp_dob(h.dob, o.dob), cmp_sex(h.sex, o.sex)])


# --------------------------------------------------------------------------- linking

@dataclass
class Link:
    system: str
    record_id: str
    record_label: str
    decision: str                  # "auto-link" | "review" | "no-match"
    mrn: str | None
    hospital_label: str | None
    score: float | None
    reasons: list[str]
    runner_up_mrn: str | None = None
    runner_up_score: float | None = None


def link_system(hospital: list[Person], others: list[Person], auto_link: float = AUTO_LINK, review: float = REVIEW,
                margin: float | None = AMBIGUITY_MARGIN, require_exact_dob: bool = True) -> list[Link]:
    """Link each record in another system to at most one hospital patient.

    The keyword arguments exist for experiments (threshold sweeps and ablations);
    production uses the defaults.
    """
    # Small data (~100 x 100), so compare all pairs. At hospital scale, add
    # blocking (e.g. birth year or phonetic surname) before this step.
    by_other: dict[str, list[Candidate]] = {}
    for o in others:
        cands = sorted((compare(h, o) for h in hospital), key=lambda c: -c.score)
        by_other[o.record_id] = cands

    # Greedy one-to-one assignment, strongest evidence first.
    pool = sorted((c for cs in by_other.values() for c in cs if c.score >= review), key=lambda c: -c.score)
    used_mrn: set[str] = set()
    chosen: dict[str, Candidate] = {}
    for c in pool:
        if c.other.record_id in chosen or c.hospital.record_id in used_mrn:
            continue
        chosen[c.other.record_id] = c
        used_mrn.add(c.hospital.record_id)

    links = []
    for o in others:
        c = chosen.get(o.record_id)
        if c is None:
            best = by_other[o.record_id][0] if by_other[o.record_id] else None
            links.append(Link(o.system, o.record_id, o.label(), "no-match", None, None,
                              best.score if best else None,
                              ["no hospital patient reached the review threshold"]
                              + ([f"closest: {best.hospital.record_id} {best.hospital.label()} score {best.score:.1f}"]
                                 if best else [])))
            continue
        rivals = [x for x in by_other[o.record_id] if x.hospital.record_id != c.hospital.record_id]
        rival = rivals[0] if rivals else None
        reasons = [e.text() for e in c.evidence]
        decision = "auto-link"
        if c.score < auto_link:
            decision = "review"; reasons.append(f"score {c.score:.1f} is below the auto-link threshold {auto_link}")
        if require_exact_dob and c.ev("date of birth").level != "exact":
            decision = "review"; reasons.append("date of birth does not agree exactly: a person must confirm")
        if c.ev("sex").level == "conflict":
            decision = "review"; reasons.append("recorded sex conflicts")
        if margin is not None and rival and rival.score >= review and c.score - rival.score < margin:
            decision = "review"; reasons.append(
                f"ambiguous: {rival.hospital.record_id} {rival.hospital.label()} also scores {rival.score:.1f}")
        links.append(Link(o.system, o.record_id, o.label(), decision, c.hospital.record_id, c.hospital.label(),
                          round(c.score, 2), reasons,
                          rival.hospital.record_id if rival else None, round(rival.score, 2) if rival else None))
    return links


def naive_exact(hospital: list[Person], others: list[Person]) -> dict[str, str]:
    """Baseline: exact folded surname + exact date of birth, unique matches only."""
    index: dict[tuple, list[str]] = {}
    for h in hospital:
        index.setdefault((h.family, h.dob), []).append(h.record_id)
    out = {}
    for o in others:
        hits = index.get((o.family, o.dob), [])
        if len(hits) == 1:
            out[o.record_id] = hits[0]
    return out


# --------------------------------------------------------------------------- evaluation (answer key)

def evaluate(links: list[Link], truth: dict[str, str], baseline: dict[str, str]) -> dict:
    """Score links against the answer key. Never used to make decisions."""
    total = len(truth)
    auto = [l for l in links if l.decision == "auto-link"]
    review = [l for l in links if l.decision == "review"]
    none = [l for l in links if l.decision == "no-match"]
    auto_ok = sum(truth.get(l.record_id) == l.mrn for l in auto)
    review_ok = sum(truth.get(l.record_id) == l.mrn for l in review)
    base_ok = sum(truth.get(k) == v for k, v in baseline.items())
    return {
        "records": total,
        "baseline_exact_correct": base_ok,
        "baseline_exact_wrong": len(baseline) - base_ok,
        "auto_link": len(auto),
        "auto_link_correct": auto_ok,
        "auto_link_wrong_merges": len(auto) - auto_ok,
        "review": len(review),
        "review_top_candidate_correct": review_ok,
        "no_match": len(none),
        "no_match_but_truth_exists": sum(l.record_id in truth for l in none),
        "auto_precision": round(auto_ok / len(auto), 4) if auto else None,
        "auto_recall": round(auto_ok / total, 4) if total else None,
        "recall_after_review": round((auto_ok + review_ok) / total, 4) if total else None,
    }
