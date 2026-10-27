from dataclasses import asdict

from . import script


@script("find_medication", kind="sort",
        does="Look up one medicine by name or ingredient across all of the patient's prescriptions, active and past.",
        args={"name": "a medicine or ingredient name, e.g. metformin, lisinopril, atorvastatin"},
        returns="n matches; for each: medication, ingredient, status, first and last prescribed, evidence ids (n = 0: never prescribed)",
        tags=["medicine", "medication", "prescription", "drug", "is he on", "taking", "prescribed"])
def run(ctx, name: str):
    q = (name or "").strip().lower()
    if not q:
        raise ValueError("name is required")
    meds = [asdict(m) for m in ctx.meds() if q in (m.medication or "").lower() or q in (m.ingredient or "").lower()]
    return {"name": q, "n": len(meds), "medications": sorted(meds, key=lambda m: m["last_prescribed"], reverse=True)}
