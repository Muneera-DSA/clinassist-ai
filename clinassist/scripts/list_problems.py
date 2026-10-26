from clinassist.analysis import is_clinical

from . import script


@script("list_problems", kind="sort",
        does="List the active diagnoses on the problem list, most recent onset first.",
        returns="diagnosis, onset date and evidence id",
        tags=["diagnosis", "problem list", "conditions", "history"])
def run(ctx):
    rows = [{"display": i.row["display"], "onset": i.when.date().isoformat() if i.when else None, "eid": i.eid}
            for i in ctx.rec.of("condition") if i.row["clinical_status"] == "active" and is_clinical(i.row["display"])]
    return {"n": len(rows), "problems": sorted(rows, key=lambda r: r["onset"] or "", reverse=True)}
