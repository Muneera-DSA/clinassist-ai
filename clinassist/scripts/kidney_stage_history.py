from clinassist.analysis import ckd_category, series

from . import script


@script("kidney_stage_history", kind="sort",
        does="Give the KDIGO GFR category of each eGFR result in date order, and the dates the category changed.",
        returns="each result with its category, and the list of category changes",
        tags=["kidney", "egfr", "stage", "ckd", "history", "kdigo"])
def run(ctx):
    pts = series(ctx.rec, ctx.rules["analytes"]["egfr"]["loinc"])
    rows = [{"date": p.when.date().isoformat(), "egfr": p.value, "category": ckd_category(p.value), "eid": p.eid} for p in pts]
    changes = [{"date": b["date"], "from": a["category"], "to": b["category"], "eid": b["eid"]}
               for a, b in zip(rows, rows[1:]) if a["category"] != b["category"]]
    return {"n": len(rows), "results": rows, "category_changes": changes}
