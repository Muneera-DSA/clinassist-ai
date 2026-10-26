from clinassist.analysis import timeline

from . import script


@script("build_timeline", kind="sort",
        does="Put the key dated events in order: new diagnoses, emergency visits and admissions, medicines started.",
        returns="date, type, text and evidence ids, oldest first",
        tags=["timeline", "events", "history", "chronology", "emergency", "diagnosis"])
def run(ctx):
    return {"events": timeline(ctx.rec, ctx.trends(), ctx.meds(), [])}
