from clinassist.analysis import series

from . import script


@script("list_lab_results", kind="sort",
        does="List every result of one lab test or vital sign in the window, sorted by date.",
        args={"analyte": "one analyte key, e.g. egfr, creatinine, acr, hba1c, potassium, hemoglobin, sbp, dbp, ldl"},
        returns="date, value and evidence id of each result, oldest first",
        tags=["lab", "results", "series", "history", "values"])
def run(ctx, analyte: str):
    a = ctx.rules["analytes"].get(analyte)
    if not a:
        raise ValueError(f"unknown analyte {analyte!r}; known: {', '.join(ctx.rules['analytes'])}")
    pts = series(ctx.rec, a["loinc"])
    return {"analyte": analyte, "label": a["label"], "unit": a["unit"], "n": len(pts),
            "results": [{"date": p.when.date().isoformat(), "value": p.value, "eid": p.eid} for p in pts]}
