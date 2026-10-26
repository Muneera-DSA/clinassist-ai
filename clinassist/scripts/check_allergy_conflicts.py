from clinassist.analysis import check_allergy_conflicts

from . import script
from ._checks import findings_out


@script("check_allergy_conflicts", kind="compute",
        does="Compare active medicines with recorded medication allergies and their drug classes.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['allergy', 'medicine', 'safety', 'penicillin'])
def run(ctx):
    return findings_out(check_allergy_conflicts(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
