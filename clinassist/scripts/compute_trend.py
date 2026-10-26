from dataclasses import asdict

from . import script


@script("compute_trend", kind="compute",
        does="Compute the robust (Theil-Sen) trend of one lab test or vital sign: slope per year, first and latest value, "
             "percent change and direction.",
        args={"analyte": "one analyte key, e.g. egfr, creatinine, acr, hba1c, potassium, hemoglobin, sbp, dbp, ldl"},
        returns="n, first, latest, min, max, slope_per_year, change_pct, direction, results above/below the band, evidence ids",
        tags=["trend", "slope", "change over time", "lab", "longitudinal", "kidney", "egfr"])
def run(ctx, analyte: str):
    t = ctx.trends().get(analyte)
    if t is None:
        return {"analyte": analyte, "available": False, "reason": "no results for this analyte in the window"}
    return {k: v for k, v in asdict(t).items() if k != "points"} | {"available": True}
