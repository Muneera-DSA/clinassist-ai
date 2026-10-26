from clinassist.analysis import check_range_crossings

from . import script
from ._checks import findings_out


@script("find_range_crossings", kind="compute",
        does="Find lab values that moved from within range to out of range on the last two tests, or that keep moving further out of range.",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['pattern', 'early risk', 'lab', 'range', 'haemoglobin', 'albumin'])
def run(ctx):
    return findings_out(check_range_crossings(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
