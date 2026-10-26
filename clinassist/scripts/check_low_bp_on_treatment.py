from clinassist.analysis import check_low_bp_on_treatment

from . import script
from ._checks import findings_out


@script("check_low_bp_on_treatment", kind="compute",
        does="Test whether systolic blood pressure was below 90 on the last two readings while blood-pressure medicines were prescribed in the last 12 months.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['blood pressure', 'hypotension', 'medicine', 'falls', 'safety'])
def run(ctx):
    return findings_out(check_low_bp_on_treatment(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
