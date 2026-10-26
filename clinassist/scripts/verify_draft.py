from clinassist.verifier import evaluate

from . import script


@script("verify_draft", kind="verify", needs_record=False,
        does="Check a draft sentence by sentence against the source records: citations exist and were retrieved, numbers and "
             "dates appear in the cited records, required HIGH findings are covered, connections stand on two findings, "
             "no treatment orders. Enforced by Meterless on every draft; not chosen by the agent.",
        args={"draft": "the text to check", "retrieved": "evidence ids the agent retrieved", "required_rules": "HIGH rules to cover",
              "identity_ids": "record ids an identity section may name"},
        returns="passed, the list of issues, and counts",
        tags=["verify", "fact-check"])
def run(ctx, draft: str, retrieved: list, required_rules: list | None = None, identity_ids: list | None = None):
    empty = {"findings": [], "trends": {}, "timeline": []}  # identity-only requests read no clinical data
    v = evaluate(draft, set(retrieved), ctx.rec, ctx.result() if ctx.rec is not None else empty, set(required_rules) if required_rules is not None else None,
                 set(identity_ids) if identity_ids is not None else None)
    return {"passed": v.passed, "issues": v.issues, "stats": v.stats}
