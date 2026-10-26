from clinassist.analysis import check_duplicate_ingredients

from . import script
from ._checks import findings_out


@script("find_duplicate_ingredients", kind="compute",
        does="Find pairs of active medicines that share any ingredient.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['medicine', 'duplicate', 'ingredient', 'statin', 'reconciliation'])
def run(ctx):
    return findings_out(check_duplicate_ingredients(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
