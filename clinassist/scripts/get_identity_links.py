from clinassist.patient_record import load_identity

from . import script


@script("get_identity_links", kind="fetch", needs_record=False,
        does="Read from the Meterless World Model which laboratory and pharmacy records are linked to this patient and which "
             "are still waiting for a person's identity decision.",
        returns="linked records (automatic or confirmed by a reviewer) and pending ones",
        tags=["identity", "matching", "linked records", "world model", "pending"])
def run(ctx):
    ident = load_identity(ctx.world_dir, ctx.mrn)
    return {"patient": ident["label"], "linked_records": ident["linked_records"], "pending_review": ident["pending_review"]}
