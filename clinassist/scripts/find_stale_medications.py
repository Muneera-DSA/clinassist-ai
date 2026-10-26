from clinassist.analysis import check_stale_medications

from . import script
from ._checks import findings_out


@script("find_stale_medications", kind="compute",
        does="List medicines marked active that have not been prescribed in over 12 months.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['medicine', 'stale', 'reconciliation', 'active list'])
def run(ctx):
    return findings_out(check_stale_medications(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
