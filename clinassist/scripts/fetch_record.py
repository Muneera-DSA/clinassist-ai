from clinassist.patient_record import load_record

from . import script


@script("fetch_record", kind="fetch", needs_record=False,
        does="Load the patient's records from the hospital, laboratory and pharmacy systems through Zetaris, for the "
             "look-back window, using only identity links that are automatic or confirmed by a person.",
        returns="counts of loaded items per kind, the linked records used and any records still waiting for identity review",
        tags=["data", "zetaris", "record", "load", "history"])
def run(ctx):
    ctx.rec = load_record(ctx.source, ctx.world_dir, ctx.mrn, ctx.as_of, ctx.years)
    ctx.cache.clear()
    kinds = ("encounter", "condition", "procedure", "observation", "allergy", "lab_result", "prescription", "administration")
    return {"patient": ctx.rec.label, "window": {"from": ctx.rec.since.isoformat(), "to": ctx.rec.as_of.isoformat()},
            "counts": {k: len(ctx.rec.of(k)) for k in kinds}, "linked_records": ctx.rec.linked, "pending_review": ctx.rec.pending}
