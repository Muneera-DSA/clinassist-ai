from clinassist.analysis import check_lab_conflicts

from . import script
from ._checks import findings_out


@script("find_lab_conflicts", kind="compute",
        does="Find tests reported twice on the same day with clearly different values (data quality).",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['data quality', 'conflict', 'lab', 'duplicate result'])
def run(ctx):
    return findings_out(check_lab_conflicts(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
