from clinassist.analysis import check_identity_pending

from . import script
from ._checks import findings_out


@script("check_identity_pending", kind="compute",
        does="List records that may belong to this patient but are waiting for a person's identity decision (not used).",
        returns="criterion_met (true/false) and the findings: title, detail, evidence ids, guideline source, rule_level",
        tags=['identity', 'matching', 'pending', 'records'])
def run(ctx):
    return findings_out(check_identity_pending(ctx.rec, ctx.trends(), ctx.meds(), ctx.rules))
