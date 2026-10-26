from clinassist.analysis import check_potassium_on_acei

from . import script
from ._checks import findings_out


@script("check_potassium_on_acei", kind="compute",
        does="Compare the latest potassium with the illustrative upper band while an ACE inhibitor is active.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['potassium', 'ace inhibitor', 'lisinopril', 'medicine', 'safety'])
def run(ctx):
    return findings_out(check_potassium_on_acei(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
