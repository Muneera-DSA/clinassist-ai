import json

from clinassist.verifier import evaluate

from . import script


def script_facts(gathered: dict) -> dict[str, str]:
    """Numbers a script computed about a record (e.g. 'n': 82 results of a test) count as support for that record's
    sentence, alongside the source row itself. Found 27 Oct: a correct '82 result(s)' was rejected as unsupported."""
    facts: dict[str, str] = {}

    def walk(v):
        if isinstance(v, dict):
            flat = {k: x for k, x in v.items() if not isinstance(x, (dict, list))}
            ids = [v["eid"]] if isinstance(v.get("eid"), str) else []
            for e in ids:
                facts[e] = facts.get(e, "") + " " + json.dumps(flat, default=str)
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk({k: v for k, v in gathered.items() if not k.startswith("verify_draft")})
    return facts


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
    result = dict(ctx.result() if ctx.rec is not None else empty)
    result["script_facts"] = script_facts(ctx.gathered)
    v = evaluate(draft, set(retrieved), ctx.rec, result, set(required_rules) if required_rules is not None else None,
                 set(identity_ids) if identity_ids is not None else None)
    return {"passed": v.passed, "issues": v.issues, "stats": v.stats}
