from . import script


@script("list_lab_visits", kind="sort",
        does="List the days the patient had samples taken at the laboratory in the review period, with how many tests and "
             "the accession numbers, newest first. Administrative only: no result values.",
        returns="n, and each lab visit: date, number of tests, accession numbers, evidence id",
        tags=["lab visits", "laboratory", "samples", "collections", "appointments", "history"])
def run(ctx):
    rec = ctx.need_record()
    days: dict[str, dict] = {}
    for i in rec.of("lab_result"):
        if not i.when or i.when.date() < rec.since:
            continue
        d = i.when.date().isoformat()
        v = days.setdefault(d, {"date": d, "n": 0, "accessions": [], "eid": i.eid})
        v["n"] += 1
        acc = i.row.get("accession_no")
        if acc and acc not in v["accessions"]:
            v["accessions"].append(acc)
    rows = sorted(days.values(), key=lambda x: x["date"], reverse=True)
    for r in rows:
        r["accessions"] = ", ".join(r["accessions"][:4])
    return {"n": len(rows), "window": {"from": rec.since.isoformat(), "to": rec.as_of.isoformat()}, "lab_visits": rows}
