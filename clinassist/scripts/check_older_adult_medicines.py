from clinassist.analysis import check_older_adult_medicines

from . import script
from ._checks import findings_out


@script("check_older_adult_medicines", kind="compute",
        does="Count the active medicines (polypharmacy) and, for patients aged 65 or more, find active medicines on the "
             "AGS Beers list of medicines usually best avoided in older adults.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['medicine', 'polypharmacy', 'elderly', 'older', 'beers', 'safety'])
def run(ctx):
    return findings_out(check_older_adult_medicines(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
