from clinassist.analysis import check_renal_dosing

from . import script
from ._checks import findings_out


@script("check_renal_dosing", kind="compute",
        does="Compare active medicines that have kidney-function limits (alendronate, metformin) with the latest eGFR.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['kidney', 'medicine', 'dose', 'alendronate', 'metformin', 'safety'])
def run(ctx):
    return findings_out(check_renal_dosing(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
