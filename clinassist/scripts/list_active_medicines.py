from . import script


@script("list_active_medicines", kind="sort",
        does="List the medicines currently marked active, each with when it was last prescribed and when it was last "
             "administered (given) according to the pharmacy record. Facts only: no safety judgement.",
        returns="n, and each active medicine: name, ingredient, first and last prescribed, prescriptions, times administered, "
                "last administered date, evidence id",
        tags=["medicine", "medication", "active", "current", "prescribed", "administered", "list", "authorization"])
def run(ctx):
    rec = ctx.need_record()
    given: dict[str, list] = {}
    for a in rec.of("administration"):
        given.setdefault(a.row.get("medication") or "", []).append(a)
    rows = []
    for m in ctx.meds():
        if m.status != "active":
            continue
        ad = sorted((a for a in given.get(m.medication, []) if a.when), key=lambda a: a.when)
        rows.append({"medication": m.medication, "ingredient": m.ingredient, "first_prescribed": m.first_prescribed,
                     "last_prescribed": m.last_prescribed, "prescriptions": m.prescriptions, "administered": len(ad),
                     "last_administered": ad[-1].when.date().isoformat() if ad else None,
                     "eid": m.evidence[0] if m.evidence else None, "admin_eid": ad[-1].eid if ad else None})
    rows.sort(key=lambda r: r["last_prescribed"], reverse=True)
    return {"n": len(rows), "medicines": rows}
