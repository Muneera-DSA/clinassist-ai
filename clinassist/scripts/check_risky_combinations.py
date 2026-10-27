from clinassist.analysis import check_risky_combinations

from . import script
from ._checks import findings_out


@script("check_risky_combinations", kind="compute",
        does="Find active medicines that are risky together: opioid + benzodiazepine, ACE inhibitor with an ARB or Entresto, "
             "NSAID with a blood thinner, two P2Y12 antiplatelets, NSAID + ACE inhibitor/ARB + diuretic.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['medicine', 'interaction', 'combination', 'opioid', 'benzodiazepine', 'nsaid', 'bleeding', 'safety'])
def run(ctx):
    return findings_out(check_risky_combinations(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
