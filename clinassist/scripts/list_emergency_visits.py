from . import script


@script("list_emergency_visits", kind="sort",
        does="List emergency and inpatient encounters in the window, oldest first.",
        returns="date, class, type, reason and evidence id",
        tags=["emergency", "admission", "hospital", "encounters", "visits"])
def run(ctx):
    rows = [{"date": i.when.date().isoformat(), "class": i.row["encounter_class"], "type": i.row["type_display"],
             "reason": i.row["reason_display"], "eid": i.eid}
            for i in ctx.rec.of("encounter") if i.row["encounter_class"] in ("EMER", "IMP")]
    return {"n": len(rows), "encounters": rows}
