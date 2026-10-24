"""Deterministic clinical analysis over a PatientRecord.

Everything here is rule-based and reproducible. Each finding carries the
evidence ids it rests on and, for rules, the public source of its threshold.
Nothing here diagnoses or recommends treatment: findings are prompts for a
qualified professional to review.
"""
from __future__ import annotations

import json
import re
import statistics
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .patient_record import Item, PatientRecord

RULES_FILE = Path(__file__).resolve().parents[1] / "config" / "clinical_rules.json"


def load_rules(path: Path = RULES_FILE) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass
class Finding:
    rule: str
    severity: str           # "info" | "review" | "high"
    title: str
    detail: str
    evidence: list[str]
    source: str | None = None


# --------------------------------------------------------------------------- lab series and trends

@dataclass
class Point:
    when: datetime
    value: float
    eid: str


def series(rec: PatientRecord, codes: list[str]) -> list[Point]:
    pts = []
    for i in rec.of("lab_result"):
        if i.row["loinc_code"] in codes and i.row["value_num"] not in ("", None) and i.when:
            try:
                pts.append(Point(i.when, float(i.row["value_num"]), i.eid))
            except ValueError:
                continue
    return sorted(pts, key=lambda p: p.when)


def theil_sen_per_year(pts: list[Point]) -> float | None:
    """Median of pairwise slopes: robust to single outlying results."""
    slopes = []
    for a in range(len(pts)):
        for b in range(a + 1, len(pts)):
            dt = (pts[b].when - pts[a].when).days / 365.25
            if dt > 0.02:
                slopes.append((pts[b].value - pts[a].value) / dt)
    return statistics.median(slopes) if slopes else None


@dataclass
class Trend:
    analyte: str
    label: str
    unit: str
    n: int
    first: dict | None
    latest: dict | None
    min: float | None
    max: float | None
    slope_per_year: float | None
    change_pct: float | None
    direction: str           # "rising" | "falling" | "stable" | "too few results"
    above_band: int
    below_band: int
    band: str
    evidence: list[str] = field(default_factory=list)
    points: list[list] = field(default_factory=list)


def trends(rec: PatientRecord, rules: dict) -> dict[str, Trend]:
    out = {}
    for key, a in rules["analytes"].items():
        pts = series(rec, a["loinc"])
        if not pts:
            continue
        lo, hi = a.get("illustrative_low"), a.get("illustrative_high")
        slope = theil_sen_per_year(pts) if len(pts) >= rules["trend_min_points"] else None
        # percent change between the median of the first and last quarter of results (less noisy than first vs last)
        q = max(1, len(pts) // 4)
        head, tail = statistics.median(p.value for p in pts[:q]), statistics.median(p.value for p in pts[-q:])
        change = (tail - head) / head * 100 if head else None
        if len(pts) < rules["trend_min_points"] or change is None:
            direction = "too few results"
        elif abs(change) < rules["trend_meaningful_change_pct"]:
            direction = "stable"
        else:
            direction = "rising" if change > 0 else "falling"
        band = f"{lo if lo is not None else ''}-{hi if hi is not None else ''} {a['unit']} (illustrative)"
        keep = sorted({0, len(pts) - 1, min(range(len(pts)), key=lambda k: pts[k].value),
                       max(range(len(pts)), key=lambda k: pts[k].value)})
        out[key] = Trend(key, a["label"], a["unit"], len(pts),
                         {"date": pts[0].when.date().isoformat(), "value": pts[0].value, "eid": pts[0].eid},
                         {"date": pts[-1].when.date().isoformat(), "value": pts[-1].value, "eid": pts[-1].eid},
                         min(p.value for p in pts), max(p.value for p in pts),
                         round(slope, 3) if slope is not None else None,
                         round(change, 1) if change is not None else None, direction,
                         sum(hi is not None and p.value > hi for p in pts),
                         sum(lo is not None and p.value < lo for p in pts), band,
                         [pts[k].eid for k in keep],
                         [[p.when.date().isoformat(), round(p.value, 3)] for p in pts])
    return out


# --------------------------------------------------------------------------- medications

INGREDIENT = re.compile(r"^([A-Za-z][A-Za-z\- ]*?)(?:\s+\d|\s*\[|$)")


def ingredient(name: str) -> str:
    m = INGREDIENT.match(name.strip())
    return (m.group(1) if m else name).strip().lower()


@dataclass
class Medication:
    medication: str
    ingredient: str
    status: str
    first_prescribed: str
    last_prescribed: str
    prescriptions: int
    prescriptions_in_window: int
    evidence: list[str]


def medications(rec: PatientRecord) -> list[Medication]:
    by_med: dict[str, list[Item]] = {}
    for i in rec.of("prescription"):
        by_med.setdefault(i.row["medication"], []).append(i)
    out = []
    for med, items in by_med.items():
        items.sort(key=lambda i: i.when or datetime.min)
        active = [i for i in items if i.row["status"] == "active"]
        in_window = [i for i in items if i.when and i.when.date() >= rec.since]
        if not active and not in_window:
            continue  # nothing current or within the look-back window
        out.append(Medication(med, ingredient(med), "active" if active else "not active",
                              items[0].when.date().isoformat() if items[0].when else "?",
                              items[-1].when.date().isoformat() if items[-1].when else "?",
                              len(items), len(in_window),
                              [i.eid for i in (active or [items[-1]])]))
    return sorted(out, key=lambda m: (m.status != "active", m.medication))


# --------------------------------------------------------------------------- rules

def ckd_category(egfr: float) -> str:
    for cut, cat in ((90, "G1"), (60, "G2"), (45, "G3a"), (30, "G3b"), (15, "G4")):
        if egfr >= cut:
            return cat
    return "G5"


CLINICAL_FINDINGS = ("prediabetes", "body mass index")


def is_clinical(display: str) -> bool:
    """Problem-list filter: disorders plus a few clinical findings (social history is left to the source record)."""
    d = display.lower()
    return "(disorder)" in d or any(w in d for w in CLINICAL_FINDINGS)


def active_conditions(rec: PatientRecord, *words: str) -> list[Item]:
    return [i for i in rec.of("condition") if i.row["clinical_status"] == "active"
            and any(w in i.row["display"].lower() for w in words)]


def run_rules(rec: PatientRecord, tr: dict[str, Trend], meds: list[Medication], rules: dict) -> list[Finding]:
    f: list[Finding] = []
    as_of = datetime.combine(rec.as_of, datetime.min.time())
    active = [m for m in meds if m.status == "active"]
    has = lambda *words: [m for m in active if any(w in m.ingredient for w in words)]  # noqa: E731

    # Kidney function
    egfr = series(rec, rules["analytes"]["egfr"]["loinc"])
    if egfr:
        last = egfr[-1]
        cat = ckd_category(last.value)
        f.append(Finding("ckd-category", "info", f"Latest eGFR {last.value:.0f} = GFR category {cat}",
                         f"Measured {last.when.date()}. GFR category from the eGFR value alone; CKD staging also needs "
                         f"chronicity (>3 months) and albuminuria, which a clinician confirms.", [last.eid], "kdigo_g"))
        # NICE accelerated progression: >=25% sustained fall with category change within 12 months
        hit = None
        for a, p in enumerate(egfr):
            for b in range(a + 1, len(egfr)):
                q = egfr[b]
                if (q.when - p.when).days > 365:
                    break
                if q.value <= 0.75 * p.value and ckd_category(q.value) != ckd_category(p.value):
                    after = egfr[b + 1:b + 3]
                    if after and all(x.value <= 0.75 * p.value for x in after):  # sustained on the next results
                        hit = (p, q, after)
                        break
            if hit:
                break
        tr_e = tr.get("egfr")
        if hit:
            p, q, after = hit
            f.append(Finding("ckd-accelerated", "high", "Accelerated fall in kidney function (NICE criterion met)",
                             f"eGFR {p.value:.0f} on {p.when.date()} ({ckd_category(p.value)}) fell to {q.value:.0f} on "
                             f"{q.when.date()} ({ckd_category(q.value)}): a {100 * (1 - q.value / p.value):.0f}% fall with a "
                             f"category change within 12 months, confirmed by the next {len(after)} result(s).",
                             [p.eid, q.eid] + [x.eid for x in after], "nice_ng203"))
        elif tr_e and tr_e.slope_per_year is not None and tr_e.slope_per_year <= -15:
            span_years = (egfr[-1].when - egfr[0].when).days / 365.25
            enough = tr_e.n >= 4 and span_years >= 1
            f.append(Finding("ckd-accelerated" if enough else "ckd-possible-fast-fall", "high" if enough else "review",
                             "Accelerated fall in kidney function (NICE criterion met)" if enough
                             else "Possible fast fall in eGFR (too few results to confirm)",
                             f"eGFR falling about {abs(tr_e.slope_per_year):.0f} mL/min/1.73m2 per year (robust trend over "
                             f"{tr_e.n} results across {span_years:.1f} years: {tr_e.first['value']:.0f} to {tr_e.latest['value']:.0f})."
                             + ("" if enough else " At least 4 results over 12 months are needed to call it sustained; "
                                "consider repeating the test."), tr_e.evidence, "nice_ng203"))

        # Medicines with kidney-function limits
        for m in has("alendron"):
            if last.value < 35:
                f.append(Finding("renal-alendronate", "high", f"{m.medication} active while eGFR is {last.value:.0f}",
                                 "Alendronate is not recommended when creatinine clearance is below 35 mL/min. eGFR is used "
                                 "here as a proxy; a pharmacist should calculate creatinine clearance and review.",
                                 m.evidence + [last.eid], "fosamax_label"))
        for m in has("metformin"):
            if last.value < 30:
                f.append(Finding("renal-metformin", "high", f"{m.medication} active while eGFR is {last.value:.0f}",
                                 "Metformin is contraindicated below eGFR 30.", m.evidence + [last.eid], "fda_metformin_2016"))
            elif last.value < 45:
                f.append(Finding("renal-metformin", "review", f"{m.medication} active with eGFR {last.value:.0f}",
                                 "Starting metformin is not recommended at eGFR 30-45; continuing needs a benefit-risk review.",
                                 m.evidence + [last.eid], "fda_metformin_2016"))

    # Potassium on an ACE inhibitor
    k = series(rec, rules["analytes"]["potassium"]["loinc"])
    acei = has("pril")
    if k and acei and k[-1].value > rules["analytes"]["potassium"]["illustrative_high"]:
        f.append(Finding("acei-potassium", "review", f"Potassium {k[-1].value:.2f} mmol/L while on {acei[0].medication}",
                         "ACE inhibitors can raise potassium; latest result is above the illustrative upper band.",
                         acei[0].evidence + [k[-1].eid], "acei_k"))

    # Diabetes monitoring
    dm = active_conditions(rec, "diabetes mellitus type 2", "type 2 diabetes")
    if dm:
        a1c = series(rec, rules["analytes"]["hba1c"]["loinc"])
        recent = [p for p in a1c if p.when >= as_of - timedelta(days=183)]
        if not recent:
            last = f"last result {a1c[-1].when.date()}" if a1c else "no result in the look-back window"
            f.append(Finding("dm-a1c-gap", "review", "No HbA1c in the last 6 months for a patient with type 2 diabetes",
                             f"Guidance is to assess glycaemic status at least twice a year; {last}.",
                             [dm[0].eid] + ([a1c[-1].eid] if a1c else []), "ada_2026_s6"))
        elif recent[-1].value >= 7:
            f.append(Finding("dm-a1c-above-goal", "review", f"Latest HbA1c {recent[-1].value:.1f}% is above the common goal of <7%",
                             "The <7% goal suits many adults but should be individualised.", [dm[0].eid, recent[-1].eid], "ada_2026_s6"))

    # Medication reconciliation
    for m in active:
        if m.last_prescribed < (rec.as_of - timedelta(days=365)).isoformat():
            f.append(Finding("rx-stale-active", "review", f"{m.medication} is marked active but last prescribed {m.last_prescribed}",
                             "Confirm with the patient whether it is still taken.", m.evidence, "reconciliation"))
    seen: dict[str, Medication] = {}
    for m in active:
        if m.ingredient in seen:
            f.append(Finding("rx-duplicate", "review", f"Two active products contain {m.ingredient}",
                             f"{seen[m.ingredient].medication} and {m.medication}.", seen[m.ingredient].evidence + m.evidence,
                             "record_hygiene"))
        seen[m.ingredient] = m

    # Problem-list hygiene: several CKD stages recorded as active at the same time
    stages = sorted(active_conditions(rec, "chronic kidney disease stage"), key=lambda i: i.row["display"])
    if len(stages) > 1:
        f.append(Finding("problem-list-ckd-stages", "review", f"{len(stages)} different CKD stages are all marked active",
                         "Only one stage can be current: " + "; ".join(i.row["display"] for i in stages)
                         + ". The problem list needs updating by the clinician.", [i.eid for i in stages], "record_hygiene"))

    # Identity: records waiting for a person are not in this review
    for p in rec.pending:
        f.append(Finding("identity-pending", "review", f"Possible {p['system']} record {p['record_id']} is waiting for identity review",
                         "It is NOT included in this summary until a person confirms it belongs to this patient.", [], None))
    order = {"high": 0, "review": 1, "info": 2}
    return sorted(f, key=lambda x: order[x.severity])


# --------------------------------------------------------------------------- timeline

def timeline(rec: PatientRecord, tr: dict[str, Trend], meds: list[Medication], findings: list[Finding]) -> list[dict]:
    ev: list[dict] = []
    for i in rec.of("encounter"):
        if i.row["encounter_class"] in ("EMER", "IMP", "inpatient", "emergency"):
            ev.append({"date": i.when.date().isoformat(), "type": "admission" if i.row["encounter_class"] == "IMP" else "emergency",
                       "text": f"{i.row['type_display']}" + (f" (reason: {i.row['reason_display']})" if i.row["reason_display"] else ""),
                       "evidence": [i.eid]})
    for i in rec.of("condition"):
        if i.when and i.when.date() >= rec.since and "(disorder)" in i.row["display"] and i.row["clinical_status"] == "active":
            ev.append({"date": i.when.date().isoformat(), "type": "diagnosis", "text": i.row["display"], "evidence": [i.eid]})
    for m in meds:
        if m.first_prescribed >= rec.since.isoformat():
            ev.append({"date": m.first_prescribed, "type": "medication started", "text": m.medication, "evidence": m.evidence[:1]})
    for f in findings:
        if f.rule == "ckd-accelerated" and f.evidence:
            items = rec.by_eid()
            d = items[f.evidence[1]].when.date().isoformat() if len(f.evidence) > 1 else items[f.evidence[0]].when.date().isoformat()
            ev.append({"date": d, "type": "flag", "text": f.title, "evidence": f.evidence})
    return sorted(ev, key=lambda e: e["date"])


def analyse(rec: PatientRecord, rules: dict | None = None) -> dict:
    rules = rules or load_rules()
    tr = trends(rec, rules)
    meds = medications(rec)
    findings = run_rules(rec, tr, meds, rules)
    return {
        "patient": {"mrn": rec.mrn, "label": rec.label, "birth_date": rec.patient.get("birth_date"),
                    "sex": rec.patient.get("sex"), "deceased_at": rec.patient.get("deceased_at") or None},
        "window": {"as_of": rec.as_of.isoformat(), "since": rec.since.isoformat()},
        "identity": {"linked_records": rec.linked, "pending_review": rec.pending},
        "counts": {k: len(rec.of(k)) for k in ("encounter", "condition", "procedure", "lab_result", "prescription", "administration")},
        "active_conditions": [{"display": i.row["display"], "onset": i.when.date().isoformat() if i.when else None, "evidence": [i.eid]}
                              for i in rec.of("condition") if i.row["clinical_status"] == "active" and is_clinical(i.row["display"])],
        "trends": {k: asdict(v) for k, v in tr.items()},
        "medications": [asdict(m) for m in meds],
        "findings": [asdict(x) for x in findings],
        "timeline": timeline(rec, tr, meds, findings),
        "rules_version": rules["version"],
        "sources": rules["sources"],
    }
