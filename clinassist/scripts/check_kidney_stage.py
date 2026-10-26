from clinassist.analysis import check_kidney_stage

from . import script
from ._checks import findings_out


@script("check_kidney_stage", kind="compute",
        does="Give the KDIGO GFR category of the latest eGFR.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['kidney', 'egfr', 'stage', 'ckd', 'kdigo'])
def run(ctx):
    return findings_out(check_kidney_stage(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
