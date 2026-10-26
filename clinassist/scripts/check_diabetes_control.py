from clinassist.analysis import check_diabetes_control

from . import script
from ._checks import findings_out


@script("check_diabetes_control", kind="compute",
        does="For type 2 diabetes, test whether an HbA1c was done in the last 6 months and compare the latest with the common <7% goal.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['diabetes', 'hba1c', 'glucose', 'monitoring'])
def run(ctx):
    return findings_out(check_diabetes_control(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
