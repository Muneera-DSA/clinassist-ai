from clinassist.analysis import check_monitoring_gaps

from . import script
from ._checks import findings_out


@script("find_monitoring_gaps", kind="compute",
        does="Find monitoring tests that are missing in the last 12 months (eGFR and albumin/creatinine ratio for CKD, haemoglobin for anaemia).",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['missing', 'overdue', 'gap', 'monitoring', 'tests', 'haemoglobin'])
def run(ctx):
    return findings_out(check_monitoring_gaps(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
