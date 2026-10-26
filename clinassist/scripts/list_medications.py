from dataclasses import asdict

from . import script


@script("list_medications", kind="sort",
        does="List the patient's medicines with status and prescribing history, most recently prescribed first.",
        args={"active_only": "true to list only medicines marked active"},
        returns="medication, ingredient, status, first and last prescribed, prescriptions in window, evidence ids",
        tags=["medicine", "medication", "prescription", "pharmacy", "drug list"])
def run(ctx, active_only: bool = True):
    meds = [asdict(m) for m in ctx.meds() if not active_only or m.status == "active"]
    return {"n": len(meds), "medications": sorted(meds, key=lambda m: m["last_prescribed"], reverse=True)}
