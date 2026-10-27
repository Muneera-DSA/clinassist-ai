from clinassist.analysis import series

from . import script


@script("list_lab_results", kind="sort",
        does="List every result of one lab test or vital sign in the window, sorted by date; with no analyte, list every "
             "lab test done in the window with its number of results and latest value.",
        args={"analyte": "optional: one analyte key, e.g. egfr, creatinine, acr, hba1c, potassium, hemoglobin, sbp, dbp, ldl"},
        returns="one test: date, value and evidence id of each result, oldest first; all tests: test name, count, latest value, "
                "unit, date and evidence id",
        tags=["lab", "results", "series", "history", "values"])
def run(ctx, analyte: str = ""):
    if not analyte:
        rec = ctx.need_record()
        tests: dict[str, dict] = {}
        for i in rec.of("lab_result"):
            if not i.when or i.when.date() < rec.since:
                continue
            name = i.row.get("test_name") or i.row.get("loinc_code") or "unnamed test"
            t = tests.setdefault(name, {"test": name, "n": 0})
            t["n"] += 1
            t.update({"latest_value": i.row.get("value_num") or i.row.get("value_text"), "unit": i.row.get("unit"),
                      "latest_date": i.when.date().isoformat(), "eid": i.eid})
        rows = sorted(tests.values(), key=lambda t: (-t["n"], t["test"]))
        return {"analyte": "all", "label": "laboratory", "n": len(rows), "window": {"from": rec.since.isoformat(), "to": rec.as_of.isoformat()},
                "tests": rows}
    a = ctx.rules["analytes"].get(analyte)
    if not a:
        raise ValueError(f"unknown analyte {analyte!r}; known: {', '.join(ctx.rules['analytes'])}")
    pts = series(ctx.rec, a["loinc"])
    return {"analyte": analyte, "label": a["label"], "unit": a["unit"], "n": len(pts),
            "results": [{"date": p.when.date().isoformat(), "value": p.value, "eid": p.eid} for p in pts]}
