from clinassist.analysis import check_egfr_decline

from . import script
from ._checks import findings_out


@script("check_egfr_decline", kind="compute",
        does="Test the NICE NG203 accelerated-progression criterion on the eGFR series (>=25% sustained fall with a category change within 12 months, or >=15 mL/min/1.73m2 per year).",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['kidney', 'egfr', 'decline', 'ckd', 'nice', 'renal function'])
def run(ctx):
    return findings_out(check_egfr_decline(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
