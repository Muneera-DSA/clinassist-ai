from clinassist.analysis import check_problem_list

from . import script
from ._checks import findings_out


@script("check_problem_list", kind="compute",
        does="Find several CKD stages marked active at the same time on the problem list.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['problem list', 'diagnosis', 'ckd stage', 'record'])
def run(ctx):
    return findings_out(check_problem_list(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
