from . import script

CLASS = {"AMB": "outpatient", "ambulatory": "outpatient", "EMER": "emergency", "emergency": "emergency", "IMP": "inpatient admission",
         "inpatient": "inpatient admission", "wellness": "wellness check", "outpatient": "outpatient", "urgentcare": "urgent care",
         "VR": "virtual", "virtual": "virtual", "home": "home visit", "HH": "home visit"}


@script("list_visits", kind="sort",
        does="List the patient's hospital visits and admissions in the review period (date, kind of visit, visit type, "
             "organisation), newest first. Administrative only: no diagnoses or reasons.",
        returns="n, counts by kind of visit, admissions, and each visit: start and end date, kind, type, organisation, evidence id",
        tags=["visits", "admissions", "encounters", "appointments", "emergency", "inpatient", "hospital", "history"])
def run(ctx):
    rec = ctx.need_record()
    rows = []
    for i in rec.of("encounter"):
        if not i.when:
            continue
        r = i.row
        rows.append({"date": i.when.date().isoformat(), "end": (r.get("end_at") or "")[:10] or None,
                     "kind": CLASS.get(r.get("encounter_class") or "", r.get("encounter_class") or "visit"),
                     "type": r.get("type_display") or "", "organisation": r.get("provider_org") or "", "eid": i.eid})
    rows.sort(key=lambda x: x["date"], reverse=True)
    counts: dict[str, int] = {}
    for x in rows:
        counts[x["kind"]] = counts.get(x["kind"], 0) + 1
    return {"n": len(rows), "window": {"from": rec.since.isoformat(), "to": rec.as_of.isoformat()}, "counts": counts,
            "admissions": counts.get("inpatient admission", 0), "visits": rows}
